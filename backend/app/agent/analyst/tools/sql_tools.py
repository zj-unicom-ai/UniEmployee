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
import threading
from contextvars import ContextVar
from datetime import date, datetime
from decimal import Decimal
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

_NUMERIC_TYPE_HINTS = (
    "int", "integer", "bigint", "smallint", "tinyint",
    "decimal", "numeric", "number", "real", "float", "double",
    "money",
)
_TIME_TYPE_HINTS = ("date", "time", "timestamp", "datetime")


# ---------------------------------------------------------------------------
# SSE 事件流桥接：把 sql_db_query 的结构化结果按 conv_id 缓冲，
# 供 streaming.py 在 ToolMessage 到达时取出，翻译成 chart/sql SSE 事件。
# 用 contextvars 而非工具参数传 conv_id，避免依赖 LLM 自觉传 conversation_id。
# ---------------------------------------------------------------------------

# 当前会话 ID（由 streaming.py 在 astream 前 set，工具内部读取）
_conv_id_var: ContextVar[str] = ContextVar("analyst_conv_id", default="")

# 当前数据源 ID（由 streaming.py 在 astream 前 set，工具内部读取）
# 设计动机：LLM 调用 sql_db_* 工具时常常瞎猜 datasource_id（试 "chinook"/"1"/"default"
# 都失败），导致工具调用链爆炸。前端选数据源后通过 query param 把真实 ID 传到后端，
# 由 streaming.py 注入到此 contextvar，工具内部优先用它兜底，LLM 不传/传错也能跑通。
_datasource_id_var: ContextVar[str] = ContextVar("analyst_datasource_id", default="")

# 当前选中的知识库 ID（用户在数据源下拉选了知识库时注入）
# kb_search 工具读取此值，非空时只检索这一个知识库；为空时检索员工绑定的全部知识库。
_kb_id_var: ContextVar[str] = ContextVar("analyst_kb_id", default="")

# 当前选中的连接器 ID（用户在数据源下拉选了连接器时注入）
# MCP 工具调用时按此 ID 限定到单个连接器，避免跨连接器误调。
_connector_id_var: ContextVar[str] = ContextVar("analyst_connector_id", default="")

# 当前会话用户上下文 (user_id, is_admin)：由 streaming.py 在 astream 前注入，
# 工具层据此做数据源归属的纵深校验（防止伪造/越权访问他人数据源）。
_user_ctx_var: ContextVar[tuple] = ContextVar("analyst_user_ctx", default=("", False))

# 按 conv_id 隔离的查询结果缓冲：conv_id -> [chart_data, ...]
# chart_data 形如 {"sql": str, "columns": list[str], "rows": list[dict], "row_count": int}
_query_results: dict[str, list[dict]] = {}
_buffer_lock = threading.Lock()


def set_conv_id(conv_id: str) -> None:
    """streaming.py 在调用 agent.astream 前注入当前会话 ID。"""
    _conv_id_var.set(conv_id)


def clear_conv_id() -> None:
    """astream 结束后清理（避免下次复用旧值）。"""
    _conv_id_var.set("")


def set_datasource_id(ds_id: str) -> None:
    """streaming.py 在 astream 前注入当前数据源 ID（由前端选数据源后传到后端）。"""
    _datasource_id_var.set(ds_id or "")


def clear_datasource_id() -> None:
    """astream 结束后清理。"""
    _datasource_id_var.set("")


def set_kb_id(kb_id: str) -> None:
    """streaming.py 在 astream 前注入当前选中的知识库 ID。

    用户在数据源下拉选了知识库时，前端把 kb:xxx 传到后端，由 streaming.py
    解析后注入此 contextvar。kb_search 工具读取此值，非空时只检索这一个知识库。
    """
    _kb_id_var.set(kb_id or "")


def clear_kb_id() -> None:
    """astream 结束后清理。"""
    _kb_id_var.set("")


def set_connector_id(connector_id: str) -> None:
    """streaming.py 在 astream 前注入当前选中的连接器 ID。

    用户在数据源下拉选了连接器时，前端把 conn:xxx 传到后端，由 streaming.py
    解析后注入此 contextvar。MCP 工具调用时按此 ID 限定到单个连接器。
    """
    _connector_id_var.set(connector_id or "")


def clear_connector_id() -> None:
    """astream 结束后清理。"""
    _connector_id_var.set("")


def set_user_ctx(user_id: str, is_admin: bool) -> None:
    """streaming.py 在 astream 前注入当前会话用户（用于数据源归属校验）。"""
    _user_ctx_var.set((user_id or "", bool(is_admin)))


def clear_user_ctx() -> None:
    """astream 结束后清理。"""
    _user_ctx_var.set(("", False))


def _check_datasource_access(datasource_id: str) -> str:
    """纵深校验当前会话用户是否有权访问该数据源。

    返回非空字符串表示拒绝（错误提示，工具直接 return 给 LLM）；空串表示放行。
    管理员 / 系统内部调用（无用户上下文）放行；数据源不存在不在此拦截
    （交由后续 get_engine 报「不存在」），仅拦截「存在但属于他人」的越权访问。
    """
    user_id, is_admin = _user_ctx_var.get()
    if is_admin or not user_id:
        return ""
    ds = ds_manager.get_datasource(datasource_id)
    if ds and ds.get("owner_id") not in (None, user_id):
        logger.warning("数据源越权访问被拦截: ds=%s user=%s owner=%s",
                       datasource_id, user_id, ds.get("owner_id"))
        return (f"错误: 无权访问数据源 {datasource_id}（该数据源属于其他用户，"
                f"请在数据源下拉中选择自己的数据源）。")
    return ""


def _resolve_datasource_id(explicit: str) -> str:
    """工具内部统一的数据源 ID 解析。

    优先级：会话注入（contextvar，用户在界面显式选择的数据源）> LLM 显式传值。

    contextvar 由 streaming.py 在每次 astream 前按前端选择注入、结束后清理，
    代表当前会话唯一有效的数据源；LLM 传值可能是历史消息里的陈旧 ID（如已删除
    的数据源）或瞎猜值（"chinook"/"1"/"default"），若让它优先，会把「用户已
    选好数据源」的会话直接跑挂（报「数据源 xxx 不存在」）。因此仅当会话未注入
    （测试 / 非界面调用）时才采用 LLM 传值。
    """
    return _datasource_id_var.get() or explicit


def _json_safe(obj):
    """递归把 Decimal/datetime/date 等 json.dumps 不能直接序列化的类型转成基本类型。

    设计动机：SQLAlchemy 从不同数据库引擎反序列化 numeric 字段时常返回 Decimal
    （MySQL 的 decimal、PG 的 numeric），datetime 字段返回 datetime 对象；
    streaming.py 用 json.dumps 把 chart 数据发 SSE 事件时会抛
    'TypeError: Object of type Decimal is not JSON serializable'，
    导致前端收到「⚠ 任务执行出错」错误提示（但 SQL 工具实际执行成功）。
    在数据源头（工具内部）统一转换比在 SSE 序列化处改 default 钩子更干净，
    因为前端 ChartRenderer 期望的是 number 而非字符串。
    """
    if isinstance(obj, dict):
        return {k: _json_safe(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_json_safe(v) for v in obj]
    # Decimal → float（数值语义，前端图表需要 number 而非字符串）
    if isinstance(obj, Decimal):
        return float(obj)
    # datetime/date/time → ISO 字符串（前端可再格式化）
    if isinstance(obj, (datetime, date)):
        return obj.isoformat()
    return obj


def _push_query_result(conv_id: str, chart_data: dict) -> None:
    """工具内部调用：把查询结果追加到该会话的缓冲队列。"""
    if not conv_id:
        return
    with _buffer_lock:
        _query_results.setdefault(conv_id, []).append(chart_data)


def pop_query_results(conv_id: str) -> list[dict]:
    """streaming.py 调用：取出并清空该会话的所有待消费结果。"""
    with _buffer_lock:
        return _query_results.pop(conv_id, [])


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


def _quote_ident(identifier: str, db_type: str = "") -> str:
    """按方言保守引用标识符，标识符来自 schema 白名单而非用户任意输入。"""
    ident = str(identifier or "")
    if db_type in ("mysql", "mariadb"):
        return f"`{ident.replace('`', '``')}`"
    if db_type in ("mssql", "sqlserver"):
        return f"[{ident.replace(']', ']]')}]"
    return f'"{ident.replace(chr(34), chr(34) + chr(34))}"'


def _column_kind(col_type: str) -> str:
    typ = (col_type or "").lower()
    if any(h in typ for h in _NUMERIC_TYPE_HINTS):
        return "numeric"
    if any(h in typ for h in _TIME_TYPE_HINTS):
        return "time"
    return "text"


def _format_pct(numerator: int | float, denominator: int | float) -> str:
    if not denominator:
        return "0.00%"
    return f"{(float(numerator) / float(denominator) * 100):.2f}%"


def _get_session_id(datasource_id: str, conversation_id: str = "") -> str:
    """构造会话标识（datasource_id + conversation_id）。"""
    return conversation_id or f"analyst_{datasource_id}"


# ---------------------------------------------------------------------------
# 5 个 @tool 工具
# ---------------------------------------------------------------------------

@tool
def sql_db_smart_search(datasource_id: str = "", user_query: str = "",
                        conversation_id: str = "") -> str:
    """智能检索数据库表：使用 BM25 检索最相关的表并返回完整 schema。

    调用此工具时必须传入用户的原始问题。表数 <= 20 时返回全量表。
    这是数据库问数的第一步，获取 schema 后直接编写 SQL，无需重复调用。

    Args:
        datasource_id: 数据源 ID（可选；不传时用当前会话选中的数据源）
        user_query: 用户的原始问题或需求（中文或英文）
        conversation_id: 会话 ID（用于防循环管理，可选）
    """
    datasource_id = _resolve_datasource_id(datasource_id)
    if not datasource_id:
        return "错误: 未指定数据源。请在对话页面选择数据源后再提问。"
    _deny = _check_datasource_access(datasource_id)
    if _deny:
        return _deny
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
def sql_db_table_schema(datasource_id: str = "", table_names: str = "",
                        conversation_id: str = "") -> str:
    """获取指定表的详细结构（字段名/类型/注释）。

    Args:
        datasource_id: 数据源 ID（可选；不传时用当前会话选中的数据源）
        table_names: 表名，多个表用逗号分隔
        conversation_id: 会话 ID（可选）
    """
    datasource_id = _resolve_datasource_id(datasource_id)
    if not datasource_id:
        return "错误: 未指定数据源。请在对话页面选择数据源后再提问。"
    _deny = _check_datasource_access(datasource_id)
    if _deny:
        return _deny
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
def sql_db_table_relationship(datasource_id: str = "", table_names: str = "",
                              conversation_id: str = "") -> str:
    """获取表间外键关联关系，用于多表 JOIN 查询。

    Args:
        datasource_id: 数据源 ID（可选；不传时用当前会话选中的数据源）
        table_names: 需要查询关联的表名列表，逗号分隔
        conversation_id: 会话 ID（可选）
    """
    datasource_id = _resolve_datasource_id(datasource_id)
    if not datasource_id:
        return "错误: 未指定数据源。请在对话页面选择数据源后再提问。"
    _deny = _check_datasource_access(datasource_id)
    if _deny:
        return _deny
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
def sql_db_query(datasource_id: str = "", query: str = "",
                 conversation_id: str = "") -> str:
    """执行 SQL SELECT 查询并返回结果。只允许 SELECT，禁止 INSERT/UPDATE/DELETE 等。

    Args:
        datasource_id: 数据源 ID（可选；不传时用当前会话选中的数据源）
        query: 要执行的 SQL SELECT 语句
        conversation_id: 会话 ID（可选）
    """
    datasource_id = _resolve_datasource_id(datasource_id)
    if not datasource_id:
        return "错误: 未指定数据源。请在对话页面选择数据源后再提问。"
    _deny = _check_datasource_access(datasource_id)
    if _deny:
        return _deny
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

        # 把结构化查询结果外推到 SSE 桥接缓冲：
        # streaming.py 收到 sql_db_query 的 ToolMessage 时会取出，发 chart/sql SSE 事件，
        # 让前端 ChartRenderer/SqlViewer 渲染。chart_type 暂留 "table"，
        # 后续可由 SQL 示例配置或 LLM 智能推断覆盖。
        # JSON 序列化兼容：SQLAlchemy 反序列化时 numeric/decimal 字段会成 Decimal，
        # datetime 会成 datetime 对象，json.dumps 都不能直接序列化，先统一转基本类型。
        _push_query_result(_conv_id_var.get(), {
            "sql": query,
            "columns": columns,
            "data": _json_safe(data[:_MAX_RESULT_ROWS]),
            "row_count": len(data),
            "chart_type": "table",
        })

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


@tool
def sql_db_profile(datasource_id: str = "", table_names: str = "",
                   sample_limit: int = 100) -> str:
    """生成数据表画像，用于正式分析前验证数据覆盖、缺失和字段分布。

    Args:
        datasource_id: 数据源 ID（可选；不传时用当前会话选中的数据源）
        table_names: 表名，多个表用逗号分隔
        sample_limit: 每张表分类字段 Top 值抽样上限，默认 100
    """
    datasource_id = _resolve_datasource_id(datasource_id)
    if not datasource_id:
        return "错误: 未指定数据源。请在对话页面选择数据源后再提问。"
    _deny = _check_datasource_access(datasource_id)
    if _deny:
        return _deny
    if not table_names or not table_names.strip():
        return "错误: table_names 不能为空，请传入需要画像的表名"
    try:
        sample_limit_int = int(sample_limit)
    except Exception:
        sample_limit_int = 100

    ds = ds_manager.get_datasource(datasource_id) or {}
    db_type = ds.get("db_type", "")
    requested = [t.strip() for t in table_names.split(",") if t.strip()]
    schema = schema_inspector.get_table_schema(datasource_id, requested)
    parts = ["数据画像结果："]

    for table_name in requested:
        info = schema.get(table_name)
        if not info:
            parts.append(f"\n表 `{table_name}`：不存在或不可读取。")
            continue
        if not ds_manager.is_table_readable(datasource_id, table_name):
            parts.append(f"\n表 `{table_name}`：未通过表名白名单校验，已跳过。")
            continue

        table_expr = _quote_ident(table_name, db_type)
        columns = info.get("columns", {})
        count_sql = f"SELECT COUNT(*) AS total_rows FROM {table_expr}"
        count_result = ds_manager.execute_query(datasource_id, count_sql, limit=1)
        if not count_result.get("success"):
            parts.append(
                f"\n表 `{table_name}`：行数统计失败：{count_result.get('error')}"
            )
            continue
        total_rows = int((count_result.get("data") or [{}])[0].get("total_rows") or 0)
        parts.append(f"\n表 `{table_name}`：")
        parts.append(f"- 行数：{total_rows}")
        parts.append(f"- 字段数：{len(columns)}")
        if total_rows == 0:
            parts.append("- 质量提示：空表，当前不适合支撑分析结论。")
            continue

        metric_exprs = []
        column_kinds = {}
        for col_name, col_info in columns.items():
            col_expr = _quote_ident(col_name, db_type)
            alias = re.sub(r"\W+", "_", col_name)
            column_kinds[col_name] = _column_kind(col_info.get("type", ""))
            metric_exprs.append(
                f"SUM(CASE WHEN {col_expr} IS NULL THEN 1 ELSE 0 END) AS "
                f"{_quote_ident(alias + '_nulls', db_type)}"
            )
            if column_kinds[col_name] in ("numeric", "time"):
                metric_exprs.extend([
                    f"MIN({col_expr}) AS {_quote_ident(alias + '_min', db_type)}",
                    f"MAX({col_expr}) AS {_quote_ident(alias + '_max', db_type)}",
                ])
            if column_kinds[col_name] == "numeric":
                metric_exprs.append(
                    f"AVG({col_expr}) AS {_quote_ident(alias + '_avg', db_type)}"
                )

        stats_sql = f"SELECT {', '.join(metric_exprs)} FROM {table_expr}"
        stats_result = ds_manager.execute_query(datasource_id, stats_sql, limit=1)
        stats = (stats_result.get("data") or [{}])[0] if stats_result.get("success") else {}

        for col_name, col_info in columns.items():
            alias = re.sub(r"\W+", "_", col_name)
            nulls = int(stats.get(f"{alias}_nulls") or 0)
            kind = column_kinds[col_name]
            line = (
                f"- `{col_name}` ({col_info.get('type', '')})："
                f"非空率 {_format_pct(total_rows - nulls, total_rows)}"
            )
            if kind in ("numeric", "time"):
                line += f"，范围 {stats.get(alias + '_min')} ~ {stats.get(alias + '_max')}"
            if kind == "numeric" and stats.get(alias + "_avg") is not None:
                line += f"，均值 {stats.get(alias + '_avg')}"
            parts.append(line)

        text_cols = [name for name, kind in column_kinds.items() if kind == "text"][:3]
        for col_name in text_cols:
            col_expr = _quote_ident(col_name, db_type)
            top_sql = (
                f"SELECT {col_expr} AS value, COUNT(*) AS cnt "
                f"FROM {table_expr} WHERE {col_expr} IS NOT NULL "
                f"GROUP BY {col_expr} ORDER BY cnt DESC LIMIT 5"
            )
            top_result = ds_manager.execute_query(
                datasource_id, top_sql, limit=max(1, min(sample_limit_int, 100))
            )
            if top_result.get("success") and top_result.get("data"):
                values = ", ".join(
                    f"{row.get('value')}({row.get('cnt')})"
                    for row in top_result["data"][:5]
                )
                parts.append(f"- `{col_name}` Top 值：{values}")

    parts.append("\n请基于以上画像判断数据是否足以支撑后续分析。")
    return "\n".join(parts)


@tool
def sql_db_quality_check(datasource_id: str = "", query: str = "",
                         table_name: str = "", expected_min_rows: int = 10) -> str:
    """检查分析 SQL 或目标表的结果可信度，重点识别空结果、样本量、缺失和重复。

    Args:
        datasource_id: 数据源 ID（可选；不传时用当前会话选中的数据源）
        query: 待分析的 SELECT SQL；为空时可传 table_name 检查整表
        table_name: 目标表名（query 为空时使用）
        expected_min_rows: 期望最小样本量，默认 10
    """
    datasource_id = _resolve_datasource_id(datasource_id)
    if not datasource_id:
        return "错误: 未指定数据源。请在对话页面选择数据源后再提问。"
    _deny = _check_datasource_access(datasource_id)
    if _deny:
        return _deny

    ds = ds_manager.get_datasource(datasource_id) or {}
    db_type = ds.get("db_type", "")
    source_label = "分析 SQL"
    check_sql = (query or "").strip().rstrip(";")
    if not check_sql:
        if not table_name or not table_name.strip():
            return "错误: query 和 table_name 至少传入一个"
        if not ds_manager.is_table_readable(datasource_id, table_name):
            return f"错误: 表 {table_name} 不存在或未通过白名单校验"
        source_label = f"表 `{table_name}`"
        check_sql = f"SELECT * FROM {_quote_ident(table_name.strip(), db_type)}"

    result = ds_manager.execute_query(datasource_id, check_sql, limit=100)
    if not result.get("success"):
        return f"数据质量检查失败：{result.get('error')}"

    rows = result.get("data") or []
    columns = result.get("columns") or []
    issues = []
    warnings = []
    positives = []

    if not rows:
        issues.append("结果为空，不能支撑业务结论。")
    elif len(rows) < max(1, int(expected_min_rows)):
        warnings.append(
            f"样本量较小：当前仅取到 {len(rows)} 行，低于期望 {expected_min_rows} 行。"
        )
    else:
        positives.append(f"样本量检查通过：当前检查 {len(rows)} 行。")

    if rows and columns:
        null_lines = []
        for col in columns:
            nulls = sum(1 for row in rows if row.get(col) is None)
            if nulls:
                null_lines.append(f"`{col}` 缺失 {nulls} 行（{_format_pct(nulls, len(rows))}）")
        if null_lines:
            warnings.append("字段缺失：" + "；".join(null_lines))
        else:
            positives.append("缺失值检查通过：抽样结果中未发现 NULL。")

        seen = set()
        duplicate_count = 0
        for row in rows:
            key = tuple(row.get(col) for col in columns)
            if key in seen:
                duplicate_count += 1
            else:
                seen.add(key)
        if duplicate_count:
            warnings.append(f"发现 {duplicate_count} 行完全重复记录，需确认是否影响口径。")
        else:
            positives.append("重复记录检查通过：未发现完全重复行。")

    lines = [f"数据质量检查结果（{source_label}）："]
    if issues:
        lines.append("结论：不通过，当前数据不足以支撑分析。")
    elif warnings:
        lines.append("结论：有风险，可分析但需要在结论中说明限制。")
    else:
        lines.append("结论：通过，可进入正式分析。")

    if positives:
        lines.append("\n通过项：")
        lines.extend(f"- {item}" for item in positives)
    if warnings:
        lines.append("\n风险项：")
        lines.extend(f"- {item}" for item in warnings)
    if issues:
        lines.append("\n阻断项：")
        lines.extend(f"- {item}" for item in issues)
    lines.append("\n后续要求：分析结论必须引用真实查询结果，并说明以上风险项。")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# 导出工具列表（供 compiler.py 注册）
# ---------------------------------------------------------------------------

ANALYST_SQL_TOOLS = [
    sql_db_smart_search,
    sql_db_table_schema,
    sql_db_table_relationship,
    sql_db_query,
    sql_db_query_checker,
    sql_db_profile,
    sql_db_quality_check,
]
