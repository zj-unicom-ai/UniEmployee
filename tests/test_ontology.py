"""企业业务本体（ontology.db）回归测试：schema 种子 / 实例种子 / CRUD / 运行时查询。"""
from app import ontology


def test_seed_schema_and_demo_are_idempotent():
    ontology.init()
    ontology.seed_schema_if_empty()
    ontology.seed_demo_if_empty()
    # 再跑一次不重复播种
    ontology.seed_schema_if_empty()
    ontology.seed_demo_if_empty()

    schema = ontology.list_schema("default")
    assert len(schema["entity_types"]) == 14
    assert len(schema["relation_types"]) == 14
    codes = {t["code"] for t in schema["entity_types"]}
    assert {"org", "employee", "customer", "project", "contract", "order",
            "station", "area"} <= codes

    stats = ontology.stats("default")
    assert stats["total_entities"] == 35
    assert stats["total_relations"] == 36


def test_find_and_query_relations_chain():
    ontology.init()
    ontology.seed_schema_if_empty()
    ontology.seed_demo_if_empty()

    # 李晓芳 → 华芯智慧工厂（manage）→ 合同 HT-2026-001
    lx = ontology.find_entities("default", entity_type="employee", keyword="李晓芳")
    assert len(lx) == 1
    lx_id = lx[0]["id"]

    rels = ontology.query_relations("default", lx_id)
    managed = [r["target"] for r in rels if r["relation_type"] == "manage"]
    assert len(managed) == 1
    assert managed[0]["name"] == "华芯智慧工厂"

    # 只查 out 方向 + 指定关系类型
    followed = ontology.query_relations("default", lx_id, relation_type="follow_up", direction="out")
    assert {r["target"]["name"] for r in followed} == {"华芯半导体", "云帆物流"}

    # 华芯半导体下单链路
    hx = ontology.find_entities("default", entity_type="customer", keyword="华芯")
    orders = ontology.query_relations("default", hx[0]["id"], relation_type="place_order", direction="out")
    assert {r["target"]["name"] for r in orders} == {"SO-1001", "SO-1002"}


def test_tenant_isolation():
    ontology.init()
    ontology.seed_schema_if_empty()
    ontology.seed_demo_if_empty()

    # 另一个租户看不到 default 的演示实体
    assert ontology.find_entities("tenant-b", keyword="李晓芳") == []
    assert ontology.stats("tenant-b")["total_entities"] == 0
    # system 预置 schema 对任何租户可见
    schema = ontology.list_schema("tenant-b")
    assert len(schema["entity_types"]) == 14


def test_entity_and_relation_crud():
    ontology.init()
    ontology.seed_schema_if_empty()

    emp = ontology.create_entity("default", {"entity_type": "employee", "name": "测试员工"})
    cus = ontology.create_entity("default", {
        "entity_type": "customer", "name": "测试客户", "props": {"grade": "A级"}})
    e = ontology.get_entity("default", cus)
    assert e["name"] == "测试客户"
    assert e["props"]["grade"] == "A级"

    ontology.update_entity("default", cus, {
        "entity_type": "customer", "name": "改名客户", "props": {"grade": "B级"}})
    assert ontology.get_entity("default", cus)["props"]["grade"] == "B级"

    rid = ontology.create_relation("default", {"from_id": emp, "to_id": cus, "relation_type": "follow_up"})
    assert len(ontology.list_relations("default", cus)) == 1
    ontology.delete_relation("default", rid)
    assert ontology.list_relations("default", cus) == []

    ontology.delete_entity("default", cus)
    assert ontology.get_entity("default", cus) is None

    # 校验：必填缺失 / 类型不存在 / 非法实体类型
    try:
        ontology.create_entity("default", {"entity_type": "customer", "name": ""})
        assert False, "应抛出 ValueError"
    except ValueError:
        pass
    try:
        ontology.create_entity("default", {"entity_type": "vendor", "name": "某供应商"})
        assert False, "实体类型不存在应抛出 ValueError"
    except ValueError:
        pass


def test_relation_constraint_validation():
    ontology.init()
    ontology.seed_schema_if_empty()

    emp = ontology.create_entity("default", {"entity_type": "employee", "name": "测试员工"})
    cus = ontology.create_entity("default", {"entity_type": "customer", "name": "测试客户"})

    # 关系类型不存在
    try:
        ontology.create_relation("default", {"from_id": emp, "to_id": cus, "relation_type": "no_such_rel"})
        assert False, "关系类型不存在应抛出 ValueError"
    except ValueError:
        pass

    # 端点实体类型与关系 from_type/to_type 不匹配（belongs_to 要求 employee→department）
    try:
        ontology.create_relation("default", {"from_id": emp, "to_id": cus, "relation_type": "belongs_to"})
        assert False, "类型不匹配应抛出 ValueError"
    except ValueError:
        pass

    # 合法关系可建
    rid = ontology.create_relation("default", {"from_id": emp, "to_id": cus, "relation_type": "follow_up"})
    assert len(ontology.list_relations("default")) == 1
    ontology.delete_relation("default", rid)


def test_system_schema_is_editable():
    ontology.init()
    ontology.seed_schema_if_empty()
    sys_et = ontology.list_schema("default")["entity_types"][0]
    sys_rt = ontology.list_schema("default")["relation_types"][0]

    # 系统预置类型可编辑（code 不可改，name/属性等可改）
    ontology.update_entity_type("default", sys_et["id"], {"name": "改名", "description": "d", "icon": "🏷️", "attrs": []})
    got = [t for t in ontology.list_schema("default")["entity_types"] if t["id"] == sys_et["id"]][0]
    assert got["name"] == "改名"
    ontology.update_relation_type("default", sys_rt["id"], {"name": "隶属于2", "description": "d"})
    got_rt = [t for t in ontology.list_schema("default")["relation_types"] if t["id"] == sys_rt["id"]][0]
    assert got_rt["name"] == "隶属于2"

    # 系统预置类型可删除
    ontology.delete_entity_type("default", sys_et["id"])
    assert not any(t["id"] == sys_et["id"] for t in ontology.list_schema("default")["entity_types"])
    ontology.delete_relation_type("default", sys_rt["id"])
    assert not any(t["id"] == sys_rt["id"] for t in ontology.list_schema("default")["relation_types"])

    # 租户自定义类型可建可删
    cid = ontology.create_entity_type("default", {"code": "vendor", "name": "供应商", "attrs": []})
    assert any(t["code"] == "vendor" for t in ontology.list_schema("default")["entity_types"])
    ontology.delete_entity_type("default", cid)
    assert not any(t["code"] == "vendor" for t in ontology.list_schema("default")["entity_types"])


def test_make_ontology_tools_bind_tenant():
    from app.tools.ontology_tools import make_ontology_tools

    ontology.init()
    ontology.seed_schema_if_empty()
    ontology.seed_demo_if_empty()

    tools = {t.name: t for t in make_ontology_tools(None)}
    assert "ontology_find_entities" in tools and "ontology_query_relations" in tools

    import json as _json
    out = _json.loads(tools["ontology_find_entities"].invoke(
        {"entity_type": "employee", "keyword": "李晓芳"}))
    assert out[0]["name"] == "李晓芳"
    rels = _json.loads(tools["ontology_query_relations"].invoke(
        {"entity_id": out[0]["id"], "relation_type": "manage"}))
    assert rels[0]["target"]["name"] == "华芯智慧工厂"


def test_netops_demo_seed_and_multihop_chain():
    """网络运营演示种子 + 故障影响分析多跳链：基站→片区→客户 / 基站→装维。"""
    ontology.init()
    ontology.seed_schema_if_empty()
    ontology.seed_netops_demo_if_empty()
    # 幂等
    ontology.seed_netops_demo_if_empty()

    # 老库补新 schema 类型（station/area 实体类型已随 seed 播种，这里验证幂等）
    ontology.backfill_schema_types()
    schema = ontology.list_schema("default")
    codes = {t["code"] for t in schema["entity_types"]}
    assert {"station", "area"} <= codes
    rcodes = {t["code"] for t in schema["relation_types"]}
    assert {"cover", "maintain", "located_in"} <= rcodes

    # 多跳链1：退服基站 BS-003 → 高新区片区 → 受影响客户（VIP：杭州智造科技）
    st = ontology.find_entities("default", entity_type="station", keyword="BS-003")
    assert len(st) == 1 and st[0]["status"] == "退服"
    areas = ontology.query_relations("default", st[0]["id"], relation_type="cover")
    assert [a["target"]["name"] for a in areas] == ["高新区片区"]
    customers = ontology.query_relations(
        "default", areas[0]["target"]["id"], relation_type="located_in", direction="in")
    names = {c["target"]["name"] for c in customers}
    assert names == {"杭州智造科技", "王秀英"}
    vip = [c["target"] for c in customers if c["target"].get("grade") == "VIP"]
    assert [v["name"] for v in vip] == ["杭州智造科技"]

    # 多跳链2：基站 → 装维负责人（maintain 入边）
    maintainers = ontology.query_relations(
        "default", st[0]["id"], relation_type="maintain", direction="in")
    assert [m["target"]["name"] for m in maintainers] == ["赵敏"]
    assert maintainers[0]["target"]["phone"] == "13800001003"


def test_netops_demo_seed_skips_when_station_exists():
    """已有基站实体的库不重复播种（保护管理员手工录入的网络数据）。"""
    ontology.init()
    ontology.seed_schema_if_empty()
    ontology.create_entity("default", {"entity_type": "station", "name": "既有基站",
                                        "props": {"code": "BS-999"}})
    ontology.seed_netops_demo_if_empty()
    assert ontology.find_entities("default", entity_type="customer", keyword="星联") == []
    assert ontology.find_entities("default", entity_type="org", keyword="星联") == []


# ---------------- 对话写回（ontology_write / source 溯源） ----------------

def test_seed_rows_default_source_and_migration_idempotent():
    """老库迁移补列后，种子数据 source=seed；init 重复执行不报错。"""
    ontology.init()
    ontology.init()  # 幂等
    ontology.seed_schema_if_empty()
    ontology.seed_demo_if_empty()
    lx = ontology.find_entities("default", entity_type="employee", keyword="李晓芳")[0]
    row = ontology.get_entity("default", lx["id"])
    assert row["source"] == "seed"
    assert row["source_ref"] is None and row["created_by"] is None
    rels = ontology.list_relations("default", lx["id"])
    assert rels and all(r["source"] == "seed" for r in rels)


def test_patch_entity_merges_props_and_tags_chat_source():
    """聊天写回的增量更新：props 浅合并不抹其他字段，None 删键，溯源三列落标。"""
    ontology.init()
    ontology.seed_schema_if_empty()
    eid = ontology.create_entity("default", {
        "entity_type": "employee", "name": "王工",
        "props": {"title": "网络运维主管", "phone": "13900000000"}})

    before, after = ontology.patch_entity(
        "default", eid, {"title": "信息化部副总监", "phone": None},
        source=ontology.SOURCE_CHAT, source_ref="conv-1", created_by="u1")

    assert before["props"]["title"] == "网络运维主管"
    assert after["props"]["title"] == "信息化部副总监"
    assert "phone" not in after["props"]
    assert after["source"] == "chat"
    assert after["source_ref"] == "conv-1"
    assert after["created_by"] == "u1"


def test_resolve_entity_exact_fuzzy_and_ambiguous():
    ontology.init()
    ontology.seed_schema_if_empty()
    ontology.create_entity("default", {"entity_type": "customer", "name": "杭州智造科技"})
    ontology.create_entity("default", {"entity_type": "customer", "name": "杭州物流科技"})

    # 精确名优先
    assert ontology.resolve_entity("default", "customer", "杭州智造科技")["name"] == "杭州智造科技"
    # 唯一包含匹配（忽略大小写）
    assert ontology.resolve_entity("default", "customer", "智造")["name"] == "杭州智造科技"
    # 歧义 / 未命中报错
    try:
        ontology.resolve_entity("default", "customer", "杭州")
        assert False, "多候选应歧义报错"
    except ValueError as e:
        assert "多个" in str(e)
    try:
        ontology.resolve_entity("default", "customer", "不存在的客户")
        assert False, "0 候选应报错"
    except ValueError:
        pass


def test_chat_create_relation_tagged_and_idempotent():
    ontology.init()
    ontology.seed_schema_if_empty()
    emp = ontology.create_entity("default", {"entity_type": "employee", "name": "测试员工"})
    cus = ontology.create_entity("default", {"entity_type": "customer", "name": "测试客户"})
    rid = ontology.create_relation(
        "default", {"from_id": emp, "to_id": cus, "relation_type": "follow_up"},
        source=ontology.SOURCE_CHAT, source_ref="conv-9", created_by="u2")
    again = ontology.create_relation(
        "default", {"from_id": emp, "to_id": cus, "relation_type": "follow_up"},
        source=ontology.SOURCE_CHAT)
    assert rid == again  # 同类型重边去重
    rows = ontology.list_relations("default", cus)
    assert len(rows) == 1 and rows[0]["source"] == "chat"
    assert rows[0]["source_ref"] == "conv-9" and rows[0]["created_by"] == "u2"


def test_ontology_write_tool_gate():
    """未授权（include_write=False）工具集里不存在 ontology_write。"""
    from app.tools.ontology_tools import make_ontology_tools
    ontology.init()
    assert "ontology_write" not in {t.name for t in make_ontology_tools(None)}
    assert "ontology_write" not in {
        t.name for t in make_ontology_tools(None, include_reads=True, include_write=False)}
    writable = {t.name for t in make_ontology_tools(
        None, include_reads=True, include_write=True)}
    assert {"ontology_find_entities", "ontology_query_relations", "ontology_write"} <= writable


def test_ontology_write_tool_full_flow_and_audit():
    """工具级闭环：新增→查重拒绝→合并更新→按名建关系→重边去重 + 审计 + 溯源。"""
    import json as _json
    from app import audit, catalog
    from app.tools.ontology_tools import make_ontology_tools

    ontology.init()
    ontology.seed_schema_if_empty()
    ontology.seed_demo_if_empty()
    uid = catalog.create_user("alice", "hash", tenant_id="default")
    tools = {t.name: t for t in make_ontology_tools(uid, include_write=True)}
    wt = tools["ontology_write"]
    cfg = {"configurable": {"thread_id": "conv-77"}}

    # 1) 新增实体
    r = _json.loads(wt.invoke({
        "op": "create_entity", "entity_type": "customer",
        "name": "写回测试客户", "props": {"grade": "A级"}}, config=cfg))
    assert r["ok"] is True
    cid = r["id"]
    row = ontology.get_entity("default", cid)
    assert row["source"] == "chat" and row["source_ref"] == "conv-77"
    assert row["created_by"] == uid and row["props"]["grade"] == "A级"

    # 2) 同名重复新增被拒（提示走 update）
    dup = _json.loads(wt.invoke({"op": "create_entity", "entity_type": "customer",
                                 "name": "写回测试客户"}, config=cfg))
    assert dup["ok"] is False and "update_entity" in dup["error"]

    # 3) 合并更新：原属性保留，新属性并入
    upd = _json.loads(wt.invoke({
        "op": "update_entity", "entity_id": cid,
        "props": {"contact": "张工"}}, config=cfg))
    assert upd["ok"] is True
    row = ontology.get_entity("default", cid)
    assert row["props"] == {"grade": "A级", "contact": "张工"}

    # 4) 按类型+名称建关系（李晓芳 follow_up 写回测试客户）
    rel = _json.loads(wt.invoke({
        "op": "create_relation", "relation_type": "follow_up",
        "from_type": "employee", "from_name": "李晓芳",
        "to_type": "customer", "to_name": "写回测试客户"}, config=cfg))
    assert rel["ok"] is True and rel["created"] is True
    rid = rel["id"]
    # 再来一次：同类型重边去重，返回同一 id 且 created=false（no-op 不记审计）
    rel2 = _json.loads(wt.invoke({
        "op": "create_relation", "relation_type": "follow_up",
        "from_type": "employee", "from_name": "李晓芳",
        "to_type": "customer", "to_name": "写回测试客户"}, config=cfg))
    assert rel2["ok"] is True and rel2["id"] == rid and rel2["created"] is False
    assert len(ontology.list_relations("default", cid)) == 1

    # 5) schema 类型不符 → ok=false（customer→employee 的 follow_up 非法）
    bad = _json.loads(wt.invoke({
        "op": "create_relation", "relation_type": "follow_up",
        "from_type": "customer", "from_name": "写回测试客户",
        "to_type": "employee", "to_name": "李晓芳"}, config=cfg))
    assert bad["ok"] is False and "要求" in bad["error"]

    # 6) 未知 op / 缺参 → ok=false
    assert _json.loads(wt.invoke({"op": "drop_all"}, config=cfg))["ok"] is False
    assert _json.loads(wt.invoke({"op": "update_entity"}, config=cfg))["ok"] is False

    # 7) 审计日志齐全（实体 2 条 + 关系 1 条），操作人为当前用户
    ent_logs, ent_total = audit.list_logs(obj_type="ontology_entity", limit=50)
    rel_logs, rel_total = audit.list_logs(obj_type="ontology_relation", limit=50)
    assert ent_total == 2 and rel_total == 1
    assert {l["action"] for l in ent_logs} == {"chat_create_entity", "chat_update_entity"}
    assert rel_logs[0]["action"] == "chat_create_relation"
    assert all(l["actor_id"] == uid for l in ent_logs + rel_logs)


def test_ontology_write_tool_respects_tenant_isolation():
    """跨租户写回：看不到别租户实体，名称解析失败、写不进对方数据。"""
    import json as _json
    from app import catalog
    from app.tools.ontology_tools import make_ontology_tools

    ontology.init()
    ontology.seed_schema_if_empty()
    ontology.seed_demo_if_empty()
    uid_b = catalog.create_user("bob", "hash", tenant_id="tenant-b")
    wt = {t.name: t for t in make_ontology_tools(uid_b, include_write=True)}["ontology_write"]

    r = _json.loads(wt.invoke({
        "op": "create_relation", "relation_type": "follow_up",
        "from_type": "employee", "from_name": "李晓芳",
        "to_type": "customer", "to_name": "华芯半导体"}))
    assert r["ok"] is False and "未找到" in r["error"]
    assert ontology.stats("tenant-b")["total_entities"] == 0
