"""审批中心（SQLite 落库版）：中断工单创建、查询、决策。

审批单持久化到 ``approvals.db``，带过期自动拒绝和 pending 数量上限。
"""
import json
import os
import time
import sqlite3

from app import db as dblayer
from app.paths import db_path

DB = db_path("approvals.db")


def _conn():
    if dblayer.is_pg():
        con = dblayer.connect("approvals")
    else:
        con = sqlite3.connect(str(DB))
        con.row_factory = sqlite3.Row
    con.execute("""
        CREATE TABLE IF NOT EXISTS approvals (
            approval_id     TEXT PRIMARY KEY,
            conversation_id TEXT NOT NULL,
            employee_id     TEXT NOT NULL,
            user_id         TEXT DEFAULT 'default',
            tool            TEXT,
            args            TEXT,
            inner_thread    TEXT,
            status          TEXT DEFAULT 'pending',
            created_at      TEXT,
            expires_at      TEXT
        )
    """)
    return con


def _now_str() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S")


def _row_to_dict(row) -> dict:
    d = dict(row)
    try:
        d["args"] = json.loads(d.get("args") or "{}")
    except Exception:
        d["args"] = {}
    return d


def _expire_if_needed(con, record: dict) -> dict:
    if record.get("status") != "pending":
        return record
    expires_at = record.get("expires_at")
    if expires_at and expires_at <= _now_str():
        con.execute("UPDATE approvals SET status='rejected' WHERE approval_id=?", (record["approval_id"],))
        record = dict(record)
        record["status"] = "rejected"
    return record


def get(approval_id: str) -> dict | None:
    """按 id 查审批单（不改变状态），供权限校验先于决策使用。"""
    with _conn() as con:
        row = con.execute("SELECT * FROM approvals WHERE approval_id=?", (approval_id,)).fetchone()
        if not row:
            return None
        return _expire_if_needed(con, _row_to_dict(row))


def create(conversation_id: str, employee_id: str, tool_name: str, tool_args: dict,
           user_id: str = "default", inner_thread: str | None = None) -> dict:
    """创建审批单。

    inner_thread 非空时，表示这是 workflow 内层图审批（Point2：refund StateGraph
    的 await_approval 节点 interrupt 产生）。decision 端点据此走双路径：
    有 inner_thread → 先 resume_refund 恢复内层图，再 resume 外层 agent；
    无 inner_thread → 老路径（外层 interrupt_on 的轻量确认，如 create_ticket）。
    user_id 记录发起审批的会话属主，decision 端点据此校验权限。
    """
    with _conn() as con:
        pending = con.execute("SELECT COUNT(*) FROM approvals WHERE status='pending'").fetchone()[0]
        limit = int(os.environ.get("APPROVAL_PENDING_LIMIT", "100"))
        if pending >= limit:
            raise RuntimeError("审批队列已满，请先处理已有审批")
        approval_id = f"ap_{int(time.time() * 1000)}_{os.urandom(3).hex()}"
        created_at = _now_str()
        ttl = int(os.environ.get("APPROVAL_TTL_SECONDS", "86400"))
        expires_at = time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(time.time() + ttl))
        con.execute(
            "INSERT INTO approvals "
            "(approval_id, conversation_id, employee_id, user_id, tool, args, inner_thread,"
            " status, created_at, expires_at) VALUES (?,?,?,?,?,?,?,?,?,?)",
            (approval_id, conversation_id, employee_id, user_id, tool_name,
             json.dumps(tool_args, ensure_ascii=False, default=str), inner_thread,
             "pending", created_at, expires_at),
        )
    record = {
        "approval_id": approval_id,
        "conversation_id": conversation_id,
        "employee_id": employee_id,
        "user_id": user_id,
        "tool": tool_name,
        "args": tool_args,
        "inner_thread": inner_thread,
        "status": "pending",
        "created_at": created_at,
        "expires_at": expires_at,
    }
    return record


def decide(approval_id: str, decision: str) -> dict | None:
    with _conn() as con:
        row = con.execute("SELECT * FROM approvals WHERE approval_id=?", (approval_id,)).fetchone()
        if not row:
            return None
        record = _expire_if_needed(con, _row_to_dict(row))
        if record["status"] != "pending" or decision not in ("approve", "reject"):
            return None
        con.execute("UPDATE approvals SET status=? WHERE approval_id=?",
                    (decision, approval_id))
        record["status"] = decision
        return record
