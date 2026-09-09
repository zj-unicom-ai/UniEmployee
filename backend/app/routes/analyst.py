"""数据分析员工（analyst）API 路由。

提供数据源管理、表结构发现、表标注等 API。
路径前缀：/api/analyst
"""

from __future__ import annotations

import json
import logging

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel

from app import auth
from app.agent.analyst.datasource import manager as ds_manager
from app.agent.analyst.datasource import schema_inspector
from app.agent.analyst.terminology import manager as term_manager
from app.agent.analyst.sql_examples import manager as ex_manager

logger = logging.getLogger("app.routes.analyst")

# 整个 analyst 路由组都要求登录：数据源含数据库连接凭据，术语/SQL 示例/知识库
# 等均为内部配置，任何接口都不允许匿名访问（此前缺失鉴权导致未登录即可列数据源、
# 甚至经详情接口拿到解密后的数据库明文密码）。
router = APIRouter(prefix="/api/analyst", tags=["analyst"],
                   dependencies=[Depends(auth.get_current_user)])


def _is_admin(user: dict) -> bool:
    return user.get("role") == "admin"


def _require_usable(ds_id: str, user: dict) -> dict:
    """校验【使用】权限（owner/管理员/公共源均可），无则统一抛 404。

    用于表结构读取、数据预览、标注读取等只读场景——普通用户可使用公共源。
    """
    ds = ds_manager.get_owned_datasource(ds_id, user["id"], _is_admin(user))
    if not ds:
        raise HTTPException(404, "数据源不存在")
    return ds


def _require_managed(ds_id: str, user: dict) -> dict:
    """校验【管理】权限（仅 owner/管理员，公共源不对普通用户开放），无则抛 404。

    用于编辑/删除/写标注/读取连接配置等修改类场景——公共种子源只能被其
    owner（管理员）维护，普通用户只能使用，不能改删。
    """
    ds = ds_manager.get_managed_datasource(ds_id, user["id"], _is_admin(user))
    if not ds:
        raise HTTPException(404, "数据源不存在或无权操作")
    return ds


# ---------------------------------------------------------------------------
# 请求模型
# ---------------------------------------------------------------------------

class DatasourceCreate(BaseModel):
    id: str | None = None
    name: str
    description: str = ""
    db_type: str  # mysql/pg/oracle/sqlServer/clickhouse
    config: dict  # {host, port, database, username, password, dbSchema, ...}
    enabled: int = 1
    is_public: int = 0  # 1=公共（全员可用）；仅管理员可置 1


class DatasourceUpdate(BaseModel):
    name: str | None = None
    description: str | None = None
    db_type: str | None = None
    config: dict | None = None
    enabled: int | None = None
    is_public: int | None = None  # 仅管理员可改


class TestConnection(BaseModel):
    db_type: str
    config: dict
    datasource_id: str | None = None  # 编辑模式未改密码时回填已保存密码


class TableAnnotationUpdate(BaseModel):
    table_comment: str = ""
    queryable: int = 1
    column_annotations: dict = {}


# ----- 术语请求模型 -----

class TerminologyCreate(BaseModel):
    word: str
    description: str = ""
    synonyms: list[str] = []
    datasource_ids: list[str] = []
    enabled: int = 1


class TerminologyUpdate(BaseModel):
    word: str | None = None
    description: str | None = None
    synonyms: list[str] | None = None
    datasource_ids: list[str] | None = None
    enabled: int | None = None


class SynonymUpdate(BaseModel):
    synonym: str


# ----- SQL 示例请求模型 -----

class SqlExampleCreate(BaseModel):
    question: str
    sql_text: str
    description: str = ""
    datasource_id: str | None = None
    chart_type: str = ""  # table/pie/bar/line
    enabled: int = 1


class SqlExampleUpdate(BaseModel):
    question: str | None = None
    sql_text: str | None = None
    description: str | None = None
    datasource_id: str | None = None
    chart_type: str | None = None
    enabled: int | None = None


# ---------------------------------------------------------------------------
# 数据源 CRUD
# ---------------------------------------------------------------------------

@router.get("/datasources")
async def list_datasources(user: dict = Depends(auth.get_current_user)):
    """列出数据源（私有隔离：普通用户仅自己创建的，管理员全部）。"""
    return ds_manager.list_datasources(owner_id=user["id"], is_admin=_is_admin(user))


@router.get("/datasources/{ds_id}")
async def get_datasource(ds_id: str, user: dict = Depends(auth.get_current_user)):
    """获取单个数据源详情（含连接配置，仅 owner/管理员）。

    详情用于编辑回显，属【管理】权限：公共源普通用户可使用（问数/看表结构），
    但不向其暴露连接配置。密码同样脱敏为 "***"。
    """
    ds = _require_managed(ds_id, user)
    cfg = ds_manager.decrypt_config(ds["config"])
    if isinstance(cfg, dict) and cfg.get("password"):
        cfg["password"] = "***"
    ds["config"] = cfg
    return ds


@router.post("/datasources")
async def create_datasource(req: DatasourceCreate,
                            user: dict = Depends(auth.get_current_user)):
    """创建数据源（owner 记为当前登录用户）。

    安全：is_public（公共数据源）仅管理员可置 1，普通用户即使传 1 也强制为 0。
    """
    data = req.model_dump()
    data["owner_id"] = user["id"]
    if not _is_admin(user):
        data["is_public"] = 0
    return ds_manager.create_datasource(data)


@router.put("/datasources/{ds_id}")
async def update_datasource(ds_id: str, req: DatasourceUpdate,
                            user: dict = Depends(auth.get_current_user)):
    """更新数据源（【管理】权限：仅 owner/管理员；公共源普通用户不可改）。

    安全：is_public 仅管理员可改；普通用户提交的该字段直接忽略。
    """
    _require_managed(ds_id, user)
    data = req.model_dump(exclude_none=True)
    if not _is_admin(user):
        data.pop("is_public", None)
    updated = ds_manager.update_datasource(ds_id, data)
    if not updated:
        raise HTTPException(404, "数据源不存在")
    return updated


@router.delete("/datasources/{ds_id}")
async def delete_datasource(ds_id: str,
                            user: dict = Depends(auth.get_current_user)):
    """删除数据源（软删，【管理】权限：仅 owner/管理员；公共源普通用户不可删）。"""
    _require_managed(ds_id, user)
    if not ds_manager.delete_datasource(ds_id):
        raise HTTPException(404, "数据源不存在")
    return {"ok": True}


@router.post("/datasources/test")
async def test_connection(req: TestConnection,
                          user: dict = Depends(auth.get_current_user)):
    """测试数据源连接。编辑模式未改密码时用已保存密码回填，避免空密码报错。

    新建模式（无 datasource_id）不校验，任何登录用户都能测试自己填写的连接；
    编辑模式（带 id，需回填已保存密码）属【管理】权限，仅 owner/管理员可对该源
    测试——公共源普通用户不能借回填读到/复用其保存的密码。
    回填的真实密码只在后端用于本次连接测试，不返回前端。
    """
    config = req.config
    pwd = config.get("password", "") if isinstance(config, dict) else ""
    if req.datasource_id and (not pwd or pwd == "***"):
        ds = ds_manager.get_managed_datasource(
            req.datasource_id, user["id"], _is_admin(user))
        if not ds:
            raise HTTPException(404, "数据源不存在或无权操作")
        saved = ds_manager.decrypt_config(ds["config"])
        config = {**config, "password": saved.get("password", "")}
    ok, msg = ds_manager.test_connection(req.db_type, config)
    return {"success": ok, "message": msg}


# ---------------------------------------------------------------------------
# 表结构发现
# ---------------------------------------------------------------------------

@router.get("/datasources/{ds_id}/tables")
async def discover_tables(ds_id: str, user: dict = Depends(auth.get_current_user)):
    """自动发现数据源的所有表结构（使用权限：owner/管理员/公共源可读）。"""
    _require_usable(ds_id, user)
    try:
        tables = schema_inspector.get_all_tables(ds_id)
        # 返回简洁的表名列表 + 字段数
        return {
            "datasource_id": ds_id,
            "total_tables": len(tables),
            "tables": [
                {
                    "name": name,
                    "comment": info.get("table_comment", ""),
                    "column_count": len(info.get("columns", {})),
                    "foreign_key_count": len(info.get("foreign_keys", [])),
                }
                for name, info in tables.items()
            ],
        }
    except Exception as e:
        logger.error("表结构发现失败: %s", e, exc_info=True)
        raise HTTPException(500, f"表结构发现失败: {str(e)[:200]}")


@router.get("/datasources/{ds_id}/tables/{table_name}/schema")
async def get_table_schema(ds_id: str, table_name: str,
                           user: dict = Depends(auth.get_current_user)):
    """获取指定表的详细结构（使用权限：owner/管理员/公共源可读）。"""
    _require_usable(ds_id, user)
    try:
        table_info = schema_inspector.get_table_schema(ds_id, [table_name])
        if table_name not in table_info:
            raise HTTPException(404, f"表 {table_name} 不存在")
        info = table_info[table_name]
        # 附带标注信息
        annotation = ds_manager.get_table_annotation(ds_id, table_name)
        return {
            "table_name": table_name,
            "columns": info.get("columns", {}),
            "foreign_keys": info.get("foreign_keys", []),
            "table_comment": info.get("table_comment", ""),
            "annotation": annotation,
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error("获取表结构失败: %s", e, exc_info=True)
        raise HTTPException(500, f"获取表结构失败: {str(e)[:200]}")


@router.get("/datasources/{ds_id}/tables/{table_name}/preview")
async def preview_table_data(ds_id: str, table_name: str, limit: int = 10,
                             user: dict = Depends(auth.get_current_user)):
    """预览表数据：返回前 N 行数据，用于库表配置页确认字段含义（使用权限：owner/管理员/公共源可读）。

    复用 datasource.manager.execute_query 跑 SELECT * LIMIT N。
    """
    _require_usable(ds_id, user)
    try:
        # 不同数据库的 LIMIT 语法不同，manager.execute_query 已对结果做了 limit 截断
        sql = f"SELECT * FROM {table_name}"
        result = ds_manager.execute_query(ds_id, sql, limit=limit)
        return {
            "table_name": table_name,
            "columns": result.get("columns", []),
            "data": result.get("data", []),
            "row_count": result.get("row_count", 0),
            "truncated": result.get("row_count", 0) >= limit,
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error("预览数据失败: %s", e, exc_info=True)
        raise HTTPException(500, f"预览数据失败: {str(e)[:200]}")


@router.get("/datasources/{ds_id}/relationships")
async def get_relationships(ds_id: str, tables: str = "",
                            user: dict = Depends(auth.get_current_user)):
    """获取表间关联关系。tables 参数为逗号分隔的表名（使用权限：owner/管理员/公共源可读）。"""
    _require_usable(ds_id, user)
    table_list = [t.strip() for t in tables.split(",")] if tables else []
    relationships = schema_inspector.get_table_relationships(ds_id, table_list)
    return {"relationships": relationships}


# ---------------------------------------------------------------------------
# 表标注 CRUD
# ---------------------------------------------------------------------------

@router.get("/datasources/{ds_id}/annotations")
async def list_annotations(ds_id: str,
                           user: dict = Depends(auth.get_current_user)):
    """列出数据源下所有表标注（使用权限：owner/管理员/公共源可读）。"""
    _require_usable(ds_id, user)
    return ds_manager.list_table_annotations(ds_id)


@router.get("/datasources/{ds_id}/annotations/{table_name}")
async def get_annotation(ds_id: str, table_name: str,
                         user: dict = Depends(auth.get_current_user)):
    """获取单表标注（使用权限：owner/管理员/公共源可读）。"""
    _require_usable(ds_id, user)
    ann = ds_manager.get_table_annotation(ds_id, table_name)
    if not ann:
        raise HTTPException(404, "标注不存在")
    return ann


@router.put("/datasources/{ds_id}/annotations/{table_name}")
async def upsert_annotation(ds_id: str, table_name: str, req: TableAnnotationUpdate,
                            user: dict = Depends(auth.get_current_user)):
    """创建或更新表标注（【管理】权限：仅 owner/管理员；公共源只读）。"""
    _require_managed(ds_id, user)
    return ds_manager.upsert_table_annotation(
        ds_id, table_name,
        table_comment=req.table_comment,
        queryable=req.queryable,
        column_annotations=req.column_annotations,
    )


# ---------------------------------------------------------------------------
# 术语 CRUD
# ---------------------------------------------------------------------------

@router.get("/terminologies")
async def list_terminologies(
    datasource_id: str | None = None,
    include_disabled: bool = False,
):
    """列出术语。可按 datasource_id 过滤，include_disabled=1 包含已禁用。"""
    return term_manager.list_terminologies(
        datasource_id=datasource_id,
        include_disabled=include_disabled,
    )


@router.get("/terminologies/{term_id}")
async def get_terminology(term_id: str):
    """获取单个术语。"""
    term = term_manager.get_terminology(term_id)
    if not term:
        raise HTTPException(404, "术语不存在")
    return term


@router.post("/terminologies")
async def create_terminology(req: TerminologyCreate):
    """创建术语。"""
    try:
        return term_manager.create_terminology(req.model_dump())
    except ValueError as e:
        raise HTTPException(400, str(e))


@router.put("/terminologies/{term_id}")
async def update_terminology(term_id: str, req: TerminologyUpdate):
    """更新术语（部分更新）。"""
    data = req.model_dump(exclude_none=True)
    updated = term_manager.update_terminology(term_id, data)
    if not updated:
        raise HTTPException(404, "术语不存在")
    return updated


@router.delete("/terminologies/{term_id}")
async def delete_terminology(term_id: str):
    """删除术语。"""
    if not term_manager.delete_terminology(term_id):
        raise HTTPException(404, "术语不存在")
    return {"ok": True}


@router.post("/terminologies/{term_id}/synonyms")
async def add_synonym(term_id: str, req: SynonymUpdate):
    """追加单个同义词（幂等去重）。"""
    try:
        updated = term_manager.add_synonym(term_id, req.synonym)
    except ValueError as e:
        raise HTTPException(400, str(e))
    if not updated:
        raise HTTPException(404, "术语不存在")
    return updated


@router.delete("/terminologies/{term_id}/synonyms/{synonym}")
async def remove_synonym(term_id: str, synonym: str):
    """移除某个同义词（幂等）。"""
    updated = term_manager.remove_synonym(term_id, synonym)
    if not updated:
        raise HTTPException(404, "术语不存在")
    return updated


@router.post("/terminologies/{term_id}/toggle")
async def toggle_terminology(term_id: str, enabled: int = 1):
    """启用/禁用术语。"""
    updated = term_manager.toggle_terminology(term_id, enabled)
    if not updated:
        raise HTTPException(404, "术语不存在")
    return updated


@router.post("/terminologies/generate-synonyms")
async def generate_synonyms(req: Request, word: str = ""):
    """AI 生成同义词：调 LLM 为术语词生成 5 个候选同义词。

    用于术语配置页「AI 生成同义词」按钮，提升术语维护效率。
    """
    import os
    from langchain_core.messages import HumanMessage

    if not word:
        body = await req.json() if req.headers.get("content-type", "").startswith("application/json") else {}
        word = body.get("word", "")
    if not word:
        raise HTTPException(400, "word is required")

    model_name = os.getenv("MODEL_NAME", "gpt-4o-mini")
    try:
        from app.compiler import _init_model
        llm = _init_model(model_name)
    except Exception as e:
        logger.error("init llm failed: %s", e)
        raise HTTPException(500, f"模型初始化失败: {e}")

    prompt = f"""请为术语「{word}」生成 5 个同义词或近义表述，用于数据分析和商业智能场景。

要求：
1. 同义词应贴近业务用户的口语表达，不要学术化
2. 包含：缩写形式、口语化变体、行业别名
3. 直接返回 JSON 数组格式的字符串，例如 ["词1", "词2", "词3"]
4. 不要包含 Markdown 标记、解释文字、代码块包裹

示例（术语「环比」）：["MoM", "上月比", "月环比", "月度环比", "环比增长"]
"""
    try:
        resp = await llm.ainvoke([HumanMessage(content=prompt)])
        content = resp.content.strip()
        # 兼容 LLM 可能包裹的 ```json 代码块
        if content.startswith("```json"):
            content = content[7:]
        elif content.startswith("```"):
            content = content[3:]
        if content.endswith("```"):
            content = content[:-3]
        content = content.strip()
        candidates = json.loads(content)
        if not isinstance(candidates, list):
            return {"word": word, "synonyms": []}
        # 去重 + 去空 + 与原词不同的过滤
        seen = set()
        result = []
        for w in candidates:
            w = str(w).strip()
            if w and w != word and w not in seen:
                seen.add(w)
                result.append(w)
        return {"word": word, "synonyms": result[:5]}
    except json.JSONDecodeError:
        # LLM 返回非 JSON 时降级：尝试按逗号/顿号分割
        try:
            raw = content.replace("[", "").replace("]", "").replace("\"", "")
            parts = [w.strip() for w in raw.replace("、", ",").split(",") if w.strip()]
            return {"word": word, "synonyms": parts[:5]}
        except Exception:
            return {"word": word, "synonyms": []}
    except Exception as e:
        logger.error("generate_synonyms LLM 调用失败: %s", e)
        raise HTTPException(500, f"LLM 调用失败: {e}")


# ---------------------------------------------------------------------------
# SQL 示例 CRUD
# ---------------------------------------------------------------------------

@router.get("/sql-examples")
async def list_sql_examples(
    datasource_id: str | None = None,
    include_disabled: bool = False,
):
    """列出 SQL 示例。可按 datasource_id 过滤。"""
    return ex_manager.list_sql_examples(
        datasource_id=datasource_id,
        include_disabled=include_disabled,
    )


@router.get("/sql-examples/{ex_id}")
async def get_sql_example(ex_id: str):
    """获取单个 SQL 示例。"""
    ex = ex_manager.get_sql_example(ex_id)
    if not ex:
        raise HTTPException(404, "SQL 示例不存在")
    return ex


@router.post("/sql-examples")
async def create_sql_example(req: SqlExampleCreate):
    """创建 SQL 示例。"""
    try:
        return ex_manager.create_sql_example(req.model_dump())
    except ValueError as e:
        raise HTTPException(400, str(e))


@router.put("/sql-examples/{ex_id}")
async def update_sql_example(ex_id: str, req: SqlExampleUpdate):
    """更新 SQL 示例（部分更新）。"""
    data = req.model_dump(exclude_none=True)
    updated = ex_manager.update_sql_example(ex_id, data)
    if not updated:
        raise HTTPException(404, "SQL 示例不存在")
    return updated


@router.delete("/sql-examples/{ex_id}")
async def delete_sql_example(ex_id: str):
    """删除 SQL 示例。"""
    if not ex_manager.delete_sql_example(ex_id):
        raise HTTPException(404, "SQL 示例不存在")
    return {"ok": True}


@router.post("/sql-examples/{ex_id}/toggle")
async def toggle_sql_example(ex_id: str, enabled: int = 1):
    """启用/禁用 SQL 示例。"""
    updated = ex_manager.toggle_sql_example(ex_id, enabled)
    if not updated:
        raise HTTPException(404, "SQL 示例不存在")
    return updated


# ---------------------------------------------------------------------------
# 数据源聚合 + 知识库 / 连接器绑定（xiaoshu 工作台专用）
# ---------------------------------------------------------------------------

@router.get("/data-sources")
async def list_all_data_sources(user: dict = Depends(auth.get_current_user)):
    """聚合返回三类数据源：数据库 / 知识库 / 连接器（仅启用的）。

    供 analyst 工作台顶部「选择数据源」下拉使用，统一渲染三类。
    数据库源按 owner 私有隔离（普通用户仅自己创建的，管理员全部）；
    知识库/连接器为员工绑定级共享资源。
    """
    return ds_manager.list_all_data_sources(
        user_id=user["id"], is_admin=_is_admin(user))


@router.get("/kbs")
async def list_kbs():
    """列出资源中心全部知识库（供 xiaoshu 工作台绑定选择）。"""
    return ds_manager.list_all_kbs()


@router.get("/kbs/bound")
async def list_bound_kbs():
    """列出 xiaoshu 已绑定的知识库。"""
    return ds_manager.list_employee_kbs(ds_manager.ANALYST_EMP_ID)


@router.post("/kbs/{kb_id}")
async def bind_kb(kb_id: str):
    """绑定知识库到 xiaoshu（幂等）。"""
    if not ds_manager.bind_kb(ds_manager.ANALYST_EMP_ID, kb_id):
        raise HTTPException(400, "绑定失败")
    return {"ok": True}


@router.delete("/kbs/{kb_id}")
async def unbind_kb(kb_id: str):
    """解绑 xiaoshu 的知识库。"""
    if not ds_manager.unbind_kb(ds_manager.ANALYST_EMP_ID, kb_id):
        raise HTTPException(404, "知识库未绑定")
    return {"ok": True}


@router.get("/connectors")
async def list_connectors():
    """列出资源中心全部连接器（供 xiaoshu 工作台绑定选择）。"""
    return ds_manager.list_all_connectors()


@router.get("/connectors/bound")
async def list_bound_connectors():
    """列出 xiaoshu 已绑定的连接器。"""
    return ds_manager.list_employee_connectors(ds_manager.ANALYST_EMP_ID)


@router.post("/connectors/{connector_id}")
async def bind_connector(connector_id: str):
    """绑定连接器到 xiaoshu（幂等）。"""
    if not ds_manager.bind_connector(ds_manager.ANALYST_EMP_ID, connector_id):
        raise HTTPException(400, "绑定失败")
    return {"ok": True}


@router.delete("/connectors/{connector_id}")
async def unbind_connector(connector_id: str):
    """解绑 xiaoshu 的连接器。"""
    if not ds_manager.unbind_connector(ds_manager.ANALYST_EMP_ID, connector_id):
        raise HTTPException(404, "连接器未绑定")
    return {"ok": True}
