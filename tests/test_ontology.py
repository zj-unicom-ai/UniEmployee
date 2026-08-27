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
    assert len(schema["entity_types"]) == 11
    assert len(schema["relation_types"]) == 12
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
    assert len(schema["entity_types"]) == 11


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
