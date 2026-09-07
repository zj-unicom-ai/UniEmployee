"""术语管理 + 术语检索测试。

覆盖 P1-1/P1-2：
- terminology/manager.py: CRUD + 同义词增删/归一化 + 数据源关联 + 启停
- terminology/retriever.py: 关键词匹配检索 + XML 格式化 + 注入一体化
- 注入点：sql_db_smart_search 命中术语时返回 XML 块
"""
import json

import pytest

from app.agent.analyst.datasource import manager as ds_manager
from app.agent.analyst.terminology import manager as term_manager
from app.agent.analyst.terminology.retriever import (
    retrieve_terminologies, format_terminologies_xml,
    build_terminology_injection,
)
from app.agent.analyst.tools.sql_tools import sql_db_smart_search


# ---------------------------------------------------------------------------
# CRUD：create / get / list / update / delete
# ---------------------------------------------------------------------------

def test_create_and_get_terminology():
    term = term_manager.create_terminology({
        "word": "客户",
        "description": "购买公司产品的企业或个人",
        "synonyms": ["用户", "会员"],
    })
    assert term["id"].startswith("term_")
    assert term["word"] == "客户"
    assert term["description"] == "购买公司产品的企业或个人"
    assert term["synonyms"] == ["用户", "会员"]
    assert term["enabled"] == 1

    fetched = term_manager.get_terminology(term["id"])
    assert fetched is not None
    assert fetched["word"] == "客户"


def test_create_terminology_rejects_empty_word():
    with pytest.raises(ValueError):
        term_manager.create_terminology({"word": ""})


def test_list_terminologies_excludes_disabled():
    term_manager.create_terminology({"word": "active_term", "enabled": 1})
    term_manager.create_terminology({"word": "disabled_term", "enabled": 0})

    listed = term_manager.list_terminologies()
    words = [t["word"] for t in listed]
    assert "active_term" in words
    assert "disabled_term" not in words

    # include_disabled=True 应包含
    all_listed = term_manager.list_terminologies(include_disabled=True)
    all_words = [t["word"] for t in all_listed]
    assert "disabled_term" in all_words


def test_list_terminologies_filter_by_datasource():
    """datasource_ids 为空（适用全部）或包含目标数据源的术语应命中。"""
    t_global = term_manager.create_terminology({
        "word": "global_term", "datasource_ids": [],
    })
    t_ds1 = term_manager.create_terminology({
        "word": "ds1_term", "datasource_ids": ["ds_a"],
    })
    t_ds2 = term_manager.create_terminology({
        "word": "ds2_term", "datasource_ids": ["ds_b"],
    })

    filtered = term_manager.list_terminologies(datasource_id="ds_a")
    words = {t["word"] for t in filtered}
    assert "global_term" in words  # 适用全部
    assert "ds1_term" in words  # 匹配
    assert "ds2_term" not in words  # 不匹配


def test_update_terminology_partial():
    term = term_manager.create_terminology({
        "word": "old", "description": "old_desc",
        "synonyms": ["s1"],
    })
    updated = term_manager.update_terminology(term["id"], {
        "description": "new_desc",
    })
    assert updated["description"] == "new_desc"
    # 未更新的字段应保留
    assert updated["word"] == "old"
    assert updated["synonyms"] == ["s1"]


def test_update_terminology_replaces_synonyms():
    """更新 synonyms 应整体替换，不追加。"""
    term = term_manager.create_terminology({
        "word": "w", "synonyms": ["a", "b"],
    })
    updated = term_manager.update_terminology(term["id"], {
        "synonyms": ["c", "d"],
    })
    assert updated["synonyms"] == ["c", "d"]
    assert "a" not in updated["synonyms"]


def test_update_terminology_returns_none_if_not_exist():
    assert term_manager.update_terminology("no_such_id", {"word": "x"}) is None


def test_delete_terminology():
    term = term_manager.create_terminology({"word": "to_delete"})
    assert term_manager.delete_terminology(term["id"]) is True
    assert term_manager.get_terminology(term["id"]) is None


def test_delete_terminology_returns_false_if_not_exist():
    assert term_manager.delete_terminology("no_such_id") is False


def test_get_terminology_returns_none_if_not_exist():
    assert term_manager.get_terminology("no_such_id") is None


# ---------------------------------------------------------------------------
# 同义词增删 + 归一化
# ---------------------------------------------------------------------------

def test_add_synonym_appends_and_dedups():
    term = term_manager.create_terminology({
        "word": "客户", "synonyms": ["用户"],
    })
    # 添加新同义词
    updated = term_manager.add_synonym(term["id"], "会员")
    assert "会员" in updated["synonyms"]

    # 重复添加应幂等（不重复）
    updated2 = term_manager.add_synonym(term["id"], "会员")
    assert updated2["synonyms"].count("会员") == 1


def test_add_synonym_rejects_empty():
    term = term_manager.create_terminology({"word": "x"})
    with pytest.raises(ValueError):
        term_manager.add_synonym(term["id"], "   ")


def test_remove_synonym():
    term = term_manager.create_terminology({
        "word": "x", "synonyms": ["a", "b", "c"],
    })
    updated = term_manager.remove_synonym(term["id"], "b")
    assert updated["synonyms"] == ["a", "c"]

    # 不存在的同义词应幂等
    updated2 = term_manager.remove_synonym(term["id"], "no_such")
    assert "a" in updated2["synonyms"]


def test_synonyms_normalize_from_comma_string():
    """字符串逗号分隔形式应被归一化。"""
    term = term_manager.create_terminology({
        "word": "w", "synonyms": "a, b, a, ,c",
    })
    assert term["synonyms"] == ["a", "b", "c"]


def test_synonyms_normalize_dedup_preserves_order():
    term = term_manager.create_terminology({
        "word": "w", "synonyms": ["b", "a", "b", "a", "c"],
    })
    assert term["synonyms"] == ["b", "a", "c"]


# ---------------------------------------------------------------------------
# 启停
# ---------------------------------------------------------------------------

def test_toggle_terminology():
    term = term_manager.create_terminology({"word": "x", "enabled": 1})
    disabled = term_manager.toggle_terminology(term["id"], 0)
    assert disabled["enabled"] == 0
    # 禁用后默认 list 不可见
    assert all(t["id"] != term["id"]
               for t in term_manager.list_terminologies())

    re_enabled = term_manager.toggle_terminology(term["id"], 1)
    assert re_enabled["enabled"] == 1


# ---------------------------------------------------------------------------
# 数据源关联字段归一化
# ---------------------------------------------------------------------------

def test_datasource_ids_normalize_from_string():
    term = term_manager.create_terminology({
        "word": "w", "datasource_ids": "ds1, ds2, ,ds1",
    })
    # 字符串归一化（不做去重，仅去空白），实际我们的 _normalize_datasource_ids 不去重
    # 查代码：_normalize_datasource_ids 不去重，仅去空白
    # 但创建时存储后，读取时 datasource_ids 是 list，包含 ds1, ds2, ds1
    assert "ds1" in term["datasource_ids"]
    assert "ds2" in term["datasource_ids"]


# ---------------------------------------------------------------------------
# retriever：检索 + XML 格式化
# ---------------------------------------------------------------------------

def test_retrieve_empty_query_returns_empty():
    assert retrieve_terminologies("") == []
    assert retrieve_terminologies("   ") == []


def test_retrieve_matches_word():
    """query 中包含术语词应命中。"""
    term_manager.create_terminology({
        "word": "客户", "description": "业务术语",
        "synonyms": ["用户"],
    })
    matched = retrieve_terminologies("查询客户的订单")
    assert any(t["word"] == "客户" for t in matched)


def test_retrieve_matches_synonym():
    """query 中包含同义词应命中对应术语。"""
    term_manager.create_terminology({
        "word": "客户", "synonyms": ["用户", "会员"],
    })
    matched = retrieve_terminologies("统计用户的订单数")
    assert any(t["word"] == "客户" for t in matched)


def test_retrieve_excludes_disabled():
    term_manager.create_terminology({
        "word": "disabled_term", "enabled": 0,
    })
    matched = retrieve_terminologies("disabled_term 的数据")
    assert all(t["word"] != "disabled_term" for t in matched)


def test_retrieve_filters_by_datasource():
    """限定 datasource_id 时，只命中该数据源相关的术语。"""
    term_manager.create_terminology({
        "word": "global_term",  # 适用全部
    })
    term_manager.create_terminology({
        "word": "ds1_term", "datasource_ids": ["ds_a"],
    })
    term_manager.create_terminology({
        "word": "ds2_term", "datasource_ids": ["ds_b"],
    })

    matched = retrieve_terminologies("global_term ds1_term ds2_term",
                                     datasource_id="ds_a")
    words = {t["word"] for t in matched}
    assert "global_term" in words
    assert "ds1_term" in words
    assert "ds2_term" not in words


def test_retrieve_max_results_limit():
    for i in range(10):
        term_manager.create_terminology({"word": f"term_{i}"})
    matched = retrieve_terminologies("term_0 term_1 term_2 term_3",
                                     max_results=2)
    assert len(matched) <= 2


def test_format_xml_empty():
    assert format_terminologies_xml([]) == ""


def test_format_xml_includes_word_and_synonyms():
    term = {
        "word": "客户",
        "description": "业务术语",
        "synonyms": ["用户", "会员"],
    }
    xml = format_terminologies_xml([term])
    assert "<terminologies>" in xml
    assert "</terminologies>" in xml
    assert 'word="客户"' in xml
    assert 'description="业务术语"' in xml
    assert "<synonym>用户</synonym>" in xml
    assert "<synonym>会员</synonym>" in xml


def test_format_xml_escapes_special_chars():
    """XML 转义：含 < > & 应被转义。"""
    term = {
        "word": "a<b",
        "description": "x & y",
        "synonyms": [],
    }
    xml = format_terminologies_xml([term])
    assert "<" not in xml.replace("<terminologies>", "").replace("</terminologies>", "").replace("<term", "").replace("</term>", "")
    assert "&lt;" in xml or "&amp;" in xml


def test_build_injection_empty_when_no_match():
    """无命中时返回空字符串。"""
    term_manager.create_terminology({"word": "客户"})
    # "abc" 不命中任何术语
    assert build_terminology_injection("abcxyz123") == ""


def test_build_injection_returns_xml_when_match():
    term_manager.create_terminology({
        "word": "客户", "synonyms": ["用户"],
    })
    xml = build_terminology_injection("统计用户数")
    assert xml.startswith("<terminologies>")
    assert "客户" in xml


# ---------------------------------------------------------------------------
# 注入点：sql_db_smart_search 命中术语时返回 XML 块
# ---------------------------------------------------------------------------

@pytest.fixture
def sqlite_datasource_with_term(monkeypatch, tmp_path):
    """建一个用 sqlite engine 注入的数据源，并预置一些术语。"""
    import sqlite3
    from sqlalchemy import create_engine

    monkeypatch.setenv("ANALYST_DB_KEY", "test-key-for-analyst-0123456789")
    monkeypatch.setattr(ds_manager, "_CIPHER_KEY", None)

    ds = ds_manager.create_datasource({
        "name": "测试库", "description": "",
        "db_type": "mysql",
        "config": {"host": "h", "username": "u", "password": "p", "database": "d"},
        "enabled": 1, "owner_id": "u",
    })
    db_file = tmp_path / "biz.sqlite"
    con = sqlite3.connect(db_file)
    con.execute("CREATE TABLE customers (id INTEGER PRIMARY KEY, name TEXT)")
    con.execute("CREATE TABLE orders (id INTEGER PRIMARY KEY, amount REAL)")
    con.commit()
    con.close()
    engine = create_engine(f"sqlite:///{db_file}", pool_pre_ping=True)
    ds_manager._engine_cache[ds["id"]] = engine

    # 预置术语
    term_manager.create_terminology({
        "word": "客户",
        "description": "购买产品的企业或个人",
        "synonyms": ["用户", "会员"],
        "datasource_ids": [ds["id"]],
    })
    yield ds["id"]
    # 清理 ToolCallManager 状态
    from app.agent.analyst.tools.tool_call_manager import get_tool_call_manager
    mgr = get_tool_call_manager()
    mgr.clear_session(f"analyst_{ds['id']}")


def test_smart_search_injects_terminology_xml(sqlite_datasource_with_term):
    """smart_search 命中术语时应在返回文本中拼入术语 XML。"""
    out = sql_db_smart_search.invoke({
        "datasource_id": sqlite_datasource_with_term,
        "user_query": "统计客户的订单数",
    })
    assert "<terminologies>" in out
    assert "客户" in out
    assert "<synonym>用户</synonym>" in out
    # schema 文本仍应存在
    assert "customers" in out


def test_smart_search_no_terminology_match_returns_no_xml(monkeypatch, tmp_path):
    """无术语命中时不应注入空 XML 块。"""
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

    # 不预置任何术语
    out = sql_db_smart_search.invoke({
        "datasource_id": ds["id"],
        "user_query": "products list",
    })
    assert "<terminologies>" not in out
    assert "products" in out
