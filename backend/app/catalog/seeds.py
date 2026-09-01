"""种子数据：首次启动将现有员工/技能/工具等原样写入 catalog.db。"""

import json
import os
import re
import time
from pathlib import Path

from .db import _conn, ROOT
from .users import create_user, get_user_by_username, set_must_change_password, list_users
from .employees import list_employees_meta
from app.spec import load_spec


def _skill_desc(skill_dir: Path) -> str:
    md = (skill_dir / "SKILL.md").read_text(encoding="utf-8")
    return next((l.split(":", 1)[1].strip() for l in md.splitlines()
                 if l.startswith("description:")), "")


# 内置连接器种子（crm 为 python stdio；newsnow 为 node/npx stdio，BASE_URL 指向本地 newsnow 容器）
CONNECTOR_SEEDS = [
    ("crm", "CRM 连接器", "订单查询 MCP（stdio）",
     {"transport": "stdio", "command": "${PYTHON_BIN}",
      "args": ["app/connectors/crm_server.py"]}),
    ("newsnow", "NewsNow 新闻连接器", "热点新闻抓取 MCP（stdio，npx）",
     {"transport": "stdio", "command": "npx",
      "args": ["-y", "newsnow-mcp-server"],
      # DOTENV_CONFIG_QUIET=true 屏蔽 dotenv 的 banner 输出，
      # 避免它在 stdout 打印非 JSON 日志污染 MCP 协议通道。
      "env": {"BASE_URL": "http://localhost:4444",
              "DOTENV_CONFIG_QUIET": "true"},
      # cwd 用无 .env 的中立目录，避免 dotenvx 把 banner 打到 stdout 污染 MCP 通道
      "cwd": "/tmp"}),
]

# 内置连接器指派给员工（与 seeds dict 的 cons 保持一致，用于独立回填）
CONNECTOR_ASSIGN = {"crm": ["xiaosu", "xiaoxiao", "hrbp"], "newsnow": ["xiaoshu"]}

# 内置员工默认启用的本体查询工具（业务事实问答依赖，资源中心可见可开关）
ONTOLOGY_TOOLS = ("ontology_find_entities", "ontology_query_relations")


def _tools_with_ontology(tools: list[str]) -> list[str]:
    """种子员工统一追加本体查询工具，让新库播种时默认具备业务事实问答能力。"""
    return tools + list(ONTOLOGY_TOOLS)


# 算网运营 SOP 种子（seed_if_empty 全量播种 / backfill_netops_upgrade 老库补缺共用）
NETOPS_SOPS = [
    ("sop_netops_emergency", "算网应急预案启动（刚性）",
     "基站退服/大面积断网/机房级故障时按本预案启动应急响应",
     "## 算网应急预案启动（刚性）\n"
     "适用场景：基站退服（P1/P2 告警）、大面积断网（≥1 个片区）、机房级故障。\n\n"
     "### 执行步骤（按顺序，不可跳过）\n\n"
     "#### 步骤 1：确认影响面\n"
     "- 查本体确认故障基站 → cover → 片区 → located_in → 受影响客户\n"
     "- 单独统计 VIP/政企客户（优先保障对象）\n\n"
     "#### 步骤 2：响应分级\n"
     "- P1 或机房级故障：15 分钟内上报值班长，启动重大故障升级流程\n"
     "  （见 sop_netops_escalation）\n"
     "- P2：30 分钟内通知片区装维工程师处置\n\n"
     "#### 步骤 3：通知责任人\n"
     "- 装维：查本体 maintain(入边) 关系，电话通知并确认接单\n\n"
     "#### 步骤 4：VIP 客户保障\n"
     "- 对受影响 VIP/政企客户主动告知故障与预计恢复时间\n\n"
     "#### 步骤 5：工单留痕\n"
     "- 预案启动后立即 create_ticket 登记应急工单（无论处置是否完成）\n\n"
     "### 注意事项\n"
     "- 应急场景先执行止损步骤再留痕，但两者都必须完成\n"
     "- 处置完成后 24 小时内输出复盘"),
    ("sop_netops_cutover", "网络割接操作规范（刚性）",
     "计划性割接/升级/扩容施工前按本规范执行",
     "## 网络割接操作规范（刚性）\n"
     "适用场景：计划性网络割接、基站升级、设备扩容施工。\n\n"
     "### 执行步骤（按顺序，不可跳过）\n\n"
     "#### 步骤 1：割接申请\n"
     "- 受理割接申请后 create_ticket 登记割接工单留痕\n\n"
     "#### 步骤 2：影响评估\n"
     "- 查本体：割接对象 → cover 关系展开受影响基站、片区、客户\n"
     "- 涉及 VIP/政企客户须提前 3 天单独告知\n\n"
     "#### 步骤 3：时间窗确认\n"
     "- 割接必须在业务低谷期（00:00-06:00）执行，节假日原则上禁止割接\n\n"
     "#### 步骤 4：回退预案\n"
     "- 必须制定回退方案并明确回退触发条件（如割接超 90 分钟未完成即回退）\n"
     "- 无回退预案的割接不得开工\n\n"
     "#### 步骤 5：执行监控\n"
     "- 割接期间持续监控告警流水与接通率，异常立即按预案处置\n\n"
     "#### 步骤 6：完工确认\n"
     "- 完工后次日核对运营指标是否恢复基线，未恢复按故障流程处理\n\n"
     "### 注意事项\n"
     "- 审批与客户告知步骤绝不跳过\n"
     "- 割接属计划性变更：执行动作由装维/机房人员实施，本流程只做评估与留痕"),
    ("sop_netops_escalation", "重大故障升级上报（刚性）",
     "P1 故障/VIP政企重大影响/处置超时按本规程升级上报",
     "## 重大故障升级上报（刚性）\n"
     "触发条件（满足其一即升级）：\n"
     "- P1 故障；VIP 或政企客户重大影响；处置超时（P1 超 2 小时 / P2 超 4 小时未恢复）\n\n"
     "### 执行步骤（按顺序，不可跳过）\n\n"
     "#### 步骤 1：判定升级条件\n"
     "- 核对告警等级（告警流水 severity）、影响客户等级（本体查询）、已处置时长\n\n"
     "#### 步骤 2：上报链路（逐级，不可越级跳过）\n"
     "- 装维工程师 → 网络监控值班长（李建国）→ 网络运营部负责人\n"
     "- 人员联系方式查本体 employee 实体 props\n\n"
     "#### 步骤 3：上报时限\n"
     "- 满足升级条件后 30 分钟内完成第一轮上报\n\n"
     "#### 步骤 4：工单留痕\n"
     "- create_ticket 登记升级工单，写明升级原因、已通知人员、当前处置进展\n\n"
     "#### 步骤 5：持续跟进\n"
     "- 每 30 分钟更新一次进展，直至故障闭环后输出复盘\n\n"
     "### 注意事项\n"
     "- 升级上报是刚性动作：宁可多报，不可瞒报漏报\n"
     "- 联系方式以本体为准，查不到时如实说明并建议人工确认"),
]

# 内置员工种子配置（seed_if_empty 全量播种 / backfill_employees_if_missing 幂等补缺共用）
EMPLOYEE_SEEDS = {
    "xiaosu": dict(
        skills=["product-faq", "complaint-handling"],
        tools=_tools_with_ontology(["kb_search", "create_ticket", "start_refund"]),
        kbs=[], sops=["sop_refund", "sop_complaint"], cons=["crm"]),
    "xiaoshu": dict(
        skills=["data-analysis"], tools=_tools_with_ontology([]), kbs=[], sops=[]),
    "xiaoxiao": dict(
        skills=["enterprise-sales"],
        tools=_tools_with_ontology(["kb_search", "bocha_search"]),
        kbs=[]),
    "hrbp": dict(
        skills=["hr-assistant"],
        tools=_tools_with_ontology(["kb_search", "create_ticket", "bocha_search"]),
        kbs=[]),
    "biz-analyzer": dict(
        skills=["business-overview", "root-cause-analysis",
                "decision-analysis", "market-intelligence"],
        tools=_tools_with_ontology(["run_python", "bocha_search", "get_current_time"]),
        kbs=[], sops=[], cons=[]),
    "net-ops": dict(
        skills=["fault-impact-analysis", "ops-metrics-analysis",
                "resource-capacity-analysis", "sop-execution"],
        tools=_tools_with_ontology(["kb_search", "create_ticket", "get_current_time"]),
        kbs=[], sops=["sop_netops_emergency", "sop_netops_cutover",
                      "sop_netops_escalation"], cons=[]),
}


def seed_if_empty():
    """把现有员工 + 目录种子进库（仅当 employees 为空时）。"""
    con = _conn()
    cur = con.cursor()
    if cur.execute("SELECT COUNT(*) FROM employees").fetchone()[0] > 0:
        con.close()
        return
    now = time.strftime("%Y-%m-%d %H:%M:%S")

    # --- skills（扫描 skills/ 目录）---
    for sd in sorted((ROOT / "skills").glob("*/")):
        sid = sd.name
        cur.execute(
            "INSERT OR IGNORE INTO skills(id,name,description,dir) VALUES(?,?,?,?)",
                    (sid, sid, _skill_desc(sd), f"skills/{sid}"))

    # --- tools（本地工具注册表）---
    tools = [
        ("kb_search", "知识库检索", "基于 RAGFlow 向量检索知识库", "local", None),
        ("create_ticket", "工单登记", "登记客服工单", "local", None),
        ("start_refund", "退款流程", "发起退款（需人工审批）", "local",
         json.dumps(["approve", "reject"])),
        ("bocha_search", "联网搜索", "联网搜索实时信息（博查）", "local", None),
        ("get_my_id", "获取用户ID", "返回当前登录用户的 ID", "local", None),
        ("get_current_time", "获取当前时间", "获取当前真实日期时间（东八区）", "local", None),
        ("generate_solution_doc", "生成方案文档",
         "根据客户信息和推荐产品生成 Word 解决方案文档", "local", None),
        ("query_product_wiki", "查询产品知识库",
         "查询自研产品/解决方案/成功案例", "local", None),
        ("list_product_catalog", "查看产品目录",
         "列出自研产品的完整目录", "local", None),
        ("ontology_find_entities", "企业本体查询",
         "按实体类型/关键词查询企业业务实体（组织/员工/客户/项目/合同/订单等）", "local", None),
        ("ontology_query_relations", "企业本体关系查询",
         "查询企业实体间的业务关系（谁负责/跟进/下单/包含等）", "local", None),
    ]
    for t in tools:
        cur.execute(
            "INSERT OR IGNORE INTO tools(id,name,description,source,needs_approval) "
            "VALUES(?,?,?,?,?)", t)

    # --- SOPs ---
    sops = [
        ("sop_refund", "退款流程（刚性）", "用户要求退款时调用 start_refund，自动进入人工审批",
         "## 退款流程（刚性）\n用户要求退款退货时，调用 start_refund 工具发起退款流程。"
         "固定三步：校验订单 → 计算金额 → 审批 → 生成退款单。\n\n"
         "### 执行路径\n"
         "1. **校验订单**：系统自动检查订单是否存在、已签收、签收 7 天内\n"
         "2. **计算金额**：按订单实际支付金额计算退款\n"
         "3. **人工审批**：流程卡在审批节点，等待管理员批准或拒绝\n"
         "4. **生成退款单**：审批通过后自动生成退款单号\n\n"
         "### 退款条件\n"
         "- 仅已签收订单可退款\n"
         "- 签收超过 7 天不可无理由退款（可走售后维修）\n"
         "- 运输中订单请先签收后再申请退款\n\n"
         "### 注意事项\n"
         "- 退款将原路返回，3-5 个工作日到账\n"
         "- 审批不可跳过，必须等待人工处理"),
        ("sop_complaint", "投诉处理（软性）",
         "用户表达不满时按 complaint-handling 技能规程执行",
         "## 投诉处理（软性）\n用户表达不满或投诉时，必须先用 read_file 读取 "
         "/skills/complaint-handling/SKILL.md，然后严格按其中的规程执行。\n\n"
         "### 执行步骤（按顺序，不可跳过）\n\n"
         "#### 步骤 1：安抚\n"
         "先共情一句话再处理，不辩解、不推责。\n"
         "- 句式参考：「非常抱歉给您带来了不便」「我完全理解您的心情」\n"
         "- 绝对禁止：「这是正常的」「您可能没看清楚」「其他用户都没问题」\n\n"
         "#### 步骤 2：核实\n"
         "- 先问订单号（如未提供），用 order_query 查订单详情\n"
         "- 用 kb_search 查该产品是否有已知问题或常见故障处理\n"
         "- 必要时查 customer_profile 了解用户等级（VIP 优先处理）\n\n"
         "#### 步骤 3：分类定级并登记工单\n"
         "紧急度判断标准：\n"
         "- urgent（安全风险/大面积故障/VIP 客诉）→ 2 小时响应\n"
         "- high（功能故障/严重影响使用）→ 24 小时响应\n"
         "- normal（一般不满/轻微问题/咨询类）→ 48 小时响应\n\n"
         "#### 步骤 4：给出答复\n"
         "告知用户工单号、预计响应时间、一个当下可执行的临时方案\n\n"
         "### 禁忌\n"
         "- 不要在未登记工单前承诺赔偿金额\n"
         "- 不要与用户争辩\n"
         "- 不要把用户晾着去查东西"),
        *NETOPS_SOPS,
    ]
    for s in sops:
        cur.execute(
            "INSERT OR IGNORE INTO sops(id,name,description,content) VALUES(?,?,?,?)", s)

    # --- connectors ---
    for cid, cname, cdesc, ccfg in CONNECTOR_SEEDS:
        cur.execute(
            "INSERT OR IGNORE INTO connectors(id,name,description,config) VALUES(?,?,?,?)",
            (cid, cname, cdesc, json.dumps(ccfg, ensure_ascii=False)))

    # --- employees ---
    for emp_id, sel in EMPLOYEE_SEEDS.items():
        spec = load_spec(str(ROOT / "employees" / f"{emp_id}.yaml"))
        model = re.sub(r"\$\{(\w+)\}", lambda m: os.environ.get(m.group(1), m.group(0)),
                       spec.model)
        cur.execute(
            "INSERT INTO employees(id,name,role,model,persona,backend,mcp_servers,"
            "interrupt_on,subagents,subagent_policy,created_at,updated_at) "
            "VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
            (emp_id, spec.name, spec.role, model, spec.persona, spec.backend,
             json.dumps(spec.mcp_servers, ensure_ascii=False),
             json.dumps(spec.interrupt_on, ensure_ascii=False),
             json.dumps(spec.subagents, ensure_ascii=False),
             spec.subagent_policy, now, now))
        for s in sel.get("skills", []):
            cur.execute("INSERT OR IGNORE INTO employee_skills VALUES(?,?)", (emp_id, s))
        for t in sel.get("tools", []):
            cur.execute("INSERT OR IGNORE INTO employee_tools VALUES(?,?)", (emp_id, t))
        for k in sel.get("kbs", []):
            cur.execute("INSERT OR IGNORE INTO employee_kbs VALUES(?,?)", (emp_id, k))
        for s in sel.get("sops", []):
            cur.execute("INSERT OR IGNORE INTO employee_sops VALUES(?,?)", (emp_id, s))
        for c in sel.get("cons", []):
            cur.execute("INSERT OR IGNORE INTO employee_connectors VALUES(?,?)", (emp_id, c))
    con.commit()
    con.close()


def backfill_connectors():
    """幂等补齐内置连接器（含指派）。对新库由 seed_if_empty 写入；对已存在的库，
    这里用 INSERT OR IGNORE 补缺——不覆盖管理员在资源中心对连接器/指派的改动。"""
    con = _conn()
    cur = con.cursor()
    for cid, cname, cdesc, ccfg in CONNECTOR_SEEDS:
        cur.execute(
            "INSERT OR IGNORE INTO connectors(id,name,description,config) VALUES(?,?,?,?)",
            (cid, cname, cdesc, json.dumps(ccfg, ensure_ascii=False)))
    for cid, emps in CONNECTOR_ASSIGN.items():
        for e in emps:
            # 仅当该员工确实存在才指派
            if cur.execute("SELECT 1 FROM employees WHERE id=? AND deleted_at IS NULL",
                           (e,)).fetchone():
                cur.execute("INSERT OR IGNORE INTO employee_connectors VALUES(?,?)", (e, cid))
    con.commit()
    con.close()


def backfill_ontology_tools():
    """幂等补齐本体工具登记与内置员工指派。

    对新库由 seed_if_empty 写入；对已存在的库用 INSERT OR IGNORE 补缺。
    仅补缺不覆盖：管理员可在资源中心关闭某员工的本体工具，下次重启会补回
    （与 backfill_connectors 语义一致，针对内置员工）。
    """
    con = _conn()
    cur = con.cursor()
    _ONTOLOGY_DESC = {
        "ontology_find_entities": ("企业本体查询",
                                   "按实体类型/关键词查询企业业务实体（组织/员工/客户/项目/合同/订单等）"),
        "ontology_query_relations": ("企业本体关系查询",
                                     "查询企业实体间的业务关系（谁负责/跟进/下单/包含等）"),
    }
    for tid in ONTOLOGY_TOOLS:
        name, desc = _ONTOLOGY_DESC[tid]
        cur.execute(
            "INSERT OR IGNORE INTO tools(id,name,description,source,needs_approval) "
            "VALUES(?,?,?,?,?)",
            (tid, name, desc, "local", None))
    for e in ("xiaosu", "xiaoshu", "xiaoxiao", "hrbp", "biz-analyzer", "net-ops"):
        if cur.execute("SELECT 1 FROM employees WHERE id=? AND deleted_at IS NULL",
                       (e,)).fetchone():
            for t in ONTOLOGY_TOOLS:
                cur.execute("INSERT OR IGNORE INTO employee_tools VALUES(?,?)", (e, t))
    con.commit()
    con.close()


def backfill_employees_if_missing():
    """幂等补齐内置种子员工：新库由 seed_if_empty 全量写入；老库升级新增的
    员工（如 net-ops）靠这里补种。已存在（含软删除）的员工不覆盖，
    尊重管理员在资源中心的改动与删除。"""
    con = _conn()
    cur = con.cursor()
    now = time.strftime("%Y-%m-%d %H:%M:%S")

    # 老库可能缺新技能目录（如 fault-impact-analysis），扫描 skills/ 补登记
    for sd in sorted((ROOT / "skills").glob("*/")):
        cur.execute(
            "INSERT OR IGNORE INTO skills(id,name,description,dir) VALUES(?,?,?,?)",
            (sd.name, sd.name, _skill_desc(sd), f"skills/{sd.name}"))

    added = []
    for emp_id, sel in EMPLOYEE_SEEDS.items():
        if cur.execute("SELECT 1 FROM employees WHERE id=?", (emp_id,)).fetchone():
            continue  # 已存在（含软删除）：不覆盖
        yaml_path = ROOT / "employees" / f"{emp_id}.yaml"
        if not yaml_path.exists():
            continue
        spec = load_spec(str(yaml_path))
        model = re.sub(r"\$\{(\w+)\}", lambda m: os.environ.get(m.group(1), m.group(0)),
                       spec.model)
        cur.execute(
            "INSERT INTO employees(id,name,role,model,persona,backend,mcp_servers,"
            "interrupt_on,subagents,subagent_policy,created_at,updated_at) "
            "VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
            (emp_id, spec.name, spec.role, model, spec.persona, spec.backend,
             json.dumps(spec.mcp_servers, ensure_ascii=False),
             json.dumps(spec.interrupt_on, ensure_ascii=False),
             json.dumps(spec.subagents, ensure_ascii=False),
             spec.subagent_policy, now, now))
        for s in sel.get("skills", []):
            cur.execute("INSERT OR IGNORE INTO employee_skills VALUES(?,?)", (emp_id, s))
        for t in sel.get("tools", []):
            cur.execute("INSERT OR IGNORE INTO employee_tools VALUES(?,?)", (emp_id, t))
        for k in sel.get("kbs", []):
            cur.execute("INSERT OR IGNORE INTO employee_kbs VALUES(?,?)", (emp_id, k))
        for s in sel.get("sops", []):
            cur.execute("INSERT OR IGNORE INTO employee_sops VALUES(?,?)", (emp_id, s))
        for c in sel.get("cons", []):
            cur.execute("INSERT OR IGNORE INTO employee_connectors VALUES(?,?)", (emp_id, c))
        added.append(emp_id)

    # 新补种的员工授予所有现有用户（管理员之后可在用户管理里回收）
    if added:
        for u in list_users():
            for emp_id in added:
                cur.execute(
                    "INSERT OR IGNORE INTO user_employee_assignments"
                    "(user_id,employee_id,granted_by,overrides,created_at) VALUES(?,?,?,?,?)",
                    (u["id"], emp_id, "u_admin", "{}", now))
    con.commit()
    con.close()
    if added:
        print(f"[seed] 已为老库补种内置员工：{', '.join(added)}")


# net-ops 升级前后 persona 的特征句：用于判断老库中的 persona 是否被管理员改过
# （旧版首句 / 新版特征句，与 backend/employees/net-ops.yaml 保持一致）
_NETOPS_OLD_PERSONA_MARKER = "负责基站运维、装维调度与客户网络保障"
_NETOPS_NEW_PERSONA_MARKER = "围绕四项核心能力开展工作"


def backfill_netops_upgrade():
    """net-ops「算网运营专家」老库一次性升级（幂等）。

    补齐三类升级缺口（新库由 seed_if_empty 直接写入，无需本函数）：
      1. 算网 SOP 种子行（INSERT OR IGNORE，不覆盖管理员改过的 SOP 内容）；
      2. net-ops 的新技能 / SOP 绑定（INSERT OR IGNORE，不覆盖管理员增删）；
      3. persona/role 同步：仅当库中 persona 仍是旧版特征句（未被管理员改过）
         才更新为新版 yaml 内容；管理员改过则保留并打印提示。
    """
    con = _conn()
    cur = con.cursor()

    # 1. SOP 种子行补缺
    for s in NETOPS_SOPS:
        cur.execute("INSERT OR IGNORE INTO sops(id,name,description,content) "
                    "VALUES(?,?,?,?)", s)

    if not cur.execute(
        "SELECT 1 FROM employees WHERE id='net-ops' AND deleted_at IS NULL"
    ).fetchone():
        con.commit()
        con.close()
        return

    # 2. 技能/SOP 绑定补齐（skills 表行由 backfill_employees_if_missing 的
    #    目录扫描保证，这里再兜底扫描一次，保持本函数自包含）
    for sd in sorted((ROOT / "skills").glob("*/")):
        cur.execute(
            "INSERT OR IGNORE INTO skills(id,name,description,dir) VALUES(?,?,?,?)",
            (sd.name, sd.name, _skill_desc(sd), f"skills/{sd.name}"))
    sel = EMPLOYEE_SEEDS["net-ops"]
    for s in sel.get("skills", []):
        cur.execute("INSERT OR IGNORE INTO employee_skills VALUES(?,?)", ("net-ops", s))
    for s in sel.get("sops", []):
        cur.execute("INSERT OR IGNORE INTO employee_sops VALUES(?,?)", ("net-ops", s))

    # 3. persona/role 同步（仅未改过时）
    row = cur.execute(
        "SELECT persona FROM employees WHERE id='net-ops' AND deleted_at IS NULL"
    ).fetchone()
    persona = (row["persona"] if row else "") or ""
    if _NETOPS_OLD_PERSONA_MARKER in persona:
        spec = load_spec(str(ROOT / "employees" / "net-ops.yaml"))
        cur.execute(
            "UPDATE employees SET role=?, persona=?, updated_at=? WHERE id='net-ops'",
            (spec.role, spec.persona, time.strftime("%Y-%m-%d %H:%M:%S")))
        print("[seed] net-ops 已升级为「算网运营专家」（persona 同步为新版）")
    elif _NETOPS_NEW_PERSONA_MARKER in persona:
        pass  # 已是新版
    else:
        print("[seed] net-ops persona 已被管理员修改，跳过自动升级（技能/SOP 绑定已补齐）")

    con.commit()
    con.close()


def backfill_ragflow_knowledge_bases():
    """从 RAGFlow 同步真实知识库列表到 catalog。

    catalog 中只保留真实存在于 RAGFlow 的 dataset。旧本地逻辑库或演示库
    会软删除；若旧库已映射到某个 RAGFlow dataset，会先迁移员工绑定。
    """
    from app.connectors import ragflow_client
    if not ragflow_client.is_ragflow_configured():
        return
    try:
        datasets = ragflow_client.list_datasets()
    except Exception as e:
        print(f"[seed] RAGFlow 知识库同步失败，已跳过：{type(e).__name__}: {e}")
        return
    dataset_ids = [d["id"] for d in datasets if d.get("id")]
    if not dataset_ids:
        return

    con = _conn()
    cur = con.cursor()
    for d in datasets:
        dataset_id = d.get("id")
        if not dataset_id:
            continue
        cur.execute(
            "INSERT OR IGNORE INTO knowledge_bases(id,name,description,ragflow_dataset_id) "
            "VALUES(?,?,?,?)",
            (dataset_id, d.get("name") or dataset_id, d.get("description") or "", dataset_id))
        cur.execute(
            "UPDATE knowledge_bases SET name=?, description=?, ragflow_dataset_id=?, deleted_at=NULL "
            "WHERE id=?",
            (d.get("name") or dataset_id, d.get("description") or "", dataset_id, dataset_id))

    # 旧 catalog 知识库如果已映射到真实 RAGFlow dataset，先把员工绑定迁移过去。
    for row in cur.execute(
        "SELECT id, ragflow_dataset_id FROM knowledge_bases "
        "WHERE deleted_at IS NULL AND ragflow_dataset_id IS NOT NULL AND ragflow_dataset_id != ''"
    ).fetchall():
        old_id = row["id"]
        dataset_id = row["ragflow_dataset_id"]
        if old_id == dataset_id or dataset_id not in dataset_ids:
            continue
        cur.execute(
            "INSERT OR IGNORE INTO employee_kbs(employee_id,kb_id) "
            "SELECT employee_id, ? FROM employee_kbs WHERE kb_id=?",
            (dataset_id, old_id))
        cur.execute("DELETE FROM employee_kbs WHERE kb_id=?", (old_id,))

    now = time.strftime("%Y-%m-%d %H:%M:%S")
    placeholders = ",".join("?" for _ in dataset_ids)
    cur.execute(
        f"UPDATE knowledge_bases SET deleted_at=? WHERE deleted_at IS NULL "
        f"AND (ragflow_dataset_id IS NULL OR ragflow_dataset_id='' "
        f"OR ragflow_dataset_id NOT IN ({placeholders}) OR id != ragflow_dataset_id)",
        (now, *dataset_ids))
    cur.execute(
        "DELETE FROM employee_kbs WHERE kb_id NOT IN "
        "(SELECT id FROM knowledge_bases WHERE deleted_at IS NULL)")
    con.commit()
    con.close()


# 内置员工知识库指派：按 RAGFlow 数据集名称绑定（dataset id 随环境变化，
# 名称是稳定约定；只在数据集存在时补绑，不覆盖管理员手动增删）。
EMPLOYEE_KB_ASSIGN = {
    "xiaoxiao": ["自研产品Wiki", "产品知识库", "客户档案"],
}


def backfill_employee_kb_assignments():
    """把内置员工按数据集名称绑定到已同步的 RAGFlow 知识库（幂等补缺）。"""
    con = _conn()
    cur = con.cursor()
    for emp_id, kb_names in EMPLOYEE_KB_ASSIGN.items():
        if not cur.execute(
            "SELECT 1 FROM employees WHERE id=? AND deleted_at IS NULL", (emp_id,)
        ).fetchone():
            continue
        for name in kb_names:
            row = cur.execute(
                "SELECT id FROM knowledge_bases "
                "WHERE name=? AND deleted_at IS NULL AND ragflow_dataset_id IS NOT NULL "
                "AND ragflow_dataset_id != ''",
                (name,)).fetchone()
            if row:
                cur.execute(
                    "INSERT OR IGNORE INTO employee_kbs(employee_id,kb_id) VALUES(?,?)",
                    (emp_id, row["id"]))
    con.commit()
    con.close()


def backfill_subagents_if_empty():
    """给已有 DB 的种子员工补子代理配置（仅当 subagents 为空时写入，不覆盖管理员配置）。"""
    from .db import _conn
    for emp in list_employees_meta():
        yaml_path = ROOT / "employees" / f"{emp['id']}.yaml"
        if not yaml_path.exists():
            continue
        spec = load_spec(str(yaml_path))
        if not spec.subagents:
            continue
        con = _conn()
        cur = con.cursor()
        row = cur.execute(
            "SELECT subagents, subagent_policy FROM employees WHERE id=? AND deleted_at IS NULL",
            (emp["id"],)).fetchone()
        if row and (not row["subagents"] or row["subagents"] == "[]" or not row["subagent_policy"]):
            new_subagents = json.loads(row["subagents"]) \
                if row["subagents"] and row["subagents"] != "[]" else spec.subagents
            new_policy = row["subagent_policy"] or spec.subagent_policy
            cur.execute("UPDATE employees SET subagents=?, subagent_policy=? WHERE id=?",
                        (json.dumps(new_subagents, ensure_ascii=False), new_policy, emp["id"]))
            con.commit()
            print(f"[seed] 已为员工 {emp['id']} 补种子子代理配置/策略")
        con.close()


def seed_assignments_if_empty():
    """启动一次性种子：若某已有用户 0 分配，则授予全部现有员工。"""
    users = list_users()
    emps = list_employees_meta()
    if not users or not emps:
        return
    now = time.strftime("%Y-%m-%d %H:%M:%S")
    con = _conn()
    cur = con.cursor()
    for u in users:
        cnt = cur.execute(
            "SELECT COUNT(*) FROM user_employee_assignments WHERE user_id=?",
            (u["id"],)).fetchone()[0]
        if cnt == 0:
            for e in emps:
                cur.execute(
                    "INSERT OR IGNORE INTO user_employee_assignments"
                    "(user_id,employee_id,granted_by,overrides,created_at) VALUES(?,?,?,?,?)",
                    (u["id"], e["id"], "u_admin", "{}", now))
    con.commit()
    con.close()


def seed_admin_if_empty():
    """确保默认管理员账号可用（.env ADMIN_USER/ADMIN_PASS，默认 admin/admin123）。

    只负责空库时创建；已存在用户绝不重置密码，避免每次重启把用户改过的
    密码打回默认值（旧实现会无条件对齐 ADMIN_PASS）。"""
    from app.auth import hash_password
    username = os.environ.get("ADMIN_USER", "admin")
    password = os.environ.get("ADMIN_PASS", "admin123")

    if get_user_by_username(username):
        return
    uid = create_user(username, hash_password(password), role="admin", user_id="u_admin")
    print(f"[seed] 已创建初始管理员：{username} / {password}（首次登录须修改密码）")
    if password == "admin123":
        set_must_change_password(uid, True)


def flag_default_admin_password():
    """启动检查：若 admin 仍在用默认密码 admin123，标记首登强制改密。"""
    from app.auth import verify_password
    u = get_user_by_username(os.environ.get("ADMIN_USER", "admin"))
    if u and not u.get("must_change_password") and verify_password("admin123", u["password_hash"]):
        set_must_change_password(u["id"], True)
        print("[security] admin 仍为默认密码，已标记首登强制改密")
