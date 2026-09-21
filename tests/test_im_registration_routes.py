"""扫码一键创建应用的接口层回归（3 个路由 + 权限与脱敏边界）。

协议层细节见 `tests/test_im_registration.py`；这里盯的是前端要用的契约：

- 仅 admin 可用（401/403），且只对飞书频道开放（非飞书频道 400）
- 会话必须属于该频道（拿别的频道查不到 → 404）
- 启动响应不含 `device_code`，任何响应都不含 App Secret
- 扫码成功后写入的是同一个 `put_credential`，并触发频道重连（下游与手工填写无分叉）

飞书注册接口用 `httpx.MockTransport` 顶掉，不联网、不碰真实租户。
"""

import json
import time
from urllib.parse import parse_qs

import httpx
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app import auth
from app.im import registry as registry_module
from app.im.jobs import get_credential
from app.im.registration import AppRegistrationService
from app.routes import im as im_routes

ADMIN = {"id": "u_admin", "username": "admin", "role": "admin"}
USER = {"id": "u_user", "username": "user", "role": "user"}

SECRET = "scanned_secret_value"


def _begin_payload(interval: float = 0.02) -> dict:
    return {
        "device_code": "dc_test",
        "user_code": "AB12-CD34",
        "verification_uri_complete": "https://accounts.feishu.cn/page/launcher?user_code=AB12-CD34",
        "expires_in": 3600,
        "interval": interval,
    }


def _success_payload() -> dict:
    return {
        "client_id": "cli_scanned",
        "client_secret": SECRET,
        "user_info": {"open_id": "ou_owner", "tenant_brand": "feishu"},
    }


def _handler(final: dict):
    """按 action 分派的假飞书端点；`final` 是 poll 的返回。"""

    def handler(request: httpx.Request) -> httpx.Response:
        form = parse_qs(request.content.decode("utf-8"))
        action = (form.get("action") or [""])[0]
        if action == "init":
            return httpx.Response(200, json={"supported_auth_methods": ["client_secret"]})
        if action == "begin":
            return httpx.Response(200, json=_begin_payload())
        return httpx.Response(200, json=final)

    return handler


def _app(monkeypatch, user: dict, final: dict):
    """挂载 im 路由，注入假注册服务，并记录 reconcile（重连）调用。"""
    service = AppRegistrationService(transport=httpx.MockTransport(_handler(final)))
    monkeypatch.setattr(im_routes, "app_registration", service)

    reconciled: list[str | None] = []

    async def fake_reconcile(*, force_channel_id: str | None = None, **_kwargs) -> None:
        reconciled.append(force_channel_id)

    monkeypatch.setattr(registry_module.registry, "reconcile", fake_reconcile)

    app = FastAPI()
    app.include_router(im_routes.router)
    app.dependency_overrides[auth.get_current_user_or_fallback] = lambda: user
    return app, reconciled, service


def _create_channel(client: TestClient, provider: str = "feishu") -> str:
    resp = client.post(
        "/api/im/channels",
        json={
            "name": f"{provider}-测试频道",
            "description": "扫码回归",
            "provider": provider,
            "enabled": True,
            "employee_ids": ["xiaoshu"] if provider == "feishu" else [],
        },
    )
    assert resp.status_code == 200, resp.text
    return resp.json()["id"]


def _start(client: TestClient, channel_id: str) -> dict:
    resp = client.post(f"/api/im/channels/{channel_id}/registration/start")
    assert resp.status_code == 200, resp.text
    return resp.json()


def _wait_terminal(client: TestClient, channel_id: str, session_id: str, timeout: float = 5.0) -> dict:
    deadline = time.time() + timeout
    payload: dict = {}
    while time.time() < deadline:
        resp = client.get(f"/api/im/channels/{channel_id}/registration/{session_id}")
        assert resp.status_code == 200, resp.text
        payload = resp.json()
        if payload.get("status") != "pending":
            return payload
        time.sleep(0.05)
    return payload


def test_scan_success_writes_credential_without_echoing_secret(monkeypatch):
    app, reconciled, service = _app(monkeypatch, ADMIN, _success_payload())

    with TestClient(app) as client:
        channel_id = _create_channel(client)
        started = _start(client, channel_id)

        # 启动响应：有二维码与有效期，但不含 device_code、不含 App Secret。
        assert started["status"] == "pending"
        assert started["qr_url"].startswith("https://accounts.feishu.cn/page/launcher")
        assert "user_code=AB12-CD34" in started["qr_url"]
        assert started["expire_in"] == 3600
        assert "device_code" not in started
        assert SECRET not in json.dumps(started)

        payload = _wait_terminal(client, channel_id, started["session_id"])

        assert payload["status"] == "success"
        assert payload["app_id"] == "cli_scanned"
        assert payload["qr_url"] is None
        # 状态响应只给脱敏摘要：App Secret 永远不出接口。
        assert SECRET not in json.dumps(payload)
        assert payload["credential"]["configured"] is True
        assert "app_secret" not in json.dumps(payload["credential"])
        # 成功后必须触发该频道的重连。
        assert channel_id in reconciled

    credential = get_credential(channel_id)
    assert credential is not None
    assert credential.app_id == "cli_scanned"
    assert credential.app_secret == SECRET
    # 扫码不返回 tenant_key，留空由事件头识别。
    assert credential.tenant_key == ""


def test_cancel_marks_session_cancelled_and_stops_polling(monkeypatch):
    app, _, _ = _app(monkeypatch, ADMIN, {"error": "authorization_pending"})

    with TestClient(app) as client:
        channel_id = _create_channel(client)
        started = _start(client, channel_id)

        cancelled = client.post(
            f"/api/im/channels/{channel_id}/registration/{started['session_id']}/cancel"
        )
        assert cancelled.status_code == 200
        assert cancelled.json()["status"] == "cancelled"
        assert cancelled.json()["qr_url"] is None

        # 取消是终态，后续查询稳定返回 cancelled（后台轮询任务已清理）。
        again = client.get(
            f"/api/im/channels/{channel_id}/registration/{started['session_id']}"
        )
        assert again.json()["status"] == "cancelled"


def test_registration_endpoints_require_admin(monkeypatch):
    app, _, _ = _app(monkeypatch, ADMIN, _success_payload())

    with TestClient(app) as client:
        channel_id = _create_channel(client)

        app.dependency_overrides[auth.get_current_user_or_fallback] = lambda: USER
        assert client.post(
            f"/api/im/channels/{channel_id}/registration/start"
        ).status_code == 403
        assert client.get(
            f"/api/im/channels/{channel_id}/registration/reg_unknown"
        ).status_code == 403
        assert client.post(
            f"/api/im/channels/{channel_id}/registration/reg_unknown/cancel"
        ).status_code == 403


def test_registration_only_accepts_feishu_channel_and_matching_session(monkeypatch):
    app, _, _ = _app(monkeypatch, ADMIN, {"error": "authorization_pending"})

    with TestClient(app) as client:
        web_id = _create_channel(client, provider="web")
        feishu_id = _create_channel(client)

        # 非飞书频道直接拒绝，避免把协议用在错误的地方。
        rejected = client.post(f"/api/im/channels/{web_id}/registration/start")
        assert rejected.status_code == 400
        assert "飞书" in rejected.json()["detail"]

        # 未知会话 → 404（服务重启后会话只在内存里，前端据此提示重来）。
        assert client.get(
            f"/api/im/channels/{feishu_id}/registration/reg_missing"
        ).status_code == 404

        # 会话必须属于该频道：换另一个飞书频道去查/取消同一个 session → 404。
        started = _start(client, feishu_id)
        other_feishu_id = _create_channel(client)
        assert client.get(
            f"/api/im/channels/{other_feishu_id}/registration/{started['session_id']}"
        ).status_code == 404
        assert client.post(
            f"/api/im/channels/{other_feishu_id}/registration/{started['session_id']}/cancel"
        ).status_code == 404

        # 收尾：取消本频道会话，避免留下后台轮询任务。
        client.post(
            f"/api/im/channels/{feishu_id}/registration/{started['session_id']}/cancel"
        )
