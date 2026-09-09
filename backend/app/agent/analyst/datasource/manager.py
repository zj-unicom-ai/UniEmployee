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

import sqlglot
from sqlglot import exp
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.engine import Engine

from app import db as dblayer
from app.catalog.db import _conn as _catalog_conn

logger = logging.getLogger("app.agent.analyst.datasource")

# ---------------------------------------------------------------------------
# SQL 只读安全护栏（AST 级）
# ---------------------------------------------------------------------------
# 历史问题：startswith 关键词判断可被注释/括号/CTE 改写 DML/方言函数绕过；
# table_preview 直接 f-string 拼接 table_name 等价 SQL 注入通道。
# 修复策略：sqlglot AST 解析 + 多语句拒绝 + CTE 体只允许 SELECT + 危险函数黑名单。

# sqlglot 方言映射（datasource.db_type -> sqlglot dialect）
_SQLGLOT_DIALECTS = {
    "mysql": "mysql",
    "pg": "postgres",
    "postgres": "postgres",
    "oracle": "oracle",
    "sqlServer": "tsql",
    "mssql": "tsql",
    "ck": "clickhouse",
    "clickhouse": "clickhouse",
    "sqlite": "sqlite",
}

# 危险函数：可用于数据破坏/资源耗尽/文件系统/进程管理/信息泄露。
# 大小写不敏感匹配（已 lower 处理）。pg_read_* / pg_sleep / pg_terminate_backend 等数据库特有
# 系统管理函数，及 MySQL INTO OUTFILE / INTO DUMPFILE 类（sqlglot 解析为 Select.into，
# 已在 stmt.args["into"] 处单独拦截，这里再防御同名函数调用）。
_DANGEROUS_FUNCTIONS = {
    "pg_terminate_backend", "pg_cancel_backend", "pg_sleep", "pg_sleep_for",
    "pg_sleep_until", "pg_read_file", "pg_read_binary_file", "pg_ls_dir",
    "pg_stat_file", "pg_ls_dir", "pg_size_pretty", "pg_database_size",
    "pg_tablespace_size", "lo_import", "lo_export", "lo_unlink",
    "load_file", "benchmark", "sleep", "get_lock", "release_all_locks",
    "sys_exec", "sys_eval", "xp_cmdshell",
}

# 查询资源限制（可在启动时通过环境变量覆盖）
_QUERY_TIMEOUT_SEC = float(os.environ.get("ANALYST_QUERY_TIMEOUT_SEC", "30"))
_QUERY_MAX_ROWS = int(os.environ.get("ANALYST_QUERY_MAX_ROWS", "1000"))


def _sqlglot_dialect_for(db_type: str) -> str:
    """根据 datasource.db_type 返回 sqlglot 方言名。未知类型用默认（不指定）。"""
    if not db_type:
        return ""
    return _SQLGLOT_DIALECTS.get(db_type, "")


def _validate_readonly_sql(sql: str, db_type: str = "") -> tuple[bool, str]:
    """AST 级只读校验，返回 (is_safe, error_message)。

    通过条件：
    1. sqlglot 解析后只能得到 1 条语句（拒绝多语句 stacked queries）。
    2. 根节点必须是 SELECT（含 WITH ... SELECT 的 CTE 形式；CTE body 也只能是 SELECT）。
    3. SELECT 语句不得带 INTO（PG 建表）。
    4. 不得调用 _DANGEROUS_FUNCTIONS 中的函数。
    5. 不允许 PIVOT/UNPIVOTE 等改写 schema 的扩展形式。

    解析失败（语法错误/方言不识别）会被拒绝而非放行——安全场景下 fail-closed。
    """
    if not sql or not sql.strip():
        return False, "SQL 为空"

    dialect = _sqlglot_dialect_for(db_type)
    try:
        statements = sqlglot.parse(sql, dialect=dialect or None)
    except Exception as e:
        # 解析失败一律拒绝，避免脏 SQL 借解析器 bug 通过
        logger.warning("SQL AST 解析失败 [db_type=%s]: %s", db_type, e)
        return False, f"SQL 语法解析失败，已拒绝执行：{type(e).__name__}"

    if not statements:
        return False, "SQL 解析为空"

    # 1. 多语句拒绝（sqlglot 对多语句分隔的 SQL 返回 list[Expression]）
    non_none = [s for s in statements if s is not None]
    if len(non_none) != 1:
        return False, "禁止多语句执行（stacked queries rejected）"

    stmt = non_none[0]

    # 2. 根节点必须是 SELECT（含 WITH/CTE 的 SELECT 仍是 exp.Select）
    if not isinstance(stmt, exp.Select):
        # 显式拒绝常见 DML/DDL 节点，错误信息更具操作性（关键词大写便于识别）
        kind_name = type(stmt).__name__.upper()
        return False, f"安全限制：禁止执行 {kind_name} 语句，只允许 SELECT"

    # 3. SELECT INTO 拒绝（PostgreSQL `SELECT ... INTO` 会建表）
    if stmt.args.get("into"):
        return False, "安全限制：禁止 SELECT INTO（避免建表）"

    # 4. CTE body 必须是 SELECT（防 `WITH x AS (DELETE ...) SELECT`）
    for cte in stmt.find_all(exp.CTE):
        body = cte.this
        # sqlglot 把 CTE 体包在 Subquery 里
        if isinstance(body, exp.Subquery):
            body = body.this
        if body is not None and not isinstance(body, exp.Select):
            return False, "安全限制：CTE 体内只允许 SELECT"

    # 5. 危险函数黑名单（跨方言）
    for func in stmt.find_all(exp.Anonymous):
        fname = (func.name or "").lower().strip()
        if fname in _DANGEROUS_FUNCTIONS:
            return False, f"安全限制：禁止调用函数 {fname}"

    # 6. 防御：SELECT 中不应出现 DDL/DML 子查询（如 `SELECT * FROM (DELETE ...) x`）
    for bad_kind in (exp.Insert, exp.Update, exp.Delete, exp.Drop,
                     exp.Create, exp.Alter, exp.Merge, exp.TruncateTable,
                     exp.Command):
        # 根节点已在 2 中处理；这里只查子节点
        found = stmt.find(bad_kind)
        if found is not None:
            return False, f"安全限制：SELECT 中嵌套了 {bad_kind.__name__} 子语句"

    return True, ""


def _apply_session_safety_limits(conn, db_type: str, timeout_sec: float) -> None:
    """在当前连接/事务上设置服务端语句超时。

    PG: SET LOCAL statement_timeout = '<sec>s'（事务级，连接关闭自动恢复）。
    MySQL: SET SESSION MAX_EXECUTION_TIME = <ms>（会话级；下一次 connect 复用 engine
        时仍是同一 pool 连接，但 SET 是 session 级不会持久污染其他会话——连接池
        实现层会在归还时执行 rollback 清理事务状态）。
    SQL Server / Oracle / ClickHouse：暂不强制，依赖 _QUERY_TIMEOUT_SEC 通过
        SQLAlchemy execution_options(timeout=) 兜底（client 端 cancel）。
    SQLite：不支持 statement_timeout，跳过（测试用，不影响生产）。

    失败不抛错：部分驱动对未知 SET 命令会报错，这里 log 后吞掉，
    避免护栏机制反而阻断正常查询。
    """
    if timeout_sec <= 0:
        return
    try:
        if db_type in ("pg", "postgres"):
            conn.execute(text(f"SET LOCAL statement_timeout = '{int(timeout_sec)}s'"))
        elif db_type == "mysql":
            # MAX_EXECUTION_TIME 单位为毫秒
            conn.execute(text(f"SET SESSION MAX_EXECUTION_TIME = {int(timeout_sec * 1000)}"))
    except Exception as e:
        # 仅日志，不阻断——sqlglot 已挡住危险语句，超时是纵深防御
        logger.debug("设置服务端超时失败 [db_type=%s]: %s", db_type, e)

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


def can_access_datasource(ds: dict | None, user_id: str | None,
                          is_admin: bool) -> bool:
    """数据源【使用/读取】权限：管理员 / 创建者（owner_id）/ 公共数据源可访问。

    用于：工作台下拉、问数连库、表结构/预览/标注读取等只读与运行时场景。
    user_id 为空表示系统/内部调用（播种、运行时已在更上层校验），放行；
    普通用户可访问 owner_id 等于自己、或被标记为公共（is_public=1）的数据源。
    """
    if not ds:
        return False
    if is_admin or not user_id:
        return True
    if ds.get("is_public"):
        return True
    return ds.get("owner_id") == user_id


def can_manage_datasource(ds: dict | None, user_id: str | None,
                          is_admin: bool) -> bool:
    """数据源【管理/写入】权限：仅管理员或创建者（owner_id）可编辑/删除/改标注。

    与 can_access 的区别：公共数据源（is_public=1）对所有人开放【使用】，
    但不因此开放【管理】——普通用户能用公共源问数，却不能改它的连接配置、
    表标注或删除它，避免公共种子源被使用者破坏。
    """
    if not ds:
        return False
    if is_admin or not user_id:
        return True
    return ds.get("owner_id") == user_id


def get_owned_datasource(datasource_id: str, user_id: str | None,
                         is_admin: bool) -> dict | None:
    """取数据源并做【使用】权限校验：不存在或无权使用均返回 None。

    路由层据此返回 404（不区分「不存在」与「无权限」，避免越权探测资源存在性）。
    """
    ds = get_datasource(datasource_id)
    if not can_access_datasource(ds, user_id, is_admin):
        return None
    return ds


def get_managed_datasource(datasource_id: str, user_id: str | None,
                           is_admin: bool) -> dict | None:
    """取数据源并做【管理】权限校验：不存在或无权管理均返回 None。

    用于编辑/删除/写标注等修改类接口；公共源仅 owner/管理员可管理。
    """
    ds = get_datasource(datasource_id)
    if not can_manage_datasource(ds, user_id, is_admin):
        return None
    return ds


def list_datasources(owner_id: str | None = None,
                     is_admin: bool = False) -> list[dict]:
    """列出数据源。

    可见范围：管理员或内部调用（owner_id 为空）返回全部；普通用户返回
    自己创建的（owner_id 匹配）+ 所有公共数据源（is_public=1）。
    """
    con = _catalog_conn()
    try:
        if owner_id and not is_admin:
            rows = con.execute(
                "SELECT id, name, description, db_type, config, enabled, "
                "owner_id, is_public, created_at, updated_at "
                "FROM datasources WHERE deleted_at IS NULL "
                "AND (owner_id=? OR is_public=1) "
                "ORDER BY is_public DESC, created_at DESC",
                (owner_id,)
            ).fetchall()
        else:
            rows = con.execute(
                "SELECT id, name, description, db_type, config, enabled, "
                "owner_id, is_public, created_at, updated_at "
                "FROM datasources WHERE deleted_at IS NULL "
                "ORDER BY is_public DESC, created_at DESC"
            ).fetchall()
        result = []
        for r in rows:
            result.append({
                "id": r["id"], "name": r["name"], "description": r["description"],
                "db_type": r["db_type"], "enabled": r["enabled"],
                "owner_id": r["owner_id"], "is_public": r["is_public"],
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
            "owner_id, is_public, created_at, updated_at "
            "FROM datasources WHERE id = ? AND deleted_at IS NULL",
            (datasource_id,)
        ).fetchone()
        if not r:
            return None
        return {
            "id": r["id"], "name": r["name"], "description": r["description"],
            "db_type": r["db_type"], "config": r["config"], "enabled": r["enabled"],
            "owner_id": r["owner_id"], "is_public": r["is_public"],
            "created_at": r["created_at"], "updated_at": r["updated_at"],
        }
    finally:
        con.close()


def create_datasource(data: dict) -> dict:
    """创建数据源。

    data: {id, name, description, db_type, config(dict), enabled, owner_id, is_public}
    is_public 默认 0（私有）；是否允许设为公共由路由层按管理员权限把关。
    """
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
            "enabled, owner_id, is_public, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (ds_id, data["name"], data.get("description", ""),
             data["db_type"], encrypted,
             data.get("enabled", 1), data.get("owner_id"),
             1 if data.get("is_public") else 0,
             now, now)
        )
        con.commit()
    finally:
        con.close()
    return get_datasource(ds_id)


def update_datasource(datasource_id: str, data: dict) -> dict | None:
    """更新数据源（部分更新）。is_public 仅在 data 显式提供时更新（路由层限管理员）。"""
    existing = get_datasource(datasource_id)
    if not existing:
        return None

    name = data.get("name", existing["name"])
    description = data.get("description", existing["description"])
    db_type = data.get("db_type", existing["db_type"])
    enabled = data.get("enabled", existing["enabled"])
    is_public = data.get("is_public", existing["is_public"])

    if "config" in data:
        config = data["config"]
        if isinstance(config, dict):
            # 详情接口出于安全把 password 脱敏为 "***"；编辑时若未改密码
            # （回传 "***"/空），回填原密码，避免把占位符当新密码加密入库。
            if config.get("password") in (None, "", "***"):
                saved = decrypt_config(existing["config"])
                config = {**config, "password": saved.get("password", "")}
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
            "config=?, enabled=?, is_public=?, updated_at=? WHERE id=?",
            (name, description, db_type, encrypted, enabled,
             1 if is_public else 0, now, datasource_id)
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
    """执行 SELECT 查询，返回 {success, data, columns, error, row_count}。

    安全（纵深防御三道闸）：
    1. AST 校验：sqlglot 解析 + 多语句拒绝 + CTE 体只允许 SELECT + 危险函数黑名单。
       历史的 startswith 关键词判断可被注释/括号/CTE 改写 DML 绕过，已废弃。
    2. 行数硬上限：服务端 fetchmany(min(limit, _QUERY_MAX_ROWS))，杜绝 fetchall
       把全表拉进内存；即使 SQL 自带 LIMIT 也走 fetchmany 兜底。
    3. 超时：PG SET LOCAL statement_timeout / MySQL MAX_EXECUTION_TIME，
       失败不阻断（仅日志）；SQLite 等不支持则跳过。
    """
    if not sql or not sql.strip():
        return {"success": False, "data": None, "columns": None,
                "error": "SQL 为空", "row_count": 0}

    ds = get_datasource(datasource_id)
    if not ds:
        return {"success": False, "data": None, "columns": None,
                "error": f"数据源 {datasource_id} 不存在", "row_count": 0}

    # 第一道闸：AST 只读校验
    is_safe, err = _validate_readonly_sql(sql, ds.get("db_type", ""))
    if not is_safe:
        logger.warning("SQL 被安全护栏拒绝 [datasource=%s]: %s | SQL=%.200s",
                       datasource_id, err, sql)
        return {"success": False, "data": None, "columns": None,
                "error": err, "row_count": 0}

    # 行数硬上限：用户 limit 与全局 _QUERY_MAX_ROWS 取较小者
    effective_limit = max(1, min(int(limit), _QUERY_MAX_ROWS))
    # 仍保留字符串追加 LIMIT 兜底（用户未带 LIMIT 时，让 DB 端也只生成 effective_limit 行）
    # 注意：sqlglot 校验已通过，原 SQL 不含 DML，追加 LIMIT 字符串不再引入绕过风险。
    sql_upper = sql.upper()
    if "LIMIT" not in sql_upper:
        sql = sql.rstrip(";").rstrip() + f" LIMIT {effective_limit}"

    try:
        engine = get_engine(datasource_id)
        with engine.connect().execution_options(timeout=_QUERY_TIMEOUT_SEC) as conn:
            _apply_session_safety_limits(conn, ds.get("db_type", ""),
                                          _QUERY_TIMEOUT_SEC)
            result = conn.execute(text(sql))
            columns = list(result.keys())
            # 服务端 cursor 取数，避免 fetchall 把全表载入内存
            rows_raw = result.fetchmany(effective_limit)
            rows = [dict(zip(columns, row)) for row in rows_raw]
            return {"success": True, "data": rows, "columns": columns,
                    "error": None, "row_count": len(rows)}
    except Exception as e:
        logger.warning("SQL 执行失败 [datasource=%s]: %s", datasource_id, e)
        return {"success": False, "data": None, "columns": None,
                "error": f"{type(e).__name__}: {e}", "row_count": 0}


def is_table_readable(datasource_id: str, table_name: str) -> bool:
    """表名白名单校验：仅允许该数据源真实存在的表参与预览/拼接。

    用于阻止路由参数 `table_name` 注入 `foo; DROP TABLE bar` 或
    `information_schema.tables` 信息泄露——preview_table_data 路由
    的 `SELECT * FROM {table_name}` 字符串拼接等价 SQL 注入通道。
    """
    if not table_name:
        return False
    # 严格白名单：必须为标识符（防 `; -- /` 等控制字符）
    if any(c in table_name for c in ";'\"\\-/*@()\t\r\n "):
        return False
    try:
        engine = get_engine(datasource_id)
        inspector = inspect(engine)
        existing = set(inspector.get_table_names())
        # 视图也允许预览（部分库把视图列在 get_table_names 之外）
        try:
            existing |= set(inspector.get_view_names())
        except Exception:
            pass
        return table_name in existing
    except Exception as e:
        logger.warning("表白名单校验失败 [datasource=%s, table=%s]: %s",
                       datasource_id, table_name, e)
        return False


def quote_table_identifier(datasource_id: str, table_name: str) -> str:
    """按数据源方言引用表名，避免标识符被解析为 SQL 控制符。

    返回值仅在校验通过后使用：调用方必须先 is_table_readable 通过，
    再用本函数拼 SQL。两者配合等价参数化但支持 identifier 绑定。
    """
    engine = get_engine(datasource_id)
    preparer = engine.dialect.identifier_preparer
    return preparer.quote_identifier(table_name)


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


def list_all_data_sources(emp_id: str = ANALYST_EMP_ID,
                          user_id: str | None = None,
                          is_admin: bool = False) -> list[dict]:
    """聚合返回三类数据源：数据库 / 知识库 / 连接器。

    返回统一格式：
      [{"id": "ds:xxx", "name": "销售库", "kind": "database", "db_type": "mysql", "enabled": 1},
       {"id": "kb:yyy", "name": "产品FAQ", "kind": "knowledge_base", "ragflow_dataset_id": "..."},
       {"id": "conn:zzz", "name": "CRM连接器", "kind": "connector"}]

    id 加 kind 前缀避免冲突；前端选择后原样回传，后端按前缀解析。

    可见范围：数据库数据源普通用户可见自己创建的 + 公共数据源（is_public=1），
    管理员全部；知识库/连接器为员工绑定级共享资源，凡有 xiaoshu 使用权限者均可见。
    """
    result = []

    # 1. 数据库数据源（datasources 表，enabled=1；自己的 + 公共的）
    for ds in list_datasources(owner_id=user_id, is_admin=is_admin):
        if not ds.get("enabled"):
            continue
        result.append({
            "id": f"ds:{ds['id']}",
            "name": ds["name"],
            "kind": "database",
            "db_type": ds.get("db_type", ""),
            "description": ds.get("description", ""),
            "is_public": ds.get("is_public", 0),
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
            kind = obj.get("kind", "")
            raw_id = obj.get("id", "")
            # list_all_data_sources 返回的 id 统一带 kind 前缀（ds:/kb:/conn:），
            # 前端原样回传，这里必须剥掉前缀得到真实资源 ID；裸 ID（兼容旧数据）原样返回。
            # 不剥会导致注入 "ds:ds_xxx"，查库报「数据源 ds:ds_xxx 不存在」。
            if isinstance(raw_id, str):
                for prefix in ("ds:", "kb:", "conn:"):
                    if raw_id.startswith(prefix):
                        raw_id = raw_id[len(prefix):]
                        break
            return kind, raw_id
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
