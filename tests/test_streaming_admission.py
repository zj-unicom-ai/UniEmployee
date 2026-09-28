"""确认流式 Agent 入口实际执行准入、Trace 拒绝收尾和槽位释放。"""

import asyncio
import json
from types import SimpleNamespace

from app import catalog, model_admission, runtime, traces
from app.streaming import _stream_run, conv_emp_map


def test_streaming_rejects_full_model_and_finishes_trace(monkeypatch):
    monkeypatch.setenv("MODEL_MAX_CONCURRENT", "1")
    monkeypatch.setenv("MODEL_MAX_QUEUE", "0")
    monkeypatch.setenv("MODEL_QUEUE_TIMEOUT_SEC", "1")
    model_admission.reset_for_tests()
    conv_id = "c_admission_reject"
    model_name = "openai:test-capacity-model"
    conv_emp_map[conv_id] = "test-capacity-employee"

    class Agent:
        async def aget_state_history(self, *args, **kwargs):
            if False:
                yield None

        async def astream(self, *args, **kwargs):
            raise AssertionError("准入失败后不能调用 Agent")
            yield None

    async def fake_get_agent(*args, **kwargs):
        return Agent(), []

    async def noop_async(*args, **kwargs):
        return None

    finished = []
    monkeypatch.setattr(runtime, "get_agent", fake_get_agent)
    monkeypatch.setattr(runtime, "ensure_user_memory", noop_async)
    monkeypatch.setattr(catalog, "get_employee_config", lambda _eid: {"model": model_name})
    monkeypatch.setattr(traces, "start_run", lambda *args, **kwargs: "trace_capacity_reject")
    monkeypatch.setattr(traces, "TraceHandler", lambda _rid: SimpleNamespace(flush_pending=lambda: None))
    monkeypatch.setattr(traces, "finish_run",
                        lambda run_id, status="done", error="": finished.append((run_id, status)))

    async def scenario():
        lease = await model_admission.acquire(model_name)
        try:
            events = [json.loads(line[6:].strip()) async for line in _stream_run(
                conv_id, {"messages": [{"role": "user", "content": "test"}]}, role="admin")]
        finally:
            model_admission.release(lease)
        return events

    try:
        events = asyncio.run(scenario())
    finally:
        conv_emp_map.pop(conv_id, None)
    error = next(event for event in events if event["type"] == "error")
    assert error["error_code"] == "model_capacity_exceeded"
    assert finished == [("trace_capacity_reject", "error")]
    assert model_admission.stats()["models"][0]["active"] == 0
