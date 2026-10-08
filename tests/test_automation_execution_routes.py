"""自动化执行账本 HTTP 验收：Webhook 幂等、管理员查询和人工重跑权限。"""

import hashlib
import hmac
import time

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app import auth, automations, catalog, streaming
from app.routes.automations import router


def _client(user=None):
    app = FastAPI()
    app.include_router(router)
    current_user = user or {
        "id": "u_auto_admin", "username": "admin", "role": "admin",
    }
    catalog.create_employee({"id": "xiaoshu", "name": "测试员工"})
    for uid in {"default", current_user["id"]}:
        tenant_id = current_user.get("tenant_id", "default") if uid == current_user["id"] else "default"
        role = current_user.get("role", "user") if uid == current_user["id"] else "user"
        catalog.create_user(uid, "!test-only", role=role, tenant_id=tenant_id, user_id=uid)
        catalog.assign_employee(uid, "xiaoshu", granted_by="test")
    app.dependency_overrides[auth.get_current_user_or_fallback] = lambda: current_user
    return TestClient(app)


def test_webhook_idempotency_header_prevents_duplicate_agent_run(monkeypatch):
    monkeypatch.setenv("APP_ENV", "development")
    calls = 0

    async def fake_stream(*args, **kwargs):
        nonlocal calls
        calls += 1
        yield 'data: {"type":"token","content":"ok"}\n\n'

    monkeypatch.setattr(streaming, "_stream_run", fake_stream)
    auto = automations.create("事件验收", "event", "xiaoshu", "处理 {{payload}}",
                              event_key="order.updated", secret="secret-1")
    client = _client()
    body = {"secret": "secret-1", "payload": {"order_id": "A-1"}}

    missing = client.post("/api/automations/events/order.updated", json=body)
    assert missing.status_code == 422
    first = client.post("/api/automations/events/order.updated", json=body,
                        headers={"Idempotency-Key": "evt-order-1"})
    replay = client.post("/api/automations/events/order.updated", json=body,
                         headers={"Idempotency-Key": "evt-order-1"})
    assert first.status_code == replay.status_code == 200
    assert first.json()["results"][0]["execution_id"] == replay.json()["results"][0]["execution_id"]
    assert replay.json()["results"][0]["duplicate"] is True
    assert calls == 1
    assert len(automations.list_executions(auto["id"])) == 1


def _signed_headers(body: bytes, secret: str, event_key: str, timestamp: str,
                    idempotency_key: str, tenant_id: str = "default") -> dict[str, str]:
    path = f"/api/automations/events/{event_key}"
    body_digest = hashlib.sha256(body).hexdigest()
    message = "\n".join(("v2", "POST", path, tenant_id, timestamp,
                          idempotency_key, body_digest)).encode()
    signature = hmac.new(secret.encode(), message, hashlib.sha256).hexdigest()
    return {
        "Content-Type": "application/json",
        "Idempotency-Key": idempotency_key,
        "X-UniEmployee-Timestamp": timestamp,
        "X-UniEmployee-Signature": signature,
    }


def test_webhook_signature_is_bound_to_tenant(monkeypatch):
    monkeypatch.setenv("APP_ENV", "production")
    catalog.create_employee({"id": "xiaoshu", "name": "测试员工"})
    for user_id, tenant_id in (("u_hook_a", "tenant-a"), ("u_hook_b", "tenant-b")):
        catalog.create_user(user_id, "!test-only", tenant_id=tenant_id, user_id=user_id)
        catalog.assign_employee(user_id, "xiaoshu", granted_by="test")
    executed_tenants = []

    async def fake_stream(conv_id, input_, **kwargs):
        executed_tenants.append(kwargs["tenant_id"])
        yield 'data: {"type":"token","content":"ok"}\n\n'

    monkeypatch.setattr(streaming, "_stream_run", fake_stream)
    shared_secret = "x" * 32
    first = automations.create("租户 A", "event", "xiaoshu", "处理",
                               event_key="shared.event", secret=shared_secret,
                               run_as="u_hook_a", tenant_id="tenant-a")
    automations.create("租户 B", "event", "xiaoshu", "处理",
                       event_key="shared.event", secret=shared_secret,
                       run_as="u_hook_b", tenant_id="tenant-b")
    body = b'{"payload":{"id":"a-1"}}'
    headers = _signed_headers(body, shared_secret, "shared.event", str(int(time.time())),
                              "evt-a", tenant_id="tenant-a")

    response = _client().post("/api/automations/events/shared.event",
                              content=body, headers=headers)

    assert response.status_code == 200
    assert [result["id"] for result in response.json()["results"]] == [first["id"]]
    assert executed_tenants == ["tenant-a"]


def test_webhook_hmac_authenticates_body_and_idempotency_key(monkeypatch):
    monkeypatch.setenv("APP_ENV", "production")
    calls = 0

    async def fake_stream(*args, **kwargs):
        nonlocal calls
        calls += 1
        yield 'data: {"type":"token","content":"ok"}\n\n'

    monkeypatch.setattr(streaming, "_stream_run", fake_stream)
    secret = "s" * 32
    auto = automations.create("签名事件", "event", "xiaoshu", "处理 {{payload}}",
                              event_key="order.signed", secret=secret)
    client = _client()
    raw_body = b'{"payload":{"order_id":"A-1"}}'
    timestamp = str(int(time.time()))
    headers = _signed_headers(raw_body, secret, "order.signed", timestamp, "evt-1")

    first = client.post("/api/automations/events/order.signed", content=raw_body,
                        headers=headers)
    replay = client.post("/api/automations/events/order.signed", content=raw_body,
                         headers=headers)
    changed_key = {**headers, "Idempotency-Key": "evt-2"}
    changed_key_replay = client.post("/api/automations/events/order.signed",
                                     content=raw_body, headers=changed_key)
    changed_body = b'{"payload":{"order_id":"A-2"}}'
    changed_body_replay = client.post("/api/automations/events/order.signed",
                                      content=changed_body, headers=headers)

    assert first.status_code == 200
    assert replay.status_code == 200
    assert replay.json()["results"][0]["duplicate"] is True
    assert changed_key_replay.status_code == 403
    assert changed_body_replay.status_code == 403
    assert calls == 1
    assert len(automations.list_executions(auto["id"])) == 1


def test_production_rejects_expired_legacy_weak_and_secretless_webhooks(monkeypatch):
    monkeypatch.setenv("APP_ENV", "production")
    calls = 0

    async def fake_stream(*args, **kwargs):
        nonlocal calls
        calls += 1
        yield 'data: {"type":"token","content":"ok"}\n\n'

    monkeypatch.setattr(streaming, "_stream_run", fake_stream)
    secret = "t" * 32
    auto = automations.create("过期签名", "event", "xiaoshu", "处理事件",
                              event_key="order.expired", secret=secret)
    client = _client()
    raw_body = b'{"payload":{"order_id":"A-1"}}'
    expired = str(int(time.time()) - 301)
    expired_headers = _signed_headers(raw_body, secret, "order.expired", expired, "evt-expired")
    expired_response = client.post("/api/automations/events/order.expired",
                                   content=raw_body, headers=expired_headers)
    legacy_response = client.post(
        "/api/automations/events/order.expired",
        json={"secret": secret, "payload": {"order_id": "A-1"}},
        headers={"Idempotency-Key": "evt-legacy"})

    weak_secret = "too-short"
    weak_auto = automations.create("弱密钥", "event", "xiaoshu", "处理事件",
                                   event_key="order.weak", secret=weak_secret)
    weak_body = b'{"payload":{"order_id":"A-3"}}'
    weak_timestamp = str(int(time.time()))
    weak_headers = _signed_headers(weak_body, weak_secret, "order.weak",
                                   weak_timestamp, "evt-weak")
    weak_response = client.post("/api/automations/events/order.weak",
                                content=weak_body, headers=weak_headers)

    secretless = automations.create("无密钥", "event", "xiaoshu", "处理事件",
                                    event_key="order.no-secret", secret="")
    unsigned_response = client.post(
        "/api/automations/events/order.no-secret", json={"payload": {"order_id": "A-2"}},
        headers={"Idempotency-Key": "evt-no-secret"})

    assert expired_response.status_code == 401
    assert legacy_response.status_code == 401
    assert weak_response.status_code == 403
    assert unsigned_response.status_code == 401
    assert calls == 0
    assert automations.list_executions(auto["id"]) == []
    assert automations.list_executions(weak_auto["id"]) == []
    assert automations.list_executions(secretless["id"]) == []


def test_webhook_secret_is_not_returned_and_blank_update_preserves_it(monkeypatch):
    monkeypatch.setenv("APP_ENV", "development")
    monkeypatch.setattr("app.routes.automations.runtime.discover_employees",
                        lambda: [{"id": "xiaoshu"}])
    secret = "management-secret-32-characters-long"
    auto = automations.create("密钥脱敏", "event", "xiaoshu", "处理事件",
                              event_key="secret.redaction", secret=secret)
    client = _client()

    listed = client.get("/api/automations")
    listed_item = next(item for item in listed.json()["items"] if item["id"] == auto["id"])
    updated = client.put(f"/api/automations/{auto['id']}",
                         json={"name": "密钥仍保留", "secret": None})

    assert listed.status_code == 200
    assert "secret" not in listed_item
    assert listed_item["has_secret"] is True
    assert updated.status_code == 200
    assert "secret" not in updated.json()
    assert updated.json()["has_secret"] is True
    assert automations.get(auto["id"])["secret"] == secret


def test_enabled_production_webhook_requires_strong_secret(monkeypatch):
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setattr("app.routes.automations.runtime.discover_employees",
                        lambda: [{"id": "xiaoshu"}])
    response = _client().post("/api/automations", json={
        "name": "生产事件",
        "trigger_type": "event",
        "event_key": "production.event",
        "employee_id": "xiaoshu",
        "prompt": "处理事件",
        "enabled": True,
    })

    assert response.status_code == 400
    assert "secret" not in response.json()["detail"].lower()


def test_execution_history_and_retry_require_admin(monkeypatch):
    auto = automations.create("失败后可重跑", "event", "xiaoshu", "处理事件",
                              event_key="retry.event", enabled=False)
    failed, _ = automations.create_execution(auto["id"], "event", "evt-failed")
    automations.update_execution(failed["id"], "error", error="模型超时", finished=True)

    response = _client().get(f"/api/automations/{auto['id']}/executions")
    assert response.status_code == 200
    assert response.json()["items"][0]["error"] == "模型超时"

    denied = _client({"id": "u_reader", "username": "reader", "role": "user"}).get(
        f"/api/automations/{auto['id']}/executions")
    assert denied.status_code == 403

    calls = 0

    async def fake_stream(*args, **kwargs):
        nonlocal calls
        calls += 1
        yield 'data: {"type":"token","content":"重跑完成"}\n\n'

    monkeypatch.setattr(streaming, "_stream_run", fake_stream)
    retry = _client().post(
        f"/api/automations/{auto['id']}/executions/{failed['id']}/retry",
        json={"payload": {"event": "replayed"}},
        headers={"Idempotency-Key": "retry-key-1"},
    )
    assert retry.status_code == 200
    assert retry.json()["retry_of"] == failed["id"]
    assert calls == 1
