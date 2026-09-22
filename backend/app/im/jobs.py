"""IM 身份、会话映射与持久 Inbox/Outbox 队列。"""

from __future__ import annotations

import json
import sqlite3
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from app import db as dblayer
from app.im.context import ActorContext
from app.im.contracts import NormalizedInbound, OutboundMessage
from app.im.credentials import ChannelCredential, decrypt_secret, encrypt_secret
from app.paths import db_path


DB = db_path("conversations.db")

_DDL = """
CREATE TABLE IF NOT EXISTS channel_credentials (
    channel_id TEXT PRIMARY KEY,
    app_id TEXT NOT NULL,
    app_secret_ciphertext TEXT NOT NULL,
    tenant_key TEXT NOT NULL,
    verification_token_ciphertext TEXT,
    encrypt_key_ciphertext TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS channel_inbox (
    id TEXT PRIMARY KEY,
    channel_id TEXT NOT NULL,
    provider_event_id TEXT NOT NULL,
    provider_message_id TEXT NOT NULL,
    payload TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'received',
    attempts INTEGER NOT NULL DEFAULT 0,
    lease_owner TEXT,
    lease_expires_at TEXT,
    error TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE(channel_id, provider_message_id)
);
CREATE INDEX IF NOT EXISTS idx_channel_inbox_claim
    ON channel_inbox(status, lease_expires_at, created_at);
CREATE TABLE IF NOT EXISTS channel_outbox (
    id TEXT PRIMARY KEY,
    inbox_id TEXT NOT NULL,
    channel_id TEXT NOT NULL,
    receive_id TEXT NOT NULL,
    receive_id_type TEXT NOT NULL,
    reply_to_message_id TEXT,
    content TEXT NOT NULL,
    provider_uuid TEXT NOT NULL UNIQUE,
    status TEXT NOT NULL DEFAULT 'pending',
    attempts INTEGER NOT NULL DEFAULT 0,
    lease_owner TEXT,
    lease_expires_at TEXT,
    next_attempt_at TEXT,
    provider_message_id TEXT,
    error TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE(inbox_id)
);
CREATE INDEX IF NOT EXISTS idx_channel_outbox_claim
    ON channel_outbox(status, next_attempt_at, lease_expires_at, created_at);
CREATE TABLE IF NOT EXISTS channel_identities (
    id TEXT PRIMARY KEY,
    provider TEXT NOT NULL,
    app_id TEXT NOT NULL,
    tenant_key TEXT NOT NULL,
    open_id TEXT NOT NULL,
    internal_user_id TEXT,
    binding_status TEXT NOT NULL DEFAULT 'external',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE(provider, app_id, tenant_key, open_id)
);
CREATE TABLE IF NOT EXISTS channel_threads (
    id TEXT PRIMARY KEY,
    channel_id TEXT NOT NULL,
    tenant_key TEXT NOT NULL,
    chat_id TEXT NOT NULL,
    sender_open_id TEXT NOT NULL,
    root_id TEXT,
    scope_key TEXT NOT NULL,
    employee_id TEXT NOT NULL,
    conv_id TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE(channel_id, scope_key, employee_id)
);
CREATE TABLE IF NOT EXISTS channel_card_sessions (
    id TEXT PRIMARY KEY,
    inbox_id TEXT NOT NULL,
    channel_id TEXT NOT NULL,
    out_track_id TEXT NOT NULL,
    template_id TEXT NOT NULL,
    level TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'opened',
    update_count INTEGER NOT NULL DEFAULT 0,
    error TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE(inbox_id)
);
"""


def _now(value: datetime | None = None) -> str:
    return (value or datetime.now(timezone.utc)).isoformat(timespec="milliseconds")


def _new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex}"


def _conn():
    if dblayer.is_pg():
        con = dblayer.connect("conversations")
    else:
        con = sqlite3.connect(str(DB), timeout=30)
        con.row_factory = sqlite3.Row
        con.execute("PRAGMA busy_timeout=30000")
    con.executescript(_DDL)
    return con


def init() -> None:
    with _conn():
        pass


def put_credential(
    *, channel_id: str, app_id: str, app_secret: str, tenant_key: str,
    verification_token: str | None = None, encrypt_key: str | None = None,
) -> None:
    now = _now()
    values = (
        channel_id, app_id, encrypt_secret(app_secret), tenant_key,
        encrypt_secret(verification_token) if verification_token else None,
        encrypt_secret(encrypt_key) if encrypt_key else None, now, now,
    )
    with _conn() as con:
        con.execute(
            "INSERT INTO channel_credentials(channel_id,app_id,app_secret_ciphertext,"
            "tenant_key,verification_token_ciphertext,encrypt_key_ciphertext,created_at,updated_at) "
            "VALUES (?,?,?,?,?,?,?,?) ON CONFLICT(channel_id) DO UPDATE SET "
            "app_id=excluded.app_id,app_secret_ciphertext=excluded.app_secret_ciphertext,"
            "tenant_key=excluded.tenant_key,verification_token_ciphertext=excluded.verification_token_ciphertext,"
            "encrypt_key_ciphertext=excluded.encrypt_key_ciphertext,updated_at=excluded.updated_at",
            values,
        )


def get_credential(channel_id: str) -> ChannelCredential | None:
    with _conn() as con:
        row = con.execute(
            "SELECT * FROM channel_credentials WHERE channel_id=?", (channel_id,)
        ).fetchone()
    if not row:
        return None
    return ChannelCredential(
        channel_id=row["channel_id"], app_id=row["app_id"],
        tenant_key=row["tenant_key"],
        app_secret=decrypt_secret(row["app_secret_ciphertext"]),
        verification_token=(decrypt_secret(row["verification_token_ciphertext"])
                            if row["verification_token_ciphertext"] else None),
        encrypt_key=(decrypt_secret(row["encrypt_key_ciphertext"])
                     if row["encrypt_key_ciphertext"] else None),
    )


def credential_summary(channel_id: str) -> dict[str, Any] | None:
    with _conn() as con:
        row = con.execute(
            "SELECT channel_id,app_id,tenant_key,app_secret_ciphertext,updated_at "
            "FROM channel_credentials WHERE channel_id=?", (channel_id,)
        ).fetchone()
    if not row:
        return None
    return {
        "channel_id": row["channel_id"], "app_id": row["app_id"],
        "tenant_key": row["tenant_key"], "configured": bool(row["app_secret_ciphertext"]),
        "updated_at": row["updated_at"],
    }


def enqueue_inbound(message: NormalizedInbound) -> tuple[str, bool]:
    inbox_id = _new_id("inbox")
    now = _now()
    payload = json.dumps(message.persisted_payload(), ensure_ascii=False, separators=(",", ":"))
    with _conn() as con:
        cur = con.execute(
            "INSERT OR IGNORE INTO channel_inbox"
            "(id,channel_id,provider_event_id,provider_message_id,payload,status,created_at,updated_at) "
            "VALUES (?,?,?,?,?,'received',?,?)",
            (inbox_id, message.channel_id, message.event_id, message.message_id, payload, now, now),
        )
        created = cur.rowcount > 0
        if not created:
            row = con.execute(
                "SELECT id FROM channel_inbox WHERE channel_id=? AND provider_message_id=?",
                (message.channel_id, message.message_id),
            ).fetchone()
            inbox_id = row["id"]
    return inbox_id, created


def _claim(table: str, ready: tuple[str, ...], worker_id: str, lease_seconds: int,
           now: datetime | None = None,
           channel_id: str | None = None) -> dict[str, Any] | None:
    moment = now or datetime.now(timezone.utc)
    now_s = _now(moment)
    lease_s = _now(moment + timedelta(seconds=lease_seconds))
    placeholders = ",".join("?" for _ in ready)
    channel_clause = "channel_id=? AND " if channel_id else ""
    channel_params = (channel_id,) if channel_id else ()
    with _conn() as con:
        row = con.execute(
            f"SELECT id FROM {table} WHERE {channel_clause}((status IN ({placeholders}) "
            "AND (next_attempt_at IS NULL OR next_attempt_at<=?)) "
            "OR (status IN ('processing','sending') AND lease_expires_at<=?)) "
            "ORDER BY created_at,id LIMIT 1",
            (*channel_params, *ready, now_s, now_s),
        ).fetchone()
        if not row:
            return None
        target = "processing" if table == "channel_inbox" else "sending"
        cur = con.execute(
            f"UPDATE {table} SET status=?,attempts=attempts+1,lease_owner=?,"
            f"lease_expires_at=?,updated_at=? WHERE id=? AND {channel_clause}((status IN ("
            f"{placeholders}) AND (next_attempt_at IS NULL OR next_attempt_at<=?)) "
            "OR (status IN ('processing','sending') AND lease_expires_at<=?))",
            (
                target, worker_id, lease_s, now_s, row["id"],
                *channel_params, *ready, now_s, now_s,
            ),
        )
        if cur.rowcount != 1:
            return None
        claimed = con.execute(f"SELECT * FROM {table} WHERE id=?", (row["id"],)).fetchone()
    result = dict(claimed)
    if "payload" in result:
        result["payload"] = json.loads(result["payload"])
    return result


def claim_inbox(worker_id: str, lease_seconds: int = 60,
                now: datetime | None = None,
                channel_id: str | None = None) -> dict[str, Any] | None:
    # Inbox 没有 next_attempt_at，为复用查询补一个始终为 NULL 的表达式列不可行；
    # 单独实现其 CAS 条件。
    moment = now or datetime.now(timezone.utc)
    now_s = _now(moment)
    lease_s = _now(moment + timedelta(seconds=lease_seconds))
    channel_clause = "channel_id=? AND " if channel_id else ""
    channel_params = (channel_id,) if channel_id else ()
    with _conn() as con:
        row = con.execute(
            f"SELECT id FROM channel_inbox WHERE {channel_clause}(status='received' OR "
            "(status='processing' AND lease_expires_at<=?)) ORDER BY created_at,id LIMIT 1",
            (*channel_params, now_s),
        ).fetchone()
        if not row:
            return None
        cur = con.execute(
            "UPDATE channel_inbox SET status='processing',attempts=attempts+1,"
            "lease_owner=?,lease_expires_at=?,updated_at=? WHERE id=? AND "
            f"{channel_clause}(status='received' OR (status='processing' AND lease_expires_at<=?))",
            (worker_id, lease_s, now_s, row["id"], *channel_params, now_s),
        )
        if cur.rowcount != 1:
            return None
        claimed = con.execute("SELECT * FROM channel_inbox WHERE id=?", (row["id"],)).fetchone()
    result = dict(claimed)
    result["payload"] = json.loads(result["payload"])
    return result


def finish_inbox(inbox_id: str, worker_id: str, *, error: str | None = None) -> bool:
    status = "failed" if error else "completed"
    with _conn() as con:
        cur = con.execute(
            "UPDATE channel_inbox SET status=?,error=?,lease_owner=NULL,lease_expires_at=NULL,"
            "updated_at=? WHERE id=? AND status='processing' AND lease_owner=?",
            (status, error, _now(), inbox_id, worker_id),
        )
        return cur.rowcount == 1


def create_outbox(inbox_id: str, message: OutboundMessage) -> tuple[str, bool]:
    outbox_id = _new_id("outbox")
    now = _now()
    stable_uuid = str(uuid.uuid5(uuid.NAMESPACE_URL, f"uniemployee:{inbox_id}"))
    with _conn() as con:
        cur = con.execute(
            "INSERT OR IGNORE INTO channel_outbox"
            "(id,inbox_id,channel_id,receive_id,receive_id_type,reply_to_message_id,content,"
            "provider_uuid,status,created_at,updated_at) VALUES (?,?,?,?,?,?,?,?, 'pending',?,?)",
            (outbox_id, inbox_id, message.channel_id, message.receive_id,
             message.receive_id_type, message.reply_to_message_id, message.text,
             stable_uuid, now, now),
        )
        created = cur.rowcount > 0
        if not created:
            row = con.execute("SELECT id FROM channel_outbox WHERE inbox_id=?", (inbox_id,)).fetchone()
            outbox_id = row["id"]
    return outbox_id, created


def claim_outbox(worker_id: str, lease_seconds: int = 60,
                 now: datetime | None = None,
                 channel_id: str | None = None) -> dict[str, Any] | None:
    return _claim(
        "channel_outbox", ("pending", "retry"), worker_id, lease_seconds, now,
        channel_id,
    )


def finish_outbox(outbox_id: str, worker_id: str, *, provider_message_id: str) -> bool:
    with _conn() as con:
        cur = con.execute(
            "UPDATE channel_outbox SET status='sent',provider_message_id=?,error=NULL,"
            "lease_owner=NULL,lease_expires_at=NULL,updated_at=? WHERE id=? "
            "AND status='sending' AND lease_owner=?",
            (provider_message_id, _now(), outbox_id, worker_id),
        )
        return cur.rowcount == 1


def retry_outbox(outbox_id: str, worker_id: str, *, error: str,
                 retry_at: datetime | None) -> bool:
    status = "retry" if retry_at else "dead"
    with _conn() as con:
        cur = con.execute(
            "UPDATE channel_outbox SET status=?,error=?,next_attempt_at=?,lease_owner=NULL,"
            "lease_expires_at=NULL,updated_at=? WHERE id=? AND status='sending' AND lease_owner=?",
            (status, error, _now(retry_at) if retry_at else None, _now(), outbox_id, worker_id),
        )
        return cur.rowcount == 1


def list_outbox(
    *, channel_id: str | None = None, status: str | None = None, limit: int = 50
) -> list[dict[str, Any]]:
    """列出投递状态；不返回消息正文和目标标识。"""
    clauses: list[str] = []
    params: list[Any] = []
    if channel_id:
        clauses.append("channel_id=?")
        params.append(channel_id)
    if status:
        clauses.append("status=?")
        params.append(status)
    where = " WHERE " + " AND ".join(clauses) if clauses else ""
    params.append(max(1, min(int(limit), 200)))
    with _conn() as con:
        rows = con.execute(
            "SELECT id,inbox_id,channel_id,status,attempts,next_attempt_at,"
            "provider_message_id,error,created_at,updated_at FROM channel_outbox"
            f"{where} ORDER BY created_at DESC,id DESC LIMIT ?",
            params,
        ).fetchall()
    return [dict(row) for row in rows]


def replay_outbox(outbox_id: str) -> dict[str, Any] | None:
    """将失败投递重新放回队列，保留稳定 provider_uuid 以维持幂等语义。"""
    now = _now()
    with _conn() as con:
        cur = con.execute(
            "UPDATE channel_outbox SET status='pending',attempts=0,error=NULL,"
            "next_attempt_at=NULL,lease_owner=NULL,lease_expires_at=NULL,updated_at=? "
            "WHERE id=? AND status IN ('dead','retry')",
            (now, outbox_id),
        )
        if cur.rowcount != 1:
            return None
        row = con.execute(
            "SELECT id,inbox_id,channel_id,status,attempts,next_attempt_at,"
            "provider_message_id,error,created_at,updated_at "
            "FROM channel_outbox WHERE id=?",
            (outbox_id,),
        ).fetchone()
    return dict(row)


def ensure_external_identity(context: ActorContext) -> dict[str, Any]:
    identity_id = _new_id("identity")
    now = _now()
    with _conn() as con:
        con.execute(
            "INSERT OR IGNORE INTO channel_identities"
            "(id,provider,app_id,tenant_key,open_id,internal_user_id,binding_status,created_at,updated_at) "
            "VALUES (?,?,?,?,?,NULL,'external',?,?)",
            (identity_id, context.provider, context.app_id, context.tenant_key,
             context.sender_open_id, now, now),
        )
        row = con.execute(
            "SELECT * FROM channel_identities WHERE provider=? AND app_id=? "
            "AND tenant_key=? AND open_id=?",
            (context.provider, context.app_id, context.tenant_key, context.sender_open_id),
        ).fetchone()
    return dict(row)


def get_or_create_thread(context: ActorContext, *, channel_id: str,
                         employee_id: str) -> tuple[dict[str, Any], bool]:
    thread_id = _new_id("thread")
    conv_id = _new_id("c_im")
    now = _now()
    with _conn() as con:
        cur = con.execute(
            "INSERT OR IGNORE INTO channel_threads"
            "(id,channel_id,tenant_key,chat_id,sender_open_id,root_id,scope_key,employee_id,"
            "conv_id,created_at,updated_at) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            (thread_id, channel_id, context.tenant_key, context.chat_id,
             context.sender_open_id, None, context.subject_id, employee_id, conv_id, now, now),
        )
        created = cur.rowcount > 0
        row = con.execute(
            "SELECT * FROM channel_threads WHERE channel_id=? AND scope_key=? AND employee_id=?",
            (channel_id, context.subject_id, employee_id),
        ).fetchone()
    return dict(row), created


def create_card_session(
    *, inbox_id: str, channel_id: str, out_track_id: str, template_id: str, level: str
) -> str:
    """登记一次卡片投放。

    这不是队列：卡片必须在员工执行期间同步推进，异步投递帮不上忙。落库只为
    可观测与排障 —— 哪条消息开了卡片、用的是哪档节流、最后收在什么状态。
    """
    session_id = _new_id("card")
    now = _now()
    with _conn() as con:
        con.execute(
            "INSERT OR IGNORE INTO channel_card_sessions"
            "(id,inbox_id,channel_id,out_track_id,template_id,level,status,"
            "update_count,created_at,updated_at) VALUES (?,?,?,?,?,?,'opened',0,?,?)",
            (session_id, inbox_id, channel_id, out_track_id, template_id, level, now, now),
        )
    return session_id


def finish_card_session(
    inbox_id: str, *, status: str, update_count: int, error: str | None = None
) -> bool:
    """收尾卡片会话状态。

    取值：``completed``（卡片承载了结果）、``truncated``（卡片被截断，已补文本）、
    ``finalize_failed``（收尾失败，已补文本）、``abandoned``（执行失败）。
    """
    with _conn() as con:
        cur = con.execute(
            "UPDATE channel_card_sessions SET status=?,update_count=?,error=?,updated_at=? "
            "WHERE inbox_id=?",
            (status, max(int(update_count), 0), error, _now(), inbox_id),
        )
        return cur.rowcount == 1
