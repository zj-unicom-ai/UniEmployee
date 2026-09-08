"""数据源管理：CRUD + 加密 + SQLAlchemy engine 缓存 + SQL 执行。

借鉴 Aix-DB common/datasource_util.py，适配 UniEmployee 的 db.py 连接层。
数据源元数据存 catalog 库 datasources 表，连接密码 AES 加密存储。
engine 按 datasource_id 缓存，进程级复用。
"""

from __future__ import annotations

import json
import logging
import os
import time
import urllib.parse
from typing import Any

from sqlalchemy import create_engine, inspect, text
from sqlalchemy.engine import Engine

from app import db as dblayer
from app.catalog.db import _conn as _catalog_conn

logger = logging.getLogger("app.agent.analyst.datasource")

# ---------------------------------------------------------------------------
# 加密 / 解密（轻量 AES-GCM，密钥取环境变量）
# ---------------------------------------------------------------------------

_CIPHER_KEY: bytes | None = None


def _get_cipher_key() -> bytes:
    """从环境变量获取加密密钥（32 字节），首次调用时缓存。"""
    global _CIPHER_KEY
    if _CIPHER_KEY is not None:
        return _CIPHER_KEY
    raw = os.environ.get("ANALYST_DB_KEY", "")
    if not raw:
        # 退化：用 JWT_SECRET 的前 32 字节做密钥（开发环境可用，生产应配专用密钥）
        raw = os.environ.get("JWT_SECRET", "uniemployee-default-key-change-me!!")
    key = raw.encode("utf-8")[:32].ljust(32, b"0")
    _CIPHER_KEY = key
    return key


def encrypt_config(config: dict) -> str:
    """加密数据源连接配置 JSON。"""
    import base64
    from cryptography.fernet import Fernet
    import hashlib

    key = hashlib.sha256(_get_cipher_key()).digest()
    fernet_key = base64.urlsafe_b64encode(key)
    f = Fernet(fernet_key)
    raw = json.dumps(config, ensure_ascii=False).encode("utf-8")
    return f.encrypt(raw).decode("utf-8")


def decrypt_config(encrypted: str) -> dict:
    """解密数据源连接配置。"""
    import base64
    from cryptography.fernet import Fernet
    import hashlib

    key = hashlib.sha256(_get_cipher_key()).digest()
    fernet_key = base64.urlsafe_b64encode(key)
    f = Fernet(fernet_key)
    raw = f.decrypt(encrypted.encode("utf-8"))
    return json.loads(raw.decode("utf-8"))


# ---------------------------------------------------------------------------
# 连接 URI 构建（借鉴 Aix-DB DatasourceConnectionUtil.build_connection_uri）
# ---------------------------------------------------------------------------

# SQLAlchemy 可连接的数据库类型
SQLALCHEMY_DB_TYPES = {"mysql", "pg", "oracle", "sqlServer", "ck"}


def build_connection_uri(db_type: str, config: dict) -> str:
    """根据数据库类型和配置构建 SQLAlchemy URI。"""
    host = config.get("host", "localhost")
    port = config.get("port", 3306)
    username = urllib.parse.quote(str(config.get("username", "")))
    password = urllib.parse.quote(str(config.get("password", "")))
    database = config.get("database", "")
    db_schema = config.get("dbSchema", "")
    extra_jdbc = config.get("extraJdbc", "")

    if db_type == "mysql":
        uri = f"mysql+pymysql://{username}:{password}@{host}:{port}/{database}"
        return f"{uri}?{extra_jdbc}" if extra_jdbc else uri

    if db_type == "pg":
        uri = f"postgresql+psycopg2://{username}:{password}@{host}:{port}/{database}"
        if db_schema:
            uri += f"?options=-c%20search_path%3D{db_schema}"
        elif extra_jdbc:
            uri += f"?{extra_jdbc}"
        return uri

    if db_type == "oracle":
        mode = config.get("mode", "service_name")
        if mode == "service_name":
            uri = f"oracle+oracledb://{username}:{password}@{host}:{port}?service_name={database}"
        else:
            uri = f"oracle+oracledb://{username}:{password}@{host}:{port}/{database}"
        return f"{uri}&{extra_jdbc}" if extra_jdbc else uri

    if db_type == "sqlServer":
        uri = f"mssql+pymssql://{username}:{password}@{host}:{port}/{database}"
        return f"{uri}?{extra_jdbc}" if extra_jdbc else uri

    if db_type == "ck":
        uri = f"clickhouse+http://{username}:{password}@{host}:{port}/{database}"
        return f"{uri}?{extra_jdbc}" if extra_jdbc else uri

    raise ValueError(f"不支持 SQLAlchemy 连接的数据库类型: {db_type}")


# ---------------------------------------------------------------------------
# Engine 缓存（按 datasource_id）
# ---------------------------------------------------------------------------

_engine_cache: dict[str, Engine] = {}


def get_engine(datasource_id: str) -> Engine:
    """按 datasource_id 获取或创建 SQLAlchemy engine（带缓存）。"""
    if datasource_id in _engine_cache:
        return _engine_cache[datasource_id]

    ds = get_datasource(datasource_id)
    if not ds:
        raise ValueError(f"数据源 {datasource_id} 不存在")

    config = decrypt_config(ds["config"])
    db_type = ds["db_type"]
    uri = build_connection_uri(db_type, config)

    engine = create_engine(uri, pool_pre_ping=True)
    _engine_cache[datasource_id] = engine
    logger.info("数据源 %s (%s) engine 已创建", datasource_id, db_type)
    return engine


def clear_engine_cache(datasource_id: str | None = None):
    """清除 engine 缓存（数据源更新/删除时调用）。"""
    if datasource_id:
        eng = _engine_cache.pop(datasource_id, None)
        if eng:
            eng.dispose()
    else:
        for eng in _engine_cache.values():
            eng.dispose()
        _engine_cache.clear()


# ---------------------------------------------------------------------------
# CRUD（datasources 表）
# ---------------------------------------------------------------------------

def _now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S")


def list_datasources() -> list[dict]:
    """列出所有数据源。"""
    con = _catalog_conn()
    try:
        rows = con.execute(
            "SELECT id, name, description, db_type, config, enabled, "
            "owner_id, created_at, updated_at "
            "FROM datasources WHERE deleted_at IS NULL ORDER BY created_at DESC"
        ).fetchall()
        result = []
        for r in rows:
            result.append({
                "id": r["id"], "name": r["name"], "description": r["description"],
                "db_type": r["db_type"], "enabled": r["enabled"],
                "owner_id": r["owner_id"],
                "created_at": r["created_at"], "updated_at": r["updated_at"],
            })
        return result
    finally:
        con.close()


def get_datasource(datasource_id: str) -> dict | None:
    """获取单个数据源（含解密后的 config）。"""
    con = _catalog_conn()
    try:
        r = con.execute(
            "SELECT id, name, description, db_type, config, enabled, "
            "owner_id, created_at, updated_at "
            "FROM datasources WHERE id = ? AND deleted_at IS NULL",
            (datasource_id,)
        ).fetchone()
        if not r:
            return None
        return {
            "id": r["id"], "name": r["name"], "description": r["description"],
            "db_type": r["db_type"], "config": r["config"], "enabled": r["enabled"],
            "owner_id": r["owner_id"],
            "created_at": r["created_at"], "updated_at": r["updated_at"],
        }
    finally:
        con.close()


def create_datasource(data: dict) -> dict:
    """创建数据源。data: {id, name, description, db_type, config(dict), enabled, owner_id}"""
    import uuid
    ds_id = data.get("id") or f"ds_{int(time.time()*1000)}_{uuid.uuid4().hex[:8]}"
    config = data.get("config", {})
    if isinstance(config, dict):
        encrypted = encrypt_config(config)
    else:
        encrypted = config  # 已加密
    now = _now()
    con = _catalog_conn()
    try:
        con.execute(
            "INSERT INTO datasources (id, name, description, db_type, config, "
            "enabled, owner_id, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (ds_id, data["name"], data.get("description", ""),
             data["db_type"], encrypted,
             data.get("enabled", 1), data.get("owner_id"),
             now, now)
        )
        con.commit()
    finally:
        con.close()
    return get_datasource(ds_id)


def update_datasource(datasource_id: str, data: dict) -> dict | None:
    """更新数据源（部分更新）。"""
    existing = get_datasource(datasource_id)
    if not existing:
        return None

    name = data.get("name", existing["name"])
    description = data.get("description", existing["description"])
    db_type = data.get("db_type", existing["db_type"])
    enabled = data.get("enabled", existing["enabled"])

    if "config" in data:
        config = data["config"]
        if isinstance(config, dict):
            encrypted = encrypt_config(config)
        else:
            encrypted = config
    else:
        encrypted = existing["config"]

    now = _now()
    con = _catalog_conn()
    try:
        con.execute(
            "UPDATE datasources SET name=?, description=?, db_type=?, "
            "config=?, enabled=?, updated_at=? WHERE id=?",
            (name, description, db_type, encrypted, enabled, now, datasource_id)
        )
        con.commit()
    finally:
        con.close()
    # 配置变更后清除 engine 缓存
    clear_engine_cache(datasource_id)
    return get_datasource(datasource_id)


def delete_datasource(datasource_id: str) -> bool:
    """软删除数据源。"""
    con = _catalog_conn()
    try:
        now = _now()
        cur = con.execute(
            "UPDATE datasources SET deleted_at=? WHERE id=? AND deleted_at IS NULL",
            (now, datasource_id)
        )
        con.commit()
        deleted = cur.rowcount > 0
    finally:
        con.close()
    clear_engine_cache(datasource_id)
    return deleted


# ---------------------------------------------------------------------------
# SQL 执行
# ---------------------------------------------------------------------------

def execute_query(datasource_id: str, sql: str, limit: int = 100) -> dict:
    """执行 SELECT 查询，返回 {success, data, columns, error}。

    安全：只允许 SELECT，禁止 INSERT/UPDATE/DELETE 等。
    """
    sql_stripped = sql.strip().upper()
    forbidden = ("INSERT", "UPDATE", "DELETE", "DROP", "ALTER",
                 "TRUNCATE", "CREATE", "GRANT", "REVOKE")
    # 检查是否以禁止语句开头（跳过前导空白和 WITH/括号）
    check_sql = sql.strip()
    # CTE 以 WITH 开头是允许的
    if check_sql.upper().startswith("WITH"):
        pass
    elif not check_sql.upper().startswith("SELECT"):
        for kw in forbidden:
            if check_sql.upper().startswith(kw):
                return {"success": False, "data": None, "columns": None,
                        "error": f"安全限制：禁止执行 {kw} 语句，只允许 SELECT"}

    # 加 LIMIT（如果用户没加）
    if "LIMIT" not in sql_stripped:
        sql = sql.rstrip(";").rstrip() + f" LIMIT {limit}"

    try:
        engine = get_engine(datasource_id)
        with engine.connect() as conn:
            result = conn.execute(text(sql))
            columns = list(result.keys())
            rows = [dict(zip(columns, row)) for row in result.fetchall()]
            return {"success": True, "data": rows, "columns": columns, "error": None}
    except Exception as e:
        logger.warning("SQL 执行失败 [datasource=%s]: %s", datasource_id, e)
        return {"success": False, "data": None, "columns": None,
                "error": f"{type(e).__name__}: {e}"}


def test_connection(db_type: str, config: dict) -> tuple[bool, str]:
    """测试数据源连接是否可用。"""
    try:
        uri = build_connection_uri(db_type, config)
        engine = create_engine(uri)
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        engine.dispose()
        return True, "连接成功"
    except Exception as e:
        return False, f"{type(e).__name__}: {e}"


# ---------------------------------------------------------------------------
# 表标注 CRUD（table_annotations 表）
# ---------------------------------------------------------------------------

def get_table_annotation(datasource_id: str, table_name: str) -> dict | None:
    """获取单表标注。"""
    con = _catalog_conn()
    try:
        r = con.execute(
            "SELECT id, datasource_id, table_name, table_comment, "
            "queryable, column_annotations, created_at, updated_at "
            "FROM table_annotations WHERE datasource_id=? AND table_name=?",
            (datasource_id, table_name)
        ).fetchone()
        if not r:
            return None
        col_ann = r["column_annotations"]
        return {
            "id": r["id"], "datasource_id": r["datasource_id"],
            "table_name": r["table_name"], "table_comment": r["table_comment"],
            "queryable": r["queryable"],
            "column_annotations": json.loads(col_ann) if col_ann else {},
            "created_at": r["created_at"], "updated_at": r["updated_at"],
        }
    finally:
        con.close()


def list_table_annotations(datasource_id: str) -> list[dict]:
    """列出某数据源下所有表标注。"""
    con = _catalog_conn()
    try:
        rows = con.execute(
            "SELECT id, datasource_id, table_name, table_comment, "
            "queryable, column_annotations, created_at, updated_at "
            "FROM table_annotations WHERE datasource_id=?",
            (datasource_id,)
        ).fetchall()
        result = []
        for r in rows:
            col_ann = r["column_annotations"]
            result.append({
                "id": r["id"], "datasource_id": r["datasource_id"],
                "table_name": r["table_name"], "table_comment": r["table_comment"],
                "queryable": r["queryable"],
                "column_annotations": json.loads(col_ann) if col_ann else {},
                "created_at": r["created_at"], "updated_at": r["updated_at"],
            })
        return result
    finally:
        con.close()


def upsert_table_annotation(datasource_id: str, table_name: str,
                            table_comment: str = "",
                            queryable: int = 1,
                            column_annotations: dict | None = None) -> dict:
    """创建或更新表标注（upsert）。"""
    existing = get_table_annotation(datasource_id, table_name)
    col_json = json.dumps(column_annotations or {}, ensure_ascii=False)
    now = _now()

    con = _catalog_conn()
    try:
        if existing:
            con.execute(
                "UPDATE table_annotations SET table_comment=?, queryable=?, "
                "column_annotations=?, updated_at=? "
                "WHERE datasource_id=? AND table_name=?",
                (table_comment, queryable, col_json, now,
                 datasource_id, table_name)
            )
        else:
            import uuid
            ann_id = f"ann_{int(time.time()*1000)}_{uuid.uuid4().hex[:8]}"
            con.execute(
                "INSERT INTO table_annotations (id, datasource_id, table_name, "
                "table_comment, queryable, column_annotations, created_at, updated_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (ann_id, datasource_id, table_name, table_comment,
                 queryable, col_json, now, now)
            )
        con.commit()
    finally:
        con.close()
    return get_table_annotation(datasource_id, table_name)


# ---------------------------------------------------------------------------
# 数据源聚合 API（数据库 + 员工绑定的知识库 + 员工绑定的连接器）
# ---------------------------------------------------------------------------

# xiaoshu 是定制型员工，其数据源由 analyst 工作台独立管理。
# 知识库 / 连接器复用 catalog 库的 employee_kbs / employee_connectors 关联表，
# 不进入 datasources 表，避免污染 SQL 数据源模型。
ANALYST_EMP_ID = "xiaoshu"


def list_employee_kbs(emp_id: str) -> list[dict]:
    """列出员工已绑定的知识库（含 ragflow_dataset_id）。"""
    con = _catalog_conn()
    try:
        rows = con.execute(
            "SELECT kb.id, kb.name, kb.description, kb.ragflow_dataset_id "
            "FROM employee_kbs ek JOIN knowledge_bases kb ON ek.kb_id = kb.id "
            "WHERE ek.employee_id=? AND kb.deleted_at IS NULL "
            "ORDER BY kb.name",
            (emp_id,)
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        con.close()


def list_employee_connectors(emp_id: str) -> list[dict]:
    """列出员工已绑定的连接器（含 config）。"""
    con = _catalog_conn()
    try:
        rows = con.execute(
            "SELECT c.id, c.name, c.description, c.config "
            "FROM employee_connectors ec JOIN connectors c ON ec.connector_id = c.id "
            "WHERE ec.employee_id=? AND c.deleted_at IS NULL "
            "ORDER BY c.name",
            (emp_id,)
        ).fetchall()
        out = []
        for r in rows:
            d = dict(r)
            try:
                d["config"] = json.loads(d["config"]) if isinstance(d["config"], str) else d.get("config", {})
            except (json.JSONDecodeError, TypeError):
                d["config"] = {}
            out.append(d)
        return out
    finally:
        con.close()


def list_all_kbs() -> list[dict]:
    """列出资源中心全部知识库（供绑定选择）。"""
    con = _catalog_conn()
    try:
        rows = con.execute(
            "SELECT id, name, description, ragflow_dataset_id "
            "FROM knowledge_bases WHERE deleted_at IS NULL ORDER BY name"
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        con.close()


def list_all_connectors() -> list[dict]:
    """列出资源中心全部连接器（供绑定选择）。"""
    con = _catalog_conn()
    try:
        rows = con.execute(
            "SELECT id, name, description "
            "FROM connectors WHERE deleted_at IS NULL ORDER BY name"
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        con.close()


def bind_kb(emp_id: str, kb_id: str) -> bool:
    """绑定知识库到员工（幂等）。"""
    con = _catalog_conn()
    try:
        con.execute(
            "INSERT OR IGNORE INTO employee_kbs (employee_id, kb_id) VALUES (?, ?)",
            (emp_id, kb_id)
        )
        con.commit()
        return True
    finally:
        con.close()


def unbind_kb(emp_id: str, kb_id: str) -> bool:
    """解绑员工的知识库。"""
    con = _catalog_conn()
    try:
        cur = con.execute(
            "DELETE FROM employee_kbs WHERE employee_id=? AND kb_id=?",
            (emp_id, kb_id)
        )
        con.commit()
        return cur.rowcount > 0
    finally:
        con.close()


def bind_connector(emp_id: str, connector_id: str) -> bool:
    """绑定连接器到员工（幂等）。"""
    con = _catalog_conn()
    try:
        con.execute(
            "INSERT OR IGNORE INTO employee_connectors (employee_id, connector_id) "
            "VALUES (?, ?)",
            (emp_id, connector_id)
        )
        con.commit()
        return True
    finally:
        con.close()


def unbind_connector(emp_id: str, connector_id: str) -> bool:
    """解绑员工的连接器。"""
    con = _catalog_conn()
    try:
        cur = con.execute(
            "DELETE FROM employee_connectors WHERE employee_id=? AND connector_id=?",
            (emp_id, connector_id)
        )
        con.commit()
        return cur.rowcount > 0
    finally:
        con.close()


def list_all_data_sources(emp_id: str = ANALYST_EMP_ID) -> list[dict]:
    """聚合返回三类数据源：数据库 / 知识库 / 连接器。

    返回统一格式：
      [{"id": "ds:xxx", "name": "销售库", "kind": "database", "db_type": "mysql", "enabled": 1},
       {"id": "kb:yyy", "name": "产品FAQ", "kind": "knowledge_base", "ragflow_dataset_id": "..."},
       {"id": "conn:zzz", "name": "CRM连接器", "kind": "connector"}]

    id 加 kind 前缀避免冲突；前端选择后原样回传，后端按前缀解析。
    """
    result = []

    # 1. 数据库数据源（datasources 表，enabled=1）
    for ds in list_datasources():
        if not ds.get("enabled"):
            continue
        result.append({
            "id": f"ds:{ds['id']}",
            "name": ds["name"],
            "kind": "database",
            "db_type": ds.get("db_type", ""),
            "description": ds.get("description", ""),
        })

    # 2. 员工绑定的知识库
    for kb in list_employee_kbs(emp_id):
        result.append({
            "id": f"kb:{kb['id']}",
            "name": kb["name"],
            "kind": "knowledge_base",
            "ragflow_dataset_id": kb.get("ragflow_dataset_id", ""),
            "description": kb.get("description", ""),
        })

    # 3. 员工绑定的连接器
    for c in list_employee_connectors(emp_id):
        result.append({
            "id": f"conn:{c['id']}",
            "name": c["name"],
            "kind": "connector",
            "description": c.get("description", ""),
        })

    return result


def parse_data_source(data_source: str) -> tuple[str, str]:
    """解析前端传来的 data_source 字符串，返回 (kind, raw_id)。

    支持两种格式：
      1. JSON: '{"kind":"database","id":"ds:xxx"}'（新格式）
      2. 纯 ID: 'ds:xxx' 或裸 datasource_id 'ds_xxx'（兼容旧格式）
    """
    if not data_source:
        return "", ""

    # 尝试 JSON 解析
    if data_source.startswith("{"):
        try:
            obj = json.loads(data_source)
            return obj.get("kind", ""), obj.get("id", "")
        except (json.JSONDecodeError, TypeError):
            pass

    # 兼容旧格式：纯 datasource_id（无前缀，老前端调用）
    if not data_source.startswith(("ds:", "kb:", "conn:")):
        return "database", data_source

    # 按前缀解析
    if data_source.startswith("ds:"):
        return "database", data_source[3:]
    if data_source.startswith("kb:"):
        return "knowledge_base", data_source[3:]
    if data_source.startswith("conn:"):
        return "connector", data_source[5:]

    return "", data_source
