"""目录库（员工/技能/工具/知识库/SOP/连接器）CRUD 回归测试。"""
import json
import sqlite3

from app import catalog


def _seed_tool(tid: str, needs_approval=None):
    con = sqlite3.connect(str(catalog.db.DB))
    con.execute(
        "INSERT OR IGNORE INTO tools(id,name,description,source,needs_approval) VALUES(?,?,?,?,?)",
        (tid, tid, "d", "local", json.dumps(needs_approval) if needs_approval else None))
    con.commit()
    con.close()


# ---- 员工 ----

def test_employee_crud_and_interrupt_derivation():
    _seed_tool("start_refund", ["approve", "reject"])
    _seed_tool("kb_search")
    eid = catalog.create_employee({
        "name": "测试员", "model": "openai:m", "backend": "state", "persona": "p",
        "tools": ["start_refund", "kb_search"], "skills": [], "kbs": [], "sops": [], "connectors": [],
    })
    cfg = catalog.get_employee_config(eid)
    assert cfg["name"] == "测试员"
    assert set(cfg["tools"]) == {"start_refund", "kb_search"}
    # interrupt_on 由工具 needs_approval 自动推导
    assert cfg["interrupt_on"]["start_refund"]["allowed_decisions"] == ["approve", "reject"]
    assert cfg["interrupt_on"]["kb_search"] is False

    # 更新（改名 + 去掉工具）
    assert catalog.update_employee(eid, {
        "name": "改名", "model": "openai:m", "backend": "state", "persona": "p2",
        "tools": [], "skills": [], "kbs": [], "sops": [], "connectors": [],
    })
    cfg2 = catalog.get_employee_config(eid)
    assert cfg2["name"] == "改名"
    assert cfg2["tools"] == []

    # 删除
    catalog.delete_employee(eid)
    assert catalog.get_employee_config(eid) is None


def test_employee_partial_update_keeps_other_fields():
    """部分更新：只传某一资源类型/字段时，其余配置沿用现值不丢。"""
    _seed_tool("kb_search")
    eid = catalog.create_employee({
        "name": "局部更新员", "role": "客服", "model": "openai:m", "backend": "state",
        "persona": "原人设", "tools": ["kb_search"], "skills": [], "kbs": [],
        "sops": [], "connectors": [],
    })

    # 只改连接器：名称/人设/工具等应保持不变
    assert catalog.update_employee(eid, {"connectors": ["crm"]})
    cfg = catalog.get_employee_config(eid)
    assert cfg["connectors"] == ["crm"]
    assert cfg["name"] == "局部更新员"
    assert cfg["persona"] == "原人设"
    assert cfg["tools"] == ["kb_search"]

    # 只改名称：资源关联保持不变
    assert catalog.update_employee(eid, {"name": "局部更新员2"})
    cfg2 = catalog.get_employee_config(eid)
    assert cfg2["name"] == "局部更新员2"
    assert cfg2["connectors"] == ["crm"]
    assert cfg2["tools"] == ["kb_search"]

    catalog.delete_employee(eid)


def test_backfill_employees_if_missing_adds_netops():
    """老库补种：net-ops 员工缺失时由 backfill 补回（含技能/工具/本体工具）。"""
    catalog.init()
    catalog.seed_if_empty()  # 新库播种已含 net-ops
    assert catalog.get_employee_config("net-ops")["name"] == "小网"
    assert "fault-impact-analysis" in catalog.get_employee_config("net-ops")["skills"]

    # 模拟老库（无 net-ops）：硬删相关行后 backfill 应补回
    con = sqlite3.connect(str(catalog.db.DB))
    for tbl in ("employee_skills", "employee_tools", "employee_kbs",
                "employee_sops", "employee_connectors"):
        con.execute(f"DELETE FROM {tbl} WHERE employee_id='net-ops'")
    con.execute("DELETE FROM user_employee_assignments WHERE employee_id='net-ops'")
    con.execute("DELETE FROM employees WHERE id='net-ops'")
    con.commit()
    con.close()
    assert catalog.get_employee_config("net-ops") is None

    catalog.backfill_employees_if_missing()
    cfg = catalog.get_employee_config("net-ops")
    assert cfg is not None and cfg["name"] == "小网"
    assert "ontology_find_entities" in cfg["tools"]
    assert "fault-impact-analysis" in cfg["skills"]
    # 幂等：再跑一次不重复
    catalog.backfill_employees_if_missing()


def test_backfill_employees_if_missing_adds_market_intel():
    """老库补种：market-intel 员工缺失时由 backfill 补回（含技能/工具/连接器指派）。"""
    catalog.init()
    catalog.seed_if_empty()  # 新库播种已含 market-intel
    cfg = catalog.get_employee_config("market-intel")
    assert cfg["name"] == "小察"
    assert "market-daily-brief" in cfg["skills"]

    # 模拟老库（无 market-intel）：硬删相关行后 backfill 应补回
    con = sqlite3.connect(str(catalog.db.DB))
    for tbl in ("employee_skills", "employee_tools", "employee_kbs",
                "employee_sops", "employee_connectors"):
        con.execute(f"DELETE FROM {tbl} WHERE employee_id='market-intel'")
    con.execute("DELETE FROM user_employee_assignments WHERE employee_id='market-intel'")
    con.execute("DELETE FROM employees WHERE id='market-intel'")
    con.commit()
    con.close()
    assert catalog.get_employee_config("market-intel") is None

    catalog.backfill_employees_if_missing()
    catalog.backfill_connectors()
    cfg = catalog.get_employee_config("market-intel")
    assert cfg is not None and cfg["name"] == "小察"
    assert set(cfg["skills"]) >= {"market-daily-brief", "competitor-deep-dive",
                                  "market-alert-triage"}
    assert "bocha_search" in cfg["tools"]
    assert "ontology_find_entities" in cfg["tools"]
    # 连接器指派：newsnow + playwright
    assert set(cfg.get("connectors") or []) >= {"newsnow", "playwright"}
    # 幂等：再跑一次不重复
    catalog.backfill_employees_if_missing()
    catalog.backfill_connectors()


# ---- 知识库（RAGFlow 映射） ----

def test_kb_crud_only_tracks_ragflow_dataset_mapping():
    catalog.create_kb("kb1", "库1", "说明", ragflow_dataset_id="ds-001")
    kb = catalog.get_kb("kb1")
    assert kb["name"] == "库1"
    assert kb["ragflow_dataset_id"] == "ds-001"
    assert catalog.update_kb("kb1", "库改", "说明2", "ds-002")
    assert catalog.get_kb("kb1")["ragflow_dataset_id"] == "ds-002"
    catalog.delete_kb("kb1")
    assert catalog.get_kb("kb1") is None


def test_kb_ragflow_dataset_mapping_in_employee_config():
    catalog.create_kb("kb_rf", "RAGFlow 库", "说明", ragflow_dataset_id="ds-001")
    catalog.create_employee({
        "id": "emp_rf", "name": "RF", "kbs": ["kb_rf"],
        "tools": [], "skills": [], "sops": [], "connectors": [],
    })
    cfg = catalog.get_employee_config("emp_rf")
    assert cfg["kb_ragflow_datasets"] == {"kb_rf": "ds-001"}

    assert catalog.update_kb("kb_rf", "RAGFlow 库", "说明", "ds-002")
    assert catalog.get_kb("kb_rf")["ragflow_dataset_id"] == "ds-002"


def test_backfill_employee_kb_assignments_binds_by_dataset_name():
    """内置员工按数据集名称补绑 RAGFlow 知识库，重复执行不重复插入。"""
    catalog.create_kb("ds-cust", "客户档案", "", ragflow_dataset_id="ds-cust")
    catalog.create_kb("ds-prod", "产品知识库", "", ragflow_dataset_id="ds-prod")
    catalog.create_employee({"id": "xiaoxiao", "name": "客户经理", "kbs": []})

    catalog.backfill_employee_kb_assignments()
    cfg = catalog.get_employee_config("xiaoxiao")
    assert cfg["kb_ragflow_datasets"] == {"ds-cust": "ds-cust", "ds-prod": "ds-prod"}

    catalog.backfill_employee_kb_assignments()
    cfg2 = catalog.get_employee_config("xiaoxiao")
    assert set(cfg2["kb_ragflow_datasets"]) == {"ds-cust", "ds-prod"}


# ---- SOP ----

def test_sop_crud():
    catalog.create_sop("sop1", "SOP1", "d", "content")
    assert catalog.get_sop("sop1")["content"] == "content"
    assert catalog.update_sop("sop1", "SOP改", "d2", "c2")
    assert catalog.get_sop("sop1")["name"] == "SOP改"
    catalog.delete_sop("sop1")
    assert catalog.get_sop("sop1") is None


# ---- 连接器 ----

def test_connector_crud():
    catalog.create_connector("c1", "连接器1", "d", {"transport": "stdio"})
    c = catalog.get_connector("c1")
    assert c["config"]["transport"] == "stdio"
    assert catalog.update_connector("c1", "改", "d2", {"transport": "stdio", "command": "x"})
    assert catalog.get_connector("c1")["config"]["command"] == "x"
    catalog.delete_connector("c1")
    assert catalog.get_connector("c1") is None


# ---- 技能 upsert ----

def test_skill_upsert_and_delete():
    catalog.upsert_skill("sk1", "技能1", "d", "skills/sk1")
    assert catalog.get_skill("sk1")["dir"] == "skills/sk1"
    catalog.upsert_skill("sk1", "技能改", "d2", "skills-custom/sk1")  # 同 id 更新
    assert catalog.get_skill("sk1")["dir"] == "skills-custom/sk1"
    catalog.delete_skill("sk1")
    assert catalog.get_skill("sk1") is None


# ---- 市场情报 V2：发布审批工具 ----

def test_backfill_market_intel_publish_tool():
    """publish_briefing 登记 + market-intel 指派，needs_approval 派生审批中断。"""
    catalog.init()
    catalog.seed_if_empty()
    catalog.backfill_market_intel_v2()

    con = sqlite3.connect(str(catalog.db.DB))
    row = con.execute(
        "SELECT needs_approval FROM tools WHERE id='publish_briefing'").fetchone()
    con.close()
    assert row, "publish_briefing 必须登记进 tools 表"
    assert json.loads(row[0]) == ["approve", "reject"]

    cfg = catalog.get_employee_config("market-intel")
    assert "publish_briefing" in cfg["tools"]
    # 编译层据此自动派生 interrupt_on（发布前挂人工审批）
    assert cfg["interrupt_on"].get("publish_briefing") == {
        "allowed_decisions": ["approve", "reject"]}

    # 模拟老库（工具未登记/未指派）→ backfill 幂等补回
    con = sqlite3.connect(str(catalog.db.DB))
    con.execute("DELETE FROM employee_tools WHERE employee_id='market-intel'"
                " AND tool_id='publish_briefing'")
    con.execute("DELETE FROM tools WHERE id='publish_briefing'")
    con.commit()
    con.close()
    catalog.backfill_market_intel_v2()
    cfg = catalog.get_employee_config("market-intel")
    assert "publish_briefing" in cfg["tools"]


def test_publish_briefing_archives_html(tmp_path, monkeypatch):
    """发布归档：写用户 briefings 目录、文件名清洗、HTML 兜底包装。"""
    from app.tools import publish_tools
    monkeypatch.setattr(publish_tools, "DATA_DIR", tmp_path)

    # 片段 HTML 自动包装成可打开的完整文档
    p1 = publish_tools.write_briefing("u1", "每日简报 · 2026/09/12", "<div>看板</div>")
    assert p1.exists() and p1.parent.name == "briefings"
    text = p1.read_text(encoding="utf-8")
    assert "<!DOCTYPE html>" in text and "<div>看板</div>" in text and "每日简报" in text

    # 完整 HTML 原样归档；文件名非法字符被清洗
    full = '<!DOCTYPE html><html lang="zh-CN"><body>完整看板</body></html>'
    p2 = publish_tools.write_briefing("u1", '竞品对标:声湃/X1?', full)
    assert "/" not in p2.name and ":" not in p2.name and "?" not in p2.name
    assert p2.read_text(encoding="utf-8") == full


def test_publish_briefing_registered_in_compiler():
    """编译层注册表必须包含 publish_briefing（员工按名挑选的前提）。"""
    from app.compiler import ALL_LOCAL_TOOLS
    assert "publish_briefing" in ALL_LOCAL_TOOLS
