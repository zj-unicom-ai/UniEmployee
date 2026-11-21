"""个人 MCP OAuth 授权与连接状态。"""

from __future__ import annotations

import os
from urllib.parse import urlparse

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import RedirectResponse

from app import auth, catalog, runtime
from app.auth_context import AuthContext
from app.catalog import resources
from app.connectors import oauth

router = APIRouter(prefix="/api/connectors", tags=["connectors"])


def _connector_oauth_redirect_uri() -> str:
    value = os.environ.get("CONNECTOR_OAUTH_REDIRECT_URI", "").strip()
    if not value:
        raise HTTPException(
            503,
            "OAuth 尚未配置 CONNECTOR_OAUTH_REDIRECT_URI，请设置公网回调地址后重试。",
        )
    parsed = urlparse(value)
    if (not parsed.scheme or not parsed.netloc or parsed.username or parsed.password
            or parsed.query or parsed.fragment):
        raise HTTPException(503, "CONNECTOR_OAUTH_REDIRECT_URI 格式无效。")
    try:
        parsed.port
    except ValueError as exc:
        raise HTTPException(503, "CONNECTOR_OAUTH_REDIRECT_URI 端口无效。") from exc
    if parsed.scheme != "https" and parsed.hostname not in {"localhost", "127.0.0.1", "::1"}:
        raise HTTPException(503, "OAuth 回调地址必须使用 HTTPS（本机开发除外）。")
    if parsed.path != "/api/connectors/oauth/callback":
        raise HTTPException(503, "OAuth 回调路径必须是 /api/connectors/oauth/callback。")
    return value


def _visible_oauth_connectors(context: AuthContext) -> dict[str, dict]:
    if context.allows("*"):
        employee_ids = [row["id"] for row in catalog.list_employees_meta()]
    else:
        employee_ids = catalog.assigned_employee_ids(context.user_id)

    found: dict[str, dict] = {}
    for employee_id in employee_ids:
        cfg = (catalog.get_employee_config(employee_id) if context.allows("*")
               else catalog.get_effective_config(context.user_id, employee_id)) or {}
        employee_name = str(cfg.get("name") or employee_id)
        for connector_id in cfg.get("connectors") or []:
            connector = catalog.get_connector(connector_id)
            if not connector or not oauth.is_oauth_config(connector.get("config")):
                continue
            item = found.setdefault(connector_id, {
                "id": connector_id,
                "name": connector.get("name") or connector_id,
                "description": connector.get("description") or "",
                "employees": [],
            })
            if employee_name not in item["employees"]:
                item["employees"].append(employee_name)
    return found


@router.get("")
async def list_my_connectors(context: AuthContext = Depends(auth.get_auth_context)):
    """List OAuth connectors exposed by employees assigned to the caller."""
    items = []
    for connector_id, item in _visible_oauth_connectors(context).items():
        status = oauth.connection_status(connector_id, context.user_id, context.tenant_id)
        items.append({**item, **status})
    items.sort(key=lambda item: (item["name"].lower(), item["id"]))
    return {"items": items}


@router.post("/{connector_id}/oauth/start")
async def start_connector_oauth(
    connector_id: str,
    context: AuthContext = Depends(auth.get_auth_context),
):
    if connector_id not in _visible_oauth_connectors(context):
        raise HTTPException(404, "没有找到当前用户可用的 OAuth 连接器。")
    try:
        authorization_url = await oauth.begin_authorization(
            connector_id,
            context.user_id,
            context.tenant_id,
            _connector_oauth_redirect_uri(),
        )
    except oauth.OAuthError as exc:
        raise HTTPException(422, str(exc)) from exc
    return {"authorization_url": authorization_url}


async def _invalidate_connector_runtime(connector_id: str, user_id: str) -> None:
    for employee_id in resources.employees_using_connector(connector_id):
        await runtime.invalidate_user_runtime(employee_id, user_id)


@router.delete("/{connector_id}/oauth")
async def disconnect_connector_oauth(
    connector_id: str,
    context: AuthContext = Depends(auth.get_auth_context),
):
    if connector_id not in _visible_oauth_connectors(context):
        raise HTTPException(404, "没有找到当前用户可用的 OAuth 连接器。")
    removed = oauth.disconnect(connector_id, context.user_id, context.tenant_id)
    if removed:
        await _invalidate_connector_runtime(connector_id, context.user_id)
    return {"ok": True, "disconnected": removed}


@router.get("/oauth/callback", name="connector_oauth_callback")
async def connector_oauth_callback(
    code: str | None = Query(default=None, max_length=4096),
    state: str | None = Query(default=None, max_length=256),
    error: str | None = Query(default=None, max_length=128),
):
    """Consume the one-time server-side state and exchange the OAuth code."""
    if not state:
        return RedirectResponse("/app/my-connectors?oauth=failed&reason=missing_state", status_code=303)
    try:
        if error:
            oauth.consume_denied_authorization(state)
            return RedirectResponse("/app/my-connectors?oauth=denied", status_code=303)
        if not code:
            oauth.consume_denied_authorization(state)
            return RedirectResponse("/app/my-connectors?oauth=failed&reason=missing_code", status_code=303)
        details = await oauth.finish_authorization(code, state)
        await _invalidate_connector_runtime(details["connector_id"], details["user_id"])
        return RedirectResponse("/app/my-connectors?oauth=connected", status_code=303)
    except oauth.OAuthError:
        return RedirectResponse("/app/my-connectors?oauth=failed&reason=exchange", status_code=303)
