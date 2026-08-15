"""运行时：多员工 agent 缓存 + checkpointer + store。

- 每个员工独立编译、独立缓存（_agents[emp_id]），各自的 MCP stdio
  会话由各自的 mcp_client 保活（_mcp_clients[emp_id]）。
- thread_id = conversation_id，会话状态全在 AsyncSqliteSaver（checkpoints.db），
  人工审批可跨请求 resume。
- 长期记忆在 Store 的 /memories/ 路由，按 (user_id, emp_id) 命名空间隔离；
  Store 用 AsyncSqliteStore（store.db），记忆重启不丢（生产可换 Postgres）。
- 员工配置来自 catalog.db（页面可配置）；discover_employees / get_agent 改读目录库，
  employees/*.yaml 仅作种子来源。
"""
import asyncio
from pathlib import Path

from langgraph.store.sqlite import AsyncSqliteStore

from app import catalog
from app.spec import EmployeeSpec
from app.compiler import compile_agent
from app.paths import WORKSPACE_DATA

ROOT = Path(__file__).resolve().parent.parent

_store = None          # 生命周期启动时由 lifespan 注入 AsyncSqliteStore(store.db)
_checkpointer = None  # 生命周期启动时由 lifespan 注入 AsyncSqliteSaver(checkpoints.db)
_agents = {}          # emp_id -> (agent, stage_meta)
_mcp_clients = {}     # emp_id -> mcp_client | None
_lock = asyncio.Lock()


def set_checkpointer(cp):
    global _checkpointer
    _checkpointer = cp


def set_store(store):
    global _store
    _store = store


def discover_employees() -> list[dict]:
    """返回精简元数据（含 skills/tools，供选择器与历史恢复匹配用），不编译。"""
    out = []
    for m in catalog.list_employees_meta():
        cfg = catalog.get_employee_config(m["id"]) or {}
        out.append({
            "id": m["id"],
            "name": m["name"],
            "role": m["role"],
            "model": m["model"],
            "skills": cfg.get("skills", []),
            "tools": cfg.get("tools", []),
        })
    return out


def discover_assigned_employees(user_id: str) -> list[dict]:
    """返回某用户已分配员工的精简元数据（对话选择器用，只含已分配）。"""
    out = []
    for eid in catalog.assigned_employee_ids(user_id):
        m = next((x for x in catalog.list_employees_meta() if x["id"] == eid), None)
        if not m:
            continue
        cfg = catalog.get_employee_config(eid) or {}
        out.append({
            "id": eid,
            "name": m["name"],
            "role": m["role"],
            "model": m["model"],
            "skills": cfg.get("skills", []),
            "tools": cfg.get("tools", []),
        })
    return out


def build_spec(cfg: dict) -> EmployeeSpec:
    """目录库配置 → EmployeeSpec（编译层输入）。"""
    return EmployeeSpec(
        id=cfg["id"], name=cfg["name"], role=cfg.get("role", ""), model=cfg["model"],
        persona=cfg["persona"], backend=cfg.get("backend", "state"),
        interrupt_on=cfg.get("interrupt_on", {}),
        skills=cfg.get("skills", []), tools=cfg.get("tools", []),
        mcp_servers=cfg.get("mcp_servers", {}),
        kbs=cfg.get("kbs", []),
        sops=cfg.get("sops", []),
        sop_text=cfg.get("sop_text", ""), connectors=cfg.get("connectors", []),
        skill_dirs=cfg.get("skill_dirs", {}),
    )


def invalidate(employee_id: str):
    """配置变更后丢弃缓存，下次 get_agent 重新编译。
    同时清掉该员工的全部按用户变体（emp_id|user_id）。"""
    _agents.pop(employee_id, None)
    _mcp_clients.pop(employee_id, None)
    for k in list(_agents.keys()):
        if k.startswith(f"{employee_id}|"):
            _agents.pop(k, None)
            _mcp_clients.pop(k, None)


def invalidate_user(employee_id: str, user_id: str):
    """只丢弃某用户视角的 agent 变体，不动模板路径和其他用户。"""
    key = f"{employee_id}|{user_id}"
    _agents.pop(key, None)
    _mcp_clients.pop(key, None)


async def _close_mcp_client(client) -> None:
    if client is None:
        return
    close = getattr(client, "aclose", None)
    if close is not None:
        try:
            await close()
            return
        except Exception as e:
            print(f"[mcp] 关闭 MCP client 失败（aclose）：{type(e).__name__}: {e}")
    exit_method = getattr(client, "__aexit__", None)
    if exit_method is not None:
        try:
            await exit_method(None, None, None)
        except Exception as e:
            print(f"[mcp] 关闭 MCP client 失败（__aexit__）：{type(e).__name__}: {e}")


async def shutdown_mcp() -> None:
    """应用退出时关闭全部 MCP client，并清空 agent 缓存。"""
    async with _lock:
        clients = list(_mcp_clients.values())
        _mcp_clients.clear()
        _agents.clear()
    for client in clients:
        await _close_mcp_client(client)


async def dump_store(employee_id: str = "xiaosu") -> list[dict]:
    """调试用：导出 Store 里某员工的全部虚拟文件（记忆/技能的实体所在）。"""
    items = await _store.asearch((employee_id,))
    return [{"key": i.key, "value": i.value} for i in items]


async def dump_user_memory(user_id: str, employee_id: str) -> list[dict]:
    """调试用：导出某用户在某员工下的记忆（/memories namespace=(user_id, emp_id)）。"""
    items = await _store.asearch((user_id, employee_id))
    return [{"key": i.key, "value": i.value} for i in items]


async def ensure_user_memory(user_id: str, employee_id: str):
    """用户级记忆懒初始化：若 (user_id, emp_id) namespace 下还没有 AGENTS.md，
    播种一份空模板。记忆按用户隔离——不同用户问同一员工，记忆互不可见。
    同时建好看板目录 workspace/data/{user_id}/，供数据分析师按用户隔离生成看板。"""
    from deepagents.backends.utils import create_file_data
    ns = (user_id, employee_id)
    existing = [i.key for i in await _store.asearch(ns)]
    if "/AGENTS.md" not in existing:
        await _store.aput(ns, "/AGENTS.md",
                          create_file_data("## 用户档案\n（随着对话积累）\n"))
    # 用户专属看板目录（与 /api/dashboards 服务目录保持一致，统一在项目根 workspace/data 下）
    (WORKSPACE_DATA / user_id).mkdir(parents=True, exist_ok=True)


async def sync_skills_to_store(employee_id: str, user_id: str | None = None,
                                skill_dirs: dict[str, str] | None = None,
                                desired_skills: list[str] | None = None):
    """把某员工当前技能写入 Store namespace=(employee_id,)。

    技能动态加载的第一层：技能内容不再是 compile_agent 独有的副作用，
    而是 get_agent 每次运行前都会同步的运行时资源。

    - skill_dirs / desired_skills 未提供时从 catalog 自动取
      （普通用户视角取 effective 技能，管理员/模板视角取员工模板技能）。
    - 只增不删：compile_agent 也能继续播种，避免先删除旧技能导致 read_file 失败；
      后续 #70/#73 再补齐“移除已取消技能”的精确回收逻辑。
    """
    from deepagents.backends.utils import create_file_data
    if _store is None:
        return

    if skill_dirs is None or desired_skills is None:
        effective_dirs = catalog.get_skill_dirs_for_employee(employee_id, user_id)
        if skill_dirs is None:
            skill_dirs = effective_dirs
        if desired_skills is None:
            desired_skills = list(effective_dirs.keys())

    namespace = (user_id or "default", employee_id)
    existing = {i.key: i for i in await _store.asearch(namespace)}
    for skill_name in desired_skills:
        sdir = skill_dirs.get(skill_name) or f"skills/{skill_name}"
        skill_dir = Path(sdir) if Path(sdir).is_absolute() else ROOT / sdir
        md_path = skill_dir / "SKILL.md"
        if not md_path.exists():
            continue
        skill_md = md_path.read_text(encoding="utf-8")
        key = f"/{skill_name}/SKILL.md"
        cur = existing.get(key)
        if cur is not None and _item_data_equals(cur, skill_md):
            continue
        await _store.aput(namespace, key, create_file_data(skill_md))


async def refresh_skills_for_employees(employee_ids: list[str]):
    """技能内容变更后只刷新 Store，不重建 agent。

    - 对每个员工只触发 sync_skills_to_store（模板技能路径）。
    - 不调用 invalidate，避免无谓重编译。
    - 用户级覆盖技能由 get_agent 编译前自动同步。
    """
    for emp_id in employee_ids or []:
        try:
            await refresh_skills(emp_id)
        except Exception as e:
            print(f"[skills] 刷新员工 {emp_id} 技能失败：{type(e).__name__}: {e}")


async def refresh_skills(employee_id: str, user_id: str | None = None):
    """技能资源统一刷新入口（#73）。

    - user_id 为空：刷新员工模板技能 Store，保持已编译 agent 不变。
    - user_id 指定：刷新该用户技能视图，并只清该用户变体缓存。
    """
    await sync_skills_to_store(employee_id, user_id)
    if user_id:
        invalidate_user(employee_id, user_id)


async def sync_sops_to_store(employee_id: str, user_id: str | None = None,
                             sops: list[str] | None = None):
    """把某员工当前 SOP 写入 Store（/sops/<id>.md）。

    - sops 未提供时从 catalog 自动取 effective config。
    - 与技能一致：内容变化才写盘，避免重复写。
    """
    from deepagents.backends.utils import create_file_data
    if _store is None:
        return
    if sops is None:
        cfg = (catalog.get_effective_config(user_id, employee_id)
               if user_id else catalog.get_employee_config(employee_id)) or {}
        sops = cfg.get("sops") or []

    namespace = (user_id or "default", employee_id)
    existing = {i.key: i for i in await _store.asearch(namespace)}
    for sop_id in sops:
        row = catalog.get_sop(sop_id)
        if not row or not row.get("content"):
            continue
        text = row["content"]
        key = f"/{sop_id}.md"
        cur = existing.get(key)
        if cur is not None and _item_data_equals(cur, text):
            continue
        await _store.aput(namespace, key, create_file_data(text))


async def refresh_sops_for_employees(employee_ids: list[str], user_id: str | None = None):
    """SOP 内容变更后刷新 Store，不重建 agent。"""
    for emp_id in employee_ids or []:
        try:
            await sync_sops_to_store(emp_id, user_id)
        except Exception as e:
            print(f"[sops] 刷新员工 {emp_id} SOP 失败：{type(e).__name__}: {e}")


def _item_data_equals(item, text: str) -> bool:
    """判断 Store item 是否已经是文本内容，避免每次 get_agent 都重复写盘。"""
    try:
        value = item.value
        if not isinstance(value, dict):
            return False
        data = value.get("data") or value.get("content") or ""
        if isinstance(data, bytes):
            return data.decode("utf-8", "replace") == text
        return str(data) == text
    except Exception:
        return False


async def resume_refund(inner_thread: str, approved: bool) -> str:
    """恢复挂起的退款内层图，返回最终 summary（供审批 decision 端点调用）。"""
    from app.workflows.refund import resume_refund as _resume_refund
    return await _resume_refund(inner_thread, approved, _checkpointer)


async def get_agent(employee_id: str, user_id: str | None = None,
                     overrides: dict | None = None):
    """按员工懒编译 + 进程内缓存。

    - 管理员 / 模板路径：user_id=None → 缓存键为 emp_id，用纯模板配置。
    - 普通用户路径：user_id 给定 → 缓存键为 f"{emp_id}|{user_id}"，
      用 get_effective_config（模板 + 该用户覆盖合并）编译，A/B 互不影响。
    overrides 由调用方传入（来自该用户的分配行），避免在编译层再查库。
    """
    async with _lock:
        if user_id:
            key = f"{employee_id}|{user_id}"
            cfg = catalog.get_effective_config(user_id, employee_id)
            if not cfg:  # 兜底：分配缺失时用纯模板
                cfg = catalog.get_employee_config(employee_id)
        else:
            key = employee_id
            cfg = catalog.get_employee_config(employee_id)
        if not cfg:
            raise KeyError(f"未知员工：{employee_id}")
        # 编译前先同步当前有效技能到 Store，让技能成为运行时资源，
        # compile_agent 只负责把技能挂进 deepagents，不再承担“唯一播种入口”。
        await sync_skills_to_store(employee_id, user_id)
        # SOP 同样运行时同步：即使 agent 已缓存，也先把最新 SOP 刷新进 /sops/。
        await sync_sops_to_store(employee_id, user_id)
        if key not in _agents:
            agent, stage_meta, mcp_client = await compile_agent(
                build_spec(cfg), _checkpointer, _store, user_id=user_id)
            _agents[key] = (agent, stage_meta)
            _mcp_clients[key] = mcp_client
    return _agents[key]


async def warmup_all():
    """生命周期启动时预热所有员工，切换即时可用。
    单个员工配置错误（如模型名写错）不应拖垮整个服务——记录后跳过。"""
    for emp in discover_employees():
        try:
            await get_agent(emp["id"])
        except Exception as e:
            print(f"[warmup] 跳过员工 {emp['id']}（编译失败）：{type(e).__name__}: {e}")
