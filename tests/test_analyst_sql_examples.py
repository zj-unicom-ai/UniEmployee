"""SQL 示例管理 + 示例检索测试。

覆盖 P1-3/P1-4：
- sql_examples/manager.py: CRUD + chart_type 归一化 + 数据源关联 + 启停
- sql_examples/retriever.py: 关键词命中比例检索 + XML 格式化 + 注入一体化
- 注入点：sql_db_smart_search 命中示例时返回 XML 块
"""
import pytest

from app.agent.analyst.datasource import manager as ds_manager
from app.agent.analyst.sql_examples import manager as ex_manager
from app.agent.analyst.sql_examples.retriever import (
    retrieve_sql_examples, format_sql_examples_xml,
    build_sql_example_injection,
)
from app.agent.analyst.terminology import manager as term_manager
from app.agent.analyst.tools.sql_tools import sql_db_smart_search


# ---------------------------------------------------------------------------
# CRUD：create / get / list / update / delete
# ---------------------------------------------------------------------------

def test_create_and_get_example():
    ex = ex_manager.create_sql_example({
        "question": "本月销售额 TOP10 客户",
        "sql_text": "SELECT customer_name, SUM(amount) FROM orders GROUP BY 1 ORDER BY 2 DESC LIMIT 10",
        "description": "按销售额倒序的 TOP10",
        "chart_type": "bar",
    })
    assert ex["id"].startswith("ex_")
    assert ex["question"] == "本月销售额 TOP10 客户"
    assert "SUM(amount)" in ex["sql_text"]
    assert ex["chart_type"] == "bar"
    assert ex["enabled"] == 1

    fetched = ex_manager.get_sql_example(ex["id"])
    assert fetched is not None
    assert fetched["question"] == "本月销售额 TOP10 客户"


def test_create_rejects_empty_question():
    with pytest.raises(ValueError):
        ex_manager.create_sql_example({"question": "", "sql_text": "SELECT 1"})


def test_create_rejects_empty_sql():
    with pytest.raises(ValueError):
        ex_manager.create_sql_example({"question": "x", "sql_text": ""})


def test_list_excludes_disabled():
    ex_manager.create_sql_example({
        "question": "active", "sql_text": "SELECT 1", "enabled": 1,
    })
    ex_manager.create_sql_example({
        "question": "disabled", "sql_text": "SELECT 1", "enabled": 0,
    })
    listed = ex_manager.list_sql_examples()
    questions = [e["question"] for e in listed]
    assert "active" in questions
    assert "disabled" not in questions

    all_listed = ex_manager.list_sql_examples(include_disabled=True)
    all_q = [e["question"] for e in all_listed]
    assert "disabled" in all_q


def test_list_filter_by_datasource():
    ex_manager.create_sql_example({
        "question": "global_ex", "sql_text": "SELECT 1",
        "datasource_id": None,  # 适用全部
    })
    ex_manager.create_sql_example({
        "question": "ds1_ex", "sql_text": "SELECT 1",
        "datasource_id": "ds_a",
    })
    ex_manager.create_sql_example({
        "question": "ds2_ex", "sql_text": "SELECT 1",
        "datasource_id": "ds_b",
    })
    filtered = ex_manager.list_sql_examples(datasource_id="ds_a")
    questions = {e["question"] for e in filtered}
    assert "global_ex" in questions
    assert "ds1_ex" in questions
    assert "ds2_ex" not in questions


def test_update_partial():
    ex = ex_manager.create_sql_example({
        "question": "old_q", "sql_text": "old_sql",
    })
    updated = ex_manager.update_sql_example(ex["id"], {"description": "new_desc"})
    assert updated["description"] == "new_desc"
    assert updated["question"] == "old_q"
    assert updated["sql_text"] == "old_sql"


def test_update_returns_none_if_not_exist():
    assert ex_manager.update_sql_example("no_such", {"question": "x"}) is None


def test_delete_example():
    ex = ex_manager.create_sql_example({
        "question": "to_del", "sql_text": "SELECT 1",
    })
    assert ex_manager.delete_sql_example(ex["id"]) is True
    assert ex_manager.get_sql_example(ex["id"]) is None


def test_delete_returns_false_if_not_exist():
    assert ex_manager.delete_sql_example("no_such") is False


def test_get_returns_none_if_not_exist():
    assert ex_manager.get_sql_example("no_such") is None


# ---------------------------------------------------------------------------
# chart_type 归一化
# ---------------------------------------------------------------------------

def test_chart_type_normalize_valid():
    ex = ex_manager.create_sql_example({
        "question": "q", "sql_text": "SELECT 1",
        "chart_type": "PIE",  # 大写
    })
    assert ex["chart_type"] == "pie"  # 归一化为小写


def test_chart_type_normalize_invalid_to_empty():
    ex = ex_manager.create_sql_example({
        "question": "q", "sql_text": "SELECT 1",
        "chart_type": "scatter",  # 不支持
    })
    assert ex["chart_type"] == ""


def test_chart_type_normalize_empty():
    ex = ex_manager.create_sql_example({
        "question": "q", "sql_text": "SELECT 1",
    })
    assert ex["chart_type"] == ""


# ---------------------------------------------------------------------------
# 启停
# ---------------------------------------------------------------------------

def test_toggle_example():
    ex = ex_manager.create_sql_example({
        "question": "x", "sql_text": "SELECT 1", "enabled": 1,
    })
    disabled = ex_manager.toggle_sql_example(ex["id"], 0)
    assert disabled["enabled"] == 0
    assert all(e["id"] != ex["id"]
               for e in ex_manager.list_sql_examples())

    re_enabled = ex_manager.toggle_sql_example(ex["id"], 1)
    assert re_enabled["enabled"] == 1


# ---------------------------------------------------------------------------
# retriever：检索 + XML 格式化
# ---------------------------------------------------------------------------

def test_retrieve_empty_query_returns_empty():
    assert retrieve_sql_examples("") == []


def test_retrieve_matches_by_question_keywords():
    ex_manager.create_sql_example({
        "question": "本月销售额 TOP10 客户",
        "sql_text": "SELECT * FROM orders",
        "chart_type": "bar",
    })
    matched = retrieve_sql_examples("查本月销售额排行")
    assert any("销售额" in e["question"] for e in matched)


def test_retrieve_excludes_disabled():
    ex_manager.create_sql_example({
        "question": "disabled question xyzabc",
        "sql_text": "SELECT 1",
        "enabled": 0,
    })
    matched = retrieve_sql_examples("disabled question xyzabc")
    assert all(e["question"] != "disabled question xyzabc" for e in matched)


def test_retrieve_filters_by_datasource():
    ex_manager.create_sql_example({
        "question": "global q abc", "sql_text": "SELECT 1",
    })
    ex_manager.create_sql_example({
        "question": "ds1 q abc", "sql_text": "SELECT 1",
        "datasource_id": "ds_a",
    })
    ex_manager.create_sql_example({
        "question": "ds2 q abc", "sql_text": "SELECT 1",
        "datasource_id": "ds_b",
    })

    matched = retrieve_sql_examples("global ds1 ds2 q abc",
                                   datasource_id="ds_a")
    questions = {e["question"] for e in matched}
    assert "global q abc" in questions
    assert "ds1 q abc" in questions
    assert "ds2 q abc" not in questions


def test_retrieve_max_results_limit():
    for i in range(10):
        ex_manager.create_sql_example({
            "question": f"sample question {i}",
            "sql_text": "SELECT 1",
        })
    matched = retrieve_sql_examples("sample question",
                                   max_results=3)
    assert len(matched) <= 3


def test_retrieve_filters_low_hit_ratio():
    """完全无相关 token 且无子串命中时应被过滤。"""
    ex_manager.create_sql_example({
        "question": "abc def ghi jkl mno pqr",  # 6 个不同词
        "sql_text": "SELECT 1",
    })
    # query 完全无重叠 token，且无长度>=2 的子串命中
    matched = retrieve_sql_examples("xyz_no_match_123")
    assert matched == []


def test_format_xml_empty():
    assert format_sql_examples_xml([]) == ""


def test_format_xml_includes_question_and_sql():
    ex = {
        "question": "TOP10 客户",
        "sql_text": "SELECT * FROM customers",
        "chart_type": "bar",
        "description": "备注",
    }
    xml = format_sql_examples_xml([ex])
    assert "<sql_examples>" in xml
    assert "</sql_examples>" in xml
    assert 'question="TOP10 客户"' in xml
    assert 'chart_type="bar"' in xml
    assert "SELECT * FROM customers" in xml
    assert "<description>备注</description>" in xml


def test_format_xml_escapes_sql_special_chars():
    ex = {
        "question": "q",
        "sql_text": "SELECT * FROM t WHERE x < 1 AND y > 2",
        "chart_type": "",
    }
    xml = format_sql_examples_xml([ex])
    # < > 应被转义
    assert "< 1" not in xml
    assert "&lt;" in xml or "&gt;" in xml


def test_build_injection_empty_when_no_match():
    ex_manager.create_sql_example({
        "question": "abc", "sql_text": "SELECT 1",
    })
    # query "xyz123" 不命中
    assert build_sql_example_injection("xyz123_no_match") == ""


def test_build_injection_returns_xml_when_match():
    ex_manager.create_sql_example({
        "question": "客户销售统计",
        "sql_text": "SELECT * FROM orders",
        "chart_type": "bar",
    })
    xml = build_sql_example_injection("客户销售")
    assert xml.startswith("<sql_examples>")
    assert "客户销售统计" in xml


# ---------------------------------------------------------------------------
# 注入点：sql_db_smart_search 命中示例时返回 XML 块
# ---------------------------------------------------------------------------

@pytest.fixture
def sqlite_datasource_with_example(monkeypatch, tmp_path):
    import sqlite3
    from sqlalchemy import create_engine

    monkeypatch.setenv("ANALYST_DB_KEY", "test-key-for-analyst-0123456789")
    monkeypatch.setattr(ds_manager, "_CIPHER_KEY", None)
    ds = ds_manager.create_datasource({
        "name": "测试库", "db_type": "mysql",
        "config": {"host": "h", "username": "u", "password": "p", "database": "d"},
    })
    db_file = tmp_path / "biz.sqlite"
    con = sqlite3.connect(db_file)
    con.execute("CREATE TABLE orders (id INTEGER PRIMARY KEY, amount REAL)")
    con.commit()
    con.close()
    engine = create_engine(f"sqlite:///{db_file}", pool_pre_ping=True)
    ds_manager._engine_cache[ds["id"]] = engine

    ex_manager.create_sql_example({
        "question": "本月销售额 TOP10",
        "sql_text": "SELECT id, amount FROM orders ORDER BY amount DESC LIMIT 10",
        "chart_type": "bar",
        "datasource_id": ds["id"],
    })
    yield ds["id"]
    from app.agent.analyst.tools.tool_call_manager import get_tool_call_manager
    mgr = get_tool_call_manager()
    mgr.clear_session(f"analyst_{ds['id']}")


def test_smart_search_injects_example_xml(sqlite_datasource_with_example):
    out = sql_db_smart_search.invoke({
        "datasource_id": sqlite_datasource_with_example,
        "user_query": "本月销售额排行",
    })
    assert "<sql_examples>" in out
    assert "本月销售额 TOP10" in out
    assert "ORDER BY amount DESC" in out
    # schema 文本仍存在
    assert "orders" in out


def test_smart_search_no_example_match_no_xml(monkeypatch, tmp_path):
    """无示例命中时不应注入空 XML 块。"""
    import sqlite3
    from sqlalchemy import create_engine

    monkeypatch.setenv("ANALYST_DB_KEY", "test-key-for-analyst-0123456789")
    monkeypatch.setattr(ds_manager, "_CIPHER_KEY", None)
    ds = ds_manager.create_datasource({
        "name": "DS", "db_type": "mysql",
        "config": {"host": "h", "username": "u", "password": "p", "database": "d"},
    })
    db_file = tmp_path / "biz.sqlite"
    con = sqlite3.connect(db_file)
    con.execute("CREATE TABLE products (id INTEGER PRIMARY KEY)")
    con.commit()
    con.close()
    ds_manager._engine_cache[ds["id"]] = create_engine(f"sqlite:///{db_file}")

    out = sql_db_smart_search.invoke({
        "datasource_id": ds["id"],
        "user_query": "products list",
    })
    assert "<sql_examples>" not in out
    assert "products" in out


# ---------------------------------------------------------------------------
# 同时注入术语 + 示例
# ---------------------------------------------------------------------------

def test_smart_search_injects_both_term_and_example(monkeypatch, tmp_path):
    """同时命中术语和示例时两者都应被注入。"""
    import sqlite3
    from sqlalchemy import create_engine

    monkeypatch.setenv("ANALYST_DB_KEY", "test-key-for-analyst-0123456789")
    monkeypatch.setattr(ds_manager, "_CIPHER_KEY", None)
    ds = ds_manager.create_datasource({
        "name": "DS", "db_type": "mysql",
        "config": {"host": "h", "username": "u", "password": "p", "database": "d"},
    })
    db_file = tmp_path / "biz.sqlite"
    con = sqlite3.connect(db_file)
    con.execute("CREATE TABLE customers (id INTEGER PRIMARY KEY, name TEXT)")
    con.commit()
    con.close()
    ds_manager._engine_cache[ds["id"]] = create_engine(f"sqlite:///{db_file}")

    # 预置术语
    term_manager.create_terminology({
        "word": "客户", "synonyms": ["用户"],
        "datasource_ids": [ds["id"]],
    })
    # 预置示例
    ex_manager.create_sql_example({
        "question": "客户数统计",
        "sql_text": "SELECT COUNT(*) FROM customers",
        "datasource_id": ds["id"],
    })

    out = sql_db_smart_search.invoke({
        "datasource_id": ds["id"],
        "user_query": "统计客户数量",
    })
    assert "<terminologies>" in out
    assert "<sql_examples>" in out
    # 顺序：术语在前，示例在后
    assert out.index("<terminologies>") < out.index("<sql_examples>")
