"""软删除回归测试：实体软删（记录保留、列表不可见）、关联边硬删。"""
import sqlite3

from app import catalog, conversations


def _raw(db_path, sql, params=()):
    con = sqlite3.connect(str(db_path))
    con.row_factory = sqlite3.Row
    rows = con.execute(sql, params).fetchall()
    con.close()
    return [dict(r) for r in rows]


def test_user_soft_delete():
    uid = catalog.create_user("sd_user", "hash", user_id="u_sd1")
    assert catalog.get_user(uid)
    assert catalog.delete_user(uid) is True
    # 读取层不可见
    assert catalog.get_user(uid) is None
    assert catalog.get_user_by_username("sd_user") is None
    assert all(u["id"] != uid for u in catalog.list_users())
    # 物理记录仍在，deleted_at 已标记
    rows = _raw(catalog.db.DB, "SELECT * FROM users WHERE id=?", (uid,))
    assert len(rows) == 1 and rows[0]["deleted_at"]
    # 重复删返回 False（不重复标记）
    assert catalog.delete_user(uid) is False


def test_skill_soft_delete_and_links_hard_delete():
    catalog.upsert_skill("sd_skill", "软删技能", "desc", "skills-custom/sd_skill")
    emp_id = catalog.create_employee({"id": "sd_emp1", "name": "E1", "skills": ["sd_skill"]})
    assert "sd_emp1" in catalog.employees_using_skill("sd_skill")
    catalog.delete_skill("sd_skill")
    # 技能读取不可见，但物理行保留
    assert catalog.get_skill("sd_skill") is None
    rows = _raw(catalog.db.DB, "SELECT * FROM skills WHERE id=?", ("sd_skill",))
    assert len(rows) == 1 and rows[0]["deleted_at"]
    # 关联边硬删（employee_skills 里没有了）
    assert _raw(catalog.db.DB, "SELECT * FROM employee_skills WHERE skill_id=?", ("sd_skill",)) == []
    # 员工 effective config 不再含该技能
    cfg = catalog.get_employee_config(emp_id)
    assert "sd_skill" not in (cfg.get("skills") or [])


def test_kb_soft_delete_removes_links_without_local_entries():
    catalog.create_kb("sd_kb", "软删库")
    catalog.create_employee({"id": "sd_emp2", "name": "E2", "kbs": ["sd_kb"]})
    affected = catalog.delete_kb("sd_kb")
    assert "sd_emp2" in affected
    # 库读取不可见
    assert catalog.get_kb("sd_kb") is None
    # 物理行保留且被标记
    kb_rows = _raw(catalog.db.DB, "SELECT * FROM knowledge_bases WHERE id=?", ("sd_kb",))
    assert kb_rows[0]["deleted_at"]
    # 关联边硬删
    assert _raw(catalog.db.DB, "SELECT * FROM employee_kbs WHERE kb_id=?", ("sd_kb",)) == []


def test_legacy_kb_entries_are_retired_by_migration():
    con = sqlite3.connect(str(catalog.db.DB))
    con.execute(
        "CREATE TABLE kb_entries(id TEXT PRIMARY KEY, kb_id TEXT, title TEXT, keywords TEXT, content TEXT)"
    )
    con.execute(
        "INSERT INTO kb_entries(id,kb_id,title,keywords,content) VALUES(?,?,?,?,?)",
        ("legacy_e1", "legacy_kb", "旧条目", "[]", "演示内容"),
    )
    con.commit()
    con.close()

    catalog.init()

    rows = _raw(catalog.db.DB, "SELECT * FROM kb_entries WHERE id=?", ("legacy_e1",))
    assert rows[0]["deleted_at"]


def test_sop_connector_employee_soft_delete():
    catalog.create_sop("sd_sop", "SOP", "d", "步骤")
    catalog.create_connector("sd_conn", "Conn", "d", {"url": "http://x"})
    catalog.create_employee({"id": "sd_emp3", "name": "E3",
                             "sops": ["sd_sop"], "connectors": ["sd_conn"]})
    catalog.delete_sop("sd_sop")
    catalog.delete_connector("sd_conn")
    catalog.delete_employee("sd_emp3")
    assert catalog.get_sop("sd_sop") is None
    assert catalog.get_connector("sd_conn") is None
    assert catalog.get_employee_config("sd_emp3") is None
    assert all(e["id"] != "sd_emp3" for e in catalog.list_employees_meta())
    for table, id_ in (("sops", "sd_sop"), ("connectors", "sd_conn"), ("employees", "sd_emp3")):
        rows = _raw(catalog.db.DB, f"SELECT * FROM {table} WHERE id=?", (id_,))
        assert len(rows) == 1 and rows[0]["deleted_at"], table
    # 员工的关联边全部硬删
    for table in ("employee_sops", "employee_connectors"):
        assert _raw(catalog.db.DB, f"SELECT * FROM {table} WHERE employee_id=?", ("sd_emp3",)) == []


def test_recreate_after_soft_delete_revives():
    """软删后同名/同 id 重建 = 复活（唯一键不再挡道）。"""
    # 用户：同名重建复活，沿用原 id、更新密码
    uid = catalog.create_user("rev_user", "h1", user_id="u_rev1")
    catalog.delete_user(uid)
    uid2 = catalog.create_user("rev_user", "h2")
    assert uid2 == uid
    u = catalog.get_user_by_username("rev_user")
    assert u and u["password_hash"] == "h2" and u["status"] == "active"
    # 员工：同 id 重建复活
    catalog.create_employee({"id": "rev_emp", "name": "老名"})
    catalog.delete_employee("rev_emp")
    catalog.create_employee({"id": "rev_emp", "name": "新名"})
    metas = {e["id"]: e for e in catalog.list_employees_meta()}
    assert "rev_emp" in metas and metas["rev_emp"]["name"] == "新名"
    # 技能/知识库/SOP/连接器：同 id 重建复活
    catalog.upsert_skill("rev_sk", "S", "d", "skills-custom/rev_sk")
    catalog.delete_skill("rev_sk")
    catalog.upsert_skill("rev_sk", "S2", "d", "skills-custom/rev_sk")
    assert catalog.get_skill("rev_sk")["name"] == "S2"
    catalog.create_sop("rev_sop", "P", "d", "c")
    catalog.delete_sop("rev_sop")
    catalog.create_sop("rev_sop", "P2", "d", "c")
    assert catalog.get_sop("rev_sop")["name"] == "P2"
    catalog.create_connector("rev_cn", "C", "d", {})
    catalog.delete_connector("rev_cn")
    catalog.create_connector("rev_cn", "C2", "d", {})
    assert catalog.get_connector("rev_cn")["name"] == "C2"
    # 会话：软删后再次 create 同 id = 复活
    conversations.create("c_rev", "xiaoshu", user_id="u_rev1")
    conversations.delete("c_rev")
    conversations.create("c_rev", "xiaoshu", user_id="u_rev1")
    assert conversations.exists("c_rev")


def test_conversation_soft_delete():
    conversations.create("c_sd1", "xiaoshu", title="软删会话", user_id="u_sd")
    assert conversations.exists("c_sd1")
    assert conversations.delete("c_sd1") is True
    # 读取层不可见
    assert conversations.exists("c_sd1") is False
    assert conversations.get("c_sd1") is None
    assert all(c["conv_id"] != "c_sd1" for c in conversations.list_for(user_id="u_sd"))
    assert conversations.list_paged(user_id="u_sd")["total"] == 0
    # 物理行保留
    rows = _raw(conversations.DB, "SELECT * FROM conversations WHERE conv_id=?", ("c_sd1",))
    assert len(rows) == 1 and rows[0]["deleted_at"]
    # 重复删返回 False
    assert conversations.delete("c_sd1") is False
