"""自动化任务路由：定时/事件任务的 CRUD、手动运行、事件 webhook 入口。

- 管理 API（/api/automations/*）仅 admin 可用
- 事件入口 POST /api/automations/events/{event_key} 面向外部系统，
  使用任务级 HMAC-SHA256 密钥验证；开发环境保留旧请求体 secret 兼容
"""
import hashlib
import hmac
import logging
import os
import re
import time

from fastapi import APIRouter, Depends, Header, HTTPException, Request

from app import automations, auth, catalog, demo_isolation, runtime
from app.auth_context import from_user
from app.models import (
    AutomationCreate, AutomationUpdate, AutomationEventIn, AutomationRetryIn,
)

router = APIRouter(prefix="/api/automations", tags=["automations"])
log = logging.getLogger("app.routes.automations")

_WEBHOOK_SIGNATURE_VERSION = "v2"
_WEBHOOK_SIGNATURE_RE = re.compile(r"^[0-9a-fA-F]{64}$")


def _webhook_tolerance_seconds() -> int:
    raw = os.environ.get("AUTOMATION_WEBHOOK_TOLERANCE_SECONDS", "300")
    try:
        value = int(raw)
    except ValueError:
        log.error("AUTOMATION_WEBHOOK_TOLERANCE_SECONDS 无效；使用安全默认值 300")
        return 300
    if not 1 <= value <= 3600:
        log.error("AUTOMATION_WEBHOOK_TOLERANCE_SECONDS 超出允许范围；使用安全默认值 300")
        return 300
    return value


def _webhook_signing_message(method: str, path: str, tenant_id: str,
                             timestamp: str, idempotency_key: str,
                             raw_body: bytes) -> bytes:
    """签名绑定租户、路由、幂等键和原始请求体，阻断跨租户复用。"""
    body_digest = hashlib.sha256(raw_body).hexdigest()
    parts = (_WEBHOOK_SIGNATURE_VERSION, method.upper(), path, tenant_id, timestamp,
             idempotency_key, body_digest)
    return "\n".join(parts).encode("utf-8")


def _valid_webhook_timestamp(timestamp: str, now: int | None = None) -> bool:
    if not timestamp.isascii() or not timestamp.isdigit() or len(timestamp) > 12:
        return False
    try:
        issued_at = int(timestamp)
    except ValueError:
        return False
    current = int(time.time()) if now is None else now
    return abs(current - issued_at) <= _webhook_tolerance_seconds()


def _verify_webhook_signature(secret: str, signature: str, *, method: str,
                              path: str, tenant_id: str, timestamp: str,
                              idempotency_key: str, raw_body: bytes) -> bool:
    if len(secret.encode("utf-8")) < 32 or not _WEBHOOK_SIGNATURE_RE.fullmatch(signature.strip()):
        return False
    message = _webhook_signing_message(method, path, tenant_id, timestamp,
                                       idempotency_key, raw_body)
    expected = hmac.new(secret.encode("utf-8"), message, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, signature.strip().lower())


def _require_admin(user: dict):
    if user.get("role") != "admin":
        raise HTTPException(403, "仅管理员可管理自动化任务")


def _tenant_id(user: dict) -> str:
    return from_user(user).tenant_id


def _validate_run_as(run_as: str, employee_id: str, tenant_id: str) -> None:
    principal = catalog.get_user(run_as)
    if (not principal or principal.get("status") != "active"
            or (principal.get("tenant_id") or "default") != tenant_id):
        raise HTTPException(400, "运行身份必须是本租户中的有效用户")
    if not catalog.get_assignment(run_as, employee_id):
        raise HTTPException(400, "运行身份未获授权使用所选数字员工")


def _validate(body, *, tenant_id: str, run_as: str) -> None:
    if body.trigger_type not in ("cron", "event"):
        raise HTTPException(400, "trigger_type 仅支持 cron / event")
    if not body.prompt or not body.prompt.strip():
        raise HTTPException(400, "任务指令（prompt）不能为空")
    if not any(e["id"] == body.employee_id for e in runtime.discover_employees()):
        raise HTTPException(400, f"数字员工不存在：{body.employee_id}")
    if body.enabled:
        _validate_run_as(run_as, body.employee_id, tenant_id)
    if body.trigger_type == "cron":
        err = automations.validate_cron(body.cron_expr or "")
        if err:
            raise HTTPException(400, f"cron 表达式不合法：{err}")
    else:
        if not (body.event_key or "").strip():
            raise HTTPException(400, "事件触发必须填写事件标识（event_key）")
        if demo_isolation.is_production() and body.enabled:
            if len((body.secret or "").encode("utf-8")) < 32:
                raise HTTPException(400, "生产模式启用事件自动化时必须配置至少 32 字节的 Webhook 密钥")


def _item(auto: dict) -> dict:
    item = {key: value for key, value in auto.items() if key != "secret"}
    item["has_secret"] = bool(auto.get("secret"))
    if auto.get("trigger_type") == "event" and auto.get("event_key"):
        item["event_url"] = f"/api/automations/events/{auto['event_key']}"
    return item


@router.get("")
async def list_automations(user: dict = Depends(auth.get_current_user_or_fallback)):
    _require_admin(user)
    return {"items": [_item(a) for a in automations.list_all(_tenant_id(user))]}


@router.post("")
async def create_automation(body: AutomationCreate,
                            user: dict = Depends(auth.get_current_user_or_fallback)):
    _require_admin(user)
    tenant_id = _tenant_id(user)
    run_as = body.run_as or user.get("id", "default")
    _validate(body, tenant_id=tenant_id, run_as=run_as)
    auto = automations.create(
        name=body.name.strip(), trigger_type=body.trigger_type,
        employee_id=body.employee_id, prompt=body.prompt.strip(),
        cron_expr=body.cron_expr or "", event_key=(body.event_key or "").strip(),
        secret=body.secret or "", run_as=run_as,
        channel_id=body.channel_id or "", enabled=body.enabled,
        created_by=user.get("id", ""), tenant_id=tenant_id)
    return _item(auto)


@router.put("/{aid}")
async def update_automation(aid: str, body: AutomationUpdate,
                            user: dict = Depends(auth.get_current_user_or_fallback)):
    _require_admin(user)
    tenant_id = _tenant_id(user)
    current = automations.get(aid, tenant_id=tenant_id)
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
    _validate(merged, tenant_id=tenant_id, run_as=merged.run_as or "default")
    auto = automations.update(
        aid, tenant_id=tenant_id, name=merged.name.strip(), trigger_type=merged.trigger_type,
        cron_expr=merged.cron_expr or "", event_key=merged.event_key.strip(),
        secret=merged.secret or "", employee_id=merged.employee_id,
        prompt=merged.prompt.strip(), run_as=merged.run_as,
        channel_id=merged.channel_id or "", enabled=merged.enabled)
    return _item(auto or {})


@router.delete("/{aid}")
async def delete_automation(aid: str,
                            user: dict = Depends(auth.get_current_user_or_fallback)):
    _require_admin(user)
    if not automations.delete(aid, tenant_id=_tenant_id(user)):
        raise HTTPException(404, "任务不存在")
    return {"ok": True}


@router.post("/events/{event_key}")
async def event_trigger(event_key: str, request: Request, body: AutomationEventIn,
                        idempotency_key: str = Header(alias="Idempotency-Key"),
                        timestamp: str | None = Header(default=None, alias="X-UniEmployee-Timestamp"),
                        signature: str | None = Header(default=None, alias="X-UniEmployee-Signature")):
    """外部事件入口：触发所有监听该事件的任务并返回执行结果。"""
    autos = automations.list_by_event(event_key)
    if not autos:
        raise HTTPException(404, "没有启用中的任务监听该事件")
    key = idempotency_key.strip()
    if not key or len(key) > 200:
        raise HTTPException(400, "Idempotency-Key 长度须为 1-200 个字符")

    production = demo_isolation.is_production()
    has_timestamp = timestamp is not None
    has_signature = signature is not None
    signed_request = has_timestamp or has_signature
    if signed_request and not (has_timestamp and has_signature):
        raise HTTPException(401, "Webhook authentication failed")
    if production and not signed_request:
        raise HTTPException(401, "Webhook authentication failed")
    if signed_request and not _valid_webhook_timestamp(timestamp or ""):
        raise HTTPException(401, "Webhook request expired")

    raw_body = await request.body()
    results = []
    for auto in autos:
        secret = auto.get("secret") or ""
        if signed_request:
            if not _verify_webhook_signature(
                    secret, signature or "", method=request.method,
                    path=request.url.path, tenant_id=auto.get("tenant_id") or "default",
                    timestamp=timestamp or "",
                    idempotency_key=key, raw_body=raw_body):
                continue
        elif secret:
            # 仅为开发期旧集成保留请求体密钥兼容；生产流量不会进入此路径。
            if production or not hmac.compare_digest(secret, body.secret or ""):
                continue
        elif production:
            continue
        else:
            # 兼容原有开发演示任务；不记录或输出任何密钥内容。
            log.warning("开发模式下接受未配置 Webhook 密钥的事件任务 id=%s", auto["id"])
        r = await automations.execute(auto, payload=body.payload, trigger="event",
                                      trigger_key=key, trigger_actor="system:webhook")
        results.append({"id": auto["id"], "name": auto["name"], **r})
    if not results:
        raise HTTPException(403, "Webhook authentication failed")
    return {"event": event_key, "triggered": len(results),
            "idempotency_key": key, "results": results}


@router.post("/{aid}/run")
async def run_automation(aid: str,
                         user: dict = Depends(auth.get_current_user_or_fallback)):
    """手动立即运行（验收/调试用；不影响 cron 的下次触发时间）。"""
    _require_admin(user)
    tenant_id = _tenant_id(user)
    auto = automations.get(aid, tenant_id=tenant_id)
    if not auto:
        raise HTTPException(404, "任务不存在")
    result = await automations.execute(auto, trigger="manual", trigger_actor=user.get("id", ""))
    return result


@router.get("/{aid}/executions")
async def list_automation_executions(aid: str, limit: int = 50,
                                     user: dict = Depends(auth.get_current_user_or_fallback)):
    _require_admin(user)
    tenant_id = _tenant_id(user)
    if not automations.get(aid, tenant_id=tenant_id):
        raise HTTPException(404, "任务不存在")
    return {"items": automations.list_executions(aid, limit, tenant_id=tenant_id)}


@router.post("/{aid}/executions/{execution_id}/retry")
async def retry_automation_execution(aid: str, execution_id: str,
                                     body: AutomationRetryIn | None = None,
                                     idempotency_key: str = Header(alias="Idempotency-Key"),
                                     user: dict = Depends(auth.get_current_user_or_fallback)):
    """仅显式重跑失败/中断记录；不自动重试，避免重复业务副作用。"""
    _require_admin(user)
    tenant_id = _tenant_id(user)
    auto = automations.get(aid, tenant_id=tenant_id)
    if not auto:
        raise HTTPException(404, "任务不存在")
    previous = automations.get_execution(execution_id, automation_id=aid, tenant_id=tenant_id)
    if not previous or previous["automation_id"] != aid:
        raise HTTPException(404, "执行记录不存在")
    if previous["status"] not in ("error", "interrupted"):
        raise HTTPException(409, f"当前状态不支持人工重跑：{previous['status']}")
    key = idempotency_key.strip()
    if not key:
        raise HTTPException(400, "Idempotency-Key 不能为空")
    if len(key) > 200:
        raise HTTPException(400, "Idempotency-Key 长度不能超过 200 个字符")
    result = await automations.execute(
        auto, payload=body.payload if body else None, trigger="manual_retry",
        trigger_key=key, retry_of=execution_id, trigger_actor=user.get("id", ""))
    result["retry_of"] = execution_id
    return result
