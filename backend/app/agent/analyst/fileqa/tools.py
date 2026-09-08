"""表格问答 LLM 工具集：上传附件（CSV/Excel）注册表的列表与查询。

  - file_table_list: 列出当前用户已注册的表格及结构（含样本行）
  - file_table_query: 对已注册表格执行只读 SELECT，结果走 SSE sql 事件渲染

与 sql_tools 同一模式：user_id 由 streaming.py 注入 contextvar（不信任 LLM 传参），
查询结果复用 sql_tools 的会话缓冲，由 streaming.py 翻译成 sql SSE 事件。
"""
from __future__ import annotations

import logging
from typing import Optional

from langchain_core.tools import tool

from app.agent.analyst.fileqa import manager as fileqa_manager
from app.agent.analyst.tools.sql_tools import _conv_id_var, _push_query_result
from app.agent.analyst.tools.tool_call_manager import get_tool_call_manager

logger = logging.getLogger("app.agent.analyst.fileqa.tools")


def _check_tool_call(session_id: str, tool_name: str,
                     query: Optional[str] = None) -> tuple[bool, str]:
    return get_tool_call_manager().check_before_call(session_id, tool_name, query)


def _record_tool_call(session_id: str, tool_name: str,
                      success: bool, query: Optional[str] = None) -> None:
    get_tool_call_manager().record_call(session_id, tool_name, success, query)


def _format_query_result(query: str, result: dict) -> str:
    """把执行结果格式化为 LLM 可读的文本表格（与 sql_db_query 同风格）。"""
    if not result["success"]:
        error_msg = result["error"] or "未知错误"
        return (f"SQL 执行失败: {error_msg}\n\n"
                "请检查 SQL 语法与表名/列名（可用 file_table_list 查看表结构）。")
    data, columns = result["data"], result["columns"]
    _push_query_result(_conv_id_var.get(), {
        "sql": query,
        "columns": columns,
        "data": data[:50],
        "row_count": result["row_count"],
        "chart_type": "table",
    })
    if not data:
        return "✅ 查询成功执行，但没有返回数据。"
    rows = data[:50]
    header = " | ".join(str(c) for c in columns)
    separator = "-" * min(len(header), 200)
    lines = []
    if result.get("truncated") or len(data) > len(rows):
        lines.append(f"✅ 查询成功，返回 {result['row_count']} 行数据"
                     f"（显示前 {len(rows)} 行）:\n")
    else:
        lines.append(f"✅ 查询成功，返回 {len(data)} 行数据:\n")
    lines.append(header)
    lines.append(separator)
    for row in rows:
        lines.append(" | ".join(str(row.get(c, ""))[:50] for c in columns))
    lines.append("\n✅ 查询已完成。请基于以上结果进行分析，无需重复执行相同查询。")
    return "\n".join(lines)


@tool
def file_table_list() -> str:
    """列出当前用户上传的 Excel/CSV 表格附件（已自动注册为可查询数据表）。

    返回每张表的表名、字段（含类型）、行数和样本数据。表格问答前先调用此工具
    了解可用表及其结构，再用 file_table_query 编写 SQL 查询。
    """
    uid = fileqa_manager._user_id_var.get()
    if not uid:
        return "错误: 表格问答仅在数据分析会话中可用。"
    try:
        tables = fileqa_manager.list_user_tables(uid)
    except Exception as e:
        logger.error("列出表格失败: %s", e, exc_info=True)
        return f"列出表格失败: {str(e)[:200]}"
    if not tables:
        return ("当前没有已注册的表格。用户上传 csv/xlsx 附件后会自动注册，"
                "届时可直接用 file_table_query 查询。")
    lines = [f"✅ 共 {len(tables)} 张已注册表格：\n"]
    for t in tables:
        cols = ", ".join(f"{c['name']}({c['type']})" for c in t["columns"])
        lines.append(f"表 '{t['name']}'（{t['row_count']} 行）")
        lines.append(f"  字段: {cols}")
    lines.append("\n✅ 请基于以上表结构用 file_table_query 编写 SQL 查询。")
    return "\n".join(lines)


@tool
def file_table_query(query: str, conversation_id: str = "") -> str:
    """对用户上传的表格附件执行 SQL SELECT 查询（DuckDB 引擎，只读）。

    Args:
        query: 要执行的 SQL SELECT 语句（表名/字段名以 file_table_list 返回为准，
               中文或特殊字符表名/字段名用双引号包裹）
        conversation_id: 会话 ID（用于防循环管理，可选）
    """
    uid = fileqa_manager._user_id_var.get()
    if not uid:
        return "错误: 表格问答仅在数据分析会话中可用。"
    session_id = conversation_id or f"fileqa_{uid}"

    err = fileqa_manager.check_select_only(query)
    if err:
        return err
    allowed, reason = _check_tool_call(session_id, "file_table_query", query)
    if not allowed:
        return reason

    logger.info("执行表格附件 SQL [user=%s]:\n%s", uid, query[:500])
    result = fileqa_manager.execute_query(uid, query)
    _record_tool_call(session_id, "file_table_query", result["success"], query)
    return _format_query_result(query, result)


ANALYST_FILE_TOOLS = [file_table_list, file_table_query]
