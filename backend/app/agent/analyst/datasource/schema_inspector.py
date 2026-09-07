"""表结构自动发现：连接数据源拉取所有表/字段/类型/外键。

借鉴 Aix-DB agent/text2sql/database/db_service.py 的 schema_inspector 逻辑，
适配为 UniEmployee 的 manager.py engine 缓存 + table_annotations 标注。
返回格式与 Aix-DB db_info 一致，供 BM25 检索和 SQL 工具使用。
"""

from __future__ import annotations

import logging
from typing import Any

from sqlalchemy import inspect

from app.agent.analyst.datasource import manager

logger = logging.getLogger("app.agent.analyst.schema_inspector")


def get_all_tables(datasource_id: str) -> dict[str, dict]:
    """获取数据源下所有表的结构信息。

    返回格式（与 Aix-DB db_info 对齐）:
    {
        "orders": {
            "columns": {
                "id": {"type": "INTEGER", "comment": "主键ID"},
                "amount": {"type": "DECIMAL", "comment": "金额"},
            },
            "foreign_keys": [
                {"column": "customer_id", "ref_table": "customers", "ref_column": "id"}
            ],
            "table_comment": "订单表"
        }
    }
    """
    engine = manager.get_engine(datasource_id)
    inspector = inspect(engine)

    # 加载表标注（中文注释/可查询标记）
    annotations = {a["table_name"]: a for a in manager.list_table_annotations(datasource_id)}

    result: dict[str, dict] = {}

    try:
        table_names = inspector.get_table_names()
    except Exception as e:
        logger.error("获取表列表失败 [datasource=%s]: %s", datasource_id, e)
        return result

    for table_name in table_names:
        table_info = _get_single_table_info(inspector, table_name, annotations)
        if table_info:
            result[table_name] = table_info

    return result


def get_table_schema(datasource_id: str, table_names: list[str]) -> dict[str, dict]:
    """获取指定表的结构信息（子集）。"""
    engine = manager.get_engine(datasource_id)
    inspector = inspect(engine)

    annotations = {a["table_name"]: a for a in manager.list_table_annotations(datasource_id)}

    result: dict[str, dict] = {}
    for table_name in table_names:
        table_info = _get_single_table_info(inspector, table_name, annotations)
        if table_info:
            result[table_name] = table_info
    return result


def _get_single_table_info(
    inspector, table_name: str, annotations: dict[str, dict]
) -> dict | None:
    """获取单表的完整结构信息。"""
    try:
        columns_raw = inspector.get_columns(table_name)
    except Exception as e:
        logger.warning("获取表 %s 的列信息失败: %s", table_name, e)
        return None

    # 标注覆盖：如果有用户定义的中文标注，优先使用
    ann = annotations.get(table_name, {})
    col_ann = ann.get("column_annotations", {}) if ann else {}
    table_comment = ann.get("table_comment", "") if ann else ""

    columns: dict[str, dict] = {}
    for col in columns_raw:
        col_name = col["name"]
        col_type = str(col.get("type", ""))
        # 优先使用用户标注的中文注释，其次用数据库原始注释
        user_comment = col_ann.get(col_name, {}).get("comment", "")
        db_comment = col.get("comment") or ""
        comment = user_comment or db_comment or ""

        columns[col_name] = {
            "type": col_type,
            "comment": comment,
        }

    # 外键信息
    foreign_keys: list[dict] = []
    try:
        fks = inspector.get_foreign_keys(table_name)
        for fk in fks:
            for col_pair in zip(fk.get("constrained_columns", []),
                                 fk.get("referred_columns", [])):
                foreign_keys.append({
                    "column": col_pair[0],
                    "ref_table": fk.get("referred_table", ""),
                    "ref_column": col_pair[1],
                })
    except Exception:
        pass  # 某些数据库不支持外键检查

    # 表注释（某些数据库支持）
    if not table_comment:
        try:
            table_comment = inspector.get_table_comment(table_name).get("text", "") or ""
        except Exception:
            pass

    return {
        "columns": columns,
        "foreign_keys": foreign_keys,
        "table_comment": table_comment,
    }


def get_table_relationships(datasource_id: str, table_names: list[str]) -> list[dict]:
    """获取指定表之间的外键关联关系。

    返回格式:
    [
        {"from_table": "orders", "from_column": "customer_id",
         "to_table": "customers", "to_column": "id",
         "relation": "orders.customer_id → customers.id"}
    ]
    """
    engine = manager.get_engine(datasource_id)
    inspector = inspect(engine)

    table_set = set(table_names)
    result: list[dict] = []

    for table_name in table_names:
        try:
            fks = inspector.get_foreign_keys(table_name)
        except Exception:
            continue

        for fk in fks:
            ref_table = fk.get("referred_table", "")
            if ref_table not in table_set and table_name not in table_set:
                continue

            constrained = fk.get("constrained_columns", [])
            referred = fk.get("referred_columns", [])
            for i, col in enumerate(constrained):
                ref_col = referred[i] if i < len(referred) else ""
                result.append({
                    "from_table": table_name,
                    "from_column": col,
                    "to_table": ref_table,
                    "to_column": ref_col,
                    "relation": f"{table_name}.{col} → {ref_table}.{ref_col}",
                })

    return result


def format_schema_text(table_names: list[str], table_info: dict[str, dict]) -> str:
    """格式化 schema 为文本（借鉴 Aix-DB format_schema_text）。

    输出格式:
    表名: orders (订单表)
      - id: INTEGER (主键ID)
      - customer_id: INTEGER (客户ID)
      - amount: DECIMAL (金额)
      外键: customer_id → customers.id
    """
    lines: list[str] = []
    for table_name in table_names:
        info = table_info.get(table_name)
        if not info:
            continue

        comment = info.get("table_comment", "")
        header = f"表名: {table_name}"
        if comment:
            header += f" ({comment})"
        lines.append(header)

        for col_name, col_info in info.get("columns", {}).items():
            col_type = col_info.get("type", "")
            col_comment = col_info.get("comment", "")
            line = f"  - {col_name}: {col_type}"
            if col_comment:
                line += f" ({col_comment})"
            lines.append(line)

        fks = info.get("foreign_keys", [])
        if fks:
            fk_str = ", ".join(
                f"{fk['column']} → {fk['ref_table']}.{fk['ref_column']}"
                for fk in fks
            )
            lines.append(f"  外键: {fk_str}")

        lines.append("")  # 空行分隔

    return "\n".join(lines)
