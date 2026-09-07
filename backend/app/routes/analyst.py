"""数据分析员工（analyst）API 路由。

提供数据源管理、表结构发现、表标注等 API。
路径前缀：/api/analyst
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from app.agent.analyst.datasource import manager as ds_manager
from app.agent.analyst.datasource import schema_inspector
from app.agent.analyst.terminology import manager as term_manager
from app.agent.analyst.sql_examples import manager as ex_manager

logger = logging.getLogger("app.routes.analyst")

router = APIRouter(prefix="/api/analyst", tags=["analyst"])


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


class DatasourceUpdate(BaseModel):
    name: str | None = None
    description: str | None = None
    db_type: str | None = None
    config: dict | None = None
    enabled: int | None = None


class TestConnection(BaseModel):
    db_type: str
    config: dict


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
async def list_datasources():
    """列出所有数据源。"""
    return ds_manager.list_datasources()


@router.get("/datasources/{ds_id}")
async def get_datasource(ds_id: str):
    """获取单个数据源详情。"""
    ds = ds_manager.get_datasource(ds_id)
    if not ds:
        raise HTTPException(404, "数据源不存在")
    # 不返回加密的 config，返回解密后的（去密码字段更安全，但这里先保持）
    ds["config"] = ds_manager.decrypt_config(ds["config"])
    # 隐藏密码
    if "password" in ds["config"]:
        ds["config"]["password"] = "***"
    return ds


@router.post("/datasources")
async def create_datasource(req: DatasourceCreate, request: Request):
    """创建数据源。"""
    user_id = request.state.user_id if hasattr(request.state, "user_id") else None
    data = req.model_dump()
    data["owner_id"] = user_id
    return ds_manager.create_datasource(data)


@router.put("/datasources/{ds_id}")
async def update_datasource(ds_id: str, req: DatasourceUpdate):
    """更新数据源。"""
    data = req.model_dump(exclude_none=True)
    updated = ds_manager.update_datasource(ds_id, data)
    if not updated:
        raise HTTPException(404, "数据源不存在")
    return updated


@router.delete("/datasources/{ds_id}")
async def delete_datasource(ds_id: str):
    """删除数据源（软删）。"""
    if not ds_manager.delete_datasource(ds_id):
        raise HTTPException(404, "数据源不存在")
    return {"ok": True}


@router.post("/datasources/test")
async def test_connection(req: TestConnection):
    """测试数据源连接。"""
    ok, msg = ds_manager.test_connection(req.db_type, req.config)
    return {"success": ok, "message": msg}


# ---------------------------------------------------------------------------
# 表结构发现
# ---------------------------------------------------------------------------

@router.get("/datasources/{ds_id}/tables")
async def discover_tables(ds_id: str):
    """自动发现数据源的所有表结构。"""
    ds = ds_manager.get_datasource(ds_id)
    if not ds:
        raise HTTPException(404, "数据源不存在")
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
async def get_table_schema(ds_id: str, table_name: str):
    """获取指定表的详细结构。"""
    ds = ds_manager.get_datasource(ds_id)
    if not ds:
        raise HTTPException(404, "数据源不存在")
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


@router.get("/datasources/{ds_id}/relationships")
async def get_relationships(ds_id: str, tables: str = ""):
    """获取表间关联关系。tables 参数为逗号分隔的表名。"""
    ds = ds_manager.get_datasource(ds_id)
    if not ds:
        raise HTTPException(404, "数据源不存在")
    table_list = [t.strip() for t in tables.split(",")] if tables else []
    relationships = schema_inspector.get_table_relationships(ds_id, table_list)
    return {"relationships": relationships}


# ---------------------------------------------------------------------------
# 表标注 CRUD
# ---------------------------------------------------------------------------

@router.get("/datasources/{ds_id}/annotations")
async def list_annotations(ds_id: str):
    """列出数据源下所有表标注。"""
    return ds_manager.list_table_annotations(ds_id)


@router.get("/datasources/{ds_id}/annotations/{table_name}")
async def get_annotation(ds_id: str, table_name: str):
    """获取单表标注。"""
    ann = ds_manager.get_table_annotation(ds_id, table_name)
    if not ann:
        raise HTTPException(404, "标注不存在")
    return ann


@router.put("/datasources/{ds_id}/annotations/{table_name}")
async def upsert_annotation(ds_id: str, table_name: str, req: TableAnnotationUpdate):
    """创建或更新表标注。"""
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
