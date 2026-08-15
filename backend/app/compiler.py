"""编译层：EmployeeSpec → create_deep_agent 实例。

整个 demo 最关键的设计——员工的一切产品化配置（人设、技能、工具、
连接器、审批策略）最终收敛为一次 create_deep_agent 调用。
技能与记忆通过 Store 的虚拟路径挂载（/skills/、/memories/），
技能内容在启动时从本地目录播种进 Store。

多员工：本文件是纯函数（spec 进、agent 出），新增员工只需加一个
employees/*.yaml，编译层零改动。所有工具集中登记在 ALL_LOCAL_TOOLS。
"""
import re
import sys
import os
from pathlib import Path

from deepagents import create_deep_agent
from deepagents.backends import CompositeBackend, StateBackend, StoreBackend, LocalShellBackend, FilesystemBackend
from deepagents.backends.utils import create_file_data
from langchain.chat_models import init_chat_model
from langchain.tools import tool
from langchain_mcp_adapters.client import MultiServerMCPClient

from app.spec import EmployeeSpec
from app.tools.kb import create_ticket
from app.tools.data_tools import get_my_id
from app.tools.search import bocha_search
from app.tools.time_tools import get_current_time
from app.tools.wiki_tools import query_product_wiki, list_product_catalog
from app.workflows.refund import make_start_refund
from app.paths import PROJECT_ROOT, WORKSPACE_DATA

ROOT = Path(__file__).resolve().parent.parent
VENV_BIN = str(ROOT / ".venv" / "bin")
# 全量本地工具注册表：每个员工按名挑选，编译层零改动即可扩展。
# 注意：分析师"小数"用 local_shell 后端，直接拿到 execute/read_file/ls/write_file
# 原生工具（参考官方 data-analysis 文档），不再需要 run_python 这类自定义子进程工具。
# kb_search 是"按员工所选知识库"的闭包工具，不在此注册（见 make_kb_search）。
# run_python：在数据目录直接跑 pandas/matplotlib，绕开 execute 在 virtual_mode 下
# /data/ 路径不映射的坑（模型用 pd.read_csv("/data/x.csv") 会失败）。
ALL_LOCAL_TOOLS = {
    "create_ticket": create_ticket,
    "bocha_search": bocha_search,
    "get_my_id": get_my_id,
    "get_current_time": get_current_time,
    # 兼容旧员工配置；实现已改为 RAGFlow 检索，不再读取本地 product-wiki。
    "query_product_wiki": query_product_wiki,
    "list_product_catalog": list_product_catalog,
}
# start_refund 不在此表：它需要运行时 checkpointer 注入（支持 Point2 内层图
# interrupt），由 _assemble_tools 用 make_start_refund(checkpointer) 工厂装配。

# 所有数字员工默认具备的通用工具（不依赖其 tools 字段声明）。
# 编译期无条件注入，解决「对话时不知道当前时间」的普遍问题。
GLOBAL_TOOL_NAMES = ["get_current_time"]

def make_kb_search(spec: EmployeeSpec, user_id: str | None):
    """按员工 / 用户视角动态生成 kb_search 工具（仅 RAGFlow 向量检索）。

    运行时从 catalog 读取员工绑定的知识库及其 RAGFlow dataset 映射。
    未配置 RAGFLOW_API_KEY 时返回提示信息，不回退本地检索。
    """
    from app import catalog
    from app import knowledge

    @tool
    def kb_search(query: str) -> str:
        """【知识库检索】基于 RAGFlow 向量检索知识库。

        输入产品名、政策关键词或业务问题，返回最相关的知识片段。
        未配置 RAGFLOW_API_KEY 时无法使用。
        """
        cfg = (catalog.get_effective_config(user_id, spec.id)
               if user_id else catalog.get_employee_config(spec.id)) or {}
        return knowledge.search(query, cfg=cfg, top_k=3)
    return kb_search

def _extract_skill_triggers(skill_md: str) -> str:
    """从 SKILL.md 提取触发条件文本。

    优先级：
      1. 正文 `## 触发条件` 或 `## 适用范围` 段落（语义最精确）；
      2. 兜底 frontmatter `description`（所有 SKILL.md 都有，含"当…时"触发语义）。
    """
    m = re.search(r"^##\s+(?:触发条件|适用范围)\s*\n(.+?)(?=^##\s|\Z)",
                  skill_md, re.MULTILINE | re.DOTALL)
    if m:
        return m.group(1).strip()
    m = re.search(r"^description:\s*(.+)$", skill_md, re.MULTILINE)
    if m:
        return m.group(1).strip()
    return ""


def _build_skill_routing(skills: list[dict]) -> str:
    """生成确定性技能路由指令，拼进 system_prompt。

    让模型在 system_prompt 里就看到「什么情况调什么技能」，而不是靠
    skills=["/skills/"] 挂载后模型自觉 read_file——后者无程序化保证，
    模型可能跳过。本函数把触发条件展开成明确指令，满足条件必须先查阅规程。
    """
    if not skills:
        return ""
    lines = [
        "",
        "## 技能路由（确定性激活）",
        "以下是你已挂载的技能。当用户消息满足某技能的触发条件时，",
        "必须先 read_file 查阅完整规程再执行，不可凭记忆跳过：",
        "",
    ]
    for s in skills:
        lines.append(f"### {s['name']}")
        lines.append(f"触发条件：{s.get('triggers') or s.get('description', '（未指定）')}")
        lines.append(f"规程路径：/skills/{s['name']}/SKILL.md")
        lines.append("")
    return "\n".join(lines)


def _extract_sop_preview(text: str) -> str:
    """提取 SOP 前 80 字作为清单摘要，避免全文进入 system_prompt。"""
    clean = " ".join(text.strip().splitlines())
    return clean[:80]


def _get_sop_text(spec, sop_id: str) -> str:
    """从 catalog 读取 SOP 内容；未找到返回空字符串。"""
    from app import catalog
    row = catalog.get_sop(sop_id)
    return (row.get("content") or "") if row else ""


def _build_sop_routing(sops: list[dict]) -> str:
    """生成 SOP 路由，只保留清单与摘要，完整 SOP 通过 /sops/ 运行时读取。"""
    if not sops:
        return ""
    lines = [
        "",
        "## SOP 路由（确定性激活）",
        "以下 SOP 已挂载。涉及对应流程时必须先 read_file 查阅完整规程再执行：",
        "",
    ]
    for s in sops:
        lines.append(f"- {s['id']}：{s.get('preview', '')}")
        lines.append(f"  规程路径：/sops/{s['id']}.md")
    lines.append("")
    return "\n".join(lines)


def _build_ontology_routing() -> str:
    """企业业务本体使用指引：所有员工都具备 ontology_* 查询工具。

    本体的价值是让数字员工基于真实业务关系作答（谁负责哪个项目、
    哪个客户下过哪些订单），而不是靠模型猜测。拼进 system_prompt，
    确保模型在用户问业务事实时先查本体。
    """
    lines = [
        "",
        "## 企业业务本体（必须优先查询）",
        "你已具备企业业务本体查询能力，可查企业真实的人、部门、客户、项目、合同、订单、产品及其关系。",
        "回答涉及具体业务事实时，必须先查询本体再作答，禁止编造或凭记忆猜测：",
        "- 查实体：ontology_find_entities（实体类型：org/department/position/employee/customer/product/project/contract/order）",
        "- 查关系：ontology_query_relations（如谁负责某项目、某客户下过哪些订单、某订单包含哪些产品）",
        "查询链路：先 ontology_find_entities 拿到实体 id，再 ontology_query_relations 沿关系展开。",
        "例如用户问「李晓芳负责哪些项目」：先查员工李晓芳，再用她的 id 查询 manage 关系。",
        "",
    ]
    return "\n".join(lines)


def _build_subagent_routing(subagents: list[dict]) -> str:
    """把子代理清单拼进 system_prompt，让主 agent 知道何时委派。"""
    if not subagents:
        return ""
    lines = [
        "",
        "## 子代理委派",
        "以下是可用的子代理。当任务包含独立、耗时的调研/检索/计算环节时，",
        "优先调用 task 工具委派，不要在主对话里反复执行大量工具调用：",
        "",
    ]
    for s in subagents:
        lines.append(f"- {s['name']}：{s.get('description', '')}")
    lines.append("")
    return "\n".join(lines)


async def _assemble_tools(spec: EmployeeSpec, checkpointer=None,
                          user_id: str | None = None) -> tuple[list, object]:
    """按员工配置装配工具列表，返回 (tools, mcp_client)。

    组成：
      1. 本地注册表按名挑选（spec.tools 中声明的）；
      2. kb_search 闭包（按本员工选中的知识库条目生成）；
      3. start_refund 工厂注入（需运行时 checkpointer，支持 Point2 内层图 interrupt）；
      4. **通用工具**：GLOBAL_TOOL_NAMES 对所有员工无条件注入
         （即使 spec.tools=[] 也自动具备，去重避免重复）——
         目前含 get_current_time，让所有员工都能回答时间类问题；
      5. MCP 连接器工具（spec.mcp_servers 非空时拉起 stdio/sse 客户端）。
    """
    tools = []
    for name in spec.tools:
        if name == "kb_search":
            # 按员工 / 用户视角动态生成检索工具（运行时读 catalog，不固化快照）
            tools.append(make_kb_search(spec, user_id))
        elif name == "start_refund":
            # 退款工具需注入运行时 checkpointer（支持后续 Point2 内层图 interrupt）
            tools.append(make_start_refund(checkpointer))
        elif name in ALL_LOCAL_TOOLS:
            tools.append(ALL_LOCAL_TOOLS[name])

    # --- 通用工具：即使员工 tools=[] 也自动具备（去重避免重复）---
    have = {t.name for t in tools}
    for g in GLOBAL_TOOL_NAMES:
        if g in ALL_LOCAL_TOOLS and g not in have:
            tools.append(ALL_LOCAL_TOOLS[g])

    # --- 企业业务本体闭包工具：spec.tools 声明了 ontology_* 才注入（按用户 tenant 隔离）。
    #     与 kb_search 同理，是闭包工具不进 ALL_LOCAL_TOOLS；声明任一即注入两个，
    #     配合使用（find 拿 id → query_relations 展开）。资源中心可对员工开关。---
    from app.tools.ontology_tools import make_ontology_tools
    if any(n in ("ontology_find_entities", "ontology_query_relations") for n in spec.tools):
        for t in make_ontology_tools(user_id):
            if t.name not in have:
                tools.append(t)

    # --- MCP 连接器工具 ---
    mcp_client = None
    # 临时运维开关：连接器 stdio 初始化有问题时，可先禁用 MCP，避免后台线程错误拖垮服务。
    # 修复 MCP Manager（#82/#83）后应移除该开关。
    if spec.mcp_servers and os.environ.get("MCP_DISABLED") != "1":
        servers = {}
        for name, cfg in spec.mcp_servers.items():
            cfg = dict(cfg)
            if cfg.get("transport") == "stdio":
                # ${PYTHON_BIN} 模板 = 本项目 Python 解释器，args 按仓库相对路径补 ROOT
                # （保留旧的纯 Python 连接器兼容，如 crm）。其它 command（如 npx）原样透传，
                # env/args 由配置直接给 MultiServerMCPClient，支持 node 型 MCP 连接器。
                if cfg.get("command") == "${PYTHON_BIN}":
                    cfg["command"] = sys.executable
                    cfg["args"] = [str(ROOT / a) for a in cfg.get("args", [])]
            servers[name] = cfg
        try:
            mcp_client = MultiServerMCPClient(servers)
            mcp_tools = await mcp_client.get_tools()
            tools += mcp_tools
        except Exception as e:
            # MCP 连接器失败不应拖垮服务：先降级，仅保留本地工具。
            # 后续 #82/#83 MCP Manager 会补齐重试、健康检查与进程回收。
            print(f"[mcp] 连接器初始化失败，已跳过 MCP 工具：{type(e).__name__}: {e}")
            mcp_client = None
    return tools, mcp_client

def _init_model(model: str):
    """openai: 前缀模型在 deepagents 中默认走 Responses API，
    国内 MaaS 兼容端点只支持 /chat/completions，必须显式关掉，
    否则报 404。"""
    if model.startswith("openai:"):
        return init_chat_model(model, use_responses_api=False)
    return model


async def _assemble_subagents(spec: EmployeeSpec, checkpointer) -> list[dict]:
    """按员工配置装配子代理列表，传给 create_deep_agent(subagents=...)。

    子代理的 tools 一旦指定就完全覆盖主 agent 的工具继承，因此这里为每个
    子代理单独装配工具（含通用 get_current_time）。skills/permissions 暂按
    配置原样透传，后续再补齐子代理技能隔离。
    """
    subagents = []
    for cfg in spec.subagents:
        tools, _ = await _assemble_tools(
            EmployeeSpec(
                id=cfg["name"],
                name=cfg.get("name", cfg["name"]),
                role="",
                model=spec.model,
                persona="",
                tools=cfg.get("tools", []),
            ),
            checkpointer,
        )
        subagents.append({
            "name": cfg["name"],
            "description": cfg.get("description", ""),
            "system_prompt": cfg.get("system_prompt", ""),
            "tools": tools,
            "model": _init_model(cfg.get("model") or spec.model),
            "permissions": cfg.get("permissions", []),
        })
    return subagents

def memory_namespace(user_id: str | None, emp_id: str) -> tuple[str, ...]:
    """记忆 Store 命名空间：(user_id, emp_id)。

    必须在**编译期**就由 get_agent 把 user_id 闭包捕获进来——因为
    get_agent 本就按 (emp_id, user_id) 缓存 agent，编译期 user_id 已知。

    绝不能像早期实现那样在运行时调 get_config()["configurable"]["user_id"]：
    abefore_agent（加载记忆）阶段 langgraph 的 config 上下文尚未就绪，
    get_config() 取不到 → 回退 "default" → 读不到该用户的记忆
    （但工具调用「写记忆」时 get_config() 可取 → 能写入，造成「写进、读不出」）。
    技能路由用同款闭包写法（lambda rt: (spec.id,)）一直正常，即此理。
    """
    return (user_id or "default", emp_id)


def skills_namespace(user_id: str | None, emp_id: str) -> tuple[str, ...]:
    """技能 Store 命名空间：(user_id or "default", emp_id)。

    #72：技能内容按用户视角隔离。不同用户即使共享同一员工模板，
    也可能因为 overrides 拥有不同的有效技能集合，因此 /skills/ 存储
    需要按用户级命名空间挂载，避免互相覆盖。
    """
    return (user_id or "default", emp_id)


def sops_namespace(user_id: str | None, emp_id: str) -> tuple[str, ...]:
    """SOP Store 命名空间：(user_id or "default", emp_id)，与技能保持一致。"""
    return (user_id or "default", emp_id)


def build_backends(spec: EmployeeSpec, store, user_id: str | None = None):
    """构造 CompositeBackend：默认后端 + /data、/skills、/memories、/sops 路由。"""
    if spec.backend == "local_shell":
        # virtual_mode=False：execute 是真实 shell（cwd=PROJECT_ROOT），输出会暴露真实绝对路径；
        # 若 virtual_mode=True，模型用这些绝对路径调用 write_file 会被 _resolve_path 当成虚拟路径
        # 拼到 root_dir 下，产生 PROJECT_ROOT/Users/wrg/... 镜像目录（8月7日 make_news_xlsx.py 事故）。
        # 关掉后绝对路径按字面落位，与 execute 语义一致。/data/ 等虚拟路由不受影响。
        default_backend = LocalShellBackend(
            root_dir=str(PROJECT_ROOT),
            virtual_mode=False,
            env={"PATH": f"{VENV_BIN}:{os.environ.get('PATH', '/usr/bin:/bin')}"},
            inherit_env=True,
        )
    else:
        default_backend = StateBackend()
    return CompositeBackend(
        default=default_backend,
        routes={
            "/data/": FilesystemBackend(root_dir=str(WORKSPACE_DATA), virtual_mode=True),
            "/memories/": StoreBackend(namespace=lambda rt: memory_namespace(user_id, spec.id)),
            "/skills/": StoreBackend(namespace=lambda rt: skills_namespace(user_id, spec.id)),
            "/sops/": StoreBackend(namespace=lambda rt: sops_namespace(user_id, spec.id)),
        },
    )


async def compile_agent(spec: EmployeeSpec, checkpointer, store, user_id: str | None = None):
    """返回 (agent, stage_meta, mcp_client)。
    mcp_client 由调用方按员工缓存保活；本函数不再持有模块级全局。
    user_id 由调用方（get_agent）传入并在编译期闭包进记忆命名空间。"""
    namespace = skills_namespace(user_id, spec.id)

    # --- 播种技能到 Store（注意：key 不带路由前缀，
    #     CompositeBackend 会把 /skills/xxx 解析为 key /xxx）---
    skill_summaries = []
    for skill_name in spec.skills:
        # 目录可来自项目内 skills/，也可为外部绝对路径（如 ~/.agents/skills/...）
        sdir = spec.skill_dirs.get(skill_name) or f"skills/{skill_name}"
        skill_dir = Path(sdir) if Path(sdir).is_absolute() else ROOT / sdir
        skill_md = (skill_dir / "SKILL.md").read_text(encoding="utf-8")
        await store.aput(namespace, f"/{skill_name}/SKILL.md", create_file_data(skill_md))
        desc = next((l.split(":", 1)[1].strip() for l in skill_md.splitlines()
                     if l.startswith("description:")), "")
        triggers = _extract_skill_triggers(skill_md)
        skill_summaries.append({"name": skill_name, "description": desc, "triggers": triggers})

    # --- 播种 SOP 到 Store（/sops/<id>.md）---
    sop_summaries = []
    for sop_id in spec.sops:
        text = _get_sop_text(spec, sop_id)
        if not text:
            continue
        await store.aput(sops_namespace(user_id, spec.id), f"/{sop_id}.md",
                         create_file_data(text))
        sop_summaries.append({"id": sop_id, "preview": _extract_sop_preview(text)})

    # --- 记忆文件不在编译期播种：改为运行时按 (user_id, emp_id) 懒初始化
    #     （见 runtime.ensure_user_memory），实现用户级记忆隔离 ---

    # --- 工具：本地注册表按名挑选 + 知识库闭包 + 通用工具 + MCP 连接器 ---
    tools, mcp_client = await _assemble_tools(spec, checkpointer, user_id=user_id)
    tool_names = [t.name for t in tools]
    subagents = await _assemble_subagents(spec, checkpointer)

    system_prompt = spec.persona
    system_prompt += _build_skill_routing(skill_summaries)
    system_prompt += _build_sop_routing(sop_summaries)
    if any(n in ("ontology_find_entities", "ontology_query_relations") for n in spec.tools):
        system_prompt += _build_ontology_routing()
    system_prompt += _build_subagent_routing(subagents)
    if spec.subagent_policy:
        system_prompt += "\n" + spec.subagent_policy.strip()
    sop_detail = spec.sop_text.strip() if spec.sop_text else "（无刚性 SOP，按技能规程执行）"

    backend = build_backends(spec, store, user_id)

    agent = create_deep_agent(
        model=_init_model(spec.model),
        tools=tools,
        system_prompt=system_prompt,
        skills=["/skills/"],
        memory=["/memories/AGENTS.md"],
        subagents=subagents or None,
        backend=backend,
        interrupt_on=spec.interrupt_on,
        checkpointer=checkpointer,
        store=store,
    )

    stage_meta = [
        {"stage": "employee", "status": "done",
         "detail_text": f"{spec.name}（{spec.role}）· {spec.model} · 工具 {len(tool_names)} 个"},
        {"stage": "sop", "status": "done", "detail_text": sop_detail},
        {"stage": "skills", "status": "done",
         "detail_text": "\n".join(f"· {s['name']}" for s in skill_summaries) or "（无）"},
    ]
    return agent, stage_meta, mcp_client
