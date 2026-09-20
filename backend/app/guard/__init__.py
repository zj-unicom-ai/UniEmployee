"""安全护栏：敏感词过滤 + 工具调用白名单，配置与拦截日志落 catalog 库。

设计：
- guard_settings 表：key-value 配置（开关/白名单），管理端可热改
- sensitive_words 表：敏感词库（分类/等级，首期统一硬拦截）
- guard_logs 表：拦截/命中记录，供审计页查询
- 输入硬拦截在 streaming 入口（不进模型）；输出检测在流结束后（记录+截断标记）

工具能力策略：admin 配置 allow/deny 列表；普通用户（role != admin）的员工运行时
若命中 deny 或未命中显式 allow，直接抛权限错误并记录日志。admin 角色不受限。
"""
import fnmatch
import json
import time

from .db import _conn, init_tables  # noqa: F401  init_tables 随 catalog.init() 调用

# ---- 配置读写 ----

DEFAULTS = {
    # 敏感词过滤总开关（输入拦截 + 输出检测）
    "sensitive_enabled": "1",
    # 工具白名单：逗号分隔的工具名，普通用户不可调用；空 = 不限制
    "admin_only_tools": "ontology_save_entity,ontology_link_entities",
    # 普通用户的全局允许列表；空表示沿用员工/连接器自身的授权配置
    "tool_allowlist": "",
    # 普通用户的全局拒绝列表；deny 优先于 allow，支持 * 通配符
    "tool_denylist": "",
    # 未绑定连接器来源的 MCP 工具默认拒绝；已绑定连接器的工具自动放行
    # （仍受 tool_allowlist / tool_denylist 约束）。mcp_allowlist 保留给
    # 直接注入、无法关联到连接器的 MCP 工具使用。
    "mcp_default_deny": "1",
    "mcp_allowlist": "",
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


# ---- 工具能力策略 ----

def _tool_names(key: str) -> set[str]:
    raw = get_setting(key, DEFAULTS.get(key, ""))
    return {x.strip() for x in raw.split(",") if x.strip()}


def _matches(name: str, patterns: set[str]) -> bool:
    return any(fnmatch.fnmatchcase(name, pattern) for pattern in patterns)

def admin_only_tool_set() -> set[str]:
    return _tool_names("admin_only_tools")


def tool_allowed(tool_name: str, role: str, source: str = "local",
                 connector_granted: bool = False) -> bool:
    """统一判断本地、闭包和 MCP 工具的执行权限。"""
    if role == "admin":
        return True

    if _matches(tool_name, admin_only_tool_set() | _tool_names("tool_denylist")):
        return False

    allowlist = _tool_names("tool_allowlist")
    if allowlist and not _matches(tool_name, allowlist):
        return False

    if source == "mcp":
        if connector_granted:
            return True
        default_deny = get_setting("mcp_default_deny", "1").strip().lower()
        if default_deny in {"1", "true", "yes", "on"} \
                and not _matches(tool_name, _tool_names("mcp_allowlist")):
            return False
    return True


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
