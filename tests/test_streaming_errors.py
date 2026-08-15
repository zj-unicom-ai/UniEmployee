"""#16 SSE 错误分级：不向前端泄漏原始异常细节。"""

import asyncio
import json
from types import SimpleNamespace

import pytest

from app import runtime, traces
from app.streaming import _stream_run, conv_emp_map, employee_of


class BoomAgent:
    def __init__(self, exc):
        self.exc = exc

    async def astream(self, *args, **kwargs):
        yield {"type": "updates", "data": {"fake": {}}}
        raise self.exc


async def collect_error(exc):
    conv_emp_map["c_sse_err"] = "xiaosu"
    async def fake_get_agent(*args, **kwargs):
        return BoomAgent(exc), []

    async def noop_async(*args, **kwargs):
        pass

    def noop_sync(*args, **kwargs):
        return None

    monkeypatch = pytest.MonkeyPatch()
    monkeypatch.setattr(runtime, "get_agent", fake_get_agent)
    monkeypatch.setattr(runtime, "ensure_user_memory", noop_async)
    monkeypatch.setattr(traces, "start_run", lambda *a, **k: "r1")
    monkeypatch.setattr(traces, "TraceHandler",
                        lambda run_id: SimpleNamespace(flush_pending=noop_sync))
    monkeypatch.setattr(traces, "finish_run", noop_sync)
    events = []
    try:
        async for line in _stream_run("c_sse_err", {"messages": [{"role": "user", "content": "x"}]}):
            events.append(json.loads(line[6:].strip()))
    finally:
        monkeypatch.undo()
        conv_emp_map.pop("c_sse_err", None)
    return events


def test_employee_of_empty_directory_returns_empty(monkeypatch):
    monkeypatch.setattr(runtime, "discover_employees", lambda: [])
    assert employee_of("c_new_empty") == ""


def test_context_length_error_is_masked():
    events = asyncio.run(collect_error(RuntimeError("maximum context length: this token count exceeds the limit secret-detail")))
    errs = [e for e in events if e["type"] == "error"]
    assert errs and errs[-1]["error_code"] == "context_length"
    assert "secret-detail" not in errs[-1]["message"]
    assert errs[-1]["message"]


def test_generic_error_uses_internal_code():
    events = asyncio.run(collect_error(RuntimeError("boom: secret-detail")))
    errs = [e for e in events if e["type"] == "error"]
    assert errs and errs[-1]["error_code"] == "internal_error"
    assert "secret-detail" not in errs[-1]["message"]


def test_timeout_error_maps_to_timeout():
    events = asyncio.run(collect_error(TimeoutError("timed out")))
    errs = [e for e in events if e["type"] == "error"]
    assert errs and errs[-1]["error_code"] == "timeout"
