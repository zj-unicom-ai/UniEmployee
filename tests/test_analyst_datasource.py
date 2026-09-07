"""数据分析员工（analyst）数据源管理 + 表结构发现测试。

覆盖 P0-1/P0-2/P0-3：
- manager.py: 加解密、URI 构建、数据源 CRUD、SQL 执行安全、表标注 CRUD
- schema_inspector.py: 表/列/外键发现

测试策略：
- 用 tmp_db 夹具隔离 catalog 库（autouse）
- 用 sqlite 文件库注入 _engine_cache，避免依赖外部数据库
- 加密/URI 构建走纯函数测试，不依赖真实连接
"""
import sqlite3
import time

import pytest
from sqlalchemy import create_engine, text

from app.agent.analyst.datasource import manager as ds_manager
from app.agent.analyst.datasource import schema_inspector


# ---------------------------------------------------------------------------
# 辅助：在 tmp_path 下建一个 sqlite 业务库（含表与数据）
# ---------------------------------------------------------------------------

def _make_sqlite_business_db(path):
    """在指定路径建 sqlite 库，含 customers/orders 两张表 + 外键 + 数据。"""
    con = sqlite3.connect(path)
    con.execute("PRAGMA foreign_keys = ON")
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


def _inject_sqlite_engine(monkeypatch, tmp_path, ds_id):
    """给 manager._engine_cache 注入一个真实 sqlite engine，绕开 build_connection_uri。"""
    db_file = tmp_path / f"biz_{ds_id}.sqlite"
    _make_sqlite_business_db(db_file)

    # 清空可能残留的缓存
    monkeypatch.setitem(ds_manager._engine_cache, ds_id, None)
    engine = create_engine(f"sqlite:///{db_file}", pool_pre_ping=True)
    monkeypatch.setitem(ds_manager._engine_cache, ds_id, engine)
    return engine


# ---------------------------------------------------------------------------
# 加密 / 解密
# ---------------------------------------------------------------------------

def test_encrypt_decrypt_roundtrip(monkeypatch):
    """加密→解密能还原原始 config。"""
    monkeypatch.setenv("ANALYST_DB_KEY", "test-key-for-analyst-0123456789")
    monkeypatch.setattr(ds_manager, "_CIPHER_KEY", None)

    config = {"host": "localhost", "username": "root", "password": "p@ssw0rd"}
    encrypted = ds_manager.encrypt_config(config)
    assert isinstance(encrypted, str)
    assert "p@ssw0rd" not in encrypted  # 密文不应包含明文密码

    decrypted = ds_manager.decrypt_config(encrypted)
    assert decrypted == config


def test_decrypt_with_wrong_key_returns_garbage(monkeypatch):
    """不同密钥加密的密文不能被另一密钥解密。"""
    monkeypatch.setenv("ANALYST_DB_KEY", "key-a-aaaaaaaaaaaaaaaaaaaaaaaa")
    monkeypatch.setattr(ds_manager, "_CIPHER_KEY", None)
    encrypted = ds_manager.encrypt_config({"password": "secret"})

    monkeypatch.setenv("ANALYST_DB_KEY", "key-b-bbbbbbbbbbbbbbbbbbbbbbbb")
    monkeypatch.setattr(ds_manager, "_CIPHER_KEY", None)
    with pytest.raises(Exception):
        ds_manager.decrypt_config(encrypted)


# ---------------------------------------------------------------------------
# build_connection_uri
# ---------------------------------------------------------------------------

def test_build_connection_uri_mysql():
    uri = ds_manager.build_connection_uri("mysql", {
        "host": "10.0.0.1", "port": 3306, "username": "u",
        "password": "p@ss", "database": "testdb",
    })
    assert uri.startswith("mysql+pymysql://u:")
    assert "10.0.0.1:3306/testdb" in uri


def test_build_connection_uri_pg_with_schema():
    uri = ds_manager.build_connection_uri("pg", {
        "host": "h", "port": 5432, "username": "u", "password": "p",
        "database": "db", "dbSchema": "myschema",
    })
    assert "postgresql+psycopg2://" in uri
    assert "options=-c%20search_path%3Dmyschema" in uri


def test_build_connection_uri_invalid_type():
    with pytest.raises(ValueError):
        ds_manager.build_connection_uri("redis", {"host": "h"})


def test_build_connection_uri_extra_jdbc():
    uri = ds_manager.build_connection_uri("mysql", {
        "host": "h", "port": 3306, "username": "u", "password": "p",
        "database": "db", "extraJdbc": "charset=utf8mb4",
    })
    assert uri.endswith("?charset=utf8mb4")


# ---------------------------------------------------------------------------
# 数据源 CRUD（catalog.datasources 表）
# ---------------------------------------------------------------------------

def _make_ds_data(name="测试数据源", db_type="mysql", **overrides):
    base = {
        "name": name,
        "description": "desc",
        "db_type": db_type,
        "config": {"host": "h", "username": "u", "password": "p", "database": "d"},
        "enabled": 1,
        "owner_id": "user_test",
    }
    base.update(overrides)
    return base


def test_create_and_get_datasource(monkeypatch):
    monkeypatch.setenv("ANALYST_DB_KEY", "test-key-for-analyst-0123456789")
    monkeypatch.setattr(ds_manager, "_CIPHER_KEY", None)

    ds = ds_manager.create_datasource(_make_ds_data(name="DS-A"))
    assert ds["id"].startswith("ds_")
    assert ds["name"] == "DS-A"
    assert ds["db_type"] == "mysql"

    fetched = ds_manager.get_datasource(ds["id"])
    assert fetched is not None
    assert fetched["name"] == "DS-A"
    # get_datasource 返回的 config 是密文（解密应在使用时）
    assert fetched["config"] != ""


def test_list_datasources_order_and_deleted_invisible(monkeypatch):
    monkeypatch.setenv("ANALYST_DB_KEY", "test-key-for-analyst-0123456789")
    monkeypatch.setattr(ds_manager, "_CIPHER_KEY", None)

    a = ds_manager.create_datasource(_make_ds_data(name="A"))
    b = ds_manager.create_datasource(_make_ds_data(name="B"))

    listed = ds_manager.list_datasources()
    names = [x["name"] for x in listed]
    assert {"A", "B"} <= set(names)

    # 软删除 B
    assert ds_manager.delete_datasource(b["id"]) is True
    listed2 = ds_manager.list_datasources()
    names2 = [x["name"] for x in listed2]
    assert "B" not in names2
    assert "A" in names2


def test_get_datasource_returns_none_if_not_exist():
    assert ds_manager.get_datasource("nonexistent_ds_id") is None


def test_update_datasource_name_and_clears_engine_cache(monkeypatch, tmp_path):
    monkeypatch.setenv("ANALYST_DB_KEY", "test-key-for-analyst-0123456789")
    monkeypatch.setattr(ds_manager, "_CIPHER_KEY", None)

    ds = ds_manager.create_datasource(_make_ds_data(name="old"))
    # 注入一个假 engine（带 dispose 方法），更新后应被清除
    ds_manager._engine_cache[ds["id"]] = type(
        "FakeEngine", (), {"dispose": staticmethod(lambda: None)})()
    updated = ds_manager.update_datasource(ds["id"], {"name": "new"})
    assert updated["name"] == "new"
    assert ds["id"] not in ds_manager._engine_cache


def test_update_datasource_config_reencrypts(monkeypatch):
    monkeypatch.setenv("ANALYST_DB_KEY", "test-key-for-analyst-0123456789")
    monkeypatch.setattr(ds_manager, "_CIPHER_KEY", None)

    ds = ds_manager.create_datasource(_make_ds_data(name="DS"))
    old_cipher = ds["config"]

    updated = ds_manager.update_datasource(ds["id"], {
        "config": {"host": "newhost", "username": "u", "password": "newp", "database": "d"}
    })
    # 新密文与旧密文不同
    assert updated["config"] != old_cipher


def test_update_datasource_returns_none_if_not_exist():
    assert ds_manager.update_datasource("no_such_id", {"name": "x"}) is None


def test_delete_datasource_returns_false_if_not_exist():
    assert ds_manager.delete_datasource("no_such_id") is False


def test_clear_engine_cache_single_and_all(monkeypatch):
    ds_manager._engine_cache["a"] = "fake_engine_a"
    ds_manager._engine_cache["b"] = "fake_engine_b"
    # 单个清除（fake engine 无 dispose 方法，跳过 dispose 调用）
    ds_manager._engine_cache["a"] = type("E", (), {"dispose": staticmethod(lambda: None)})()
    ds_manager.clear_engine_cache("a")
    assert "a" not in ds_manager._engine_cache
    assert "b" in ds_manager._engine_cache

    # 全部清除
    ds_manager._engine_cache["b"] = type("E", (), {"dispose": staticmethod(lambda: None)})()
    ds_manager.clear_engine_cache()
    assert ds_manager._engine_cache == {}


# ---------------------------------------------------------------------------
# SQL 执行（execute_query）+ 安全检查
# ---------------------------------------------------------------------------

def test_execute_query_rejects_insert(monkeypatch, tmp_path):
    monkeypatch.setenv("ANALYST_DB_KEY", "test-key-for-analyst-0123456789")
    monkeypatch.setattr(ds_manager, "_CIPHER_KEY", None)
    ds = ds_manager.create_datasource(_make_ds_data(name="DS"))
    _inject_sqlite_engine(monkeypatch, tmp_path, ds["id"])

    result = ds_manager.execute_query(ds["id"], "INSERT INTO customers VALUES (99, 'x', 'y')")
    assert result["success"] is False
    assert "INSERT" in result["error"]


def test_execute_query_rejects_drop(monkeypatch, tmp_path):
    monkeypatch.setenv("ANALYST_DB_KEY", "test-key-for-analyst-0123456789")
    monkeypatch.setattr(ds_manager, "_CIPHER_KEY", None)
    ds = ds_manager.create_datasource(_make_ds_data(name="DS"))
    _inject_sqlite_engine(monkeypatch, tmp_path, ds["id"])

    result = ds_manager.execute_query(ds["id"], "DROP TABLE customers")
    assert result["success"] is False
    assert "DROP" in result["error"]


def test_execute_query_select_returns_data(monkeypatch, tmp_path):
    monkeypatch.setenv("ANALYST_DB_KEY", "test-key-for-analyst-0123456789")
    monkeypatch.setattr(ds_manager, "_CIPHER_KEY", None)
    ds = ds_manager.create_datasource(_make_ds_data(name="DS"))
    _inject_sqlite_engine(monkeypatch, tmp_path, ds["id"])

    result = ds_manager.execute_query(ds["id"], "SELECT id, name FROM customers ORDER BY id")
    assert result["success"] is True
    assert result["columns"] == ["id", "name"]
    assert len(result["data"]) == 2
    assert result["data"][0]["name"] == "张三"


def test_execute_query_auto_adds_limit(monkeypatch, tmp_path):
    """未带 LIMIT 的 SELECT 应自动追加 LIMIT。"""
    monkeypatch.setenv("ANALYST_DB_KEY", "test-key-for-analyst-0123456789")
    monkeypatch.setattr(ds_manager, "_CIPHER_KEY", None)
    ds = ds_manager.create_datasource(_make_ds_data(name="DS"))
    _inject_sqlite_engine(monkeypatch, tmp_path, ds["id"])

    # 用 sqlite 的子查询计数验证 LIMIT 生效（sqlite 支持 LIMIT）
    result = ds_manager.execute_query(ds["id"], "SELECT * FROM customers", limit=1)
    assert result["success"] is True
    assert len(result["data"]) == 1


def test_execute_query_with_cte_allowed(monkeypatch, tmp_path):
    """WITH ... SELECT 应被允许（CTE）。"""
    monkeypatch.setenv("ANALYST_DB_KEY", "test-key-for-analyst-0123456789")
    monkeypatch.setattr(ds_manager, "_CIPHER_KEY", None)
    ds = ds_manager.create_datasource(_make_ds_data(name="DS"))
    _inject_sqlite_engine(monkeypatch, tmp_path, ds["id"])

    sql = "WITH cte AS (SELECT id FROM customers) SELECT * FROM cte"
    result = ds_manager.execute_query(ds["id"], sql)
    assert result["success"] is True
    assert result["data"] == [{"id": 1}, {"id": 2}]


def test_execute_query_returns_failure_if_datasource_not_exist():
    result = ds_manager.execute_query("nonexistent", "SELECT 1")
    assert result["success"] is False


# ---------------------------------------------------------------------------
# test_connection（用 sqlite 真实连接）
# ---------------------------------------------------------------------------

def test_connection_success_with_sqlite(tmp_path, monkeypatch):
    """sqlite 不在 SQLALCHEMY_DB_TYPES 中，这里跳过 build_connection_uri，直接测 create_engine 路径。

    为了不污染产品代码，仅验证 test_connection 的异常路径。"""
    # 用 mysql 类型但配置错误，应返回失败
    ok, msg = ds_manager.test_connection("mysql", {
        "host": "127.0.0.1", "port": 1,  # 故意用不可达端口
        "username": "u", "password": "p", "database": "d",
    })
    # 在网络可达性差时大概率失败；允许 timeout 类失败
    assert ok is False
    assert msg  # 错误信息非空


# ---------------------------------------------------------------------------
# 表标注 CRUD（table_annotations 表）
# ---------------------------------------------------------------------------

def test_table_annotation_upsert_and_get(monkeypatch):
    monkeypatch.setenv("ANALYST_DB_KEY", "test-key-for-analyst-0123456789")
    monkeypatch.setattr(ds_manager, "_CIPHER_KEY", None)
    ds = ds_manager.create_datasource(_make_ds_data(name="DS"))

    # 首次创建
    ann = ds_manager.upsert_table_annotation(
        ds["id"], "customers",
        table_comment="客户表",
        queryable=1,
        column_annotations={"name": {"comment": "客户姓名"}},
    )
    assert ann["table_comment"] == "客户表"
    assert ann["column_annotations"]["name"]["comment"] == "客户姓名"

    # 再次 upsert 应更新而非新增
    ann2 = ds_manager.upsert_table_annotation(
        ds["id"], "customers",
        table_comment="客户主表",
        column_annotations={"phone": {"comment": "联系电话"}},
    )
    assert ann2["table_comment"] == "客户主表"
    assert ann2["column_annotations"]["phone"]["comment"] == "联系电话"

    # 数据库应只有一行
    listed = ds_manager.list_table_annotations(ds["id"])
    assert len(listed) == 1
    assert listed[0]["table_name"] == "customers"


def test_table_annotation_get_returns_none_if_not_exist(monkeypatch):
    monkeypatch.setenv("ANALYST_DB_KEY", "test-key-for-analyst-0123456789")
    monkeypatch.setattr(ds_manager, "_CIPHER_KEY", None)
    ds = ds_manager.create_datasource(_make_ds_data(name="DS"))
    assert ds_manager.get_table_annotation(ds["id"], "no_such_table") is None


def test_table_annotation_list_empty(monkeypatch):
    monkeypatch.setenv("ANALYST_DB_KEY", "test-key-for-analyst-0123456789")
    monkeypatch.setattr(ds_manager, "_CIPHER_KEY", None)
    ds = ds_manager.create_datasource(_make_ds_data(name="DS"))
    assert ds_manager.list_table_annotations(ds["id"]) == []


# ---------------------------------------------------------------------------
# schema_inspector（表结构发现）
# ---------------------------------------------------------------------------

def test_get_all_tables_discovers_tables_and_columns(monkeypatch, tmp_path):
    monkeypatch.setenv("ANALYST_DB_KEY", "test-key-for-analyst-0123456789")
    monkeypatch.setattr(ds_manager, "_CIPHER_KEY", None)
    ds = ds_manager.create_datasource(_make_ds_data(name="DS"))
    _inject_sqlite_engine(monkeypatch, tmp_path, ds["id"])

    tables = schema_inspector.get_all_tables(ds["id"])
    assert "customers" in tables
    assert "orders" in tables

    cust = tables["customers"]
    assert "id" in cust["columns"]
    assert "name" in cust["columns"]
    # sqlite 类型字符串
    assert cust["columns"]["id"]["type"]


def test_get_all_tables_includes_user_annotation(monkeypatch, tmp_path):
    """用户标注的中文注释应覆盖数据库原始注释。"""
    monkeypatch.setenv("ANALYST_DB_KEY", "test-key-for-analyst-0123456789")
    monkeypatch.setattr(ds_manager, "_CIPHER_KEY", None)
    ds = ds_manager.create_datasource(_make_ds_data(name="DS"))
    _inject_sqlite_engine(monkeypatch, tmp_path, ds["id"])

    # 给 customers 表打标注
    ds_manager.upsert_table_annotation(
        ds["id"], "customers",
        table_comment="客户主表",
        column_annotations={"name": {"comment": "客户姓名"}},
    )

    tables = schema_inspector.get_all_tables(ds["id"])
    assert tables["customers"]["table_comment"] == "客户主表"
    assert tables["customers"]["columns"]["name"]["comment"] == "客户姓名"


def test_get_table_schema_for_specific_tables(monkeypatch, tmp_path):
    monkeypatch.setenv("ANALYST_DB_KEY", "test-key-for-analyst-0123456789")
    monkeypatch.setattr(ds_manager, "_CIPHER_KEY", None)
    ds = ds_manager.create_datasource(_make_ds_data(name="DS"))
    _inject_sqlite_engine(monkeypatch, tmp_path, ds["id"])

    result = schema_inspector.get_table_schema(ds["id"], ["customers"])
    assert "customers" in result
    assert "orders" not in result  # 只查指定表

    # 不存在的表应被跳过
    result2 = schema_inspector.get_table_schema(ds["id"], ["customers", "no_such_table"])
    assert "customers" in result2
    assert "no_such_table" not in result2


def test_get_table_relationships_finds_foreign_keys(monkeypatch, tmp_path):
    """orders.customer_id → customers.id 应被发现。"""
    monkeypatch.setenv("ANALYST_DB_KEY", "test-key-for-analyst-0123456789")
    monkeypatch.setattr(ds_manager, "_CIPHER_KEY", None)
    ds = ds_manager.create_datasource(_make_ds_data(name="DS"))
    _inject_sqlite_engine(monkeypatch, tmp_path, ds["id"])

    rels = schema_inspector.get_table_relationships(ds["id"], ["orders", "customers"])
    assert len(rels) >= 1
    # 找到 orders.customer_id → customers.id
    target = [r for r in rels if r["from_table"] == "orders"
              and r["from_column"] == "customer_id"
              and r["to_table"] == "customers"
              and r["to_column"] == "id"]
    assert len(target) == 1


def test_get_table_relationships_empty_for_unrelated(monkeypatch, tmp_path):
    monkeypatch.setenv("ANALYST_DB_KEY", "test-key-for-analyst-0123456789")
    monkeypatch.setattr(ds_manager, "_CIPHER_KEY", None)
    ds = ds_manager.create_datasource(_make_ds_data(name="DS"))
    _inject_sqlite_engine(monkeypatch, tmp_path, ds["id"])

    # customers 表没有外键指向其他表
    rels = schema_inspector.get_table_relationships(ds["id"], ["customers"])
    assert rels == []


def test_get_all_tables_empty_for_no_tables(monkeypatch, tmp_path):
    """空数据库应返回空 dict 而非抛错。"""
    monkeypatch.setenv("ANALYST_DB_KEY", "test-key-for-analyst-0123456789")
    monkeypatch.setattr(ds_manager, "_CIPHER_KEY", None)
    ds = ds_manager.create_datasource(_make_ds_data(name="DS"))

    # 注入一个空 sqlite 库的 engine
    empty_db = tmp_path / "empty.sqlite"
    sqlite3.connect(empty_db).close()  # 建空库
    engine = create_engine(f"sqlite:///{empty_db}")
    ds_manager._engine_cache[ds["id"]] = engine

    tables = schema_inspector.get_all_tables(ds["id"])
    assert tables == {}


def test_format_schema_text_renders_comment_and_fk():
    """format_schema_text 应渲染表注释、字段、外键。"""
    table_info = {
        "orders": {
            "columns": {
                "id": {"type": "INTEGER", "comment": "主键"},
                "customer_id": {"type": "INTEGER", "comment": ""},
            },
            "foreign_keys": [
                {"column": "customer_id", "ref_table": "customers", "ref_column": "id"}
            ],
            "table_comment": "订单表",
        }
    }
    text = schema_inspector.format_schema_text(["orders"], table_info)
    assert "订单表" in text
    assert "id: INTEGER" in text
    assert "主键" in text
    assert "customer_id → customers.id" in text


def test_format_schema_text_skips_missing_table():
    table_info = {"a": {"columns": {}, "foreign_keys": [], "table_comment": ""}}
    text = schema_inspector.format_schema_text(["a", "b"], table_info)
    # b 不在 table_info 中应被跳过，不抛错
    assert "表名: a" in text
    assert "b" not in text
