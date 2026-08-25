"""普通用户自助路由：查看/调整自己的员工覆盖、看板、调试。"""

from fastapi import APIRouter, Depends
from fastapi.responses import FileResponse

from app import auth, catalog, runtime
from app.paths import WORKSPACE_DATA

router = APIRouter(prefix="/api/me")


@router.get("/employees")
async def my_employees(user: dict = Depends(auth.get_current_user)):
    out = []
    for a in catalog.list_assignments(user["id"]):
        eid = a["employee_id"]
        base = catalog.get_employee_config(eid) or {}
        eff = catalog.get_effective_config(user["id"], eid) or base
        out.append({
            "employee_id": eid, "name": base.get("name"), "role": base.get("role"),
            "overrides": a["overrides"],
            "base": {"skills": base.get("skills", []), "tools": base.get("tools", []),
                     "kbs": base.get("kbs", []), "sops": base.get("sops", []),
                     "connectors": base.get("connectors", [])},
            "effective": {"skills": eff.get("skills", []), "tools": eff.get("tools", []),
                          "kbs": eff.get("kbs", []), "sops": eff.get("sops", []),
                          "connectors": eff.get("connectors", [])},
        })
    return out


@router.get("/employees/{emp_id}")
async def my_employee_detail(emp_id: str, user: dict = Depends(auth.get_current_user)):
    if emp_id not in catalog.assigned_employee_ids(user["id"]):
        return {"error": "该数字员工未分配给你"}
    base = catalog.get_employee_config(emp_id) or {}
    asg = catalog.get_assignment(user["id"], emp_id) or {}
    eff = catalog.get_effective_config(user["id"], emp_id) or base
    return {
        "employee_id": emp_id, "name": base.get("name"),
        "overrides": asg.get("overrides", {}),
        "base": {"skills": base.get("skills", []), "tools": base.get("tools", []),
                 "kbs": base.get("kbs", []), "sops": base.get("sops", []),
                 "connectors": base.get("connectors", [])},
        "effective": {"skills": eff.get("skills", []), "tools": eff.get("tools", []),
                      "kbs": eff.get("kbs", []), "sops": eff.get("sops", []),
                      "connectors": eff.get("connectors", [])},
    }


@router.put("/employees/{emp_id}/overrides")
async def update_my_overrides(emp_id: str, body: dict,
                               user: dict = Depends(auth.get_current_user)):
    if emp_id not in catalog.assigned_employee_ids(user["id"]):
        return {"error": "该数字员工未分配给你，无法调整"}
    ov = body.get("overrides", {})
    if not isinstance(ov, dict):
        return {"error": "overrides 必须是对象"}
    keys = ("skills", "tools", "kbs", "sops", "connectors")
    add = ov.get("add") if isinstance(ov.get("add"), dict) else {}
    remove = ov.get("remove") if isinstance(ov.get("remove"), dict) else {}
    clean = {
        "add": {k: (add.get(k, []) if isinstance(add.get(k), list) else []) for k in keys},
        "remove": {k: (remove.get(k, []) if isinstance(remove.get(k), list) else []) for k in keys},
    }
    catalog.set_assignment_overrides(user["id"], emp_id, clean)
    # 用户级技能覆盖变化：直接同步当前用户技能 Store，并只清该用户变体缓存。
    await runtime.refresh_skills(emp_id, user["id"])
    return {"ok": True, "overrides": clean}


# ---- 调试 + 看板 ----

debug_router = APIRouter(prefix="/api", dependencies=[Depends(auth.require_admin)])


@debug_router.get("/debug/memory")
async def debug_memory(employee_id: str = "xiaosu",
                       user: dict = Depends(auth.require_admin)):
    return {"namespace": [employee_id], "items": await runtime.dump_store(employee_id)}


dash_router = APIRouter(prefix="/api")


@dash_router.get("/dashboards/{user_id}/{filename:path}")
async def get_dashboard(user_id: str, filename: str,
                        user: dict = Depends(auth.get_current_user)):
    if user["id"] != user_id:
        raise _forbidden("无权访问该看板")
    dash_dir = (WORKSPACE_DATA / user_id).resolve()
    dash_dir.exists() or dash_dir.parent.mkdir(parents=True, exist_ok=True)
    p = (dash_dir / filename).resolve()
    try:
        p.relative_to(dash_dir)
    except ValueError:
        raise _forbidden("非法路径")
    if not p.exists() or not p.is_file():
        raise _not_found("看板不存在")
    return FileResponse(p)


def _forbidden(msg):
    from fastapi import HTTPException
    return HTTPException(403, msg)


def _not_found(msg):
    from fastapi import HTTPException
    return HTTPException(404, msg)


# ── 运行评估（用户反馈） ──────────────────────────────────────────

from pydantic import BaseModel

class EvaluationIn(BaseModel):
    run_id: str = ""
    message_id: str = ""
    employee_id: str = ""
    conversation_id: str = ""
    rating: int   # 1 or -1
    reason: str = ""

@router.post("/evaluations")
async def submit_evaluation(body: EvaluationIn,
                            user: dict = Depends(auth.get_current_user)):
    from app import traces
    traces.insert_evaluation(
        run_id=body.run_id, message_id=body.message_id,
        employee_id=body.employee_id, conversation_id=body.conversation_id,
        user_id=user["id"], rating=body.rating, reason=body.reason,
    )
    return {"ok": True}
