"""组织（部门树）CRUD。

- 树形结构：parent_id 指向父部门，NULL=顶级；数据量小，前端/筛选时内存组树。
- 删除保护：有子部门或有成员时拒绝删除（软删）。
- 移动保护：不能把自己挂到自己或自己的后代下（防环）。
"""

import time
import uuid

from .db import _conn, _soft_delete_row


def _new_id() -> str:
    return "org_" + time.strftime("%Y%m%d%H%M%S") + uuid.uuid4().hex[:6]


def create_org(name: str, parent_id: str | None = None, sort_order: int = 0) -> str | None:
    """新建部门。父部门不存在时返回 None。"""
    con = _conn()
    if parent_id:
        p = con.execute(
            "SELECT id FROM orgs WHERE id=? AND deleted_at IS NULL", (parent_id,)).fetchone()
        if not p:
            con.close()
            return None
    oid = _new_id()
    con.execute(
        "INSERT INTO orgs(id,name,parent_id,sort_order,created_at) VALUES(?,?,?,?,?)",
        (oid, name, parent_id, sort_order, time.strftime("%Y-%m-%d %H:%M:%S")))
    con.commit()
    con.close()
    return oid


def get_org(org_id: str) -> dict | None:
    con = _conn()
    r = con.execute(
        "SELECT * FROM orgs WHERE id=? AND deleted_at IS NULL", (org_id,)).fetchone()
    con.close()
    return dict(r) if r else None


def list_orgs() -> list[dict]:
    """平铺列表（含各部门直属成员数），前端按 parent_id 组树。"""
    con = _conn()
    rows = con.execute(
        "SELECT o.id, o.name, o.parent_id, o.sort_order, o.created_at, "
        "(SELECT COUNT(*) FROM users u "
        " WHERE u.org_id=o.id AND u.deleted_at IS NULL) AS member_count "
        "FROM orgs o WHERE o.deleted_at IS NULL "
        "ORDER BY COALESCE(o.parent_id,''), o.sort_order, o.created_at").fetchall()
    con.close()
    return [dict(r) for r in rows]


def descendant_ids(org_id: str, include_self: bool = True) -> list[str]:
    """收集某部门及其全部后代 id（筛选「父部门含子部门成员」用）。"""
    con = _conn()
    rows = con.execute(
        "SELECT id, parent_id FROM orgs WHERE deleted_at IS NULL").fetchall()
    con.close()
    children: dict[str, list[str]] = {}
    for r in rows:
        children.setdefault(r["parent_id"], []).append(r["id"])
    out: list[str] = []
    stack = [org_id]
    while stack:
        cur = stack.pop()
        out.append(cur)
        stack.extend(children.get(cur, []))
    return out if include_self else [i for i in out if i != org_id]


def update_org(org_id: str, name: str | None = None, parent_id: str | None = None,
               sort_order: int | None = None, move: bool = False) -> str | None:
    """更新部门。move=True 才会改动 parent_id（None=挂到顶级）。
    返回错误码：'not_found' / 'cycle' / 'bad_parent'，成功返回 None。"""
    con = _conn()
    row = con.execute(
        "SELECT * FROM orgs WHERE id=? AND deleted_at IS NULL", (org_id,)).fetchone()
    if not row:
        con.close()
        return "not_found"
    if move:
        if parent_id:
            if parent_id == org_id or parent_id in descendant_ids(org_id, include_self=False):
                con.close()
                return "cycle"
            p = con.execute(
                "SELECT id FROM orgs WHERE id=? AND deleted_at IS NULL",
                (parent_id,)).fetchone()
            if not p:
                con.close()
                return "bad_parent"
        con.execute("UPDATE orgs SET parent_id=? WHERE id=?", (parent_id or None, org_id))
    if name is not None:
        con.execute("UPDATE orgs SET name=? WHERE id=?", (name, org_id))
    if sort_order is not None:
        con.execute("UPDATE orgs SET sort_order=? WHERE id=?", (sort_order, org_id))
    con.commit()
    con.close()
    return None


def delete_org(org_id: str) -> str | None:
    """软删部门。有子部门或有成员时返回错误码，成功返回 None。"""
    con = _conn()
    row = con.execute(
        "SELECT id FROM orgs WHERE id=? AND deleted_at IS NULL", (org_id,)).fetchone()
    if not row:
        con.close()
        return "not_found"
    child = con.execute(
        "SELECT id FROM orgs WHERE parent_id=? AND deleted_at IS NULL LIMIT 1",
        (org_id,)).fetchone()
    if child:
        con.close()
        return "has_children"
    member = con.execute(
        "SELECT id FROM users WHERE org_id=? AND deleted_at IS NULL LIMIT 1",
        (org_id,)).fetchone()
    if member:
        con.close()
        return "has_members"
    con.close()
    _soft_delete_row("orgs", org_id)
    return None
