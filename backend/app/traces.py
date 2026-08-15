"""执行过程追踪（Trace）：记录每次对话运行的 LLM 调用 / 工具调用 / 耗时 / 错误。

设计：
- 存储：独立 traces.db（runs 一次运行一行；events 运行内的每个步骤一行）。
- 捕获：TraceHandler（LangChain AsyncCallbackHandler）注入 agent 调用的
  config["callbacks"]，deepagents/LangGraph 内部所有模型调用与工具调用都会
  经过回调总线，无需改动 SSE 流式逻辑。
- 原则：追踪失败绝不影响正常对话（所有写库均吞异常）。
"""
from __future__ import annotations

import json
import sqlite3
import time
import uuid
from pathlib import Path
from typing import Any

from langchain_core.callbacks import AsyncCallbackHandler

from app.paths import db_path

ROOT = Path(__file__).resolve().parent.parent
DB = db_path("traces.db")

_PREVIEW = 2000  # 输入/输出留存的最大字符数


def _conn():
    con = sqlite3.connect(DB)
    con.row_factory = sqlite3.Row
    con.execute("""CREATE TABLE IF NOT EXISTS runs(
        run_id      TEXT PRIMARY KEY,
        conv_id     TEXT,
        employee_id TEXT,
        user_id     TEXT,
        kind        TEXT,               -- message / resume
        input_preview TEXT,
        status      TEXT,               -- running / done / error / interrupted
        error       TEXT,
        llm_calls   INTEGER DEFAULT 0,
        tool_calls  INTEGER DEFAULT 0,
        total_tokens INTEGER DEFAULT 0,
        started_at  TEXT,
        ended_at    TEXT,
        duration_ms INTEGER
    )""")
    con.execute("""CREATE TABLE IF NOT EXISTS events(
        id          INTEGER PRIMARY KEY AUTOINCREMENT,
        run_id      TEXT,
        seq         INTEGER,
        etype       TEXT,               -- llm / tool
        name        TEXT,
        status      TEXT,               -- ok / error / running
        input       TEXT,
        output      TEXT,
        tokens      INTEGER,
        started_at  TEXT,
        duration_ms INTEGER
    )""")
    con.execute("CREATE INDEX IF NOT EXISTS idx_runs_conv ON runs(conv_id)")
    con.execute("CREATE INDEX IF NOT EXISTS idx_events_run ON events(run_id)")
    return con


def _now() -> str:
    return time.strftime("%Y-%m-%d %H:%M:%S")


def _clip(v: Any, n: int = _PREVIEW) -> str:
    if v is None:
        return ""
    s = v if isinstance(v, str) else json.dumps(v, ensure_ascii=False, default=str)
    return s[:n]


# ---------------------------------------------------------------------------
# runs 生命周期
# ---------------------------------------------------------------------------

def start_run(conv_id: str, employee_id: str, user_id: str,
              input_preview: str = "", kind: str = "message") -> str:
    run_id = "r_" + uuid.uuid4().hex[:16]
    try:
        with _conn() as con:
            con.execute(
                "INSERT INTO runs(run_id,conv_id,employee_id,user_id,kind,"
                "input_preview,status,started_at) VALUES(?,?,?,?,?,?,?,?)",
                (run_id, conv_id, employee_id, user_id, kind,
                 _clip(input_preview, 500), "running", _now()))
    except Exception:
        pass
    return run_id


def finish_run(run_id: str, status: str = "done", error: str = ""):
    try:
        with _conn() as con:
            row = con.execute("SELECT started_at FROM runs WHERE run_id=?", (run_id,)).fetchone()
            dur = None
            if row and row["started_at"]:
                try:
                    dur = int((time.time() - time.mktime(
                        time.strptime(row["started_at"], "%Y-%m-%d %H:%M:%S"))) * 1000)
                except Exception:
                    dur = None
            agg = con.execute(
                "SELECT SUM(etype='llm') l, SUM(etype='tool') t, COALESCE(SUM(tokens),0) tk "
                "FROM events WHERE run_id=?", (run_id,)).fetchone()
            con.execute(
                "UPDATE runs SET status=?, error=?, ended_at=?, duration_ms=?, "
                "llm_calls=?, tool_calls=?, total_tokens=? WHERE run_id=?",
                (status, _clip(error, 500), _now(), dur,
                 agg["l"] or 0, agg["t"] or 0, agg["tk"] or 0, run_id))
    except Exception:
        pass


# ---------------------------------------------------------------------------
# 查询（API 用）
# ---------------------------------------------------------------------------

def list_runs(conv_id: str) -> list[dict]:
    try:
        with _conn() as con:
            rows = con.execute(
                "SELECT * FROM runs WHERE conv_id=? ORDER BY started_at DESC, run_id DESC",
                (conv_id,)).fetchall()
        return [dict(r) for r in rows]
    except Exception:
        return []


def employee_of_conv(conv_id: str) -> str | None:
    """按会话返回最近一次 Trace 记录的员工归属，用于历史线程恢复兜底。"""
    try:
        with _conn() as con:
            r = con.execute(
                "SELECT employee_id FROM runs WHERE conv_id=? "
                "AND employee_id IS NOT NULL AND employee_id != '' "
                "ORDER BY started_at DESC, run_id DESC LIMIT 1",
                (conv_id,)).fetchone()
        return r["employee_id"] if r else None
    except Exception:
        return None


def get_run(run_id: str) -> dict | None:
    try:
        with _conn() as con:
            r = con.execute("SELECT * FROM runs WHERE run_id=?", (run_id,)).fetchone()
            if not r:
                return None
            evs = con.execute(
                "SELECT * FROM events WHERE run_id=? ORDER BY seq", (run_id,)).fetchall()
        out = dict(r)
        out["events"] = [dict(e) for e in evs]
        return out
    except Exception:
        return None


def token_stats() -> dict:
    """返回 token 使用统计：总数 + 今日数。"""
    try:
        with _conn() as con:
            total = con.execute("SELECT COALESCE(SUM(total_tokens),0) FROM runs WHERE status!='running'").fetchone()[0]
            today = con.execute(
                "SELECT COALESCE(SUM(total_tokens),0) FROM runs WHERE status!='running' AND DATE(started_at)=DATE('now')"
            ).fetchone()[0]
        return {"total_tokens": total, "today_tokens": today}
    except Exception:
        return {"total_tokens": 0, "today_tokens": 0}


# ---------------------------------------------------------------------------
# 事件写入（回调用）
# ---------------------------------------------------------------------------

def _insert_event(run_id: str, seq: int, etype: str, name: str, status: str,
                  input_: str, output: str, tokens: int | None,
                  started_at: str, duration_ms: int | None) -> None:
    try:
        with _conn() as con:
            con.execute(
                "INSERT INTO events(run_id,seq,etype,name,status,input,output,"
                "tokens,started_at,duration_ms) VALUES(?,?,?,?,?,?,?,?,?,?)",
                (run_id, seq, etype, name, status, input_, output,
                 tokens, started_at, duration_ms))
    except Exception:
        pass


class TraceHandler(AsyncCallbackHandler):
    """把 LangChain 回调事件落到 traces.db。start/end 用 lc 的 run_id(UUID) 配对。"""

    run_inline = True  # 在主事件循环内执行（sqlite 写很快，避免线程切换开销）

    def __init__(self, run_id: str):
        self.trace_run_id = run_id
        self._seq = 0
        self._pending: dict[str, dict] = {}  # lc_run_id -> {seq,name,etype,input,t0,started_at}

    def _next_seq(self) -> int:
        self._seq += 1
        return self._seq

    def _open(self, lc_id, etype: str, name: str, input_: Any):
        self._pending[str(lc_id)] = {
            "seq": self._next_seq(), "etype": etype, "name": name,
            "input": _clip(input_), "t0": time.time(), "started_at": _now()}

    def _close(self, lc_id, output: Any, status: str, tokens: int | None = None):
        p = self._pending.pop(str(lc_id), None)
        if not p:
            return
        _insert_event(self.trace_run_id, p["seq"], p["etype"], p["name"], status,
                      p["input"], _clip(output), tokens, p["started_at"],
                      int((time.time() - p["t0"]) * 1000))

    # ---- LLM ----
    async def on_chat_model_start(self, serialized, messages, *, run_id, **kwargs):
        try:
            name = (kwargs.get("metadata") or {}).get("ls_model_name") \
                or (serialized or {}).get("name") or "chat_model"
            last = ""
            if messages and messages[0]:
                m = messages[0][-1]
                last = m.content if isinstance(getattr(m, "content", None), str) else str(m)
            self._open(run_id, "llm", name, last)
        except Exception:
            pass

    async def on_llm_end(self, response, *, run_id, **kwargs):
        try:
            text, tokens = "", None
            try:
                gen = response.generations[0][0]
                text = getattr(gen, "text", "") or ""
                msg = getattr(gen, "message", None)
                usage = getattr(msg, "usage_metadata", None) if msg else None
                if usage:
                    tokens = usage.get("total_tokens")
                if tokens is None:
                    tokens = ((response.llm_output or {}).get("token_usage") or {}).get("total_tokens")
            except Exception:
                pass
            self._close(run_id, text, "ok", tokens)
        except Exception:
            pass

    async def on_llm_error(self, error, *, run_id, **kwargs):
        try:
            self._close(run_id, f"{type(error).__name__}: {error}", "error")
        except Exception:
            pass

    # ---- Tool ----
    async def on_tool_start(self, serialized, input_str, *, run_id, inputs=None, **kwargs):
        try:
            name = (serialized or {}).get("name") or kwargs.get("name") or "tool"
            self._open(run_id, "tool", name, inputs if inputs is not None else input_str)
        except Exception:
            pass

    async def on_tool_end(self, output, *, run_id, **kwargs):
        try:
            content = getattr(output, "content", output)
            self._close(run_id, content, "ok")
        except Exception:
            pass

    async def on_tool_error(self, error, *, run_id, **kwargs):
        try:
            self._close(run_id, f"{type(error).__name__}: {error}", "error")
        except Exception:
            pass

    def flush_pending(self):
        """运行结束（含中断/异常）时，把未配对的 start 事件落库为 running 状态。"""
        for lc_id in list(self._pending):
            p = self._pending.pop(lc_id)
            _insert_event(self.trace_run_id, p["seq"], p["etype"], p["name"], "running",
                          p["input"], "", None, p["started_at"],
                          int((time.time() - p["t0"]) * 1000))
