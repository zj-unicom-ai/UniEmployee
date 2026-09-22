"""钉钉扫码一键创建应用（路径 B）的协议层与接口层测试。

全部使用 `httpx.MockTransport`，不联网、不创建任何真实应用。

协议事实来自两个独立参考实现（逐项比对一致）：
- `DingTalk-Real-AI/dingtalk-openclaw-connector` 的 `src/device-auth.ts`（官方）
- `soimy/openclaw-channel-dingtalk` 的 `src/platform/device-registration.ts`（社区）

外加 2026-09-21 实测：`init` 返回 `{errcode:0, errmsg:"ok", expires_in:300, nonce:"nr_..."}`，
且 **JSON 与 form-urlencoded 两种请求体都能被接受**（飞书那边只认表单，这是关键差异）。
"""

import asyncio
import json
import time

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app import auth
from app.im import registration as registration_module
from app.im import registry as registry_module
from app.im.jobs import get_credential
from app.im.registration import (
    AppRegistrationService,
    RegistrationUnavailable,
    STATUS_ERROR,
    STATUS_EXPIRED,
    STATUS_PENDING,
    STATUS_SUCCESS,
    scan_provider_label,
    supported_scan_providers,
)
from app.routes import im as im_routes

INIT_PATH = "/app/registration/init"
BEGIN_PATH = "/app/registration/begin"
POLL_PATH = "/app/registration/poll"

SECRET = "dingtalk_scanned_secret"


def _json_body(request: httpx.Request) -> dict:
    return json.loads(request.content.decode("utf-8"))


def _init_payload() -> dict:
    # 实测响应形状（expires_in=300 实测值）。
    return {"errcode": 0, "errmsg": "ok", "expires_in": 300, "nonce": "nr_test_nonce"}


def _begin_payload(**overrides) -> dict:
    payload = {
        "errcode": 0,
        "errmsg": "ok",
        "device_code": "dt_dc_test",
        "user_code": "WXYZ-1234",
        "verification_uri": "https://login.dingtalk.com/oauth2/device/verify",
        "verification_uri_complete": "https://login.dingtalk.com/oauth2/device/verify?user_code=WXYZ-1234",
        "expires_in": 7200,
        "interval": 0.01,
    }
    payload.update(overrides)
    return payload


def _success_payload() -> dict:
    return {
        "errcode": 0,
        "errmsg": "ok",
        "status": "SUCCESS",
        "client_id": "ding_scanned_client",
        "client_secret": SECRET,
    }


def _service(handler) -> AppRegistrationService:
    return AppRegistrationService(transport=httpx.MockTransport(handler))


async def _noop(*_args, **_kwargs) -> None:
    return None


def _fast(monkeypatch) -> None:
    """把轮询下限与重试窗口压到毫秒级，避免测试真的等 2 秒 / 2 分钟。"""
    monkeypatch.setattr(registration_module, "MIN_POLL_INTERVAL_SECONDS", 0.01)
    monkeypatch.setattr(registration_module, "DINGTALK_RETRY_WINDOW_SECONDS", 0.05)


def _run(handler, *, provider: str = "dingtalk"):
    """跑一次完整 start，返回快照与回调记录。"""

    async def scenario():
        service = _service(handler)
        recorded: dict = {}
        done = asyncio.Event()

        async def on_success(channel_id, app_id, app_secret, open_id):
            recorded.update(
                channel_id=channel_id, app_id=app_id, app_secret=app_secret, open_id=open_id
            )
            done.set()

        try:
            started = await service.start(
                channel_id="chan_dt",
                created_by="u_admin",
                on_success=on_success,
                provider=provider,
            )
            for _ in range(200):
                snapshot = service.get(started["session_id"])
                if snapshot["status"] not in {STATUS_PENDING}:
                    return started, snapshot, recorded
                await asyncio.sleep(0.02)
            return started, service.get(started["session_id"]), recorded
        finally:
            await service.shutdown()

    return asyncio.run(scenario())


# ---------- 协议层 ----------


def test_begin_uses_three_paths_json_body_and_raw_qr_url(monkeypatch):
    seen: list[tuple[str, str, dict]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(
            (request.url.path, request.headers.get("content-type", ""), _json_body(request))
        )
        if request.url.path == INIT_PATH:
            return httpx.Response(200, json=_init_payload())
        return httpx.Response(200, json=_begin_payload())

    _fast(monkeypatch)

    async def scenario():
        service = _service(handler)
        try:
            return await service.start(
                channel_id="chan_dt", created_by="u_admin", on_success=_noop,
                provider="dingtalk",
            )
        finally:
            await service.shutdown()

    snapshot = asyncio.run(scenario())

    assert [path for path, _, _ in seen] == [INIT_PATH, BEGIN_PATH]
    # 钉钉走 JSON（实测两种都收，选 JSON 与两个参考实现一致）。
    assert all("application/json" in ctype for _, ctype, _ in seen)
    assert seen[0][2] == {"source": "UniEmployee"}
    assert seen[1][2] == {"nonce": "nr_test_nonce"}

    assert snapshot["provider"] == "dingtalk"
    assert snapshot["user_code"] == "WXYZ-1234"
    assert snapshot["expire_in"] == 7200
    assert "device_code" not in snapshot
    # 二维码 URL 原样使用：钉钉不接受也不需要飞书那套 from/tp 覆写。
    assert snapshot["qr_url"] == (
        "https://login.dingtalk.com/oauth2/device/verify?user_code=WXYZ-1234"
    )
    assert "from=" not in snapshot["qr_url"]


def test_poll_interval_floor_is_applied(monkeypatch):
    """服务端返回 0.5s 时按常量下限处理（参考实现用 2s 兜底）。"""
    monkeypatch.setattr(registration_module, "MIN_POLL_INTERVAL_SECONDS", 2.0)

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == INIT_PATH:
            return httpx.Response(200, json=_init_payload())
        if request.url.path == BEGIN_PATH:
            return httpx.Response(200, json=_begin_payload(interval=0.5))
        return httpx.Response(200, json={"errcode": 0, "status": "WAITING"})

    async def scenario():
        service = _service(handler)
        try:
            started = await service.start(
                channel_id="chan_dt", created_by="u", on_success=_noop, provider="dingtalk"
            )
            return started, await service.cancel(started["session_id"])
        finally:
            await service.shutdown()

    started, _ = asyncio.run(scenario())
    assert started["interval"] == 2.0


def test_poll_success_calls_back_with_credentials_and_no_open_id(monkeypatch):
    _fast(monkeypatch)

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == INIT_PATH:
            return httpx.Response(200, json=_init_payload())
        if request.url.path == BEGIN_PATH:
            return httpx.Response(200, json=_begin_payload())
        return httpx.Response(200, json=_success_payload())

    _, snapshot, recorded = _run(handler)

    assert recorded["channel_id"] == "chan_dt"
    assert recorded["app_id"] == "ding_scanned_client"
    assert recorded["app_secret"] == SECRET
    # 钉钉 Device Flow 不返回用户身份，open_id 必须为空而不是伪造。
    assert recorded["open_id"] is None

    assert snapshot["status"] == STATUS_SUCCESS
    assert snapshot["app_id"] == "ding_scanned_client"
    assert snapshot["open_id"] is None
    assert snapshot["qr_url"] is None
    assert SECRET not in json.dumps(snapshot)


def test_waiting_then_success_keeps_polling(monkeypatch):
    _fast(monkeypatch)
    polls = {"count": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == INIT_PATH:
            return httpx.Response(200, json=_init_payload())
        if request.url.path == BEGIN_PATH:
            return httpx.Response(200, json=_begin_payload())
        polls["count"] += 1
        if polls["count"] < 3:
            return httpx.Response(200, json={"errcode": 0, "status": "WAITING"})
        return httpx.Response(200, json=_success_payload())

    _, snapshot, _ = _run(handler)

    assert polls["count"] >= 3
    assert snapshot["status"] == STATUS_SUCCESS


def test_fail_status_keeps_polling_within_retry_window(monkeypatch):
    """`FAIL` 是瞬时态：窗口内不判死，继续轮（两套参考实现的共同做法）。"""
    _fast(monkeypatch)
    polls = {"count": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == INIT_PATH:
            return httpx.Response(200, json=_init_payload())
        if request.url.path == BEGIN_PATH:
            return httpx.Response(200, json=_begin_payload())
        polls["count"] += 1
        if polls["count"] == 1:
            return httpx.Response(
                200, json={"errcode": 0, "status": "FAIL", "fail_reason": "transient"}
            )
        return httpx.Response(200, json=_success_payload())

    _, snapshot, _ = _run(handler)

    assert polls["count"] >= 2
    assert snapshot["status"] == STATUS_SUCCESS


def test_fail_status_beyond_retry_window_becomes_error(monkeypatch):
    _fast(monkeypatch)

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == INIT_PATH:
            return httpx.Response(200, json=_init_payload())
        if request.url.path == BEGIN_PATH:
            return httpx.Response(200, json=_begin_payload())
        return httpx.Response(
            200, json={"errcode": 0, "status": "FAIL", "fail_reason": "应用名重复"}
        )

    _, snapshot, _ = _run(handler)

    assert snapshot["status"] == STATUS_ERROR
    assert "应用名重复" in snapshot["error"]


def test_expired_status_is_terminal(monkeypatch):
    _fast(monkeypatch)

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == INIT_PATH:
            return httpx.Response(200, json=_init_payload())
        if request.url.path == BEGIN_PATH:
            return httpx.Response(200, json=_begin_payload())
        return httpx.Response(200, json={"errcode": 0, "status": "EXPIRED"})

    _, snapshot, _ = _run(handler)

    assert snapshot["status"] == STATUS_EXPIRED
    assert snapshot["qr_url"] is None


def test_success_without_credentials_is_error(monkeypatch):
    _fast(monkeypatch)

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == INIT_PATH:
            return httpx.Response(200, json=_init_payload())
        if request.url.path == BEGIN_PATH:
            return httpx.Response(200, json=_begin_payload())
        return httpx.Response(200, json={"errcode": 0, "status": "SUCCESS"})

    _, snapshot, recorded = _run(handler)

    assert snapshot["status"] == STATUS_ERROR
    assert not recorded
    assert "未返回完整凭据" in snapshot["error"]


def test_network_error_within_window_keeps_polling(monkeypatch):
    _fast(monkeypatch)
    polls = {"count": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == INIT_PATH:
            return httpx.Response(200, json=_init_payload())
        if request.url.path == BEGIN_PATH:
            return httpx.Response(200, json=_begin_payload())
        polls["count"] += 1
        if polls["count"] == 1:
            raise httpx.ConnectError("temporary failure")
        return httpx.Response(200, json=_success_payload())

    _, snapshot, _ = _run(handler)

    assert polls["count"] >= 2
    assert snapshot["status"] == STATUS_SUCCESS


def test_nonzero_errcode_on_init_falls_back_to_manual(monkeypatch):
    _fast(monkeypatch)

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"errcode": 40078, "errmsg": "不合法请求"})

    async def scenario():
        service = _service(handler)
        try:
            await service.start(
                channel_id="chan_dt", created_by="u", on_success=_noop, provider="dingtalk"
            )
        finally:
            await service.shutdown()

    with pytest.raises(RegistrationUnavailable) as excinfo:
        asyncio.run(scenario())
    assert "40078" in str(excinfo.value)
    assert "不合法请求" in str(excinfo.value)


def test_nonzero_errcode_on_begin_falls_back_to_manual(monkeypatch):
    _fast(monkeypatch)

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == INIT_PATH:
            return httpx.Response(200, json=_init_payload())
        return httpx.Response(200, json={"errcode": 500005, "errmsg": "invalid nonce"})

    async def scenario():
        service = _service(handler)
        try:
            await service.start(
                channel_id="chan_dt", created_by="u", on_success=_noop, provider="dingtalk"
            )
        finally:
            await service.shutdown()

    with pytest.raises(RegistrationUnavailable) as excinfo:
        asyncio.run(scenario())
    assert "invalid nonce" in str(excinfo.value)


def test_unknown_provider_cannot_start_scan(monkeypatch):
    _fast(monkeypatch)

    async def scenario():
        service = _service(lambda request: httpx.Response(200, json={}))
        try:
            await service.start(
                channel_id="chan_x", created_by="u", on_success=_noop, provider="wecom"
            )
        finally:
            await service.shutdown()

    with pytest.raises(RegistrationUnavailable):
        asyncio.run(scenario())


def test_scan_registry_lists_both_providers():
    assert supported_scan_providers() == frozenset({"feishu", "dingtalk"})
    assert scan_provider_label("dingtalk") == "钉钉"
    assert scan_provider_label("feishu") == "飞书"


def test_feishu_flow_still_requires_form_encoding(monkeypatch):
    """守住飞书那条链路的实测约束：它只认 form-urlencoded。"""
    _fast(monkeypatch)
    content_types: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        content_types.append(request.headers.get("content-type", ""))
        if "action=init" in request.content.decode():
            return httpx.Response(200, json={"supported_auth_methods": ["client_secret"]})
        return httpx.Response(
            200,
            json={
                "device_code": "dc",
                "verification_uri_complete": "https://accounts.feishu.cn/x",
                "interval": 0.01,
                "expires_in": 3600,
            },
        )

    async def scenario():
        service = _service(handler)
        try:
            started = await service.start(
                channel_id="chan_fs", created_by="u", on_success=_noop, provider="feishu"
            )
            await service.cancel(started["session_id"])
        finally:
            await service.shutdown()

    asyncio.run(scenario())
    assert content_types
    assert all("application/x-www-form-urlencoded" in value for value in content_types)


# ---------- 接口层 ----------


def _route_app(monkeypatch):
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == INIT_PATH:
            return httpx.Response(200, json=_init_payload())
        if request.url.path == BEGIN_PATH:
            return httpx.Response(200, json=_begin_payload())
        return httpx.Response(200, json=_success_payload())

    service = AppRegistrationService(transport=httpx.MockTransport(handler))
    monkeypatch.setattr(im_routes, "app_registration", service)

    reconciled: list[str | None] = []

    async def fake_reconcile(*, force_channel_id: str | None = None, **_kwargs) -> None:
        reconciled.append(force_channel_id)

    monkeypatch.setattr(registry_module.registry, "reconcile", fake_reconcile)

    app = FastAPI()
    app.include_router(im_routes.router)
    app.dependency_overrides[auth.get_current_user_or_fallback] = lambda: {
        "id": "u_admin",
        "username": "admin",
        "role": "admin",
    }
    return app, reconciled, service


def test_dingtalk_channel_can_scan_end_to_end(monkeypatch):
    _fast(monkeypatch)
    app, reconciled, _ = _route_app(monkeypatch)

    def _bodies(request: httpx.Request) -> dict:
        try:
            return json.loads(request.content.decode("utf-8"))
        except Exception:  # noqa: BLE001
            return {}

    with TestClient(app) as client:
        created = client.post(
            "/api/im/channels",
            json={
                "name": "钉钉扫码通道",
                "description": "扫码回归",
                "provider": "dingtalk",
                "enabled": True,
                "employee_ids": ["xiaoshu"],
            },
        )
        assert created.status_code == 200, created.text
        channel_id = created.json()["id"]

        started = client.post(f"/api/im/channels/{channel_id}/registration/start")
        assert started.status_code == 200, started.text
        payload = started.json()
        assert payload["provider"] == "dingtalk"
        assert payload["status"] == "pending"
        assert "device_code" not in payload
        assert SECRET not in json.dumps(payload)
        # 钉钉的 request body 是 JSON，不是飞书那种表单。
        assert payload["qr_url"].startswith("https://login.dingtalk.com/")

        deadline = time.time() + 5
        while time.time() < deadline:
            status = client.get(
                f"/api/im/channels/{channel_id}/registration/{payload['session_id']}"
            )
            assert status.status_code == 200, status.text
            snapshot = status.json()
            if snapshot["status"] != "pending":
                break
            time.sleep(0.05)

        assert snapshot["status"] == "success"
        assert snapshot["app_id"] == "ding_scanned_client"
        assert SECRET not in json.dumps(snapshot)
        assert snapshot["credential"]["configured"] is True
        assert channel_id in reconciled

    credential = get_credential(channel_id)
    assert credential is not None
    assert credential.app_id == "ding_scanned_client"
    assert credential.app_secret == SECRET
    # 钉钉扫码不返回 corpId，留空由事件里的 chatbotCorpId 兜底识别租户。
    assert credential.tenant_key == ""


def test_non_scan_channel_is_rejected_with_provider_neutral_message(monkeypatch):
    _fast(monkeypatch)
    app, _, _ = _route_app(monkeypatch)

    with TestClient(app) as client:
        created = client.post(
            "/api/im/channels",
            json={
                "name": "web 通道",
                "description": "",
                "provider": "web",
                "enabled": True,
                "employee_ids": [],
            },
        )
        assert created.status_code == 200, created.text
        channel_id = created.json()["id"]

        rejected = client.post(f"/api/im/channels/{channel_id}/registration/start")
        assert rejected.status_code == 400
        assert "不支持扫码" in rejected.json()["detail"]
