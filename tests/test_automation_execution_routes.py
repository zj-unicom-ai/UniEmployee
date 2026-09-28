"""自动化执行账本 HTTP 验收：Webhook 幂等、管理员查询和人工重跑权限。"""

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app import auth, automations, streaming
from app.routes.automations import router


def _client(user=None):
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[auth.get_current_user_or_fallback] = lambda: user or {
        "id": "u_auto_admin", "username": "admin", "role": "admin",
    }
    return TestClient(app)


def test_webhook_idempotency_header_prevents_duplicate_agent_run(monkeypatch):
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
