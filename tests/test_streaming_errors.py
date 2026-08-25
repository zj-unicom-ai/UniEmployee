"""#16 SSE 错误分级：不向前端泄漏原始异常细节。"""

import asyncio
import json
from types import SimpleNamespace

import pytest
from langchain_core.messages import ToolMessage

from app import runtime, traces
from app.streaming import _stream_run, conv_emp_map, employee_of


class BoomAgent:
    def __init__(self, exc):
        self.exc = exc
        self.updated_states = []

    async def astream(self, *args, **kwargs):
        yield {"type": "updates", "data": {"fake": {}}}
        raise self.exc

    async def aupdate_state(self, config, values):
        self.updated_states.append(values)


async def collect_error(exc):
    conv_emp_map["c_sse_err"] = "xiaosu"
    agent = BoomAgent(exc)

    async def fake_get_agent(*args, **kwargs):
        return agent, []

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
    return events, agent


def test_employee_of_empty_directory_returns_empty(monkeypatch):
    monkeypatch.setattr(runtime, "discover_employees", lambda: [])
    assert employee_of("c_new_empty") == ""


def test_context_length_error_is_masked():
    events, _ = asyncio.run(collect_error(RuntimeError("maximum context length: this token count exceeds the limit secret-detail")))
    errs = [e for e in events if e["type"] == "error"]
    assert errs and errs[-1]["error_code"] == "context_length"
    assert "secret-detail" not in errs[-1]["message"]
    assert errs[-1]["message"]


def test_generic_error_uses_internal_code():
    events, _ = asyncio.run(collect_error(RuntimeError("boom: secret-detail")))
    errs = [e for e in events if e["type"] == "error"]
    assert errs and errs[-1]["error_code"] == "internal_error"
    assert "secret-detail" not in errs[-1]["message"]


def test_timeout_error_maps_to_timeout():
    events, _ = asyncio.run(collect_error(TimeoutError("timed out")))
    errs = [e for e in events if e["type"] == "error"]
    assert errs and errs[-1]["error_code"] == "timeout"


def test_connection_refused_maps_to_upstream_unavailable():
    events, _ = asyncio.run(collect_error(RuntimeError("URLError: <urlopen error [Errno 61] Connection refused>")))
    errs = [e for e in events if e["type"] == "error"]
    assert errs and errs[-1]["error_code"] == "upstream_unavailable"
    assert "Errno 61" not in errs[-1]["message"]


def test_error_message_persisted_to_checkpoint():
    events, agent = asyncio.run(collect_error(RuntimeError("boom")))
    errs = [e for e in events if e["type"] == "error"]
    assert errs
    # 错误提示以 AIMessage 形式写入 checkpoint，刷新后历史可见
    assert len(agent.updated_states) == 1
    msgs = agent.updated_states[0]["messages"]
    assert len(msgs) == 1 and msgs[0].content.startswith("⚠ ")


def test_tool_error_status_passed_through():
    """工具异常包装为 status='error' 的 ToolMessage 时，SSE 事件应带 error 状态。"""

    class ToolErrAgent:
        async def astream(self, *args, **kwargs):
            yield {"type": "updates", "data": {"tools": {
                "messages": [ToolMessage(name="kb_search", content="URLError: connection refused",
                                         status="error", tool_call_id="t1")]
            }}}

    async def run():
        events = []
        async for line in _stream_run("c_tool_err", {"messages": [{"role": "user", "content": "x"}]}):
            events.append(json.loads(line[6:].strip()))
        return events

    conv_emp_map["c_tool_err"] = "xiaosu"
    monkeypatch = pytest.MonkeyPatch()
    monkeypatch.setattr(runtime, "get_agent",
                        lambda *a, **k: _async_return((ToolErrAgent(), [])))
    monkeypatch.setattr(runtime, "ensure_user_memory", _noop_async)
    monkeypatch.setattr(traces, "start_run", lambda *a, **k: "r2")
    monkeypatch.setattr(traces, "TraceHandler",
                        lambda run_id: SimpleNamespace(flush_pending=lambda: None))
    monkeypatch.setattr(traces, "finish_run", lambda *a, **k: None)
    try:
        events = asyncio.run(run())
    finally:
        monkeypatch.undo()
        conv_emp_map.pop("c_tool_err", None)
    tool_events = [e for e in events if e["type"] == "tool"]
    assert tool_events and tool_events[0]["status"] == "error"
    assert "URLError" in tool_events[0]["preview"]


async def _async_return(v):
    return v


async def _noop_async(*args, **kwargs):
    pass
