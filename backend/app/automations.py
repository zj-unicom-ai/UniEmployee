"""自动化任务：定时(cron) / 事件触发，自动起 run 并推送结果。

两类触发器统一为 automation 记录：
- cron : 5 字段 cron 表达式（服务器本地时间），调度器每 30s 扫描 next_fire_at 到期任务
- event: 外部系统 POST /api/automations/events/{event_key}（可配 secret 校验）

执行复用 streaming._stream_run——护栏、长期记忆、Trace 全走现有链路；
结果落会话（run_as 用户在会话历史/IM 频道可见），可选经频道
outbound_webhook 推送到外部 IM。

表结构与 channels 同库（conversations.db），双方言（sqlite/postgres）。
"""
import asyncio
import json
import logging
import os
import time
import uuid
from datetime import datetime, timedelta

import httpx

from app import conversations

log = logging.getLogger("app.automations")

_DDL = """
CREATE TABLE IF NOT EXISTS automations (
    id           TEXT PRIMARY KEY,
    name         TEXT NOT NULL,
    trigger_type TEXT NOT NULL DEFAULT 'cron',
    cron_expr    TEXT DEFAULT '',
    event_key    TEXT DEFAULT '',
    secret       TEXT DEFAULT '',
    employee_id  TEXT NOT NULL,
    prompt       TEXT NOT NULL,
    run_as       TEXT DEFAULT 'default',
    channel_id   TEXT DEFAULT '',
    enabled      INTEGER DEFAULT 1,
    next_fire_at TEXT,
    last_run_at  TEXT,
    last_status  TEXT DEFAULT '',
    last_error   TEXT DEFAULT '',
    last_conv_id TEXT,
    run_count    INTEGER DEFAULT 0,
    created_by   TEXT,
    created_at   TEXT,
    updated_at   TEXT
);
CREATE TABLE IF NOT EXISTS automation_executions (
    id              TEXT PRIMARY KEY,
    automation_id   TEXT NOT NULL,
    trigger_type    TEXT NOT NULL,
    trigger_key     TEXT NOT NULL,
    status          TEXT NOT NULL,
    conversation_id TEXT DEFAULT '',
    error           TEXT DEFAULT '',
    retry_of        TEXT DEFAULT '',
    created_at      TEXT NOT NULL,
    started_at      TEXT DEFAULT '',
    heartbeat_at    TEXT DEFAULT '',
    finished_at     TEXT DEFAULT '',
    UNIQUE (automation_id, trigger_type, trigger_key)
);
CREATE INDEX IF NOT EXISTS idx_auto_exec_created
    ON automation_executions(automation_id, created_at DESC);
"""

TS = "%Y-%m-%dT%H:%M"          # 触发点（分钟精度，字符串比较即时间比较）
TS_FULL = "%Y-%m-%dT%H:%M:%S"  # 记录时间戳


def _conn():
    """复用 conversations 的连接入口（同库；测试夹具 patch conversations.DB
    时自动跟随），再补建 automations 表。"""
    con = conversations._conn()
    con.executescript(_DDL)
    return con


# ---------------------------------------------------------------------------
# cron 解析（5 字段：分 时 日 月 周；支持 * / , - 与 7=周日）
# ---------------------------------------------------------------------------

def _parse_field(expr: str, lo: int, hi: int) -> set[int] | None:
    """单字段 -> 值集合；None 表示 '*'（任意值）。"""
    values: set[int] = set()
    for part in expr.strip().split(","):
        part = part.strip()
        if not part:
            raise ValueError(f"cron 字段含空段: {expr!r}")
        step = 1
        if "/" in part:
            part, step_s = part.split("/", 1)
            step = int(step_s)
            if step <= 0:
                raise ValueError(f"cron 步长必须为正: {expr!r}")
        if part == "*":
            if step == 1:
                return None
            values.update(range(lo, hi + 1, step))
            continue
        if "-" in part:
            a, b = part.split("-", 1)
            start, end = int(a), int(b)
            if not (lo <= start <= hi and lo <= end <= hi and start <= end):
                raise ValueError(f"cron 范围越界: {part!r}（允许 {lo}-{hi}）")
        else:
            start = end = int(part)
            if not (lo <= start <= hi):
                raise ValueError(f"cron 值越界: {part!r}（允许 {lo}-{hi}）")
        values.update(range(start, end + 1, step))
    if not values:
        raise ValueError(f"cron 字段无有效值: {expr!r}")
    return values


def parse_cron(expr: str):
    """解析 5 字段 cron 表达式，返回 (minute, hour, dom, month, dow)。"""
    fields = expr.split()
    if len(fields) != 5:
        raise ValueError("cron 表达式需要 5 个字段：分 时 日 月 周")
    dow = _parse_field(fields[4], 0, 7)
    if dow is not None:  # cron 里 7 也表示周日
        dow = {0 if v == 7 else v for v in dow}
    return (_parse_field(fields[0], 0, 59), _parse_field(fields[1], 0, 23),
            _parse_field(fields[2], 1, 31), _parse_field(fields[3], 1, 12), dow)


def cron_match(parsed, dt: datetime) -> bool:
    """判断 dt 是否命中 cron（标准语义：日与周都受限时取并集）。"""
    minute, hour, dom, month, dow = parsed
    if minute is not None and dt.minute not in minute:
        return False
    if hour is not None and dt.hour not in hour:
        return False
    if month is not None and dt.month not in month:
        return False
    dom_ok = dom is None or dt.day in dom
    dow_ok = dow is None or (dt.weekday() + 1) % 7 in dow  # 0=周日
    if dom is not None and dow is not None:
        return dom_ok or dow_ok
    return dom_ok and dow_ok


def next_fire(expr: str, after: datetime, max_minutes: int = 527040) -> datetime | None:
    """after 之后的下一个触发时间；一年内无匹配返回 None（如 2/30）。"""
    parsed = parse_cron(expr)
    t = after.replace(second=0, microsecond=0) + timedelta(minutes=1)
    for _ in range(max_minutes):
        if cron_match(parsed, t):
            return t
        t += timedelta(minutes=1)
    return None


def validate_cron(expr: str) -> str:
    """校验表达式并确认一年内有触发点，返回错误信息（空串=合法）。"""
    try:
        if next_fire(expr, datetime.now()) is None:
            return "该表达式一年内没有可触发的时间点"
        return ""
    except ValueError as e:
        return str(e)


# ---------------------------------------------------------------------------
# CRUD
# ---------------------------------------------------------------------------

def _row(r) -> dict:
    d = dict(r)
    d["enabled"] = bool(d.get("enabled"))
    return d


def create(name: str, trigger_type: str, employee_id: str, prompt: str,
           cron_expr: str = "", event_key: str = "", secret: str = "",
           run_as: str = "default", channel_id: str = "", enabled: bool = True,
           created_by: str = "") -> dict:
    aid = "auto_" + time.strftime("%Y%m%d%H%M%S") + str(time.time()).split(".")[1]
    now = time.strftime(TS_FULL)
    next_fire_at = None
    if trigger_type == "cron" and enabled:
        nxt = next_fire(cron_expr, datetime.now())
        next_fire_at = nxt.strftime(TS) if nxt else None
    with _conn() as con:
        con.execute(
            "INSERT INTO automations"
            "(id, name, trigger_type, cron_expr, event_key, secret, employee_id, prompt,"
            " run_as, channel_id, enabled, next_fire_at, created_by, created_at, updated_at) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (aid, name, trigger_type, cron_expr, event_key, secret, employee_id,
             prompt, run_as or "default", channel_id, 1 if enabled else 0,
             next_fire_at, created_by, now, now))
        con.commit()
    return get(aid) or {}


def update(aid: str, **fields) -> dict | None:
    """局部更新；cron 字段变化时重算 next_fire_at。"""
    auto = get(aid)
    if not auto:
        return None
    merged = {**auto, **{k: v for k, v in fields.items() if v is not None}}
    now = time.strftime(TS_FULL)
    next_fire_at = auto.get("next_fire_at")
    if merged["trigger_type"] == "cron":
        if merged["enabled"]:
            nxt = next_fire(merged["cron_expr"], datetime.now())
            next_fire_at = nxt.strftime(TS) if nxt else None
        else:
            next_fire_at = None
    with _conn() as con:
        con.execute(
            "UPDATE automations SET name=?, trigger_type=?, cron_expr=?, event_key=?,"
            " secret=?, employee_id=?, prompt=?, run_as=?, channel_id=?, enabled=?,"
            " next_fire_at=?, updated_at=? WHERE id=?",
            (merged["name"], merged["trigger_type"], merged["cron_expr"],
             merged["event_key"], merged["secret"], merged["employee_id"],
             merged["prompt"], merged["run_as"] or "default", merged["channel_id"],
             1 if merged["enabled"] else 0, next_fire_at, now, aid))
        con.commit()
    return get(aid)


def delete(aid: str) -> bool:
    with _conn() as con:
        cur = con.execute("DELETE FROM automations WHERE id=?", (aid,))
        ok = cur.rowcount > 0
        con.commit()
    return ok


def get(aid: str) -> dict | None:
    with _conn() as con:
        r = con.execute("SELECT * FROM automations WHERE id=?", (aid,)).fetchone()
    return _row(r) if r else None


def list_all() -> list[dict]:
    with _conn() as con:
        rows = con.execute(
            "SELECT * FROM automations ORDER BY created_at DESC, id DESC").fetchall()
    return [_row(r) for r in rows]


def list_by_event(event_key: str) -> list[dict]:
    with _conn() as con:
        rows = con.execute(
            "SELECT * FROM automations WHERE trigger_type='event' AND enabled=1 "
            "AND event_key=?", (event_key,)).fetchall()
    return [_row(r) for r in rows]


def due_crons(now_minute: str) -> list[dict]:
    """到期（next_fire_at <= now）且启用的 cron 任务。"""
    with _conn() as con:
        rows = con.execute(
            "SELECT * FROM automations WHERE trigger_type='cron' AND enabled=1 "
            "AND next_fire_at IS NOT NULL AND next_fire_at<=? ORDER BY next_fire_at",
            (now_minute,)).fetchall()
    return [_row(r) for r in rows]


def claim_next(aid: str, expected_next: str, new_next: str | None) -> bool:
    """CAS 抢占触发点：多实例/慢执行重入时只有一个赢家。"""
    with _conn() as con:
        cur = con.execute(
            "UPDATE automations SET next_fire_at=?, last_status='running', updated_at=? "
            "WHERE id=? AND next_fire_at=?",
            (new_next, time.strftime(TS_FULL), aid, expected_next))
        ok = cur.rowcount > 0
        con.commit()
    return ok


def mark_result(aid: str, status: str, error: str = "", conv_id: str = "") -> None:
    with _conn() as con:
        con.execute(
            "UPDATE automations SET last_run_at=?, last_status=?, last_error=?,"
            " last_conv_id=?, run_count=run_count+1, updated_at=? WHERE id=?",
            (time.strftime(TS_FULL), status, error[:500], conv_id,
             time.strftime(TS_FULL), aid))
        con.commit()


def create_execution(aid: str, trigger: str, trigger_key: str,
                     retry_of: str = "") -> tuple[dict, bool]:
    """创建执行记录；唯一键冲突表示重复投递，返回旧记录且不重复执行。"""
    execution_id = "aex_" + uuid.uuid4().hex
    now = time.strftime(TS_FULL)
    with _conn() as con:
        con.execute(
            "INSERT INTO automation_executions"
            "(id, automation_id, trigger_type, trigger_key, status, retry_of, created_at) "
            "VALUES (?,?,?,?,?,?,?) ON CONFLICT (automation_id, trigger_type, trigger_key) DO NOTHING",
            (execution_id, aid, trigger, trigger_key, "queued", retry_of, now))
        con.commit()
        row = con.execute(
            "SELECT * FROM automation_executions WHERE automation_id=? AND trigger_type=? AND trigger_key=?",
            (aid, trigger, trigger_key)).fetchone()
    result = dict(row)
    return result, result["id"] == execution_id


def update_execution(execution_id: str, status: str, *, conv_id: str = "",
                     error: str = "", finished: bool = False) -> None:
    now = time.strftime(TS_FULL)
    with _conn() as con:
        con.execute(
            "UPDATE automation_executions SET status=?, conversation_id=CASE WHEN ?='' THEN conversation_id ELSE ? END,"
            " error=?, started_at=CASE WHEN ?='running' AND started_at='' THEN ? ELSE started_at END,"
            " heartbeat_at=?, finished_at=CASE WHEN ?=1 THEN ? ELSE finished_at END WHERE id=?",
            (status, conv_id, conv_id, error[:1000], status, now, now,
             1 if finished else 0, now, execution_id))
        con.commit()


def get_execution(execution_id: str) -> dict | None:
    with _conn() as con:
        row = con.execute("SELECT * FROM automation_executions WHERE id=?", (execution_id,)).fetchone()
    return dict(row) if row else None


def list_executions(aid: str, limit: int = 50) -> list[dict]:
    with _conn() as con:
        rows = con.execute(
            "SELECT * FROM automation_executions WHERE automation_id=? ORDER BY created_at DESC, id DESC LIMIT ?",
            (aid, max(1, min(int(limit), 200)))).fetchall()
    return [dict(row) for row in rows]


def recover_stale_executions(max_age_seconds: int = 120) -> int:
    """把心跳过期的 queued/running 标成 interrupted，供人工判断后重跑。"""
    cutoff = datetime.now() - timedelta(seconds=max_age_seconds)
    stamp = cutoff.strftime(TS_FULL)
    now = time.strftime(TS_FULL)
    with _conn() as con:
        cur = con.execute(
            "UPDATE automation_executions SET status='interrupted', error='执行进程心跳超时；请检查会话后人工重跑', finished_at=? "
            "WHERE status IN ('queued','running') AND COALESCE(NULLIF(heartbeat_at,''), created_at)<?",
            (now, stamp))
        con.commit()
    return cur.rowcount


def purge_executions(retention_days: int | None = None) -> int:
    days = retention_days if retention_days is not None else int(os.environ.get("AUTOMATION_EXECUTION_RETENTION_DAYS", "90"))
    if days < 1:
        raise ValueError("自动化执行记录保留期限至少为 1 天")
    cutoff = (datetime.now() - timedelta(days=days)).strftime(TS_FULL)
    with _conn() as con:
        cur = con.execute(
            "DELETE FROM automation_executions WHERE status NOT IN ('queued','running') AND created_at<?",
            (cutoff,))
        con.commit()
    return cur.rowcount


async def _execution_heartbeat(execution_id: str) -> None:
    while True:
        await asyncio.sleep(20)
        update_execution(execution_id, "running")


# ---------------------------------------------------------------------------
# 市场情报员工 V2 值守种子任务（幂等，默认停用——管理员在自动化任务页开启）
# ---------------------------------------------------------------------------

AUTOMATION_SEEDS = [
    {
        "id": "auto_seed_market_daily_brief",
        "name": "每日市场简报（小察）",
        "trigger_type": "cron",
        "cron_expr": "30 8 * * 1-5",
        "event_key": "",
        "secret": "",
        # 无人值守提示词：直接按默认监测范围执行，收尾必须走发布审批
        "prompt": ("【自动化值守】现在是 {{now}}。请按 market-daily-brief 技能规程"
                   "生成今日市场简报看板：完整执行采集→筛选→成文流程，"
                   "不要向用户提问（无人值守，直接按默认监测范围执行），"
                   "完成后调用 publish_briefing 提交发布审批。"),
        "run_as": "u_admin",
        "channel_id": "",
    },
    {
        "id": "auto_seed_market_alert_event",
        "name": "市场信号预警研判（小察）",
        "trigger_type": "event",
        "cron_expr": "",
        "event_key": "market-signal",
        "secret": "",
        "prompt": ("【自动化值守】收到外部市场信号，请按 market-alert-triage 技能规程"
                   "先核实后分级，产出预警简卡（无人值守，检索不到佐证时如实标注），"
                   "信号内容如下：\n{{payload}}"),
        "run_as": "u_admin",
        "channel_id": "",
    },
]


def backfill_seeds():
    """幂等补种市场情报员工的值守任务模板（仅缺行时插入，默认停用）。

    不覆盖已有行：管理员开启/修改后重启不会被种子重置。默认 enabled=0，
    避免部署即开始消耗模型调用；启用与调度（含审批流）在自动化任务页完成。"""
    now = time.strftime(TS_FULL)
    with _conn() as con:
        for s in AUTOMATION_SEEDS:
            con.execute(
                "INSERT OR IGNORE INTO automations"
                "(id, name, trigger_type, cron_expr, event_key, secret, employee_id,"
                " prompt, run_as, channel_id, enabled, next_fire_at, created_by,"
                " created_at, updated_at) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,0,NULL,'seed',?,?)",
                (s["id"], s["name"], s["trigger_type"], s["cron_expr"], s["event_key"],
                 s["secret"], "market-intel", s["prompt"], s["run_as"], s["channel_id"],
                 now, now))
        con.commit()


# ---------------------------------------------------------------------------
# 执行引擎：复用 _stream_run，结果落会话 + 可选推送
# ---------------------------------------------------------------------------

def render_prompt(template: str, payload=None) -> str:
    """模板渲染：{{now}} 当前时间；{{payload}} 事件数据（JSON）。"""
    out = template.replace("{{now}}", time.strftime("%Y-%m-%d %H:%M:%S"))
    if payload is not None:
        blob = json.dumps(payload, ensure_ascii=False)
        if "{{payload}}" in out:
            out = out.replace("{{payload}}", blob)
        else:  # 模板没占位但事件带了数据：附加在尾部，保证员工能看到
            out = f"{out}\n\n[事件数据]\n{blob}"
    return out


async def _push(channel: dict, conv_id: str, reply: str) -> None:
    cfg = channel.get("config") or {}
    url = cfg.get("outbound_webhook")
    if not url or not reply:
        return
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            await client.post(url, json={
                "conversation_id": conv_id,
                "channel_id": channel["id"],
                "message": reply,
            })
    except Exception:
        log.warning("自动任务结果推送失败 channel=%s", channel.get("id"), exc_info=True)


async def execute(auto: dict, payload=None, trigger: str = "cron",
                  trigger_key: str | None = None, retry_of: str = "",
                  execution_id: str | None = None) -> dict:
    """执行一次自动任务，并用触发键保证重试请求幂等。"""
    from app.streaming import _stream_run  # 延迟导入避免环

    trigger_key = str(uuid.uuid4()) if trigger_key is None else str(trigger_key)
    if execution_id:
        execution = get_execution(execution_id)
        if (not execution or execution["automation_id"] != auto["id"]
                or execution["trigger_type"] != trigger or execution["trigger_key"] != trigger_key
                or execution["status"] != "queued"):
            raise ValueError("预创建的自动化执行记录与本次触发不匹配")
        created = True
    else:
        execution, created = create_execution(auto["id"], trigger, trigger_key, retry_of)
    if not created:
        return {"execution_id": execution["id"], "conversation_id": execution["conversation_id"],
                "status": execution["status"], "error": execution["error"],
                "duplicate": True, "approval_id": "", "reply": ""}

    emp_id = auto["employee_id"]
    user_id = auto.get("run_as") or "default"
    prompt = render_prompt(auto["prompt"], payload)
    suffix = time.strftime("%Y%m%d%H%M%S") + str(time.time()).split(".")[1]
    conv_id = f"c_auto_{auto['id']}_{suffix}"
    channel = conversations.get_channel(auto["channel_id"]) if auto.get("channel_id") else None

    conversations.create(conv_id, emp_id, user_id=user_id,
                         channel_id=auto.get("channel_id") or None,
                         title=f"[自动] {auto['name']}"[:40],
                         preview=prompt[:60], count=1)
    update_execution(execution["id"], "running", conv_id=conv_id)
    heartbeat = asyncio.create_task(_execution_heartbeat(execution["id"]))
    input_ = {"messages": [{"role": "user", "content": prompt}]}
    parts: list[str] = []
    status, error = "ok", ""
    approval_id = ""
    try:
        async for raw in _stream_run(conv_id, input_, user_id=user_id, role="user"):
            if not raw.startswith("data: "):
                continue
            try:
                ev = json.loads(raw[len("data: "):])
            except Exception:
                continue
            if ev.get("type") == "token":
                parts.append(ev.get("content", ""))
            elif ev.get("type") == "error":
                status, error = "error", ev.get("message", "任务执行出错")
            elif ev.get("type") == "approval_required":
                status = "awaiting_approval"
                approval_id = ev.get("approval_id", "")
                error = f"等待人工审批：{approval_id}" if approval_id else "等待人工审批"
                break
    except Exception as e:
        status, error = "error", f"{type(e).__name__}: {e}"
        log.exception("自动任务执行异常 id=%s", auto["id"])
    finally:
        heartbeat.cancel()
        await asyncio.gather(heartbeat, return_exceptions=True)

    reply = "".join(parts).strip()
    mark_result(auto["id"], status, error, conv_id)
    update_execution(execution["id"], status, conv_id=conv_id, error=error, finished=True)
    if reply:
        conversations.touch(conv_id, preview=reply[:60], bump=1)
    if channel and status == "ok":
        await _push(channel, conv_id, reply)
    return {"execution_id": execution["id"], "conversation_id": conv_id, "status": status, "error": error,
            "reply": reply, "approval_id": approval_id}
