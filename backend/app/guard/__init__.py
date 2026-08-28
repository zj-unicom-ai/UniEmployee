"""安全护栏：敏感词过滤 + 工具调用白名单，配置与拦截日志落 catalog 库。

设计：
- guard_settings 表：key-value 配置（开关/白名单），管理端可热改
- sensitive_words 表：敏感词库（分类/等级，首期统一硬拦截）
- guard_logs 表：拦截/命中记录，供审计页查询
- 输入硬拦截在 streaming 入口（不进模型）；输出检测在流结束后（记录+截断标记）

工具白名单：admin 配置「仅管理员可调用」的工具名列表；普通用户（role != admin）
的员工运行时若调用这些工具，直接抛权限错误并记录日志。admin 角色不受限。
"""
import json
import time

from .db import _conn, init_tables  # noqa: F401  init_tables 随 catalog.init() 调用

# ---- 配置读写 ----

DEFAULTS = {
    # 敏感词过滤总开关（输入拦截 + 输出检测）
    "sensitive_enabled": "1",
    # 工具白名单：逗号分隔的工具名，普通用户不可调用；空 = 不限制
    "admin_only_tools": "ontology_save_entity,ontology_link_entities",
}


def get_setting(key: str, default: str = "") -> str:
    con = _conn()
    r = con.execute("SELECT value FROM guard_settings WHERE key=?", (key,)).fetchone()
    con.close()
    return (r["value"] if r else None) or default


def set_setting(key: str, value: str):
    con = _conn()
    con.execute(
        "INSERT INTO guard_settings(key,value,updated_at) VALUES(?,?,?) "
        "ON CONFLICT(key) DO UPDATE SET value=excluded.value, updated_at=excluded.updated_at",
        (key, value, time.strftime("%Y-%m-%d %H:%M:%S")))
    con.commit()
    con.close()


def get_settings() -> dict:
    return {k: get_setting(k, v) for k, v in DEFAULTS.items()}


# ---- 敏感词 ----

def list_words() -> list[dict]:
    con = _conn()
    rows = con.execute(
        "SELECT id, word, category, level, created_at FROM sensitive_words "
        "WHERE deleted_at IS NULL ORDER BY id DESC").fetchall()
    con.close()
    return [dict(r) for r in rows]


def add_word(word: str, category: str = "", level: str = "block") -> dict:
    word = (word or "").strip()
    con = _conn()
    cur = con.cursor()
    cur.execute(
        "INSERT INTO sensitive_words(word,category,level,created_at) VALUES(?,?,?,?) "
        "ON CONFLICT(word) DO UPDATE SET deleted_at=NULL, category=excluded.category",
        (word, category, level, time.strftime("%Y-%m-%d %H:%M:%S")))
    con.commit()
    row = cur.execute("SELECT * FROM sensitive_words WHERE word=?", (word,)).fetchone()
    con.close()
    return dict(row)


def delete_word(word_id: int):
    con = _conn()
    con.execute("UPDATE sensitive_words SET deleted_at=? WHERE id=?",
                (time.strftime("%Y-%m-%d %H:%M:%S"), word_id))
    con.commit()
    con.close()


def check_text(text: str) -> dict | None:
    """命中敏感词则返回 {word, category}，否则 None。大文本走逐词 contains。"""
    if not text:
        return None
    con = _conn()
    rows = con.execute(
        "SELECT word, category FROM sensitive_words WHERE deleted_at IS NULL").fetchall()
    con.close()
    for r in rows:
        if r["word"] and r["word"] in text:
            return {"word": r["word"], "category": r["category"]}
    return None


# ---- 工具白名单 ----

def admin_only_tool_set() -> set[str]:
    raw = get_setting("admin_only_tools", DEFAULTS["admin_only_tools"])
    return {x.strip() for x in raw.split(",") if x.strip()}


def tool_allowed(tool_name: str, role: str) -> bool:
    if role == "admin":
        return True
    return tool_name not in admin_only_tool_set()


# ---- 拦截日志 ----

def log(event_type: str, detail: str, user_id: str = "", employee_id: str = "",
        conversation_id: str = "", extra: dict | None = None):
    con = _conn()
    con.execute(
        "INSERT INTO guard_logs(event_type,detail,user_id,employee_id,conversation_id,extra,created_at) "
        "VALUES(?,?,?,?,?,?,?)",
        (event_type, detail, user_id, employee_id, conversation_id,
         json.dumps(extra, ensure_ascii=False) if extra else None,
         time.strftime("%Y-%m-%d %H:%M:%S")))
    con.commit()
    con.close()


def list_logs(limit: int = 100, event_type: str = "") -> list[dict]:
    con = _conn()
    if event_type:
        rows = con.execute(
            "SELECT * FROM guard_logs WHERE event_type=? ORDER BY id DESC LIMIT ?",
            (event_type, limit)).fetchall()
    else:
        rows = con.execute(
            "SELECT * FROM guard_logs ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
    con.close()
    return [dict(r) for r in rows]
