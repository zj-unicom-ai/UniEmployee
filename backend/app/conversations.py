"""会话元数据库（独立于 LangGraph checkpointer）。

checkpointer（checkpoints.db）负责"对话状态本身"（消息、工具调用中间态），
本模块负责"会话的清单信息"：标题、预览、归属员工、时间戳、消息数——
也就是前端"历史对话"侧栏要展示的元数据。

两者通过 conversation_id（= checkpointer 的 thread_id）关联。
本库用独立 sqlite 文件，避免与 LangGraph 的 checkpointer 并发读写相互干扰。
"""
import json
import sqlite3
import time
from pathlib import Path

from app.paths import db_path

ROOT = Path(__file__).resolve().parent.parent
DB = db_path("conversations.db")


def _conn():
    con = sqlite3.connect(str(DB))
    con.row_factory = sqlite3.Row
    con.execute(
        """CREATE TABLE IF NOT EXISTS conversations (
            conv_id      TEXT PRIMARY KEY,
            employee_id TEXT NOT NULL,
            user_id      TEXT DEFAULT 'default',
            channel_id   TEXT,
            title        TEXT DEFAULT '',
            preview      TEXT DEFAULT '',
            message_count INTEGER DEFAULT 0,
            created_at   TEXT,
            updated_at   TEXT
        )"""
    )
    con.execute(
        """CREATE TABLE IF NOT EXISTS channels (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            description TEXT DEFAULT '',
            kind TEXT DEFAULT 'web',
            provider TEXT DEFAULT 'web',
            config TEXT DEFAULT '{}',
            enabled INTEGER DEFAULT 1,
            status TEXT DEFAULT 'active',
            created_by TEXT,
            created_at TEXT,
            updated_at TEXT
        )"""
    )
    con.execute(
        """CREATE TABLE IF NOT EXISTS channel_members (
            channel_id TEXT NOT NULL,
            employee_id TEXT NOT NULL,
            is_default INTEGER DEFAULT 0,
            sort_order INTEGER DEFAULT 0,
            PRIMARY KEY(channel_id, employee_id)
        )"""
    )
    # 老库迁移：补 user_id 列
    cols = [r[1] for r in con.execute("PRAGMA table_info(conversations)")]
    if "user_id" not in cols:
        con.execute("ALTER TABLE conversations ADD COLUMN user_id TEXT DEFAULT 'default'")
    if "channel_id" not in cols:
        con.execute("ALTER TABLE conversations ADD COLUMN channel_id TEXT")
    # 软删迁移：补 deleted_at 列（NULL=未删除）
    if "deleted_at" not in cols:
        con.execute("ALTER TABLE conversations ADD COLUMN deleted_at TEXT")
    # IM 频道配置迁移：provider / config / enabled
    ch_cols = [r[1] for r in con.execute("PRAGMA table_info(channels)")]
    if "provider" not in ch_cols:
        con.execute("ALTER TABLE channels ADD COLUMN provider TEXT DEFAULT 'web'")
    if "config" not in ch_cols:
        con.execute("ALTER TABLE channels ADD COLUMN config TEXT DEFAULT '{}'")
    if "enabled" not in ch_cols:
        con.execute("ALTER TABLE channels ADD COLUMN enabled INTEGER DEFAULT 1")
    return con


def _channel_row(row) -> dict:
    d = dict(row)
    try:
        d["config"] = json.loads(d.get("config") or "{}") or {}
    except Exception:
        d["config"] = {}
    d["enabled"] = bool(d.get("enabled"))
    return d


def create(conv_id: str, employee_id: str, title: str = "", preview: str = "",
           count: int = 0, user_id: str = "default", channel_id: str | None = None):
    now = time.strftime("%Y-%m-%dT%H:%M:%S")
    with _conn() as con:
        con.execute(
            "INSERT INTO conversations "
            "(conv_id, employee_id, user_id, channel_id, title, preview, message_count, created_at, updated_at) "
            "VALUES (?,?,?,?,?,?,?,?,?) "
            "ON CONFLICT(conv_id) DO UPDATE SET deleted_at=NULL, updated_at=excluded.updated_at",
            (conv_id, employee_id, user_id, channel_id, title, preview, count, now, now),
        )


def exists(conv_id: str) -> bool:
    with _conn() as con:
        return con.execute("SELECT 1 FROM conversations WHERE conv_id=? AND deleted_at IS NULL", (conv_id,)).fetchone() is not None


def touch(conv_id: str, *, title: str | None = None, preview: str | None = None, bump: int = 0):
    """更新会话清单。title 仅在当前为空时写入（首条消息定标题，后续不覆盖）。"""
    now = time.strftime("%Y-%m-%dT%H:%M:%S")
    with _conn() as con:
        if title is not None:
            con.execute(
                "UPDATE conversations SET title=?, updated_at=? "
                "WHERE conv_id=? AND (title='' OR title IS NULL)",
                (title, now, conv_id),
            )
        if preview is not None:
            con.execute(
                "UPDATE conversations SET preview=?, updated_at=? WHERE conv_id=?",
                (preview, now, conv_id),
            )
        if bump:
            con.execute(
                "UPDATE conversations SET message_count=message_count+?, updated_at=? WHERE conv_id=?",
                (bump, now, conv_id),
            )


def _where(employee_id=None, user_id=None, channel_id=None, exclude_channel=False):
    sql = "WHERE deleted_at IS NULL"; params = []
    if employee_id: sql += " AND employee_id=?"; params.append(employee_id)
    if user_id: sql += " AND user_id=?"; params.append(user_id)
    if channel_id: sql += " AND channel_id=?"; params.append(channel_id)
    if exclude_channel: sql += " AND (channel_id IS NULL OR channel_id='')"
    return sql, params


def list_for(employee_id: str | None = None, user_id: str | None = None,
             limit: int | None = None) -> list[dict]:
    """会话清单（按员工/用户过滤；limit 限制条数，用于侧栏最近会话）。"""
    with _conn() as con:
        wh, params = _where(employee_id, user_id, exclude_channel=True)
        sql = f"SELECT * FROM conversations {wh} ORDER BY updated_at DESC, created_at DESC, conv_id DESC"
        if limit:
            sql += " LIMIT ?"; params.append(limit)
        rows = con.execute(sql, params).fetchall()
    return [dict(r) for r in rows]


def list_for_channel(channel_id: str, user_id: str | None = None,
                     limit: int | None = None) -> list[dict]:
    """频道会话清单：只返回某个频道下的会话。"""
    with _conn() as con:
        wh, params = _where(channel_id=channel_id, user_id=user_id)
        sql = f"SELECT * FROM conversations {wh} ORDER BY updated_at DESC, created_at DESC, conv_id DESC"
        if limit:
            sql += " LIMIT ?"; params.append(limit)
        rows = con.execute(sql, params).fetchall()
    return [dict(r) for r in rows]


def list_paged(employee_id: str | None = None, user_id: str | None = None,
               page: int = 1, page_size: int = 10) -> dict:
    """分页会话清单，返回 {items, total, page, page_size}。"""
    page = max(1, page)
    with _conn() as con:
        sql, params = _where(employee_id, user_id, exclude_channel=True)
        total = con.execute(f"SELECT COUNT(*) FROM conversations {sql}", params).fetchone()[0]
        full = f"SELECT * FROM conversations {sql} ORDER BY updated_at DESC, created_at DESC, conv_id DESC LIMIT ? OFFSET ?"
        rows = con.execute(full, params + [page_size, (page - 1) * page_size]).fetchall()
    return {"items": [dict(r) for r in rows], "total": total,
            "page": page, "page_size": page_size, "pages": (total + page_size - 1) // page_size}


def set_title(conv_id: str, title: str):
    """强制更新会话标题（用于 AI 提炼标题覆盖首句截断）。"""
    now = time.strftime("%Y-%m-%dT%H:%M:%S")
    with _conn() as con:
        con.execute("UPDATE conversations SET title=?, updated_at=? WHERE conv_id=?",
                    (title[:40], now, conv_id))


def claim(conv_id: str, user_id: str):
    """把历史遗留的 default 归属会话认领为某个用户（首条消息时调用）。"""
    with _conn() as con:
        con.execute(
            "UPDATE conversations SET user_id=? "
            "WHERE conv_id=? AND user_id='default' AND deleted_at IS NULL",
            (user_id, conv_id))


def get(conv_id: str) -> dict | None:
    with _conn() as con:
        r = con.execute("SELECT * FROM conversations WHERE conv_id=? AND deleted_at IS NULL", (conv_id,)).fetchone()
    return dict(r) if r else None


def delete(conv_id: str) -> bool:
    """软删会话元数据（deleted_at 标记，记录与对话正文均保留）。返回是否有行受影响。"""
    now = time.strftime("%Y-%m-%dT%H:%M:%S")
    with _conn() as con:
        cur = con.cursor()
        cur.execute(
            "UPDATE conversations SET deleted_at=? WHERE conv_id=? AND deleted_at IS NULL",
            (now, conv_id))
        ok = cur.rowcount > 0
        con.commit()
    return ok


def create_channel(name: str, description: str = "", kind: str = "web",
                   provider: str | None = None, config: dict | None = None,
                   enabled: bool = True, status: str = "active",
                   created_by: str = "admin", employee_ids: list[str] | None = None) -> dict:
    """创建一个 IM 频道，并可选地挂载员工。"""
    cid = "chan_" + time.strftime("%Y%m%d%H%M%S") + str(time.time()).split(".")[1]
    now = time.strftime("%Y-%m-%dT%H:%M:%S")
    provider = provider or kind or "web"
    config_json = json.dumps(config or {}, ensure_ascii=False)
    with _conn() as con:
        con.execute(
            "INSERT INTO channels(id, name, description, kind, provider, config, enabled, status, created_by, created_at, updated_at) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            (cid, name, description, kind, provider, config_json, 1 if enabled else 0,
             status, created_by, now, now),
        )
        for idx, emp_id in enumerate(employee_ids or []):
            con.execute(
                "INSERT OR IGNORE INTO channel_members"
                "(channel_id, employee_id, is_default, sort_order) VALUES (?,?,?,?)",
                (cid, emp_id, 1 if idx == 0 else 0, idx),
            )
    return get_channel(cid) or {"id": cid, "name": name, "description": description,
                                "kind": kind, "provider": provider, "config": config or {},
                                "enabled": enabled}


def ensure_default_channel(employee_ids: list[str] | None = None) -> dict | None:
    """启动时确保至少有一个 Web IM 频道，避免 IM 页面无可选频道。"""
    rows = list_channels()
    if rows:
        return rows[0]
    return create_channel(
        "全员频道",
        description="默认 Web IM 频道，可挂载全部数字员工",
        kind="web",
        employee_ids=employee_ids or [],
    )


def get_channel(channel_id: str) -> dict | None:
    with _conn() as con:
        r = con.execute(
            "SELECT * FROM channels WHERE id=? AND status='active'",
            (channel_id,),
        ).fetchone()
    return _channel_row(r) if r else None


def list_channels() -> list[dict]:
    with _conn() as con:
        rows = con.execute(
            "SELECT * FROM channels WHERE status='active' ORDER BY created_at, id"
        ).fetchall()
    return [_channel_row(r) for r in rows]


def update_channel(channel_id: str, *, name: str | None = None,
                   description: str | None = None, kind: str | None = None,
                   provider: str | None = None, config: dict | None = None,
                   enabled: bool | None = None, status: str | None = None,
                   employee_ids: list[str] | None = None) -> dict | None:
    """更新 IM 频道；employee_ids 传入时整组替换频道挂载的员工。"""
    now = time.strftime("%Y-%m-%dT%H:%M:%S")
    with _conn() as con:
        fields = ["updated_at=?"]
        params: list = [now]
        row = con.execute("SELECT * FROM channels WHERE id=?", (channel_id,)).fetchone()
        cur = dict(row) if row else {}
        if not cur:
            return None
        if name is not None:
            fields.append("name=?"); params.append(name)
        if description is not None:
            fields.append("description=?"); params.append(description)
        if kind is not None:
            fields.append("kind=?"); params.append(kind)
        if provider is not None:
            fields.append("provider=?"); params.append(provider)
        if config is not None:
            fields.append("config=?"); params.append(json.dumps(config, ensure_ascii=False))
        if enabled is not None:
            fields.append("enabled=?"); params.append(1 if enabled else 0)
        if status is not None:
            fields.append("status=?"); params.append(status)
        params.append(channel_id)
        con.execute(f"UPDATE channels SET {', '.join(fields)} WHERE id=?", params)
        if employee_ids is not None:
            con.execute("DELETE FROM channel_members WHERE channel_id=?", (channel_id,))
            for idx, emp_id in enumerate(employee_ids):
                con.execute(
                    "INSERT OR IGNORE INTO channel_members"
                    "(channel_id, employee_id, is_default, sort_order) VALUES (?,?,?,?)",
                    (channel_id, emp_id, 1 if idx == 0 else 0, idx),
                )
    return get_channel(channel_id)


def delete_channel(channel_id: str) -> bool:
    """软删除 IM 频道：status 置为 disabled。"""
    now = time.strftime("%Y-%m-%dT%H:%M:%S")
    with _conn() as con:
        cur = con.execute(
            "UPDATE channels SET status='disabled', updated_at=? WHERE id=? AND status='active'",
            (now, channel_id),
        )
        return cur.rowcount > 0


def find_channel_conversation(channel_id: str, user_id: str,
                              employee_id: str | None = None) -> dict | None:
    """取某个外部用户在指定频道里最近的会话（按员工可再过滤）。"""
    with _conn() as con:
        sql = ("SELECT * FROM conversations WHERE channel_id=? AND user_id=? "
               "AND deleted_at IS NULL")
        params: list = [channel_id, user_id]
        if employee_id:
            sql += " AND employee_id=?"
            params.append(employee_id)
        sql += " ORDER BY updated_at DESC, created_at DESC, conv_id DESC LIMIT 1"
        r = con.execute(sql, params).fetchone()
    return dict(r) if r else None


def add_channel_member(channel_id: str, employee_id: str,
                       is_default: bool = False, sort_order: int = 0) -> None:
    with _conn() as con:
        con.execute(
            "INSERT OR IGNORE INTO channel_members"
            "(channel_id, employee_id, is_default, sort_order) VALUES (?,?,?,?)",
            (channel_id, employee_id, 1 if is_default else 0, sort_order),
        )


def list_channel_members(channel_id: str) -> list[dict]:
    with _conn() as con:
        rows = con.execute(
            "SELECT * FROM channel_members WHERE channel_id=? ORDER BY sort_order, employee_id",
            (channel_id,),
        ).fetchall()
    return [dict(r) for r in rows]


def list_employee_ids_for_channel(channel_id: str) -> list[str]:
    return [r["employee_id"] for r in list_channel_members(channel_id)]


def all_conv_ids() -> list[str]:
    with _conn() as con:
        return [r[0] for r in con.execute("SELECT conv_id FROM conversations").fetchall()]
