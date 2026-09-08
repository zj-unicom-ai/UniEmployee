"""SQL 工具集 + ToolCallManager 测试。

覆盖 P0-4/P0-5/P0-6：
- schema_retriever.py: 分词、文档构建、BM25 检索、schema 文本格式化
- tool_call_manager.py: 单例、会话隔离、防循环（上限/重复查询/循环模式）
- sql_tools.py: 5 个 @tool 工具的安全检查与正常路径
"""
import sqlite3

import pytest
from sqlalchemy import create_engine

from app.agent.analyst.datasource import manager as ds_manager
from app.agent.analyst.datasource import schema_inspector
from app.agent.analyst.tools import schema_retriever
from app.agent.analyst.tools.tool_call_manager import (
    ToolCallManager, get_tool_call_manager, set_current_session,
    get_current_session,
)
from app.agent.analyst.tools.sql_tools import (
    sql_db_smart_search, sql_db_table_schema, sql_db_table_relationship,
    sql_db_query, sql_db_query_checker,
)


# ---------------------------------------------------------------------------
# 辅助：建 sqlite 业务库 + 注入 engine 缓存
# ---------------------------------------------------------------------------

def _make_sqlite_business_db(path):
    con = sqlite3.connect(path)
    con.execute("""
        CREATE TABLE customers(
            id INTEGER PRIMARY KEY,
            name TEXT,
            phone TEXT
        )
    """)
    con.execute("""
        CREATE TABLE orders(
            id INTEGER PRIMARY KEY,
            customer_id INTEGER,
            amount REAL,
            created_at TEXT,
            FOREIGN KEY (customer_id) REFERENCES customers(id)
        )
    """)
    con.execute("INSERT INTO customers VALUES (1, '张三', '13800000001')")
    con.execute("INSERT INTO customers VALUES (2, '李四', '13800000002')")
    con.execute("INSERT INTO orders VALUES (1, 1, 99.5, '2026-09-01')")
    con.execute("INSERT INTO orders VALUES (2, 2, 199.0, '2026-09-02')")
    con.commit()
    con.close()


@pytest.fixture
def sqlite_datasource(monkeypatch, tmp_path):
    """建一个用 sqlite engine 注入的数据源，供 SQL 工具测试使用。"""
    monkeypatch.setenv("ANALYST_DB_KEY", "test-key-for-analyst-0123456789")
    monkeypatch.setattr(ds_manager, "_CIPHER_KEY", None)

    ds = ds_manager.create_datasource({
        "name": "测试库", "description": "",
        "db_type": "mysql",  # type 字段不影响，engine 已注入
        "config": {"host": "h", "username": "u", "password": "p", "database": "d"},
        "enabled": 1, "owner_id": "u",
    })
    db_file = tmp_path / "biz.sqlite"
    _make_sqlite_business_db(db_file)
    engine = create_engine(f"sqlite:///{db_file}", pool_pre_ping=True)
    ds_manager._engine_cache[ds["id"]] = engine
    yield ds["id"]
    # 清理：清空该会话 ToolCallManager 状态
    mgr = get_tool_call_manager()
    mgr.clear_session(f"analyst_{ds['id']}")


# ---------------------------------------------------------------------------
# schema_retriever：分词 / 文档构建 / BM25 检索
# ---------------------------------------------------------------------------

def test_tokenize_text_filters_punctuation():
    tokens = schema_retriever.tokenize_text("客户，订单！@# 的 金额")
    # 标点应被过滤
    assert "客户" in tokens
    assert "订单" in tokens
    assert "金额" in tokens
    assert "，" not in tokens
    assert "！" not in tokens
    assert "@" not in tokens


def test_tokenize_text_keeps_alphanumeric():
    tokens = schema_retriever.tokenize_text("user_order_v2 table123")
    # 英文+数字应保留
    assert len(tokens) > 0
    for t in tokens:
        assert t.strip() != ""


def test_build_document_includes_all_parts():
    table_info = {
        "columns": {
            "id": {"type": "INT", "comment": "主键"},
            "name": {"type": "TEXT", "comment": "姓名"},
        },
        "table_comment": "客户表",
    }
    doc = schema_retriever.build_document("customers", table_info)
    assert "customers" in doc
    assert "客户表" in doc
    assert "id" in doc and "主键" in doc
    assert "name" in doc and "姓名" in doc


def test_bm25_retrieve_empty_table_info():
    assert schema_retriever.bm25_retrieve_tables({}, "anything") == []


def test_bm25_retrieve_empty_query_returns_default():
    """空 query 应返回前 top_k 张表。"""
    table_info = {
        "a": {"columns": {}, "table_comment": "", "foreign_keys": []},
        "b": {"columns": {}, "table_comment": "", "foreign_keys": []},
    }
    result = schema_retriever.bm25_retrieve_tables(table_info, "", top_k=5)
    assert len(result) == 2
    assert set(result) == {"a", "b"}


def test_bm25_retrieve_returns_relevant_table():
    """用户问'客户'应优先返回含'客户'注释的表。"""
    table_info = {
        "orders": {
            "columns": {"id": {"type": "INT", "comment": ""}},
            "table_comment": "订单",
            "foreign_keys": [],
        },
        "customers": {
            "columns": {"name": {"type": "TEXT", "comment": "客户姓名"}},
            "table_comment": "客户表",
            "foreign_keys": [],
        },
        "products": {
            "columns": {"sku": {"type": "TEXT", "comment": "商品SKU"}},
            "table_comment": "商品",
            "foreign_keys": [],
        },
    }
    result = schema_retriever.bm25_retrieve_tables(table_info, "客户的姓名", top_k=2)
    assert "customers" in result
    # customers 应排在前面（评分更高）
    assert result[0] == "customers"


def test_format_schema_text_includes_comment_and_fk():
    """schema_retriever.format_schema_text 输出表/注释/字段（不渲染外键，外键由 schema_inspector.format_schema_text 输出）。"""
    table_info = {
        "orders": {
            "columns": {"id": {"type": "INT", "comment": "主键"}},
            "foreign_keys": [
                {"column": "customer_id", "ref_table": "customers", "ref_column": "id"}
            ],
            "table_comment": "订单表",
        }
    }
    text = schema_retriever.format_schema_text(["orders"], table_info)
    assert "orders" in text
    assert "订单表" in text
    assert "主键" in text


def test_format_schema_text_skips_missing_table():
    table_info = {"a": {"columns": {}, "table_comment": "", "foreign_keys": []}}
    text = schema_retriever.format_schema_text(["a", "no_such"], table_info)
    assert "表 'a'" in text
    assert "no_such" not in text


# ---------------------------------------------------------------------------
# ToolCallManager：单例 / 会话隔离 / 防循环
# ---------------------------------------------------------------------------

def test_get_tool_call_manager_singleton():
    m1 = get_tool_call_manager()
    m2 = get_tool_call_manager()
    assert m1 is m2


def test_set_and_get_current_session():
    set_current_session("test_session_1")
    assert get_current_session() == "test_session_1"
    set_current_session(None)
    assert get_current_session() is None


def test_session_isolation():
    """不同会话的调用计数互不影响。"""
    mgr = ToolCallManager()
    s1, s2 = "session_a", "session_b"

    for _ in range(3):
        mgr.record_call(s1, "sql_db_query", True, "SELECT 1")
    mgr.record_call(s2, "sql_db_query", True, "SELECT 2")

    stats1 = mgr.get_stats(s1)
    stats2 = mgr.get_stats(s2)
    assert stats1["total_calls"] == 3
    assert stats2["total_calls"] == 1


def test_max_calls_per_tool_terminates():
    """单工具调用超过 MAX_CALLS_PER_TOOL 应终止。"""
    mgr = ToolCallManager()
    mgr.MAX_CALLS_PER_TOOL = 3  # 调小阈值便于测试
    sid = "test_max_per_tool"

    # 每次用不同的 query 避免触发重复查询检测
    for i in range(3):
        q = f"SELECT {i} FROM t"
        allowed, _ = mgr.check_before_call(sid, "sql_db_query", q)
        assert allowed is True
        mgr.record_call(sid, "sql_db_query", True, q)

    # 第 4 次应被拒绝
    allowed, reason = mgr.check_before_call(sid, "sql_db_query", "SELECT 4 FROM t")
    assert allowed is False
    assert "上限" in reason


def test_max_total_calls_terminates():
    """总调用数超过 MAX_TOTAL_CALLS 应终止。"""
    mgr = ToolCallManager()
    mgr.MAX_TOTAL_CALLS = 5
    sid = "test_max_total"

    for i in range(5):
        mgr.check_before_call(sid, "tool_a", "q")
        mgr.record_call(sid, "tool_a", True, "q")

    allowed, reason = mgr.check_before_call(sid, "tool_b", "q")
    assert allowed is False
    assert "总次数" in reason or "上限" in reason


def test_consecutive_failures_terminates():
    """连续失败超过 MAX_CONSECUTIVE_FAILURES 应终止。"""
    mgr = ToolCallManager()
    mgr.MAX_CONSECUTIVE_FAILURES = 3
    sid = "test_failures"

    for _ in range(3):
        mgr.check_before_call(sid, "sql_db_query", "SELECT 1")
        mgr.record_call(sid, "sql_db_query", False, "SELECT 1")

    allowed, reason = mgr.check_before_call(sid, "sql_db_query", "SELECT 2")
    assert allowed is False
    assert "失败" in reason


def test_repeated_query_detected():
    """重复执行相同 SQL 应被拒绝。"""
    mgr = ToolCallManager()
    sid = "test_repeat_query"

    sql = "SELECT id, name FROM customers"
    mgr.check_before_call(sid, "sql_db_query", sql)
    mgr.record_call(sid, "sql_db_query", True, sql)

    allowed, reason = mgr.check_before_call(sid, "sql_db_query", sql)
    assert allowed is False
    assert "重复" in reason


def test_repeated_query_normalized_whitespace():
    """仅空白差异的 SQL 应视为同一查询。"""
    mgr = ToolCallManager()
    sid = "test_norm_query"

    mgr.check_before_call(sid, "sql_db_query", "SELECT  id,  name FROM  customers")
    mgr.record_call(sid, "sql_db_query", True, "SELECT  id,  name FROM  customers")

    allowed, reason = mgr.check_before_call(
        sid, "sql_db_query", "SELECT id, name FROM customers")
    assert allowed is False
    assert "重复" in reason


def test_clear_session_resets_state():
    mgr = ToolCallManager()
    sid = "test_clear"
    mgr.check_before_call(sid, "sql_db_query", "SELECT 1")
    mgr.record_call(sid, "sql_db_query", True, "SELECT 1")
    assert mgr.get_stats(sid)["total_calls"] == 1

    mgr.clear_session(sid)
    # 清除后 stats 应重置为 0
    assert mgr.get_stats(sid)["total_calls"] == 0


def test_reset_session_recreates_context():
    mgr = ToolCallManager()
    sid = "test_reset"
    mgr.check_before_call(sid, "sql_db_query", "SELECT 1")
    mgr.record_call(sid, "sql_db_query", False, "SELECT 1")
    mgr.reset_session(sid)
    # 重置后 stats 应为初始值
    assert mgr.get_stats(sid)["total_calls"] == 0
    assert mgr.get_stats(sid)["consecutive_failures"] == 0


def test_termination_is_sticky():
    """一旦触发终止，后续所有调用都应被拒绝。"""
    mgr = ToolCallManager()
    mgr.MAX_CALLS_PER_TOOL = 2
    sid = "test_sticky"

    for _ in range(2):
        mgr.check_before_call(sid, "tool_a", "q")
        mgr.record_call(sid, "tool_a", True, "q")

    allowed, _ = mgr.check_before_call(sid, "tool_a", "q")
    assert allowed is False
    # 切换工具也应仍被拒绝（sticky）
    allowed2, _ = mgr.check_before_call(sid, "tool_b", "q")
    assert allowed2 is False


# ---------------------------------------------------------------------------
# sql_db_query_checker：纯静态检查工具
# ---------------------------------------------------------------------------

def test_query_checker_rejects_empty():
    out = sql_db_query_checker.invoke({"query": ""})
    assert "为空" in out


def test_query_checker_rejects_insert():
    out = sql_db_query_checker.invoke({"query": "INSERT INTO t VALUES (1)"})
    assert "INSERT" in out


def test_query_checker_rejects_delete():
    out = sql_db_query_checker.invoke({"query": "DELETE FROM t WHERE id=1"})
    assert "DELETE" in out


def test_query_checker_rejects_drop():
    out = sql_db_query_checker.invoke({"query": "DROP TABLE t"})
    assert "DROP" in out


def test_query_checker_rejects_non_select():
    out = sql_db_query_checker.invoke({"query": "SHOW TABLES"})
    assert "SELECT" in out


def test_query_checker_warns_missing_from():
    out = sql_db_query_checker.invoke({"query": "SELECT 1"})
    assert "FROM" in out or "语法" in out


def test_query_checker_warns_unbalanced_parens():
    out = sql_db_query_checker.invoke({"query": "SELECT * FROM t WHERE (id = 1"})
    assert "括号" in out


def test_query_checker_warns_unbalanced_quotes():
    out = sql_db_query_checker.invoke({"query": "SELECT * FROM t WHERE name = 'abc"})
    assert "单引号" in out


def test_query_checker_passes_valid_select():
    out = sql_db_query_checker.invoke({"query": "SELECT id FROM customers"})
    assert "通过" in out or "✅" in out


def test_query_checker_allows_cte():
    out = sql_db_query_checker.invoke({
        "query": "WITH cte AS (SELECT 1) SELECT * FROM cte"
    })
    assert "错误" not in out


# ---------------------------------------------------------------------------
# sql_db_query：安全检查 + 执行
# ---------------------------------------------------------------------------

def test_sql_db_query_rejects_non_select(sqlite_datasource):
    out = sql_db_query.invoke({
        "datasource_id": sqlite_datasource,
        "query": "INSERT INTO customers VALUES (99, 'x', 'y')",
    })
    assert "INSERT" in out
    assert "不允许" in out or "错误" in out


def test_sql_db_query_rejects_delete(sqlite_datasource):
    out = sql_db_query.invoke({
        "datasource_id": sqlite_datasource,
        "query": "DELETE FROM customers WHERE id = 1",
    })
    assert "DELETE" in out


def test_sql_db_query_rejects_drop(sqlite_datasource):
    out = sql_db_query.invoke({
        "datasource_id": sqlite_datasource,
        "query": "DROP TABLE customers",
    })
    assert "DROP" in out


def test_sql_db_query_executes_select(sqlite_datasource):
    out = sql_db_query.invoke({
        "datasource_id": sqlite_datasource,
        "query": "SELECT id, name FROM customers ORDER BY id",
    })
    assert "查询成功" in out
    assert "张三" in out
    assert "李四" in out


def test_sql_db_query_executes_select_with_columns(sqlite_datasource):
    out = sql_db_query.invoke({
        "datasource_id": sqlite_datasource,
        "query": "SELECT COUNT(*) AS cnt FROM customers",
    })
    assert "查询成功" in out
    assert "2" in out


def test_sql_db_query_returns_empty_message(sqlite_datasource):
    out = sql_db_query.invoke({
        "datasource_id": sqlite_datasource,
        "query": "SELECT * FROM customers WHERE id = 9999",
    })
    assert "没有返回数据" in out


def test_sql_db_query_detects_repeated_query(sqlite_datasource):
    """同一会话重复执行相同 SQL 应被拒绝。"""
    sql = "SELECT id FROM customers"
    # 第一次执行
    out1 = sql_db_query.invoke({
        "datasource_id": sqlite_datasource,
        "query": sql,
        "conversation_id": "conv_repeat",
    })
    assert "查询成功" in out1

    # 第二次执行同一 SQL 应被拒绝
    out2 = sql_db_query.invoke({
        "datasource_id": sqlite_datasource,
        "query": sql,
        "conversation_id": "conv_repeat",
    })
    assert "重复" in out2


def test_sql_db_query_invalid_sql_returns_error(sqlite_datasource):
    out = sql_db_query.invoke({
        "datasource_id": sqlite_datasource,
        "query": "SELECT * FROM no_such_table",
    })
    assert "失败" in out or "error" in out.lower()


# ---------------------------------------------------------------------------
# sql_db_smart_search：表检索 + schema 返回
# ---------------------------------------------------------------------------

def test_smart_search_returns_schema(sqlite_datasource):
    out = sql_db_smart_search.invoke({
        "datasource_id": sqlite_datasource,
        "user_query": "客户的姓名",
    })
    # 应包含表名（表数 <= 20，返回全量）
    assert "customers" in out
    assert "orders" in out
    assert "schema 已获取" in out or "schema" in out.lower()


def test_smart_search_empty_query_rejected(sqlite_datasource):
    out = sql_db_smart_search.invoke({
        "datasource_id": sqlite_datasource,
        "user_query": "",
    })
    assert "user_query" in out or "不能为空" in out


def test_smart_search_records_call_status(sqlite_datasource):
    """smart_search 成功调用后应记录成功状态。"""
    sid = f"analyst_{sqlite_datasource}"
    mgr = get_tool_call_manager()
    mgr.clear_session(sid)  # 清理残留

    sql_db_smart_search.invoke({
        "datasource_id": sqlite_datasource,
        "user_query": "客户",
    })
    stats = mgr.get_stats(sid)
    assert stats["total_calls"] >= 1
    assert stats["successful_calls"] >= 1


# ---------------------------------------------------------------------------
# sql_db_table_schema：指定表查询
# ---------------------------------------------------------------------------

def test_table_schema_returns_columns(sqlite_datasource):
    out = sql_db_table_schema.invoke({
        "datasource_id": sqlite_datasource,
        "table_names": "customers",
    })
    assert "customers" in out
    assert "id" in out
    assert "name" in out


def test_table_schema_handles_missing_table(sqlite_datasource):
    out = sql_db_table_schema.invoke({
        "datasource_id": sqlite_datasource,
        "table_names": "no_such_table",
    })
    assert "不存在" in out or "未找到" in out


def test_table_schema_multi_tables(sqlite_datasource):
    out = sql_db_table_schema.invoke({
        "datasource_id": sqlite_datasource,
        "table_names": "customers,orders",
    })
    assert "customers" in out
    assert "orders" in out


# ---------------------------------------------------------------------------
# sql_db_table_relationship：外键关联
# ---------------------------------------------------------------------------

def test_table_relationship_returns_fk(sqlite_datasource):
    out = sql_db_table_relationship.invoke({
        "datasource_id": sqlite_datasource,
        "table_names": "orders,customers",
    })
    assert "orders" in out
    assert "customers" in out
    assert "customer_id" in out


def test_table_relationship_no_fk_returns_message(sqlite_datasource):
    out = sql_db_table_relationship.invoke({
        "datasource_id": sqlite_datasource,
        "table_names": "customers",
    })
    assert "外键关系" in out or "未找到" in out
