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
    assert len(schema["entity_types"]) == 15
    assert len(schema["relation_types"]) == 16
    codes = {t["code"] for t in schema["entity_types"]}
    assert {"org", "employee", "customer", "project", "contract", "order",
            "station", "area", "contact"} <= codes
    relation_codes = {t["code"] for t in schema["relation_types"]}
    assert {"sign", "decide"} <= relation_codes

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
    assert len(schema["entity_types"]) == 15


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


# ---------------- 关系展开 / 路径 / 场景查询 ----------------

def test_query_relations_enforces_tenant_scope():
    """跨租户实体 id 不能借关系查询探测，即使两端实体真实存在。"""
    ontology.init()
    ontology.seed_schema_if_empty()
    emp = ontology.create_entity("tenant-b", {
        "entity_type": "employee", "name": "租户B员工"})
    cus = ontology.create_entity("tenant-b", {
        "entity_type": "customer", "name": "租户B客户"})
    ontology.create_relation("tenant-b", {
        "from_id": emp, "to_id": cus, "relation_type": "follow_up"})

    assert ontology.query_relations("default", emp) == []
    assert ontology.query_relations("default", cus) == []
    assert len(ontology.query_relations("tenant-b", emp)) == 1


def test_expand_entity_returns_evidence_paths_and_honors_filters():
    ontology.init()
    ontology.seed_schema_if_empty()
    ontology.seed_netops_demo_if_empty()
    station = ontology.find_entities("default", "station", "BS-003")[0]

    graph = ontology.expand_entity("default", station["id"], depth=2)
    assert graph["center"]["name"] == "高新区1号基站"
    assert graph["truncated"] is False
    assert any(
        path["text"] == "高新区1号基站 -覆盖-> 高新区片区 <-居住于- 杭州智造科技"
        for path in graph["relation_paths"]
    )

    only_cover = ontology.expand_entity(
        "default", station["id"], depth=2, relation_types=["cover"])
    assert {edge["relation_type"] for edge in only_cover["edges"]} == {"cover"}
    assert all(step["relation_type"] == "cover"
               for path in only_cover["relation_paths"] for step in path["steps"])


def test_find_paths_to_entity_and_type():
    ontology.init()
    ontology.seed_schema_if_empty()
    ontology.seed_netops_demo_if_empty()
    station = ontology.find_entities("default", "station", "BS-003")[0]
    customer = ontology.find_entities("default", "customer", "杭州智造科技")[0]

    exact = ontology.find_paths(
        "default", station["id"], target_id=customer["id"], max_depth=2)
    assert len(exact) == 1
    assert exact[0]["hops"] == 2
    assert exact[0]["target"]["name"] == "杭州智造科技"
    assert "高新区片区" in exact[0]["text"]

    by_type = ontology.find_paths(
        "default", station["id"], target_type="customer", max_depth=2)
    assert {p["target"]["name"] for p in by_type} == {
        "杭州智造科技", "王秀英"}


def test_find_paths_more_business_scenarios():
    """扩展场景：客户签约产品、算力节点归属、基站回传链路。"""
    ontology.init()
    ontology.seed_schema_if_empty()
    ontology.seed_demo_if_empty()
    ontology.seed_netops_demo_if_empty()
    ontology.seed_netops_resources_if_empty()
    ontology.seed_crm_demo_if_empty()

    def entity(type_, name):
        return ontology.find_entities("default", type_, name)[0]

    geely = entity("customer", "吉利汽车")
    product = entity("product", "5G 专网")
    customer_paths = ontology.find_paths(
        "default", geely["id"], target_id=product["id"], max_depth=2)
    assert any(
        p["hops"] == 2
        and p["text"].startswith("吉利汽车 -签约-> HT-2025-0031 -包含-> 5G 专网")
        for p in customer_paths
    )

    node = entity("compute_node", "GPU训练节点01")
    datacenter = entity("datacenter", "滨江核心机房")
    resource_paths = ontology.find_paths(
        "default", node["id"], target_id=datacenter["id"], max_depth=1)
    assert len(resource_paths) == 1
    assert resource_paths[0]["text"] == "GPU训练节点01 -部署于-> 滨江核心机房"

    station = entity("station", "BS-003")
    link = entity("link", "高新-下沙光缆")
    backhaul_paths = ontology.find_paths(
        "default", station["id"], target_id=link["id"], max_depth=1)
    assert len(backhaul_paths) == 1
    assert backhaul_paths[0]["text"] == "高新区1号基站 -回传-> 高新-下沙光缆"


def test_expand_customer_context_contains_contracts_and_products():
    ontology.init()
    ontology.seed_schema_if_empty()
    ontology.seed_crm_demo_if_empty()

    geely = ontology.find_entities("default", "customer", "吉利汽车")[0]
    graph = ontology.expand_entity("default", geely["id"], depth=2)
    nodes = {n["name"]: n for n in graph["nodes"]}
    edges = {(e["relation_type"], e["from"]["name"], e["to"]["name"])
             for e in graph["edges"]}

    assert {"HT-2025-0031", "HT-2025-0044", "5G 专网", "联通云"} <= set(nodes)
    assert ("sign", "吉利汽车", "HT-2025-0031") in edges
    assert ("include", "HT-2025-0031", "5G 专网") in edges


def test_customer_360_scenario():
    ontology.init()
    ontology.seed_schema_if_empty()
    ontology.seed_crm_demo_if_empty()

    out = ontology.customer_360("default", "吉利汽车")
    assert out["customer"]["name"] == "吉利汽车"
    assert [x["name"] for x in out["account_owners"]] == ["万仁刚"]
    assert {x["name"] for x in out["contacts"]} == {"李总监", "王工"}
    assert {x["name"] for x in out["projects"]} == {
        "极氪工厂 5G 专网二期", "车联网数据合规平台", "视频云园区安防扩容"}
    assert "HT-2025-0031" in {x["name"] for x in out["contracts"]}
    assert "联通云" in {x["name"] for x in out["products"]}
    assert any("-签约->" in p["text"] for p in out["relation_paths"])


def test_customer_360_zero_run():
    ontology.init()
    ontology.seed_schema_if_empty()
    ontology.seed_crm_demo_if_empty()

    out = ontology.customer_360("default", "零跑汽车")
    assert [x["name"] for x in out["account_owners"]] == ["万仁刚"]
    assert [x["name"] for x in out["contacts"]] == ["陈经理"]
    assert {x["name"] for x in out["contracts"]} == {
        "HT-2025-0089", "HT-2026-0007"}
    assert {x["name"] for x in out["products"]} == {
        "SD-WAN 智选专线", "联通云"}


def test_fault_impact_scenario():
    ontology.init()
    ontology.seed_schema_if_empty()
    ontology.seed_netops_demo_if_empty()
    ontology.seed_netops_resources_if_empty()

    out = ontology.fault_impact("default", "BS-003")
    assert out["station"]["name"] == "高新区1号基站"
    assert [x["name"] for x in out["areas"]] == ["高新区片区"]
    assert {x["name"] for x in out["affected_customers"]} == {
        "杭州智造科技", "王秀英"}
    assert [x["name"] for x in out["vip_customers"]] == ["杭州智造科技"]
    assert [x["name"] for x in out["maintainers"]] == ["赵敏"]
    assert [x["name"] for x in out["backhaul_links"]] == ["高新-下沙光缆"]


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


def test_ontology_scenario_tools_are_gated_and_tenant_bound():
    import json as _json
    from app.tools.ontology_tools import make_ontology_tools

    ontology.init()
    ontology.seed_schema_if_empty()
    ontology.seed_netops_demo_if_empty()
    ontology.seed_crm_demo_if_empty()

    general = {t.name for t in make_ontology_tools(None)}
    assert {
        "ontology_find_entities", "ontology_query_relations",
        "ontology_expand", "ontology_find_paths",
    } <= general
    assert "ontology_customer_360" not in general
    assert "ontology_fault_impact" not in general

    tools = {t.name: t for t in make_ontology_tools(
        None, include_customer_360=True, include_fault_impact=True)}
    customer = _json.loads(tools["ontology_customer_360"].invoke(
        {"customer_name": "吉利汽车"}))
    fault = _json.loads(tools["ontology_fault_impact"].invoke(
        {"station_name": "BS-003"}))
    assert customer["customer"]["name"] == "吉利汽车"
    assert fault["vip_customers"][0]["name"] == "杭州智造科技"


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
