"""Web 对话的持久运行记录与可重放 SSE 事件（单实例执行版）。

Agent 任务由独立 asyncio task 持有；HTTP 连接只订阅事件。进程意外退出时，
启动恢复将遗留 queued/running 标记为 abandoned，避免永久占住会话。
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import sqlite3
import time
import uuid
from datetime import datetime, timedelta, timezone

from app import conversations, db as dblayer
from app.streaming import _stream_run, sse

log = logging.getLogger("app.agent_runs")
TERMINAL = frozenset({"done", "error", "interrupted", "cancelled", "abandoned"})
_tasks: dict[str, asyncio.Task] = {}

_DDL = """
CREATE TABLE IF NOT EXISTS agent_runs (
    id TEXT PRIMARY KEY,
    conv_id TEXT NOT NULL,
    tenant_id TEXT NOT NULL,
    user_id TEXT NOT NULL,
    employee_id TEXT NOT NULL,
    status TEXT NOT NULL,
    trace_run_id TEXT DEFAULT '',
    last_seq INTEGER NOT NULL DEFAULT 0,
    error TEXT DEFAULT '',
    created_at TEXT NOT NULL,
    started_at TEXT,
    finished_at TEXT
);
CREATE TABLE IF NOT EXISTS active_agent_runs (
    conv_id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL UNIQUE
);
CREATE TABLE IF NOT EXISTS agent_run_events (
    run_id TEXT NOT NULL,
    seq INTEGER NOT NULL,
    payload TEXT NOT NULL,
    created_at TEXT NOT NULL,
    PRIMARY KEY(run_id, seq)
);
CREATE INDEX IF NOT EXISTS idx_agent_runs_owner ON agent_runs(tenant_id, user_id, conv_id, created_at);
"""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def init_tables() -> None:
    con = conversations._conn()
    try:
        con.executescript(_DDL)
        con.commit()
    finally:
        con.close()


def _conn():
    """事件写入热路径不重复执行会话表迁移和 DDL。"""
    if dblayer.is_pg():
        return dblayer.connect("conversations")
    con = sqlite3.connect(str(conversations.DB), timeout=30)
    con.row_factory = sqlite3.Row
    return con


class ActiveRunError(Exception):
    def __init__(self, run_id: str):
        self.run_id = run_id
        super().__init__(f"会话已有运行中任务：{run_id}")


def get(run_id: str) -> dict | None:
    with _conn() as con:
        row = con.execute("SELECT * FROM agent_runs WHERE id=?", (run_id,)).fetchone()
    return dict(row) if row else None


def active_for_conversation(conv_id: str) -> dict | None:
    with _conn() as con:
        row = con.execute(
            "SELECT r.* FROM active_agent_runs a JOIN agent_runs r ON a.run_id=r.id "
            "WHERE a.conv_id=?", (conv_id,),
        ).fetchone()
    return dict(row) if row else None


def create(*, conv_id: str, tenant_id: str, user_id: str, employee_id: str) -> dict:
    run_id = "ar_" + uuid.uuid4().hex
    now = _now()
    try:
        with _conn() as con:
            con.execute("INSERT INTO active_agent_runs(conv_id, run_id) VALUES(?,?)",
                        (conv_id, run_id))
            con.execute(
                "INSERT INTO agent_runs(id,conv_id,tenant_id,user_id,employee_id,status,created_at) "
                "VALUES(?,?,?,?,?,'queued',?)",
                (run_id, conv_id, tenant_id, user_id, employee_id, now),
            )
    except Exception as create_error:
        try:
            existing = active_for_conversation(conv_id)
        except Exception:
            raise create_error
        if existing:
            raise ActiveRunError(existing["id"]) from None
        raise
    try:
        append_event(run_id, {"type": "run_started", "run_id": run_id})
    except Exception:
        finish(run_id, "error", "无法记录启动事件")
        raise
    return get(run_id) or {}


def mark_running(run_id: str) -> None:
    with _conn() as con:
        con.execute("UPDATE agent_runs SET status='running',started_at=? "
                    "WHERE id=? AND status='queued'", (_now(), run_id))


def append_event(run_id: str, payload: dict) -> int:
    with _conn() as con:
        row = con.execute(
            "UPDATE agent_runs SET last_seq=last_seq+1 WHERE id=? RETURNING last_seq",
            (run_id,),
        ).fetchone()
        if not row:
            raise KeyError(run_id)
        seq = row[0]
        con.execute(
            "INSERT INTO agent_run_events(run_id,seq,payload,created_at) VALUES(?,?,?,?)",
            (run_id, seq, json.dumps(payload, ensure_ascii=False), _now()),
        )
    return seq


def events_after(run_id: str, after: int, limit: int = 100) -> list[dict]:
    with _conn() as con:
        rows = con.execute(
            "SELECT seq,payload FROM agent_run_events WHERE run_id=? AND seq>? "
            "ORDER BY seq LIMIT ?", (run_id, after, min(max(limit, 1), 500)),
        ).fetchall()
    return [{"seq": row[0], "payload": json.loads(row[1])} for row in rows]


def set_trace(run_id: str, trace_run_id: str) -> None:
    with _conn() as con:
        con.execute("UPDATE agent_runs SET trace_run_id=? WHERE id=?",
                    (trace_run_id, run_id))


def finish(run_id: str, status: str, error: str = "") -> None:
    if status not in TERMINAL:
        raise ValueError(f"非法运行状态：{status}")
    with _conn() as con:
        con.execute(
            "UPDATE agent_runs SET status=?,error=?,finished_at=? "
            "WHERE id=? AND status IN ('queued','running')",
            (status, error[:500], _now(), run_id),
        )
        con.execute("DELETE FROM active_agent_runs WHERE run_id=?", (run_id,))


def recover_abandoned() -> int:
    """单实例服务重启后，收口上个进程未完成的任务。"""
    with _conn() as con:
        cur = con.execute(
            "UPDATE agent_runs SET status='abandoned',error='worker process restarted',finished_at=? "
            "WHERE status IN ('queued','running')", (_now(),),
        )
        con.execute("DELETE FROM active_agent_runs")
        return cur.rowcount


def purge_events(days: int | None = None) -> int:
    """只清理已结束且超出保留期的事件；运行元数据仍保留。"""
    if days is None:
        days = max(1, int(os.environ.get("AGENT_RUN_EVENT_RETENTION_DAYS", "7")))
    before = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat(timespec="seconds")
    with _conn() as con:
        cur = con.execute(
            "DELETE FROM agent_run_events WHERE run_id IN "
            "(SELECT id FROM agent_runs WHERE finished_at IS NOT NULL AND finished_at<?)",
            (before,),
        )
        return cur.rowcount


def _payload(raw: str) -> dict:
    if not raw.startswith("data: "):
        raise ValueError("SSE 事件格式无效")
    return json.loads(raw[6:].strip())


async def _worker(run_id: str, input_, *, user_id: str, role: str,
                  datasource_id: str = "", data_source: str = "",
                  model_override: str = "", tenant_id: str,
                  auth_context: dict | None = None,
                  refund_thread: str | None = None,
                  refund_approved: bool | None = None) -> None:
    status = "error"
    error = ""
    token_buffer = ""
    token_buffered_at = time.monotonic()

    def flush_tokens() -> None:
        nonlocal token_buffer, token_buffered_at
        if token_buffer:
            append_event(run_id, {"type": "token", "content": token_buffer})
            token_buffer = ""
            token_buffered_at = time.monotonic()

    try:
        mark_running(run_id)
        run = get(run_id)
        if not run:
            raise RuntimeError("运行记录不存在")
        if refund_thread:
            from app import runtime
            from langgraph.types import Command
            summary = await runtime.resume_refund(refund_thread, bool(refund_approved))
            input_ = Command(resume=summary)
        async for raw in _stream_run(
            run["conv_id"], input_, user_id=user_id, role=role,
            datasource_id=datasource_id, data_source=data_source,
            model_override=model_override, tenant_id=tenant_id,
            auth_context=auth_context,
        ):
            payload = _payload(raw)
            if payload.get("type") == "trace_started":
                set_trace(run_id, payload.get("trace_run_id", ""))
            if payload.get("type") == "token":
                token_buffer += str(payload.get("content", ""))
                if len(token_buffer) < 512 and time.monotonic() - token_buffered_at < 0.05:
                    continue
                flush_tokens()
                continue
            flush_tokens()
            append_event(run_id, payload)
            if payload.get("type") == "message_end":
                status = "done"
            elif payload.get("type") == "approval_required":
                status = "interrupted"
            elif payload.get("type") == "error":
                status = "error"
                error = str(payload.get("message", ""))
        flush_tokens()
        if status == "error" and not error:
            error = "运行未产生完成事件"
    except asyncio.CancelledError:
        flush_tokens()
        status = "cancelled"
        error = "用户取消或服务关闭"
        append_event(run_id, {"type": "run_cancelled", "message": "运行已取消"})
        raise
    except Exception as exc:
        flush_tokens()
        log.exception("后台运行失败 run=%s", run_id)
        error = "后台任务执行失败"
        append_event(run_id, {"type": "error", "error_code": "internal_error",
                              "message": "后台任务执行失败，请查看运行记录"})
    finally:
        try:
            finish(run_id, status, error)
        finally:
            _tasks.pop(run_id, None)


def launch(run_id: str, input_, **kwargs) -> None:
    if run_id in _tasks:
        raise RuntimeError("运行已启动")
    _tasks[run_id] = asyncio.create_task(_worker(run_id, input_, **kwargs),
                                         name=f"agent-run-{run_id}")


def cancel(run_id: str) -> bool:
    task = _tasks.get(run_id)
    if task and not task.done():
        task.cancel()
        return True
    return False


async def shutdown() -> None:
    tasks = list(_tasks.values())
    for task in tasks:
        task.cancel()
    if tasks:
        await asyncio.gather(*tasks, return_exceptions=True)


async def subscribe(run_id: str, after: int = 0):
    """只订阅数据库事件；取消订阅不会取消执行任务。"""
    seq = max(0, after)
    while True:
        batch = await asyncio.to_thread(events_after, run_id, seq)
        for item in batch:
            seq = item["seq"]
            yield sse({**item["payload"], "_event_seq": seq})
        run = await asyncio.to_thread(get, run_id)
        if not run:
            return
        if run["status"] in TERMINAL:
            if seq >= run["last_seq"]:
                return
            # 清理策略可能已删除旧事件；不能让订阅请求永久轮询。
            yield sse({"type": "error", "error_code": "run_events_expired",
                       "message": "运行事件已过保留期限，请刷新会话历史查看最终结果"})
            return
        await asyncio.sleep(0.2)
