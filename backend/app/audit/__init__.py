"""管理端审计日志：admin 的员工/资源/用户/组织/护栏等变更操作落库。

设计：
- audit_logs 表（挂 catalog 库）：操作人、动作（create/update/delete）、
  对象类型与 ID、变更前后 JSON 快照、来源 IP、时间。
- 记录失败不阻断业务（审计是旁路，写库异常只打日志）。
- 查询走 list_logs，供审计页按对象/操作人/动作筛选。
"""
import json
import time

from .db import _conn, init_tables  # noqa: F401  init_tables 随 catalog.init() 调用


def _json(value) -> str | None:
    if value is None:
        return None
    try:
        return json.dumps(value, ensure_ascii=False, default=str)
    except Exception:
        return str(value)


def log(action: str, obj_type: str, obj_id: str = "",
        admin: dict | None = None, request=None,
        before=None, after=None):
    """记录一条管理端变更。action: create/update/delete；before/after 为快照。"""
    ip = ""
    if request is not None:
        ip = request.client.host if request.client else ""
        fwd = request.headers.get("x-forwarded-for", "")
        if fwd:
            ip = fwd.split(",")[0].strip()
    try:
        con = _conn()
        con.execute(
            "INSERT INTO audit_logs(actor_id,actor_name,action,obj_type,obj_id,"
            "before,after,ip,created_at) VALUES(?,?,?,?,?,?,?,?,?)",
            ((admin or {}).get("id", ""), (admin or {}).get("username", ""),
             action, obj_type, obj_id,
             _json(before), _json(after), ip,
             time.strftime("%Y-%m-%d %H:%M:%S")))
        con.commit()
        con.close()
    except Exception as e:  # 审计写失败不阻断业务
        print(f"[audit] 写审计日志失败: {type(e).__name__}: {e}")


def list_logs(limit: int = 100, offset: int = 0, obj_type: str = "",
              actor_id: str = "", action: str = "") -> tuple[list[dict], int]:
    """分页查询审计日志，返回 (rows, total)。"""
    where, params = [], []
    if obj_type:
        where.append("obj_type=?")
        params.append(obj_type)
    if actor_id:
        where.append("actor_id=?")
        params.append(actor_id)
    if action:
        where.append("action=?")
        params.append(action)
    cond = (" WHERE " + " AND ".join(where)) if where else ""
    con = _conn()
    total = con.execute(
        f"SELECT COUNT(*) AS c FROM audit_logs{cond}", params).fetchone()["c"]
    rows = con.execute(
        f"SELECT * FROM audit_logs{cond} ORDER BY id DESC LIMIT ? OFFSET ?",
        params + [limit, offset]).fetchall()
    con.close()
    return [dict(r) for r in rows], total
