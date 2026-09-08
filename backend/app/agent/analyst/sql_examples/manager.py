"""SQL 示例管理：CRUD。

SQL 示例（sql_examples）是数据分析员工的"问数模板"，用于：
  - LLM 写 SQL 时参考相似问题的标准写法
  - 给前端"推荐问题"提供数据源

sql_examples 表字段：
  - id: 主键
  - question: 问题（用户问法，如"本月销售额 TOP10 客户"）
  - sql_text: 参考 SQL
  - description: 描述/备注
  - datasource_id: 关联数据源（None=适用全部数据源）
  - chart_type: 推荐图表类型（table/pie/bar/line）
  - enabled: 启用状态
  - embedding: 预留向量（P1 用关键词匹配，P2 可升级向量检索）
  - created_at/updated_at: 时间戳

存储策略：
  - 不在 _SOFT_DELETE_TABLES，硬删
  - datasource_id 单值（与术语的多值不同，示例通常绑定具体数据源）
"""

from __future__ import annotations

import logging
import time
import uuid
from typing import Any

from app.catalog.db import _conn as _catalog_conn

logger = logging.getLogger("app.agent.analyst.sql_examples")


def _now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S")


def _gen_id() -> str:
    return f"ex_{int(time.time()*1000)}_{uuid.uuid4().hex[:8]}"


_VALID_CHART_TYPES = {"table", "pie", "bar", "line", ""}


def _normalize_chart_type(raw: Any) -> str:
    """图表类型归一化：空/未知统一为空字符串（默认表格）。"""
    if not raw:
        return ""
    s = str(raw).strip().lower()
    if s not in _VALID_CHART_TYPES:
        return ""
    return s


# ---------------------------------------------------------------------------
# 行解析
# ---------------------------------------------------------------------------

def _row_to_example(r) -> dict:
    return {
        "id": r["id"],
        "question": r["question"],
        "sql_text": r["sql_text"],
        "description": r["description"] or "",
        "datasource_id": r["datasource_id"] or "",
        "chart_type": r["chart_type"] or "",
        "enabled": r["enabled"],
        "created_at": r["created_at"],
        "updated_at": r["updated_at"],
    }


# ---------------------------------------------------------------------------
# CRUD
# ---------------------------------------------------------------------------

def list_sql_examples(
    datasource_id: str | None = None,
    include_disabled: bool = False,
) -> list[dict]:
    """列出 SQL 示例。

    Args:
        datasource_id: 过滤关联此数据源的示例（None=全部；空 datasource_id 的示例也命中）
        include_disabled: 是否包含已禁用
    """
    sql = (
        "SELECT id, question, sql_text, description, datasource_id, "
        "chart_type, enabled, created_at, updated_at FROM sql_examples"
    )
    clauses = []
    params: list = []
    if not include_disabled:
        clauses.append("enabled = 1")
    if clauses:
        sql += " WHERE " + " AND ".join(clauses)
    sql += " ORDER BY created_at DESC"

    con = _catalog_conn()
    try:
        rows = con.execute(sql, params).fetchall()
    finally:
        con.close()

    result = [_row_to_example(r) for r in rows]
    if datasource_id:
        # 客户端过滤：datasource_id 为空（适用全部）或匹配
        result = [e for e in result
                  if not e["datasource_id"]
                  or e["datasource_id"] == datasource_id]
    return result


def get_sql_example(example_id: str) -> dict | None:
    """获取单个 SQL 示例。"""
    con = _catalog_conn()
    try:
        r = con.execute(
            "SELECT id, question, sql_text, description, datasource_id, "
            "chart_type, enabled, created_at, updated_at "
            "FROM sql_examples WHERE id=?",
            (example_id,)
        ).fetchone()
        if not r:
            return None
        return _row_to_example(r)
    finally:
        con.close()


def create_sql_example(data: dict) -> dict:
    """创建 SQL 示例。

    data: {id?, question, sql_text, description?, datasource_id?, chart_type?, enabled?}
    """
    if not data.get("question"):
        raise ValueError("question 不能为空")
    if not data.get("sql_text"):
        raise ValueError("sql_text 不能为空")

    ex_id = data.get("id") or _gen_id()
    now = _now()

    con = _catalog_conn()
    try:
        con.execute(
            "INSERT INTO sql_examples (id, question, sql_text, description, "
            "datasource_id, chart_type, enabled, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (ex_id, data["question"], data["sql_text"],
             data.get("description", ""),
             data.get("datasource_id") or None,
             _normalize_chart_type(data.get("chart_type")),
             data.get("enabled", 1), now, now)
        )
        con.commit()
    finally:
        con.close()
    logger.info("创建 SQL 示例: %s (%s)", data["question"][:30], ex_id)
    return get_sql_example(ex_id)


def update_sql_example(example_id: str, data: dict) -> dict | None:
    """更新 SQL 示例（部分更新）。"""
    existing = get_sql_example(example_id)
    if not existing:
        return None

    question = data.get("question", existing["question"])
    sql_text = data.get("sql_text", existing["sql_text"])
    description = data.get("description", existing["description"])
    datasource_id = data.get("datasource_id", existing["datasource_id"])
    # chart_type 即使不在 data 中也要归一化（用 existing 即可，已经归一过）
    chart_type = data.get("chart_type", existing["chart_type"])
    chart_type = _normalize_chart_type(chart_type)
    enabled = data.get("enabled", existing["enabled"])

    # datasource_id 空字符串转 None
    if not datasource_id:
        datasource_id = None

    now = _now()
    con = _catalog_conn()
    try:
        con.execute(
            "UPDATE sql_examples SET question=?, sql_text=?, description=?, "
            "datasource_id=?, chart_type=?, enabled=?, updated_at=? WHERE id=?",
            (question, sql_text, description, datasource_id,
             chart_type, enabled, now, example_id)
        )
        con.commit()
    finally:
        con.close()
    return get_sql_example(example_id)


def delete_sql_example(example_id: str) -> bool:
    """硬删 SQL 示例。"""
    con = _catalog_conn()
    try:
        con.execute("DELETE FROM sql_examples WHERE id=?", (example_id,))
        con.commit()
        deleted = con.total_changes > 0
    finally:
        con.close()
    if deleted:
        logger.info("删除 SQL 示例: %s", example_id)
    return deleted


def toggle_sql_example(example_id: str, enabled: int) -> dict | None:
    """启用/禁用 SQL 示例。"""
    return update_sql_example(example_id, {"enabled": enabled})
