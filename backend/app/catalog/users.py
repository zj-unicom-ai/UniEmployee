"""用户 CRUD 与 用户-员工分配管理。"""

import json
import time
from .db import _conn, _soft_delete_row


# ---------------------------------------------------------------------------
# 用户管理
# ---------------------------------------------------------------------------

def create_user(username: str, password_hash: str, role: str = "user",
                tenant_id: str = "default", user_id: str | None = None) -> str:
    uid = user_id or ("u_" + time.strftime("%Y%m%d%H%M%S"))
    now = time.strftime("%Y-%m-%d %H:%M:%S")
    con = _conn()
    old = con.execute(
        "SELECT id FROM users WHERE username=? AND deleted_at IS NOT NULL",
        (username,)).fetchone()
    if old:
        con.execute(
            "UPDATE users SET password_hash=?, role=?, status='active', tenant_id=?, deleted_at=NULL "
            "WHERE username=?",
            (password_hash, role, tenant_id, username))
        con.commit()
        con.close()
        return old["id"]
    con.execute(
        "INSERT OR IGNORE INTO users(id,username,password_hash,role,status,tenant_id,created_at) "
        "VALUES(?,?,?,?,?,?,?)",
        (uid, username, password_hash, role, "active", tenant_id, now))
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


def list_users() -> list[dict]:
    con = _conn()
    rows = con.execute(
        "SELECT id,username,role,status,tenant_id,created_at FROM users "
        "WHERE deleted_at IS NULL ORDER BY created_at").fetchall()
    con.close()
    return [dict(r) for r in rows]


def list_users_paged(page: int = 1, page_size: int = 10) -> dict:
    page = max(1, page)
    con = _conn()
    total = con.execute("SELECT COUNT(*) FROM users WHERE deleted_at IS NULL").fetchone()[0]
    offset = (page - 1) * page_size
    rows = con.execute(
        "SELECT id,username,role,status,tenant_id,created_at FROM users "
        "WHERE deleted_at IS NULL ORDER BY created_at LIMIT ? OFFSET ?",
        (page_size, offset)).fetchall()
    con.close()
    return {
        "items": [dict(r) for r in rows],
        "total": total,
        "page": page,
        "page_size": page_size,
        "pages": (total + page_size - 1) // page_size,
    }


def update_user(user_id: str, role: str | None = None, status: str | None = None) -> bool:
    con = _conn()
    cur = con.cursor()
    if role is not None:
        cur.execute("UPDATE users SET role=? WHERE id=?", (role, user_id))
    if status is not None:
        cur.execute("UPDATE users SET status=? WHERE id=?", (status, user_id))
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
    con.execute(
        "INSERT OR REPLACE INTO user_employee_assignments"
        "(user_id,employee_id,granted_by,overrides,created_at) VALUES(?,?,?,?,?)",
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