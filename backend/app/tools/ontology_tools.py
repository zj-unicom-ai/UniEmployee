"""企业业务本体运行时工具（闭包：绑定当前用户的 tenant_id）。

与 kb_search 同类：不在 ALL_LOCAL_TOOLS 静态登记，由 compiler._assemble_tools
按用户动态生成，保证读写只落在当前租户的业务数据上。

三个工具：
  ontology_find_entities    按实体类型/关键词查业务实体
  ontology_query_relations  沿实体关系走一跳，返回关联对象
  ontology_write            对话写回（新增/更新实体、建立关系）

装配红线：ontology_write 只有员工在资源中心显式勾选「企业本体写回」时才注入
（include_write=True）；未授权员工的工具集里根本不存在该工具，模型无法调用。
每次写回按 source='chat' + 会话 id 溯源，并写审计日志。
"""

import json
from typing import Any, Optional

from langchain_core.tools import tool
from langgraph.config import get_config

from app import audit, catalog, ontology


def make_ontology_tools(user_id: str | None, include_reads: bool = True,
                        include_write: bool = False) -> list:
    """按用户视角动态生成 ontology_* 工具（按 tenant 隔离）。

    include_reads: 员工声明了任一查询工具时为真，注入两个只读工具。
    include_write: 仅当员工显式声明 ontology_write 时为真，注入写回工具。
    """
    tenant = "default"
    username = ""
    if user_id:
        u = catalog.get_user(user_id)
        if u:
            tenant = u.get("tenant_id") or "default"
            username = u.get("username") or ""

    def _fmt(items: list) -> str:
        if not items:
            return "（未找到相关记录）"
        return json.dumps(items, ensure_ascii=False, indent=1)

    tools = []

    if include_reads:
        @tool
        def ontology_find_entities(entity_type: str = "", keyword: str = "") -> str:
            """【企业业务本体查询】按实体类型和/或关键词查找业务实体。

            实体类型：org(组织)/department(部门)/position(岗位)/employee(员工)/
            customer(客户)/contact(客户联系人)/product(产品)/project(项目)/
            contract(合同)/order(订单)/station(基站)/area(片区)。
            涉及公司内部的人、部门、客户、联系人、项目、合同、订单、产品信息，或网络运营的
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
        def ontology_query_relations(entity_id: int, relation_type: str = "",
                                     direction: str = "any") -> str:
            """【企业业务本体关系查询】沿某实体的关系走一跳，返回其关联对象。

            关系类型：belong_to(隶属于)/belongs_to(属于)/hold_position(担任)/
            manage(负责)/follow_up(跟进)/serve(服务)/correspond_to(对应)/
            sign(签约)/decide(决策)/place_order(下单)/include(包含)/
            cover(基站覆盖片区)/maintain(维护对接)/located_in(客户位于片区)。
            direction: any/out/in。
            查询"某人负责哪些项目、跟进哪些客户、某客户签约了哪些合同、
            某合同包含哪些产品、某商机对应哪份合同、联系人中谁是决策人/技术对接人、
            某基站覆盖哪些片区"等时使用，可连续多跳（如基站→片区→客户）。
            通常先 ontology_find_entities 拿到实体 id 再调用本工具。
            """
            rows = ontology.query_relations(
                tenant,
                entity_id=entity_id,
                relation_type=relation_type.strip() or None,
                direction=direction.strip() or "any",
            )
            return _fmt(rows)

        tools += [ontology_find_entities, ontology_query_relations]

    if include_write:
        def _conv_id() -> str:
            """从 LangGraph 运行时配置取当前会话 id（写回归宿），取不到留空。"""
            try:
                return (get_config() or {}).get("configurable", {}).get("thread_id", "") or ""
            except Exception:
                return ""

        def _audit(action: str, obj_type: str, obj_id, before, after) -> None:
            # 审计旁路：写失败不阻断业务（audit.log 内部已吞异常）。
            audit.log(action=action, obj_type=obj_type, obj_id=str(obj_id or ""),
                      admin={"id": user_id or "", "username": username},
                      before=before, after=after)

        @tool
        def ontology_write(
            op: str,
            entity_type: str = "",
            name: str = "",
            entity_id: int = 0,
            props: Optional[dict[str, Any]] = None,
            relation_type: str = "",
            from_id: int = 0,
            to_id: int = 0,
            from_type: str = "",
            from_name: str = "",
            to_type: str = "",
            to_name: str = "",
            rel_props: Optional[dict[str, Any]] = None,
        ) -> str:
            """【企业业务本体写回】把用户在对话中明确陈述的业务事实写入企业本体
            （全企业共享，其他数字员工也能查到），并自动记录来源会话与操作审计。

            仅在用户明确要求"记一下/记录/更新/新增/把…录到本体/建立…关系"时调用；
            只写用户亲口确认的事实，禁止推测或补全，信息不全先向用户追问确认。
            写之前先用 ontology_find_entities 查一下，避免重复新建。

            op 支持三种操作：
            - create_entity：新增实体。参数 entity_type（如 employee/customer/contact/
              project/contract/product/station/area 等）、name、props（属性对象）。
              同类型下已存在同名实体时会拒绝，提示改用 update_entity。
            - update_entity：更新实体（属性按 key 合并，不会抹掉其他属性）。
              参数 entity_id（必填，先 find 拿到）、props（要更新的属性，如
              {"title": "信息化部副总监"}）、name（可选，改名时传）。
            - create_relation：在两个实体间建立关系边。relation_type 必填
              （如 follow_up 跟进/manage 负责/belongs_to 属于/hold_position 担任/
              serve 服务/include 包含/correspond_to 对应/maintain 维护/cover 覆盖）。
              端点用 id 指定：from_id/to_id；或用类型+名称指定：
              from_type+from_name、to_type+to_name（自动解析，歧义会报错）。
              端点类型必须符合该关系的 schema 约束，同类型重边自动去重。

            返回 JSON：ok=true 时带写入结果；ok=false 时 error 说明原因（可据以纠正参数
            或向用户澄清），不要把失败当成功告知用户。
            """
            ref = _conv_id()
            common = dict(source=ontology.SOURCE_CHAT, source_ref=ref,
                          created_by=user_id)
            try:
                if op == "create_entity":
                    etype = entity_type.strip()
                    ename = name.strip()
                    if not etype or not ename:
                        raise ValueError("create_entity 需要 entity_type 与 name")
                    existed = ontology.find_entities(
                        tenant, entity_type=etype, keyword=ename, limit=20)
                    dup = [e for e in existed if e.get("name") == ename]
                    if dup:
                        raise ValueError(
                            f"已存在 {etype}「{ename}」(id={dup[0]['id']})，"
                            "更新信息请用 op=update_entity")
                    new_id = ontology.create_entity(
                        tenant,
                        {"entity_type": etype, "name": ename,
                         "props": props or {}},
                        **common)
                    after = ontology.get_entity(tenant, new_id)
                    _audit("chat_create_entity", "ontology_entity", new_id, None, after)
                    return json.dumps(
                        {"ok": True, "op": op, "id": new_id, "entity": after,
                         "message": f"已新增 {etype}「{ename}」并记录到企业本体"},
                        ensure_ascii=False)

                if op == "update_entity":
                    if not entity_id:
                        raise ValueError("update_entity 需要 entity_id"
                                         "（先 ontology_find_entities 查询）")
                    before, after = ontology.patch_entity(
                        tenant, entity_id, props=props, name=name.strip() or None,
                        **common)
                    _audit("chat_update_entity", "ontology_entity", entity_id,
                           before, after)
                    return json.dumps(
                        {"ok": True, "op": op, "id": entity_id, "before": before,
                         "after": after,
                         "message": f"已更新实体「{after['name']}」的信息"},
                        ensure_ascii=False)

                if op == "create_relation":
                    rel = relation_type.strip()
                    if not rel:
                        raise ValueError("create_relation 需要 relation_type")
                    fid, tid = from_id, to_id
                    f_desc = t_desc = ""
                    if not fid:
                        src = ontology.resolve_entity(
                            tenant, from_type.strip(), from_name.strip())
                        fid = src["id"]
                        f_desc = f"{src['entity_type']}:{src['name']}"
                    if not tid:
                        dst = ontology.resolve_entity(
                            tenant, to_type.strip(), to_name.strip())
                        tid = dst["id"]
                        t_desc = f"{dst['entity_type']}:{dst['name']}"
                    new_id, created = ontology.create_relation_ex(
                        tenant,
                        {"from_id": fid, "to_id": tid, "relation_type": rel,
                         "props": rel_props or {}},
                        **common)
                    after = {"id": new_id, "from_id": fid, "to_id": tid,
                             "relation_type": rel, "from": f_desc, "to": t_desc}
                    # 幂等重边是 no-op：不重复记审计，回复中如实说明已存在。
                    if created:
                        _audit("chat_create_relation", "ontology_relation", new_id,
                               None, after)
                        message = f"已建立关系 {rel}（{f_desc or fid} → {t_desc or tid}）"
                    else:
                        message = (f"关系 {rel}（{f_desc or fid} → {t_desc or tid}）"
                                   "已存在，无需重复建立")
                    return json.dumps(
                        {"ok": True, "op": op, "id": new_id, "created": created,
                         "relation": after, "message": message},
                        ensure_ascii=False)

                raise ValueError(
                    f"未知 op={op}，支持 create_entity / update_entity / create_relation")
            except ValueError as e:
                return json.dumps({"ok": False, "op": op, "error": str(e)},
                                  ensure_ascii=False)
            except Exception as e:  # 写回失败要让模型可解释，不把异常抛断对话
                print(f"[ontology_write] 写回失败: {type(e).__name__}: {e}")
                return json.dumps(
                    {"ok": False, "op": op,
                     "error": f"写回失败：{type(e).__name__}: {e}"},
                    ensure_ascii=False)

        tools.append(ontology_write)

    return tools
