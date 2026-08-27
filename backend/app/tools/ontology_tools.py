"""企业业务本体运行时工具（闭包：绑定当前用户的 tenant_id）。

与 kb_search 同类：不在 ALL_LOCAL_TOOLS 静态登记，由 compiler._assemble_tools
按用户动态生成，保证查询只落在当前租户的业务数据上。

两个工具：
  ontology_find_entities   按实体类型/关键词查业务实体
  ontology_query_relations 沿实体关系走一跳，返回关联对象
"""

import json

from langchain_core.tools import tool

from app import catalog, ontology


def make_ontology_tools(user_id: str | None) -> list:
    """按用户视角动态生成 ontology_* 工具（业务本体查询，按 tenant 隔离）。"""
    tenant = "default"
    if user_id:
        u = catalog.get_user(user_id)
        if u:
            tenant = u.get("tenant_id") or "default"

    def _fmt(items: list) -> str:
        if not items:
            return "（未找到相关记录）"
        return json.dumps(items, ensure_ascii=False, indent=1)

    @tool
    def ontology_find_entities(entity_type: str = "", keyword: str = "") -> str:
        """【企业业务本体查询】按实体类型和/或关键词查找业务实体。

        实体类型：org(组织)/department(部门)/position(岗位)/employee(员工)/
        customer(客户)/product(产品)/project(项目)/contract(合同)/order(订单)/
        station(基站)/area(片区)。
        涉及公司内部的人、部门、客户、项目、合同、订单、产品信息，或网络运营的
        基站、片区信息时，先调用本工具拿到实体 id，再配合 ontology_query_relations
        展开其关联关系。
        """
        items = ontology.find_entities(
            tenant,
            entity_type=entity_type.strip() or None,
            keyword=keyword.strip() or None,
            limit=20,
        )
        return _fmt(items)

    @tool
    def ontology_query_relations(entity_id: int, relation_type: str = "", direction: str = "any") -> str:
        """【企业业务本体关系查询】沿某实体的关系走一跳，返回其关联对象。

        关系类型：belong_to(隶属于)/belongs_to(属于)/hold_position(担任)/
        manage(负责)/follow_up(跟进)/serve(服务)/correspond_to(对应)/
        place_order(下单)/include(包含)/cover(基站覆盖片区)/
        maintain(员工维护基站)/located_in(客户位于片区)。direction: any/out/in。
        查询"某人负责哪些项目、跟进哪些客户、某客户下过哪些订单、
        某基站覆盖哪些片区、片区里有哪些客户、谁维护某基站"等时使用，
        可连续多跳（如基站→片区→客户）。通常先 ontology_find_entities
        拿到实体 id 再调用本工具。
        """
        rows = ontology.query_relations(
            tenant,
            entity_id=entity_id,
            relation_type=relation_type.strip() or None,
            direction=direction.strip() or "any",
        )
        return _fmt(rows)

    return [ontology_find_entities, ontology_query_relations]
