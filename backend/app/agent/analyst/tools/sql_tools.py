"""SQL 工具集（从 Aix-DB native_sql_tools.py 适配搬迁）。

5 个 @tool 工具，供 xiaoshu agent 的 LLM 自主调用：
  - sql_db_smart_search: BM25 检索最相关的表，返回 schema
  - sql_db_table_schema: 获取指定表的字段详情
  - sql_db_table_relationship: 获取表间外键关联
  - sql_db_query: 执行 SELECT SQL
  - sql_db_query_checker: SQL 语法检查

与 Aix-DB 的关键差异：
  - 全局变量 _current_datasource 改为 datasource_id 参数传入（多用户并发安全）
  - 数据源访问改调 manager.py（替代 Aix-DB 的 DatasourceConfigUtil/db_pool）
  - 表结构获取改调 schema_inspector.py（替代 Aix-DB 的 DatasourceTable/Field ORM）
  - ToolCallManager 按会话隔离（保持 Aix-DB 的防循环逻辑）
"""

from __future__ import annotations

import logging
import re
from typing import Optional

from langchain_core.tools import tool

from app.agent.analyst.datasource import manager as ds_manager
from app.agent.analyst.datasource import schema_inspector
from app.agent.analyst.tools.schema_retriever import bm25_retrieve_tables, format_schema_text
from app.agent.analyst.tools.tool_call_manager import get_tool_call_manager
from app.agent.analyst.terminology.retriever import build_terminology_injection
from app.agent.analyst.sql_examples.retriever import build_sql_example_injection

logger = logging.getLogger("app.agent.analyst.tools.sql_tools")

_BM25_TOP_K = 20
_MAX_RESULT_ROWS = 50


# ---------------------------------------------------------------------------
# 辅助函数
# ---------------------------------------------------------------------------

def _check_tool_call(session_id: str, tool_name: str,
                     query: Optional[str] = None) -> tuple[bool, str]:
    """工具调用前检查（防循环）。"""
    manager = get_tool_call_manager()
    return manager.check_before_call(session_id, tool_name, query)


def _record_tool_call(session_id: str, tool_name: str,
                      success: bool, query: Optional[str] = None) -> None:
    """记录工具调用。"""
    manager = get_tool_call_manager()
    manager.record_call(session_id, tool_name, success, query)


def _get_session_id(datasource_id: str, conversation_id: str = "") -> str:
    """构造会话标识（datasource_id + conversation_id）。"""
    return conversation_id or f"analyst_{datasource_id}"


# ---------------------------------------------------------------------------
# 5 个 @tool 工具
# ---------------------------------------------------------------------------

@tool
def sql_db_smart_search(datasource_id: str, user_query: str,
                        conversation_id: str = "") -> str:
    """智能检索数据库表：使用 BM25 检索最相关的表并返回完整 schema。

    调用此工具时必须传入用户的原始问题。表数 <= 20 时返回全量表。
    这是数据库问数的第一步，获取 schema 后直接编写 SQL，无需重复调用。

    Args:
        datasource_id: 数据源 ID（从数据源管理页面获取）
        user_query: 用户的原始问题或需求（中文或英文）
        conversation_id: 会话 ID（用于防循环管理，可选）
    """
    session_id = _get_session_id(datasource_id, conversation_id)

    allowed, reason = _check_tool_call(session_id, "sql_db_smart_search")
    if not allowed:
        return reason

    if not user_query or not user_query.strip():
        return "错误: user_query 不能为空，请传入用户的原始问题"

    try:
        table_info = schema_inspector.get_all_tables(datasource_id)
        total_count = len(table_info)

        if not table_info:
            _record_tool_call(session_id, "sql_db_smart_search", False)
            return "错误: 数据库中没有可用的表"

        # 表数量 <= 阈值时跳过 BM25，直接返回全量
        if total_count <= _BM25_TOP_K:
            selected_names = list(table_info.keys())
        else:
            selected_names = bm25_retrieve_tables(
                table_info, user_query, top_k=_BM25_TOP_K)
            if not selected_names:
                selected_names = list(table_info.keys())[:_BM25_TOP_K]

        schema_text = format_schema_text(selected_names, table_info)
        _record_tool_call(session_id, "sql_db_smart_search", True)

        # 注入业务术语（命中时拼到 schema 前面，帮 LLM 理解业务名词映射）
        term_xml = build_terminology_injection(user_query, datasource_id)
        # 注入相似 SQL 示例（命中时作为参考写法，加速正确 SQL 生成）
        example_xml = build_sql_example_injection(user_query, datasource_id)

        context_block = ""
        if term_xml:
            context_block += (
                "业务术语参考（命中用户问题中的业务词）：\n"
                + term_xml + "\n\n"
            )
        if example_xml:
            context_block += (
                "相似问题的参考 SQL（可参考写法但不要照抄，须按当前 schema 调整）：\n"
                + example_xml + "\n\n"
            )

        header = (
            f"✅ 智能检索完成：从 {total_count} 张表中筛选出 {len(selected_names)} 张相关表。\n"
            f"相关表：{', '.join(selected_names)}\n"
            f"（如需其他表的 schema，可额外调用 sql_db_table_schema）\n"
        )
        footer = "\n\n✅ schema 已获取。请直接基于以上信息编写 SQL，无需重复调用此工具。"
        return context_block + header + schema_text + footer

    except Exception as e:
        _record_tool_call(session_id, "sql_db_smart_search", False)
        logger.error("smart_search 失败: %s", e, exc_info=True)
        return f"检索表结构失败: {str(e)[:200]}"


@tool
def sql_db_table_schema(datasource_id: str, table_names: str,
                        conversation_id: str = "") -> str:
    """获取指定表的详细结构（字段名/类型/注释）。

    Args:
        datasource_id: 数据源 ID
        table_names: 表名，多个表用逗号分隔
        conversation_id: 会话 ID（可选）
    """
    session_id = _get_session_id(datasource_id, conversation_id)

    allowed, reason = _check_tool_call(session_id, "sql_db_table_schema")
    if not allowed:
        return reason

    try:
        table_list = [t.strip() for t in table_names.split(",")]
        table_info = schema_inspector.get_table_schema(datasource_id, table_list)

        result_parts = []
        for table_name in table_list:
            if table_name not in table_info:
                result_parts.append(f"表 '{table_name}' 不存在")
                continue
            info = table_info[table_name]
            columns = info.get("columns", {})
            table_comment = info.get("table_comment", "")

            schema_text = f"\n表 '{table_name}':"
            if table_comment:
                schema_text += f"\n注释: {table_comment}"
            schema_text += "\n列:"
            for col_name, col_info in columns.items():
                col_type = col_info.get("type", "")
                col_comment = col_info.get("comment", "")
                schema_text += f"\n  - {col_name} ({col_type})"
                if col_comment:
                    schema_text += f" - {col_comment}"

            fks = info.get("foreign_keys", [])
            if fks:
                fk_str = ", ".join(
                    f"{fk['column']} → {fk['ref_table']}.{fk['ref_column']}"
                    for fk in fks)
                schema_text += f"\n外键: {fk_str}"

            result_parts.append(schema_text)

        _record_tool_call(session_id, "sql_db_table_schema", True)
        result = "\n".join(result_parts) if result_parts else "未找到表信息"
        result += "\n\n✅ 表架构已获取。请基于此信息编写 SQL 查询。"
        return result

    except Exception as e:
        _record_tool_call(session_id, "sql_db_table_schema", False)
        logger.error("获取表架构失败: %s", e, exc_info=True)
        return f"获取表架构失败: {str(e)[:200]}"


@tool
def sql_db_table_relationship(datasource_id: str, table_names: str,
                              conversation_id: str = "") -> str:
    """获取表间外键关联关系，用于多表 JOIN 查询。

    Args:
        datasource_id: 数据源 ID
        table_names: 需要查询关联的表名列表，逗号分隔
        conversation_id: 会话 ID（可选）
    """
    session_id = _get_session_id(datasource_id, conversation_id)

    allowed, reason = _check_tool_call(session_id, "sql_db_table_relationship")
    if not allowed:
        return reason

    try:
        table_list = [t.strip() for t in table_names.split(",")]
        relationships = schema_inspector.get_table_relationships(
            datasource_id, table_list)

        _record_tool_call(session_id, "sql_db_table_relationship", True)

        if not relationships:
            return "未找到这些表之间的外键关系。可能需要通过业务逻辑关联（非物理外键）。"

        lines = ["表间关联关系：\n"]
        for rel in relationships:
            lines.append(
                f"  {rel['from_table']}.{rel['from_column']} "
                f"→ {rel['to_table']}.{rel['to_column']}"
            )
        lines.append("\n✅ 关联关系已获取。请基于此信息编写 JOIN 查询。")
        return "\n".join(lines)

    except Exception as e:
        _record_tool_call(session_id, "sql_db_table_relationship", False)
        logger.error("获取表关系失败: %s", e, exc_info=True)
        return f"获取表关系失败: {str(e)[:200]}"


@tool
def sql_db_query(datasource_id: str, query: str,
                 conversation_id: str = "") -> str:
    """执行 SQL SELECT 查询并返回结果。只允许 SELECT，禁止 INSERT/UPDATE/DELETE 等。

    Args:
        datasource_id: 数据源 ID
        query: 要执行的 SQL SELECT 语句
        conversation_id: 会话 ID（可选）
    """
    session_id = _get_session_id(datasource_id, conversation_id)

    # 安全检查
    query_upper = query.strip().upper()
    forbidden = ("INSERT", "UPDATE", "DELETE", "DROP", "ALTER",
                 "TRUNCATE", "CREATE", "GRANT", "REVOKE")
    check_sql = query.strip()
    if not check_sql.upper().startswith("WITH") and not check_sql.upper().startswith("SELECT"):
        for kw in forbidden:
            if kw in query_upper:
                return f"错误: 不允许执行 {kw} 操作，只允许 SELECT 查询"
        return "错误: 只允许执行 SELECT 查询"

    allowed, reason = _check_tool_call(session_id, "sql_db_query", query)
    if not allowed:
        return reason

    logger.info("执行 SQL [datasource=%s]:\n%s", datasource_id, query[:500])

    try:
        result = ds_manager.execute_query(datasource_id, query, limit=100)
        _record_tool_call(session_id, "sql_db_query", result["success"], query)

        if not result["success"]:
            error_msg = result["error"] or "未知错误"
            if len(error_msg) > 300:
                error_msg = error_msg[:300] + "..."
            return (
                f"SQL 执行失败: {error_msg}\n\n"
                "请检查 SQL 语法和表结构是否正确。"
                "如果之前已获取表架构，请直接使用已有信息，无需重复查询。"
            )

        data = result["data"]
        columns = result["columns"]

        if not data:
            return "✅ 查询成功执行，但没有返回数据。"

        # 格式化表格输出（限制行数）
        result_rows = data[:_MAX_RESULT_ROWS]
        col_widths = {}
        for col in columns:
            col_widths[col] = min(
                max(len(str(col)),
                    max(len(str(row.get(col, ""))[:50]) for row in result_rows)),
                50
            )

        header = " | ".join(str(col).ljust(col_widths[col]) for col in columns)
        separator = "-" * min(len(header), 200)

        lines = []
        if len(data) > _MAX_RESULT_ROWS:
            lines.append(f"✅ 查询成功，返回 {len(data)} 行数据（显示前 {_MAX_RESULT_ROWS} 行）:\n")
        else:
            lines.append(f"✅ 查询成功，返回 {len(data)} 行数据:\n")
        lines.append(header)
        lines.append(separator)
        for row in result_rows:
            row_str = " | ".join(
                str(row.get(col, ""))[:50].ljust(col_widths[col]) for col in columns
            )
            lines.append(row_str)
        lines.append("\n✅ 查询已完成。请基于以上结果进行分析，无需重复执行相同查询。")

        return "\n".join(lines)

    except Exception as e:
        _record_tool_call(session_id, "sql_db_query", False, query)
        error_msg = str(e)[:300]
        logger.error("SQL 查询失败: %s", error_msg)
        return f"SQL 执行失败: {error_msg}\n\n请检查 SQL 语法和表结构。"


@tool
def sql_db_query_checker(query: str) -> str:
    """检查 SQL 查询语法是否正确（不执行查询）。

    Args:
        query: 要检查的 SQL 查询语句
    """
    query_upper = query.strip().upper()

    if not query_upper:
        return "错误: SQL 查询为空"

    forbidden = ("INSERT", "UPDATE", "DELETE", "DROP", "ALTER",
                 "TRUNCATE", "CREATE")
    for kw in forbidden:
        if kw in query_upper:
            return f"错误: 不允许执行 {kw} 操作，只允许 SELECT 查询"

    if not query_upper.startswith("SELECT") and not query_upper.startswith("WITH"):
        return "错误: 只允许执行 SELECT 查询"

    issues = []
    if "FROM" not in query_upper:
        issues.append("缺少 FROM 子句")
    if query.count("(") != query.count(")"):
        issues.append("括号不匹配")
    if query.count("'") % 2 != 0:
        issues.append("单引号不匹配")

    if issues:
        return f"SQL 语法警告: {', '.join(issues)}"

    return "✅ SQL 查询语法检查通过，可以执行。"


# ---------------------------------------------------------------------------
# 导出工具列表（供 compiler.py 注册）
# ---------------------------------------------------------------------------

ANALYST_SQL_TOOLS = [
    sql_db_smart_search,
    sql_db_table_schema,
    sql_db_table_relationship,
    sql_db_query,
    sql_db_query_checker,
]
