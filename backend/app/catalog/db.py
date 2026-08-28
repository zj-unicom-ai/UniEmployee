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
    "sops", "connectors", "orgs",
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
      subagents TEXT, subagent_policy TEXT, created_at TEXT, updated_at TEXT);
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
    """)
    con.commit()
    _migrate_soft_delete(con)
    _migrate_must_change_password(con)
    _migrate_remove_refund_gate(con)
    _migrate_subagents(con)
    _migrate_ragflow_datasets(con)
    _migrate_retire_kb_entries(con)
    _migrate_user_org(con)
    con.close()


def _migrate_user_org(con):
    """users 表补 org_id 列（归属组织，NULL=未分配）。幂等。"""
    if "org_id" not in dblayer.table_columns(con, "users"):
        con.execute("ALTER TABLE users ADD COLUMN org_id TEXT")
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
