"""catalog 数据库连接、建表、迁移、通用工具（SQLite / PostgreSQL 双后端）。"""

import json
import os
import re
import sqlite3
import time
from pathlib import Path

from app import db as dblayer
from app.paths import db_path

# 全局默认工具名列表（与 compiler.py GLOBAL_TOOL_NAMES 保持一致）
# 这些工具自动注入所有员工，不依赖 tools 字段声明
GLOBAL_TOOL_NAMES = {"get_current_time"}

ROOT = Path(__file__).resolve().parent.parent.parent  # backend/
DB = db_path("catalog.db")

# 实体表（有独立生命周期，删除走软删）；关联表不加。
# tools 无删除入口，但通用列表查询会遍历它，补列以便统一 deleted_at 过滤。
_SOFT_DELETE_TABLES = (
    "users", "employees", "skills", "tools", "knowledge_bases",
    "sops", "connectors", "orgs", "datasources",
)

_LINK_TABLES = {
    "skill": ("employee_skills", "skill_id"),
    "tool": ("employee_tools", "tool_id"),
    "kb": ("employee_kbs", "kb_id"),
    "sop": ("employee_sops", "sop_id"),
    "connector": ("employee_connectors", "connector_id"),
}


def _conn():
    """按 DB_BACKEND 返回 sqlite3.Connection 或 PG 池化连接（见 app/db.py）。

    注意 sqlite 路径仍读取模块级 DB（测试夹具会 monkeypatch 它），
    postgres 路径按库名路由，不受 DB 影响。
    """
    if dblayer.is_pg():
        return dblayer.connect("catalog")
    con = sqlite3.connect(str(DB))
    con.row_factory = sqlite3.Row
    return con


def init():
    """建表（幂等）。"""
    con = _conn()
    con.executescript("""
    CREATE TABLE IF NOT EXISTS skills(
      id TEXT PRIMARY KEY, name TEXT NOT NULL, description TEXT, dir TEXT);
    CREATE TABLE IF NOT EXISTS tools(
      id TEXT PRIMARY KEY, name TEXT NOT NULL, description TEXT, source TEXT, needs_approval TEXT);
    CREATE TABLE IF NOT EXISTS knowledge_bases(
      id TEXT PRIMARY KEY, name TEXT NOT NULL, description TEXT, ragflow_dataset_id TEXT);
    CREATE TABLE IF NOT EXISTS sops(
      id TEXT PRIMARY KEY, name TEXT NOT NULL, description TEXT, content TEXT);
    CREATE TABLE IF NOT EXISTS connectors(
      id TEXT PRIMARY KEY, name TEXT NOT NULL, description TEXT, config TEXT);
    CREATE TABLE IF NOT EXISTS employees(
      id TEXT PRIMARY KEY, name TEXT NOT NULL, role TEXT, model TEXT,
      persona TEXT, backend TEXT DEFAULT 'state', mcp_servers TEXT, interrupt_on TEXT,
      subagents TEXT, subagent_policy TEXT, created_at TEXT, updated_at TEXT,
      kind TEXT DEFAULT 'composed');  -- 员工类型：composed=编排型（资源编排配置）；custom=定制型（独立模块化开发）
    CREATE TABLE IF NOT EXISTS employee_skills(employee_id TEXT, skill_id TEXT, PRIMARY KEY(employee_id, skill_id));
    CREATE TABLE IF NOT EXISTS employee_tools(employee_id TEXT, tool_id TEXT, PRIMARY KEY(employee_id, tool_id));
    CREATE TABLE IF NOT EXISTS employee_kbs(employee_id TEXT, kb_id TEXT, PRIMARY KEY(employee_id, kb_id));
    CREATE TABLE IF NOT EXISTS employee_sops(employee_id TEXT, sop_id TEXT, PRIMARY KEY(employee_id, sop_id));
    CREATE TABLE IF NOT EXISTS employee_connectors(employee_id TEXT, connector_id TEXT, PRIMARY KEY(employee_id, connector_id));
    CREATE TABLE IF NOT EXISTS orgs(
      id TEXT PRIMARY KEY, name TEXT NOT NULL, parent_id TEXT,
      sort_order INTEGER DEFAULT 0, created_at TEXT);
    CREATE TABLE IF NOT EXISTS users(
      id TEXT PRIMARY KEY, username TEXT UNIQUE NOT NULL,
      password_hash TEXT NOT NULL, role TEXT DEFAULT 'user',
      status TEXT DEFAULT 'active', tenant_id TEXT DEFAULT 'default',
      org_id TEXT, created_at TEXT);
    CREATE TABLE IF NOT EXISTS user_employee_assignments(
      user_id TEXT NOT NULL,
      employee_id TEXT NOT NULL,
      granted_by TEXT,
      overrides TEXT,
      created_at TEXT,
      PRIMARY KEY(user_id, employee_id));
    CREATE TABLE IF NOT EXISTS user_profiles(
      user_id TEXT PRIMARY KEY,
      display_name TEXT, position TEXT, duties TEXT, preferences TEXT,
      updated_at TEXT);
    -- 数据分析员工（analyst）专属表
    CREATE TABLE IF NOT EXISTS datasources(
      id TEXT PRIMARY KEY, name TEXT NOT NULL, description TEXT,
      db_type TEXT NOT NULL, config TEXT NOT NULL,
      enabled INTEGER DEFAULT 1, owner_id TEXT, is_public INTEGER DEFAULT 0,
      created_at TEXT, updated_at TEXT, deleted_at TEXT);
    CREATE TABLE IF NOT EXISTS table_annotations(
      id TEXT PRIMARY KEY, datasource_id TEXT NOT NULL,
      table_name TEXT NOT NULL, table_comment TEXT,
      queryable INTEGER DEFAULT 1, column_annotations TEXT,
      created_at TEXT, updated_at TEXT,
      UNIQUE(datasource_id, table_name));
    CREATE TABLE IF NOT EXISTS terminologies(
      id TEXT PRIMARY KEY, word TEXT NOT NULL, description TEXT,
      synonyms TEXT, datasource_ids TEXT,
      enabled INTEGER DEFAULT 1, embedding TEXT,
      created_at TEXT, updated_at TEXT);
    CREATE TABLE IF NOT EXISTS sql_examples(
      id TEXT PRIMARY KEY, question TEXT NOT NULL, sql_text TEXT NOT NULL,
      description TEXT, datasource_id TEXT, chart_type TEXT,
      enabled INTEGER DEFAULT 1, embedding TEXT,
      created_at TEXT, updated_at TEXT);
    """)
    con.commit()
    _migrate_soft_delete(con)
    _migrate_must_change_password(con)
    _migrate_remove_refund_gate(con)
    _migrate_subagents(con)
    _migrate_ragflow_datasets(con)
    _migrate_retire_kb_entries(con)
    _migrate_user_org(con)
    _migrate_employee_kind(con)
    _migrate_datasource_public(con)
    # 安全护栏表（guard 包）幂等建表，复用同一连接
    from ..guard.db import init_tables as _guard_init
    _guard_init(con)
    # 管理端审计日志表（audit 包）幂等建表，复用同一连接
    from ..audit.db import init_tables as _audit_init
    _audit_init(con)
    # AI 模型配置表幂等建表，复用同一连接
    from .ai_models import init_tables as _ai_models_init
    _ai_models_init(con)
    # 沙箱会话映射表（sandbox_mgr）幂等建表，复用同一连接
    from ..sandbox_mgr import init_tables as _sandbox_init
    _sandbox_init(con)
    con.close()


def _migrate_user_org(con):
    """users 表补 org_id 列（归属组织，NULL=未分配）。幂等。"""
    if "org_id" not in dblayer.table_columns(con, "users"):
        con.execute("ALTER TABLE users ADD COLUMN org_id TEXT")
    con.commit()


def _migrate_employee_kind(con):
    """employees 表补 kind 列（员工类型：composed=编排型 / custom=定制型）+ 把
    内置定制型员工打标。

    定制型员工的 kind 由代码事实决定（有独立模块化路由如 /app/analyst 与
    专属工作台），不应受页面改动影响，每次迁移强制对齐。其余员工保持 composed
    默认值，不受本迁移覆盖。
    """
    if "kind" not in dblayer.table_columns(con, "employees"):
        con.execute("ALTER TABLE employees ADD COLUMN kind TEXT DEFAULT 'composed'")
    # 定制型员工 kind 由代码决定（内置独立模块），每次迁移强制对齐，
    # 避免管理员误改或历史迁移 bug 导致分类错乱
    con.execute(
        "UPDATE employees SET kind='custom' WHERE id IN ('xiaoshu') "
        "AND deleted_at IS NULL")
    con.commit()


def _migrate_datasource_public(con):
    """datasources 表补 is_public 列（1=公共，全员可用；0=私有，仅 owner/管理员）。

    存量数据源在引入「私有隔离」前本就是全局共享的，因此首次补列时把所有
    未删除的数据源统一标记为公共（is_public=1），保留升级前的共享行为；
    之后新建的数据源默认私有（is_public=0），由管理员按需设为公共。
    """
    if "is_public" not in dblayer.table_columns(con, "datasources"):
        con.execute("ALTER TABLE datasources ADD COLUMN is_public INTEGER DEFAULT 0")
        con.execute(
            "UPDATE datasources SET is_public=1 WHERE deleted_at IS NULL")
    con.commit()


def _migrate_soft_delete(con):
    """给实体表补 deleted_at 列（NULL=未删除）。幂等。"""
    for t in _SOFT_DELETE_TABLES:
        if "deleted_at" not in dblayer.table_columns(con, t):
            con.execute(f"ALTER TABLE {t} ADD COLUMN deleted_at TEXT")
    con.commit()


def _migrate_must_change_password(con):
    """users 表补 must_change_password 列（1=首登必须改密）。幂等。"""
    if "must_change_password" not in dblayer.table_columns(con, "users"):
        con.execute("ALTER TABLE users ADD COLUMN must_change_password INTEGER DEFAULT 0")
    con.commit()


def _migrate_ragflow_datasets(con):
    """knowledge_bases 补 ragflow_dataset_id（映射到 RAGFlow 中的 dataset id）。"""
    if "ragflow_dataset_id" not in dblayer.table_columns(con, "knowledge_bases"):
        con.execute("ALTER TABLE knowledge_bases ADD COLUMN ragflow_dataset_id TEXT")
    con.commit()


def _migrate_retire_kb_entries(con):
    """旧本地知识条目表若存在则软退役；运行时知识统一来自 RAGFlow。"""
    if not dblayer.table_exists(con, "kb_entries"):
        return
    if "deleted_at" not in dblayer.table_columns(con, "kb_entries"):
        con.execute("ALTER TABLE kb_entries ADD COLUMN deleted_at TEXT")
    now = time.strftime("%Y-%m-%d %H:%M:%S")
    con.execute("UPDATE kb_entries SET deleted_at=? WHERE deleted_at IS NULL", (now,))
    con.commit()


def _migrate_remove_refund_gate(con):
    """撤 start_refund 的外层审批 gate（Point2：审批内化进 workflow 状态机）。"""
    row = con.execute("SELECT needs_approval FROM tools WHERE id='start_refund'").fetchone()
    if not row or not row["needs_approval"]:
        return
    con.execute("UPDATE tools SET needs_approval=NULL WHERE id='start_refund'")
    for emp in con.execute(
        "SELECT e.id, e.interrupt_on FROM employees e "
        "JOIN employee_tools et ON et.employee_id=e.id "
        "WHERE et.tool_id='start_refund' AND e.deleted_at IS NULL"
    ).fetchall():
        old = json.loads(emp["interrupt_on"]) if emp["interrupt_on"] else {}
        old.pop("start_refund", None)
        con.execute("UPDATE employees SET interrupt_on=? WHERE id=?",
                    (json.dumps(old, ensure_ascii=False), emp["id"]))
    con.commit()
    print("[migrate] 已撤 start_refund 外层审批 gate（Point2 内化审批）")


def _migrate_subagents(con):
    """employees 表补 subagents / subagent_policy 列。幂等。"""
    cols = dblayer.table_columns(con, "employees")
    if "subagents" not in cols:
        con.execute("ALTER TABLE employees ADD COLUMN subagents TEXT")
    if "subagent_policy" not in cols:
        con.execute("ALTER TABLE employees ADD COLUMN subagent_policy TEXT")
    con.commit()


def _soft_delete_row(table: str, id_: str, col: str = "id") -> bool:
    """把实体行标记为已删除（软删）。返回是否有行受影响（已删的不重复标记）。"""
    now = time.strftime("%Y-%m-%d %H:%M:%S")
    con = _conn()
    cur = con.cursor()
    cur.execute(
        f"UPDATE {table} SET deleted_at=? WHERE {col}=? AND deleted_at IS NULL",
        (now, id_))
    ok = cur.rowcount > 0
    con.commit()
    con.close()
    return ok


def _unlink(kind: str, res_id: str) -> list[str]:
    """删除某资源在员工关联表里的记录，返回受影响员工 id 列表。"""
    table, col = _LINK_TABLES[kind]
    con = _conn()
    cur = con.cursor()
    affected = [r[0] for r in cur.execute(
        f"SELECT employee_id FROM {table} WHERE {col}=?", (res_id,))]
    cur.execute(f"DELETE FROM {table} WHERE {col}=?", (res_id,))
    con.commit()
    con.close()
    return affected


def _unlink_view(kind: str, res_id: str) -> list[str]:
    """只查不删，供管理页面（GET /entries 等）读取受影响员工用。"""
    table, col = _LINK_TABLES[kind]
    con = _conn()
    out = [r[0] for r in con.execute(
        f"SELECT employee_id FROM {table} WHERE {col}=?", (res_id,))]
    con.close()
    return out
