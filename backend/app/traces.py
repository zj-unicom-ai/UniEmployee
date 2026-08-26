"""执行过程追踪（Trace）：记录每次对话运行的 LLM 调用 / 工具调用 / 耗时 / 错误。

设计：
- 存储：独立 traces.db（runs 一次运行一行；events 运行内的每个步骤一行）。
- 捕获：TraceHandler（LangChain AsyncCallbackHandler）注入 agent 调用的
  config["callbacks"]，deepagents/LangGraph 内部所有模型调用与工具调用都会
  经过回调总线，无需改动 SSE 流式逻辑。
- 原则：追踪失败绝不影响正常对话（所有写库均吞异常），但必须记日志，
  避免追踪数据悄悄丢失而无人察觉。
"""
from __future__ import annotations

import json
import logging
import sqlite3
import time
import uuid
import datetime
from pathlib import Path
from typing import Any

from langchain_core.callbacks import AsyncCallbackHandler

from app import db as dblayer
from app.paths import db_path

ROOT = Path(__file__).resolve().parent.parent
DB = db_path("traces.db")

logger = logging.getLogger(__name__)

_PREVIEW = 2000  # 输入/输出留存的最大字符数


def _conn():
    if dblayer.is_pg():
        con = dblayer.connect("traces")
    else:
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
        logger.warning("trace start_run 写库失败 run_id=%s conv_id=%s", run_id, conv_id, exc_info=True)
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
        logger.warning("trace finish_run 更新失败 run_id=%s status=%s", run_id, status, exc_info=True)


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
        logger.warning("trace list_runs 查询失败 conv_id=%s", conv_id, exc_info=True)
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
        logger.warning("trace employee_of_conv 查询失败 conv_id=%s", conv_id, exc_info=True)
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
        logger.warning("trace get_run 查询失败 run_id=%s", run_id, exc_info=True)
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
        logger.warning("trace token_stats 查询失败", exc_info=True)
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
        logger.warning("trace _insert_event 写库失败 run_id=%s etype=%s name=%s",
                       run_id, etype, name, exc_info=True)


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
            logger.warning("trace on_chat_model_start 处理失败", exc_info=True)

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
            logger.warning("trace on_llm_end 处理失败", exc_info=True)

    async def on_llm_error(self, error, *, run_id, **kwargs):
        try:
            self._close(run_id, f"{type(error).__name__}: {error}", "error")
        except Exception:
            logger.warning("trace on_llm_error 处理失败", exc_info=True)

    # ---- Tool ----
    async def on_tool_start(self, serialized, input_str, *, run_id, inputs=None, **kwargs):
        try:
            name = (serialized or {}).get("name") or kwargs.get("name") or "tool"
            self._open(run_id, "tool", name, inputs if inputs is not None else input_str)
        except Exception:
            logger.warning("trace on_tool_start 处理失败", exc_info=True)

    async def on_tool_end(self, output, *, run_id, **kwargs):
        try:
            content = getattr(output, "content", output)
            self._close(run_id, content, "ok")
        except Exception:
            logger.warning("trace on_tool_end 处理失败", exc_info=True)

    async def on_tool_error(self, error, *, run_id, **kwargs):
        try:
            self._close(run_id, f"{type(error).__name__}: {error}", "error")
        except Exception:
            logger.warning("trace on_tool_error 处理失败", exc_info=True)

    def flush_pending(self):
        """运行结束（含中断/异常）时，把未配对的 start 事件落库为 running 状态。"""
        for lc_id in list(self._pending):
            p = self._pending.pop(lc_id)
            _insert_event(self.trace_run_id, p["seq"], p["etype"], p["name"], "running",
                          p["input"], "", None, p["started_at"],
                          int((time.time() - p["t0"]) * 1000))


# ── 运行评估（Evaluation）─────────────────────────────────────────────

def _ensure_evaluations_table():
    """首次写入时自动建表，避免每次读库都执行 DDL。"""
    con = _conn()
    con.execute("""CREATE TABLE IF NOT EXISTS evaluations(
        id           INTEGER PRIMARY KEY AUTOINCREMENT,
        run_id       TEXT,
        message_id   TEXT,
        employee_id  TEXT,
        conversation_id TEXT,
        user_id      TEXT,
        rating       INTEGER NOT NULL,    -- 1=👍  -1=👎
        reason       TEXT,
        created_at   TEXT
    )""")
    con.execute("CREATE INDEX IF NOT EXISTS idx_evals_emp ON evaluations(employee_id)")
    con.execute("CREATE INDEX IF NOT EXISTS idx_evals_run ON evaluations(run_id)")
    con.commit()
    con.close()


def insert_evaluation(run_id, message_id, employee_id, conversation_id,
                      user_id, rating, reason=""):
    """记录一条用户反馈评价。"""
    try:
        _ensure_evaluations_table()
        con = _conn()
        con.execute(
            "INSERT INTO evaluations(run_id,message_id,employee_id,conversation_id,user_id,rating,reason,created_at)"
            " VALUES(?,?,?,?,?,?,?,?)",
            (run_id, message_id, employee_id, conversation_id, user_id,
             rating, reason, datetime.datetime.now(datetime.timezone.utc).isoformat()),
        )
        con.commit()
        con.close()
    except Exception:
        logger.warning("insert_evaluation 失败", exc_info=True)


def get_evaluation_stats(employee_id=None, period="30d"):
    """返回聚合统计指标，供管理员评估页面使用。"""
    _ensure_evaluations_table()
    days = {"7d": 7, "30d": 30, "90d": 90}.get(period, 30)
    since = (datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(days=days)).isoformat()
    con = _conn()

    # runs 聚合
    where = "WHERE r.started_at >= ?"
    params: list[Any] = [since]
    if employee_id:
        where += " AND r.employee_id = ?"
        params.append(employee_id)
    row = con.execute(f"""
        SELECT COUNT(*) AS total_runs,
               AVG(r.duration_ms) AS avg_duration_ms,
               AVG(r.total_tokens) AS avg_tokens,
               SUM(CASE WHEN r.status='error' THEN 1 ELSE 0 END)*1.0 / MAX(COUNT(*),1) AS error_rate
        FROM runs r {where}
    """, params).fetchone()

    # 工具成功率
    tool_row = con.execute(f"""
        SELECT SUM(CASE WHEN e.status='ok' THEN 1 ELSE 0 END)*1.0 / MAX(SUM(CASE WHEN e.etype='tool' THEN 1 ELSE 0 END),1) AS tool_success_rate
        FROM events e JOIN runs r ON e.run_id=r.run_id {where}
    """, params).fetchone()

    # 用户满意度
    ewhere = "WHERE created_at >= ?"
    eparams: list[Any] = [since]
    if employee_id:
        ewhere += " AND employee_id = ?"
        eparams.append(employee_id)
    eval_row = con.execute(f"""
        SELECT COUNT(*) AS total,
               SUM(CASE WHEN rating=1 THEN 1 ELSE 0 END) AS thumbs_up,
               SUM(CASE WHEN rating=-1 THEN 1 ELSE 0 END) AS thumbs_down
        FROM evaluations {ewhere}
    """, eparams).fetchone()
    total = eval_row["total"] or 0
    thumbs_up = eval_row["thumbs_up"] or 0
    score = thumbs_up / total if total else 0.0

    # Top 工具
    tw = "WHERE e.etype='tool' AND e.status='ok' AND r.started_at >= ?"
    tparams: list[Any] = [since]
    if employee_id:
        tw += " AND r.employee_id = ?"
        tparams.append(employee_id)
    top_tools = [dict(r) for r in con.execute(f"""
        SELECT e.name, COUNT(*) AS count
        FROM events e JOIN runs r ON e.run_id=r.run_id
        {tw}
        GROUP BY e.name ORDER BY count DESC LIMIT 10
    """, tparams).fetchall()]

    # 日趋势
    daily_trend = [dict(r) for r in con.execute(f"""
        SELECT DATE(r.started_at) AS date,
               r.employee_id,
               COUNT(*) AS runs,
               AVG(r.duration_ms) AS avg_ms,
               SUM(CASE WHEN r.status='error' THEN 1 ELSE 0 END) AS errors
        FROM runs r {where}
        GROUP BY DATE(r.started_at), r.employee_id ORDER BY date
    """, params).fetchall()]

    con.close()
    return {
        "total_runs": row["total_runs"],
        "avg_duration_ms": row["avg_duration_ms"],
        "avg_tokens": row["avg_tokens"],
        "error_rate": row["error_rate"],
        "tool_success_rate": tool_row["tool_success_rate"],
        "satisfaction": {"total": total, "thumbs_up": thumbs_up,
                         "thumbs_down": eval_row["thumbs_down"] or 0, "score": score},
        "top_tools": top_tools,
        "daily_trend": daily_trend,
    }


def get_feedback_list(employee_id=None, rating=None, limit=50, offset=0):
    """返回用户反馈列表，支持按员工/评分筛选。"""
    _ensure_evaluations_table()
    where, params = "WHERE 1=1", []
    if employee_id:
        where += " AND employee_id = ?"
        params.append(employee_id)
    if rating is not None:
        where += " AND rating = ?"
        params.append(rating)
    con = _conn()
    rows = con.execute(f"""
        SELECT id,run_id,message_id,employee_id,conversation_id,user_id,rating,reason,created_at
        FROM evaluations {where} ORDER BY created_at DESC LIMIT ? OFFSET ?
    """, params + [limit, offset]).fetchall()
    con.close()
    return [dict(r) for r in rows]
