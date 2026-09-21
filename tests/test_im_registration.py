"""飞书扫码一键创建应用（路径 B）的协议层测试。

全部使用 `httpx.MockTransport`，不联网，不写数据库。
覆盖文档 `docs/飞书扫码一键接入方案.md` §3 的协议事实与 §7.2 的接口约束。
"""

import asyncio
import json
from urllib.parse import parse_qs

import httpx
import pytest

from app.im.registration import (
    AppRegistrationService,
    RegistrationUnavailable,
    STATUS_CANCELLED,
    STATUS_DENIED,
    STATUS_ERROR,
    STATUS_EXPIRED,
    STATUS_PENDING,
    STATUS_SUCCESS,
)

FEISHU_HOST = "accounts.feishu.cn"
LARK_HOST = "accounts.larksuite.com"


def _body(request: httpx.Request) -> dict:
    """注册接口用 form-urlencoded（实测），这里按表单解析。"""
    parsed = parse_qs(request.content.decode("utf-8"))
    return {key: values[0] for key, values in parsed.items()}


def _begin_payload(**overrides) -> dict:
    payload = {
        "device_code": "dc_test",
        "user_code": "AB12-CD34",
        "verification_uri_complete": "https://accounts.feishu.cn/page/launcher?user_code=AB12-CD34",
        "expires_in": 3600,
        "interval": 0.01,
    }
    payload.update(overrides)
    return payload


def _success_payload() -> dict:
    return {
        "client_id": "cli_scanned",
        "client_secret": "scanned_secret_value",
        "user_info": {"open_id": "ou_owner", "tenant_brand": "feishu"},
    }


async def _noop(*_args, **_kwargs) -> None:
    return None


def _service(handler) -> AppRegistrationService:
    return AppRegistrationService(transport=httpx.MockTransport(handler))


def test_start_returns_decorated_qr_url_and_hides_device_code():
    calls: list[dict] = []
    content_types: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        payload = _body(request)
        calls.append(payload)
        content_types.append(request.headers.get("content-type", ""))
        if payload["action"] == "init":
            return httpx.Response(200, json={"supported_auth_methods": ["client_secret"]})
        return httpx.Response(200, json=_begin_payload())

    async def scenario():
        service = _service(handler)
        try:
            return await service.start(
                channel_id="chan_1", created_by="u_admin", on_success=_noop
            )
        finally:
            await service.shutdown()

    snapshot = asyncio.run(scenario())

    assert snapshot["status"] == STATUS_PENDING
    assert snapshot["channel_id"] == "chan_1"
    assert snapshot["user_code"] == "AB12-CD34"
    # 实测值 3600，不能用 SDK 源码里的兜底 600。
    assert snapshot["expire_in"] == 3600
    # 渠道标识换成我们自己的，user_code 原参数保留。
    assert "from=uniemployee" in snapshot["qr_url"]
    assert "tp=ue_web_scan" in snapshot["qr_url"]
    assert "user_code=AB12-CD34" in snapshot["qr_url"]
    # 对外快照不得泄露 device_code。
    assert "device_code" not in snapshot

    init_payload, begin_payload = calls[0], calls[1]
    assert init_payload == {"action": "init"}
    # 实测：该接口只接受 form-urlencoded，用 JSON body 会被判 invalid_request。
    assert all("application/x-www-form-urlencoded" in value for value in content_types)
    # archetype 由服务端锁死，必须是 PersonalAgent。
    assert begin_payload["archetype"] == "PersonalAgent"
    assert begin_payload["auth_method"] == "client_secret"
    assert begin_payload["request_user_info"] == "open_id"


def test_poll_success_invokes_callback_with_application_credentials():
    recorded: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        payload = _body(request)
        if payload["action"] == "init":
            return httpx.Response(200, json={"supported_auth_methods": ["client_secret"]})
        if payload["action"] == "begin":
            return httpx.Response(200, json=_begin_payload())
        return httpx.Response(200, json=_success_payload())

    async def scenario():
        service = _service(handler)
        done = asyncio.Event()

        async def on_success(channel_id, app_id, app_secret, open_id):
            recorded.update(
                channel_id=channel_id, app_id=app_id, app_secret=app_secret, open_id=open_id
            )
            done.set()

        try:
            started = await service.start(
                channel_id="chan_1", created_by="u_admin", on_success=on_success
            )
            await asyncio.wait_for(done.wait(), timeout=5)
            return service.get(started["session_id"])
        finally:
            await service.shutdown()

    snapshot = asyncio.run(scenario())

    # poll 返回的就是应用凭据本身：client_id = App ID，client_secret = App Secret。
    assert recorded["channel_id"] == "chan_1"
    assert recorded["app_id"] == "cli_scanned"
    assert recorded["app_secret"] == "scanned_secret_value"
    assert recorded["open_id"] == "ou_owner"

    assert snapshot["status"] == STATUS_SUCCESS
    assert snapshot["app_id"] == "cli_scanned"
    assert snapshot["open_id"] == "ou_owner"
    assert snapshot["qr_url"] is None
    # 成功后的快照既不含 App Secret，也不含 device_code。
    assert "scanned_secret_value" not in json.dumps(snapshot)
    assert "device_code" not in snapshot


def test_network_error_keeps_polling_until_success():
    attempts = {"poll": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        payload = _body(request)
        if payload["action"] == "init":
            return httpx.Response(200, json={"supported_auth_methods": ["client_secret"]})
        if payload["action"] == "begin":
            return httpx.Response(200, json=_begin_payload())
        attempts["poll"] += 1
        if attempts["poll"] == 1:
            raise httpx.ConnectError("temporary failure")
        return httpx.Response(200, json=_success_payload())

    async def scenario():
        service = _service(handler)
        done = asyncio.Event()

        async def on_success(*_args):
            done.set()

        try:
            started = await service.start(
                channel_id="chan_1", created_by="u_admin", on_success=on_success
            )
            await asyncio.wait_for(done.wait(), timeout=5)
            return service.get(started["session_id"])
        finally:
            await service.shutdown()

    snapshot = asyncio.run(scenario())

    assert attempts["poll"] >= 2
    assert snapshot["status"] == STATUS_SUCCESS


def test_access_denied_and_expired_token_are_terminal_states():
    def make_handler(error: str):
        def handler(request: httpx.Request) -> httpx.Response:
            payload = _body(request)
            if payload["action"] == "init":
                return httpx.Response(200, json={"supported_auth_methods": ["client_secret"]})
            if payload["action"] == "begin":
                return httpx.Response(200, json=_begin_payload())
            return httpx.Response(200, json={"error": error})

        return handler

    async def run(handler):
        service = _service(handler)
        try:
            started = await service.start(
                channel_id="chan_1", created_by="u_admin", on_success=_noop
            )
            for _ in range(50):
                snapshot = service.get(started["session_id"])
                if snapshot["status"] not in {STATUS_PENDING}:
                    return snapshot
                await asyncio.sleep(0.02)
            return service.get(started["session_id"])
        finally:
            await service.shutdown()

    denied = asyncio.run(run(make_handler("access_denied")))
    assert denied["status"] == STATUS_DENIED

    expired = asyncio.run(run(make_handler("expired_token")))
    assert expired["status"] == STATUS_EXPIRED


def test_unexpected_poll_error_is_reported_without_leaking_secrets():
    def handler(request: httpx.Request) -> httpx.Response:
        payload = _body(request)
        if payload["action"] == "init":
            return httpx.Response(200, json={"supported_auth_methods": ["client_secret"]})
        if payload["action"] == "begin":
            return httpx.Response(200, json=_begin_payload())
        return httpx.Response(200, json={"error": "invalid_grant", "error_description": "bad code"})

    async def scenario():
        service = _service(handler)
        try:
            started = await service.start(
                channel_id="chan_1", created_by="u_admin", on_success=_noop
            )
            for _ in range(50):
                snapshot = service.get(started["session_id"])
                if snapshot["status"] not in {STATUS_PENDING}:
                    return snapshot
                await asyncio.sleep(0.02)
            return service.get(started["session_id"])
        finally:
            await service.shutdown()

    snapshot = asyncio.run(scenario())

    assert snapshot["status"] == STATUS_ERROR
    assert "invalid_grant" in snapshot["error"]
    assert "scanned_secret_value" not in json.dumps(snapshot)


def test_cancel_stops_background_polling():
    def handler(request: httpx.Request) -> httpx.Response:
        payload = _body(request)
        if payload["action"] == "init":
            return httpx.Response(200, json={"supported_auth_methods": ["client_secret"]})
        if payload["action"] == "begin":
            return httpx.Response(200, json=_begin_payload())
        return httpx.Response(200, json={"error": "authorization_pending"})

    async def scenario():
        service = _service(handler)
        try:
            started = await service.start(
                channel_id="chan_1", created_by="u_admin", on_success=_noop
            )
            await asyncio.sleep(0.05)
            cancelled = await service.cancel(started["session_id"])
            return cancelled, service.get(started["session_id"])
        finally:
            await service.shutdown()

    cancelled, snapshot = asyncio.run(scenario())

    assert cancelled["status"] == STATUS_CANCELLED
    assert snapshot["status"] == STATUS_CANCELLED
    assert snapshot["qr_url"] is None


def test_restarting_on_same_channel_cancels_previous_session():
    def handler(request: httpx.Request) -> httpx.Response:
        payload = _body(request)
        if payload["action"] == "init":
            return httpx.Response(200, json={"supported_auth_methods": ["client_secret"]})
        if payload["action"] == "begin":
            return httpx.Response(200, json=_begin_payload())
        return httpx.Response(200, json={"error": "authorization_pending"})

    async def scenario():
        service = _service(handler)
        try:
            first = await service.start(channel_id="chan_1", created_by="u", on_success=_noop)
            second = await service.start(channel_id="chan_1", created_by="u", on_success=_noop)
            await asyncio.sleep(0.02)
            return service.get(first["session_id"]), service.get(second["session_id"])
        finally:
            await service.shutdown()

    first_snapshot, second_snapshot = asyncio.run(scenario())

    assert first_snapshot["status"] == STATUS_CANCELLED
    assert second_snapshot["status"] == STATUS_PENDING


def test_lark_tenant_switches_domain_and_retries():
    hosts: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        payload = _body(request)
        hosts.append(request.url.host)
        if payload["action"] == "init":
            return httpx.Response(200, json={"supported_auth_methods": ["client_secret"]})
        if payload["action"] == "begin":
            return httpx.Response(200, json=_begin_payload())
        if request.url.host == FEISHU_HOST:
            return httpx.Response(200, json={"user_info": {"tenant_brand": "lark"}})
        return httpx.Response(200, json=_success_payload())

    async def scenario():
        service = _service(handler)
        done = asyncio.Event()

        async def on_success(*_args):
            done.set()

        try:
            started = await service.start(
                channel_id="chan_1", created_by="u_admin", on_success=on_success
            )
            await asyncio.wait_for(done.wait(), timeout=5)
            return service.get(started["session_id"])
        finally:
            await service.shutdown()

    snapshot = asyncio.run(scenario())

    assert snapshot["status"] == STATUS_SUCCESS
    assert LARK_HOST in hosts


def test_environment_check_rejects_unsupported_auth_method():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"supported_auth_methods": ["private_key_jwt"]})

    async def scenario():
        service = _service(handler)
        try:
            await service.start(channel_id="chan_1", created_by="u_admin", on_success=_noop)
        finally:
            await service.shutdown()

    with pytest.raises(RegistrationUnavailable):
        asyncio.run(scenario())


def test_begin_failure_raises_unavailable_so_page_can_fall_back():
    def handler(request: httpx.Request) -> httpx.Response:
        payload = _body(request)
        if payload["action"] == "init":
            return httpx.Response(200, json={"supported_auth_methods": ["client_secret"]})
        return httpx.Response(
            400, json={"error": "invalid_request", "error_description": "unsupported"}
        )

    async def scenario():
        service = _service(handler)
        try:
            await service.start(channel_id="chan_1", created_by="u_admin", on_success=_noop)
        finally:
            await service.shutdown()

    with pytest.raises(RegistrationUnavailable):
        asyncio.run(scenario())
