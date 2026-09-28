"""后台运行与事件重放：断开订阅不取消执行。"""

import asyncio
import json
from types import SimpleNamespace

import pytest

from app import agent_runs, conversations
from app.auth_context import AuthContext
from app.models import MessageIn
from app.streaming import sse


def _create():
    agent_runs.init_tables()
    conversations.create("c_agent_run", "xiaoxiao", user_id="u1", tenant_id="t1")
    return agent_runs.create(conv_id="c_agent_run", tenant_id="t1",
                             user_id="u1", employee_id="xiaoxiao")


def test_run_store_replay_and_single_active():
    run = _create()
    assert run["status"] == "queued"
    assert agent_runs.events_after(run["id"], 0)[0]["payload"]["type"] == "run_started"
    with pytest.raises(agent_runs.ActiveRunError) as exc:
        _create()
    assert exc.value.run_id == run["id"]

    agent_runs.mark_running(run["id"])
    agent_runs.append_event(run["id"], {"type": "token", "content": "甲"})
    agent_runs.append_event(run["id"], {"type": "message_end", "run_id": "trace1"})
    batch = agent_runs.events_after(run["id"], 1)
    assert [x["seq"] for x in batch] == [2, 3]
    assert batch[0]["payload"]["content"] == "甲"
    agent_runs.finish(run["id"], "done")
    assert agent_runs.active_for_conversation("c_agent_run") is None


def test_recover_abandoned_releases_conversation():
    run = _create()
    agent_runs.mark_running(run["id"])
    assert agent_runs.recover_abandoned() == 1
    assert agent_runs.get(run["id"])["status"] == "abandoned"
    assert agent_runs.active_for_conversation("c_agent_run") is None
    assert _create()["id"] != run["id"]


def test_subscribe_reports_expired_terminal_events():
    async def scenario():
        run = _create()
        agent_runs.append_event(run["id"], {"type": "token", "content": "done"})
        agent_runs.finish(run["id"], "done")
        with agent_runs._conn() as con:
            con.execute("DELETE FROM agent_run_events WHERE run_id=?", (run["id"],))
        events = [json.loads(raw[6:]) async for raw in agent_runs.subscribe(run["id"])]
        assert events == [{"type": "error", "error_code": "run_events_expired",
                           "message": "运行事件已过保留期限，请刷新会话历史查看最终结果"}]

    asyncio.run(scenario())


def test_background_execution_survives_subscriber_disconnect(monkeypatch):
    async def scenario():
        run = _create()
        started = asyncio.Event()
        release = asyncio.Event()

        async def fake_stream(*args, **kwargs):
            yield sse({"type": "trace_started", "trace_run_id": "trace1"})
            yield sse({"type": "token", "content": "先"})
            started.set()
            await release.wait()
            yield sse({"type": "token", "content": "后"})
            yield sse({"type": "message_end", "run_id": "trace1"})

        monkeypatch.setattr(agent_runs, "_stream_run", fake_stream)
        agent_runs.launch(run["id"], {"messages": []}, user_id="u1", role="user",
                          tenant_id="t1")
        await started.wait()
        subscriber = agent_runs.subscribe(run["id"])
        first = json.loads((await anext(subscriber))[6:])
        assert first["type"] == "run_started"
        await subscriber.aclose()  # 模拟客户端断开
        assert agent_runs.get(run["id"])["status"] == "running"
        release.set()
        await agent_runs._tasks[run["id"]]
        assert agent_runs.get(run["id"])["status"] == "done"
        assert agent_runs.get(run["id"])["trace_run_id"] == "trace1"
        replay = [json.loads(raw[6:]) async for raw in agent_runs.subscribe(run["id"], 2)]
        assert [x["type"] for x in replay] == ["token", "message_end"]
        assert replay[0]["content"] == "先后"
        assert [x["_event_seq"] for x in replay] == [3, 4]

    asyncio.run(scenario())


def test_cancel_background_task(monkeypatch):
    async def scenario():
        run = _create()
        started = asyncio.Event()

        async def waiting_stream(*args, **kwargs):
            started.set()
            yield sse({"type": "token", "content": "运行中"})
            await asyncio.sleep(30)

        monkeypatch.setattr(agent_runs, "_stream_run", waiting_stream)
        agent_runs.launch(run["id"], {"messages": []}, user_id="u1", role="user",
                          tenant_id="t1")
        await started.wait()
        task = agent_runs._tasks[run["id"]]
        assert agent_runs.cancel(run["id"])
        with pytest.raises(asyncio.CancelledError):
            await task
        assert agent_runs.get(run["id"])["status"] == "cancelled"

    asyncio.run(scenario())


def test_run_routes_enforce_owner_and_tenant():
    from fastapi import HTTPException
    from app.routes.conversations import _owned_run

    run = _create()
    owner = SimpleNamespace(same_tenant=lambda t: t == "t1",
                            owns=lambda u: u == "u1", allows=lambda x: False,
                            user_id="u1")
    # 当前夹具没给 u1 指派员工；只验证越权在查员工指派之前被拦截。
    other_tenant = SimpleNamespace(same_tenant=lambda t: False,
                                   owns=lambda u: True)
    with pytest.raises(HTTPException) as exc:
        _owned_run(run["id"], other_tenant)
    assert exc.value.status_code == 404
    other_user = SimpleNamespace(same_tenant=lambda t: True,
                                 owns=lambda u: False)
    with pytest.raises(HTTPException) as exc:
        _owned_run(run["id"], other_user)
    assert exc.value.status_code == 403


def test_message_route_returns_run_id_and_rejects_parallel_turn(monkeypatch):
    from fastapi import HTTPException
    from app.routes.conversations import send_message

    conversations.create("c_route_run", "xiaoxiao", user_id="u1", tenant_id="t1")
    agent_runs.init_tables()
    context = AuthContext(user_id="u1", username="u1", tenant_id="t1",
                          org_id=None, org_ids=frozenset(), role="admin",
                          permissions=frozenset({"*"}))

    async def empty_subscribe(*args, **kwargs):
        if False:
            yield ""

    monkeypatch.setattr(agent_runs, "launch", lambda *args, **kwargs: None)
    monkeypatch.setattr(agent_runs, "subscribe", empty_subscribe)
    response = asyncio.run(send_message(
        "c_route_run", MessageIn(message="第一条"), context=context,
    ))
    run_id = response.headers["x-run-id"]
    assert run_id.startswith("ar_")
    assert agent_runs.get(run_id)["status"] == "queued"
    assert conversations.get("c_route_run")["message_count"] == 1
    with pytest.raises(HTTPException) as exc:
        asyncio.run(send_message(
            "c_route_run", MessageIn(message="不应写入"), context=context,
        ))
    assert exc.value.status_code == 409
    assert exc.value.detail["run_id"] == run_id
    assert conversations.get("c_route_run")["message_count"] == 1


def test_http_message_endpoint_replays_background_events(monkeypatch):
    import httpx
    from app import auth
    from app.main import app
    from app.streaming import conv_emp_map, conv_owner_map, conv_tenant_map

    conv_id = "c_http_run"
    agent_runs.init_tables()
    conversations.create(conv_id, "xiaoxiao", user_id="u1", tenant_id="t1")
    conv_emp_map[conv_id] = "xiaoxiao"
    conv_owner_map[conv_id] = "u1"
    conv_tenant_map[conv_id] = "t1"
    context = AuthContext(user_id="u1", username="u1", tenant_id="t1",
                          org_id=None, org_ids=frozenset(), role="admin",
                          permissions=frozenset({"*"}))
    app.dependency_overrides[auth.get_auth_context] = lambda: context

    async def fake_stream(*args, **kwargs):
        yield sse({"type": "trace_started", "trace_run_id": "trace-http"})
        yield sse({"type": "token", "content": "后台回答"})
        yield sse({"type": "message_end", "run_id": "trace-http"})

    monkeypatch.setattr(agent_runs, "_stream_run", fake_stream)

    async def request_flow():
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.post(
                f"/api/conversations/{conv_id}/messages",
                headers={"Authorization": "Bearer test"},
                json={"message": "验证后台运行"},
            )
            assert response.status_code == 200
            run_id = response.headers["x-run-id"]
            assert '"type": "token"' in response.text
            status = await client.get(f"/api/runs/{run_id}",
                                      headers={"Authorization": "Bearer test"})
            assert status.json()["status"] == "done"
            replay = await client.get(f"/api/runs/{run_id}/events?after=1",
                                      headers={"Authorization": "Bearer test"})
            assert '"content": "后台回答"' in replay.text

    try:
        asyncio.run(request_flow())
    finally:
        app.dependency_overrides.pop(auth.get_auth_context, None)
        conv_emp_map.pop(conv_id, None)
        conv_owner_map.pop(conv_id, None)
        conv_tenant_map.pop(conv_id, None)
