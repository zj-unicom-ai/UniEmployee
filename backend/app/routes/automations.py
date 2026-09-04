"""自动化任务路由：定时/事件任务的 CRUD、手动运行、事件 webhook 入口。

- 管理 API（/api/automations/*）仅 admin 可用
- 事件入口 POST /api/automations/events/{event_key} 面向外部系统，
  靠任务级 secret 校验（未配置 secret 则直接放行）
"""
from fastapi import APIRouter, Depends, HTTPException

from app import automations, auth, runtime
from app.models import (
    AutomationCreate, AutomationUpdate, AutomationEventIn,
)

router = APIRouter(prefix="/api/automations", tags=["automations"])


def _require_admin(user: dict):
    if user.get("role") != "admin":
        raise HTTPException(403, "仅管理员可管理自动化任务")


def _validate(body) -> None:
    if body.trigger_type not in ("cron", "event"):
        raise HTTPException(400, "trigger_type 仅支持 cron / event")
    if not body.prompt or not body.prompt.strip():
        raise HTTPException(400, "任务指令（prompt）不能为空")
    if not any(e["id"] == body.employee_id for e in runtime.discover_employees()):
        raise HTTPException(400, f"数字员工不存在：{body.employee_id}")
    if body.trigger_type == "cron":
        err = automations.validate_cron(body.cron_expr or "")
        if err:
            raise HTTPException(400, f"cron 表达式不合法：{err}")
    else:
        if not (body.event_key or "").strip():
            raise HTTPException(400, "事件触发必须填写事件标识（event_key）")


def _item(auto: dict) -> dict:
    item = {**auto}
    if auto.get("trigger_type") == "event" and auto.get("event_key"):
        item["event_url"] = f"/api/automations/events/{auto['event_key']}"
    return item


@router.get("")
async def list_automations(user: dict = Depends(auth.get_current_user_or_fallback)):
    _require_admin(user)
    return {"items": [_item(a) for a in automations.list_all()]}


@router.post("")
async def create_automation(body: AutomationCreate,
                            user: dict = Depends(auth.get_current_user_or_fallback)):
    _require_admin(user)
    _validate(body)
    auto = automations.create(
        name=body.name.strip(), trigger_type=body.trigger_type,
        employee_id=body.employee_id, prompt=body.prompt.strip(),
        cron_expr=body.cron_expr or "", event_key=(body.event_key or "").strip(),
        secret=body.secret or "", run_as=body.run_as or user.get("id", "default"),
        channel_id=body.channel_id or "", enabled=body.enabled,
        created_by=user.get("id", ""))
    return _item(auto)


@router.put("/{aid}")
async def update_automation(aid: str, body: AutomationUpdate,
                            user: dict = Depends(auth.get_current_user_or_fallback)):
    _require_admin(user)
    current = automations.get(aid)
    if not current:
        raise HTTPException(404, "任务不存在")
    merged = AutomationCreate(
        name=body.name if body.name is not None else current["name"],
        trigger_type=body.trigger_type or current["trigger_type"],
        cron_expr=body.cron_expr if body.cron_expr is not None else current["cron_expr"],
        event_key=body.event_key if body.event_key is not None else current["event_key"],
        secret=body.secret if body.secret is not None else current["secret"],
        employee_id=body.employee_id or current["employee_id"],
        prompt=body.prompt if body.prompt is not None else current["prompt"],
        run_as=body.run_as if body.run_as is not None else current["run_as"],
        channel_id=body.channel_id if body.channel_id is not None else current["channel_id"],
        enabled=body.enabled if body.enabled is not None else current["enabled"],
    )
    _validate(merged)
    auto = automations.update(
        aid, name=merged.name.strip(), trigger_type=merged.trigger_type,
        cron_expr=merged.cron_expr or "", event_key=merged.event_key.strip(),
        secret=merged.secret or "", employee_id=merged.employee_id,
        prompt=merged.prompt.strip(), run_as=merged.run_as,
        channel_id=merged.channel_id or "", enabled=merged.enabled)
    return _item(auto or {})


@router.delete("/{aid}")
async def delete_automation(aid: str,
                            user: dict = Depends(auth.get_current_user_or_fallback)):
    _require_admin(user)
    if not automations.delete(aid):
        raise HTTPException(404, "任务不存在")
    return {"ok": True}


@router.post("/events/{event_key}")
async def event_trigger(event_key: str, body: AutomationEventIn):
    """外部事件入口：触发所有监听该事件的任务并返回执行结果。"""
    autos = automations.list_by_event(event_key)
    if not autos:
        raise HTTPException(404, "没有启用中的任务监听该事件")
    results = []
    for auto in autos:
        if auto.get("secret") and auto["secret"] != (body.secret or ""):
            continue
        r = await automations.execute(auto, payload=body.payload, trigger="event")
        results.append({"id": auto["id"], "name": auto["name"], **r})
    if not results:
        raise HTTPException(403, "secret 校验失败")
    return {"event": event_key, "triggered": len(results), "results": results}


@router.post("/{aid}/run")
async def run_automation(aid: str,
                         user: dict = Depends(auth.get_current_user_or_fallback)):
    """手动立即运行（验收/调试用；不影响 cron 的下次触发时间）。"""
    _require_admin(user)
    auto = automations.get(aid)
    if not auto:
        raise HTTPException(404, "任务不存在")
    result = await automations.execute(auto, trigger="manual")
    return result
