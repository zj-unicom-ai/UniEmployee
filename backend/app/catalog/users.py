"""用户 CRUD 与 用户-员工分配管理。"""

import json
import time
import uuid
from . import orgs as orgs_mod
from .db import _conn, _soft_delete_row


# ---------------------------------------------------------------------------
# 用户管理
# ---------------------------------------------------------------------------

_USER_LIST_COLS = ("u.id, u.username, u.role, u.status, u.tenant_id, u.org_id, "
                   "u.created_at, o.name AS org_name")


def create_user(username: str, password_hash: str, role: str = "user",
                tenant_id: str = "default", user_id: str | None = None,
                org_id: str | None = None) -> str:
    # 秒级时间戳同秒会撞主键（批量建用户/测试夹具），追加随机段保证唯一
    uid = user_id or ("u_" + time.strftime("%Y%m%d%H%M%S") + uuid.uuid4().hex[:6])
    now = time.strftime("%Y-%m-%d %H:%M:%S")
    con = _conn()
    old = con.execute(
        "SELECT id FROM users WHERE username=? AND deleted_at IS NOT NULL",
        (username,)).fetchone()
    if old:
        con.execute(
            "UPDATE users SET password_hash=?, role=?, status='active', tenant_id=?, "
            "org_id=?, deleted_at=NULL WHERE username=?",
            (password_hash, role, tenant_id, org_id, username))
        con.commit()
        con.close()
        return old["id"]
    con.execute(
        "INSERT OR IGNORE INTO users(id,username,password_hash,role,status,tenant_id,org_id,created_at) "
        "VALUES(?,?,?,?,?,?,?,?)",
        (uid, username, password_hash, role, "active", tenant_id, org_id, now))
    con.commit()
    con.close()
    return uid


def get_user(user_id: str) -> dict | None:
    con = _conn()
    r = con.execute("SELECT * FROM users WHERE id=? AND deleted_at IS NULL", (user_id,)).fetchone()
    con.close()
    return dict(r) if r else None


def get_user_by_username(username: str) -> dict | None:
    con = _conn()
    r = con.execute("SELECT * FROM users WHERE username=? AND deleted_at IS NULL",
                    (username,)).fetchone()
    con.close()
    return dict(r) if r else None


# ---- 个人画像（用户自述，员工运行时作为当前用户上下文加载） ----

PROFILE_FIELDS = ("display_name", "position", "duties", "preferences")


def get_profile(user_id: str) -> dict:
    """返回用户画像（无记录时返回全空字段的默认结构）。"""
    con = _conn()
    r = con.execute("SELECT * FROM user_profiles WHERE user_id=?", (user_id,)).fetchone()
    con.close()
    if not r:
        return {k: "" for k in PROFILE_FIELDS}
    return {k: (r[k] or "") for k in PROFILE_FIELDS}


def upsert_profile(user_id: str, data: dict) -> bool:
    """保存用户画像（部分字段更新，未出现的字段沿用现值）。"""
    con = _conn()
    cur = con.cursor()
    if not cur.execute("SELECT 1 FROM users WHERE id=? AND deleted_at IS NULL",
                       (user_id,)).fetchone():
        con.close()
        return False
    existing = get_profile(user_id)
    merged = {k: (data.get(k) if data.get(k) is not None else existing[k])
              for k in PROFILE_FIELDS}
    cur.execute(
        "INSERT INTO user_profiles(user_id,display_name,position,duties,preferences,updated_at) "
        "VALUES(?,?,?,?,?,?) ON CONFLICT(user_id) DO UPDATE SET "
        "display_name=excluded.display_name, position=excluded.position, "
        "duties=excluded.duties, preferences=excluded.preferences, "
        "updated_at=excluded.updated_at",
        (user_id, merged["display_name"], merged["position"],
         merged["duties"], merged["preferences"],
         time.strftime("%Y-%m-%d %H:%M:%S")))
    con.commit()
    con.close()
    return True


def _org_filter(org_id: str | None) -> tuple[str, list]:
    """按部门筛选（含全部子部门）的 WHERE 片段与参数。"""
    if not org_id:
        return "", []
    ids = orgs_mod.descendant_ids(org_id)
    marks = ",".join("?" for _ in ids)
    return f" AND u.org_id IN ({marks})", list(ids)


def list_users(org_id: str | None = None) -> list[dict]:
    where, args = _org_filter(org_id)
    con = _conn()
    rows = con.execute(
        f"SELECT {_USER_LIST_COLS} FROM users u "
        f"LEFT JOIN orgs o ON o.id=u.org_id AND o.deleted_at IS NULL "
        f"WHERE u.deleted_at IS NULL{where} ORDER BY u.created_at", args).fetchall()
    con.close()
    return [dict(r) for r in rows]


def list_users_paged(page: int = 1, page_size: int = 10,
                     org_id: str | None = None) -> dict:
    page = max(1, page)
    where, args = _org_filter(org_id)
    con = _conn()
    total = con.execute(
        f"SELECT COUNT(*) FROM users u WHERE u.deleted_at IS NULL{where}", args).fetchone()[0]
    offset = (page - 1) * page_size
    rows = con.execute(
        f"SELECT {_USER_LIST_COLS} FROM users u "
        f"LEFT JOIN orgs o ON o.id=u.org_id AND o.deleted_at IS NULL "
        f"WHERE u.deleted_at IS NULL{where} "
        f"ORDER BY u.created_at LIMIT ? OFFSET ?",
        args + [page_size, offset]).fetchall()
    con.close()
    return {
        "items": [dict(r) for r in rows],
        "total": total,
        "page": page,
        "page_size": page_size,
        "pages": (total + page_size - 1) // page_size,
    }


def update_user(user_id: str, role: str | None = None, status: str | None = None,
                org_id: str | None = None, set_org: bool = False) -> bool:
    """set_org=True 才会改动归属部门（org_id=None 表示移出部门）。"""
    con = _conn()
    cur = con.cursor()
    if role is not None:
        cur.execute("UPDATE users SET role=? WHERE id=?", (role, user_id))
    if status is not None:
        cur.execute("UPDATE users SET status=? WHERE id=?", (status, user_id))
    if set_org:
        cur.execute("UPDATE users SET org_id=? WHERE id=?", (org_id, user_id))
    ok = cur.rowcount > 0
    con.commit()
    con.close()
    return ok


def set_password(user_id: str, password_hash: str) -> bool:
    con = _conn()
    cur = con.cursor()
    cur.execute("UPDATE users SET password_hash=?, must_change_password=0 WHERE id=?",
                (password_hash, user_id))
    ok = cur.rowcount > 0
    con.commit()
    con.close()
    return ok


def set_must_change_password(user_id: str, flag: bool = True) -> bool:
    con = _conn()
    cur = con.cursor()
    cur.execute("UPDATE users SET must_change_password=? WHERE id=?",
                (1 if flag else 0, user_id))
    ok = cur.rowcount > 0
    con.commit()
    con.close()
    return ok


def delete_user(user_id: str) -> bool:
    return _soft_delete_row("users", user_id)


# ---------------------------------------------------------------------------
# 用户-员工分配（模板 + 每用户覆盖）
# ---------------------------------------------------------------------------

def assign_employee(user_id: str, emp_id: str, overrides: dict | None = None,
                    granted_by: str | None = None) -> bool:
    now = time.strftime("%Y-%m-%d %H:%M:%S")
    con = _conn()
    # INSERT OR REPLACE 在 PostgreSQL 无对应写法；ON CONFLICT DO UPDATE 双方言通用，
    # 且避免了 REPLACE 的删+插语义（自增/外键副作用）。
    con.execute(
        "INSERT INTO user_employee_assignments"
        "(user_id,employee_id,granted_by,overrides,created_at) VALUES(?,?,?,?,?) "
        "ON CONFLICT(user_id,employee_id) DO UPDATE SET "
        "granted_by=excluded.granted_by, overrides=excluded.overrides, "
        "created_at=excluded.created_at",
        (user_id, emp_id, granted_by,
         json.dumps(overrides or {}, ensure_ascii=False), now))
    con.commit()
    con.close()
    return True


def unassign_employee(user_id: str, emp_id: str) -> bool:
    con = _conn()
    cur = con.cursor()
    cur.execute(
        "DELETE FROM user_employee_assignments WHERE user_id=? AND employee_id=?",
        (user_id, emp_id))
    ok = cur.rowcount > 0
    con.commit()
    con.close()
    return ok


def get_assignment(user_id: str, emp_id: str) -> dict | None:
    con = _conn()
    r = con.execute(
        "SELECT * FROM user_employee_assignments WHERE user_id=? AND employee_id=?",
        (user_id, emp_id)).fetchone()
    con.close()
    if not r:
        return None
    d = dict(r)
    d["overrides"] = json.loads(d["overrides"]) if d["overrides"] else {}
    return d


def list_assignments(user_id: str) -> list[dict]:
    con = _conn()
    rows = con.execute(
        "SELECT * FROM user_employee_assignments WHERE user_id=?", (user_id,)).fetchall()
    con.close()
    return [{**dict(r), "overrides": json.loads(r["overrides"]) if r["overrides"] else {}}
            for r in rows]


def set_assignment_overrides(user_id: str, emp_id: str, overrides: dict) -> bool:
    con = _conn()
    cur = con.cursor()
    cur.execute(
        "UPDATE user_employee_assignments SET overrides=? "
        "WHERE user_id=? AND employee_id=?",
        (json.dumps(overrides, ensure_ascii=False), user_id, emp_id))
    ok = cur.rowcount > 0
    con.commit()
    con.close()
    return ok


def assigned_employee_ids(user_id: str) -> list[str]:
    con = _conn()
    out = [r[0] for r in con.execute(
        "SELECT employee_id FROM user_employee_assignments WHERE user_id=?", (user_id,))]
    con.close()
    return out


def list_user_ids_with_emp(emp_id: str) -> list[str]:
    con = _conn()
    out = [r[0] for r in con.execute(
        "SELECT user_id FROM user_employee_assignments WHERE employee_id=?", (emp_id,))]
    con.close()
    return out