"""执行过程追踪（trace）模块测试：runs 生命周期、事件捕获、查询。"""
import asyncio
import uuid

import pytest

from app import traces


@pytest.fixture(autouse=True)
def tmp_traces_db(tmp_path, monkeypatch):
    monkeypatch.setattr(traces, "DB", tmp_path / "traces.db")
    yield


def test_run_lifecycle():
    rid = traces.start_run("c_t1", "xiaoshu", "u_t1", input_preview="你好", kind="message")
    assert rid.startswith("r_")
    runs = traces.list_runs("c_t1")
    assert len(runs) == 1
    assert runs[0]["status"] == "running"
    assert runs[0]["input_preview"] == "你好"

    traces.finish_run(rid, status="done")
    run = traces.get_run(rid)
    assert run["status"] == "done"
    assert run["ended_at"]
    assert run["duration_ms"] is not None
    assert run["events"] == []


def test_handler_captures_llm_and_tool_events():
    rid = traces.start_run("c_t2", "xiaoshu", "u_t1", input_preview="查数据")
    h = traces.TraceHandler(rid)

    class FakeMsg:
        content = "帮我查销售数据"

    async def drive():
        llm_id, tool_id = uuid.uuid4(), uuid.uuid4()
        await h.on_chat_model_start({"name": "deepseek"}, [[FakeMsg()]], run_id=llm_id)

        class Gen:
            text = "好的，我调用工具查询"
            message = None
        class Resp:
            generations = [[Gen()]]
            llm_output = {"token_usage": {"total_tokens": 123}}
        await h.on_llm_end(Resp(), run_id=llm_id)

        await h.on_tool_start({"name": "run_python"}, "print(1)", run_id=tool_id)
        await h.on_tool_end("执行结果: 1", run_id=tool_id)

    asyncio.run(drive())
    traces.finish_run(rid, status="done")

    run = traces.get_run(rid)
    assert run["llm_calls"] == 1 and run["tool_calls"] == 1
    assert run["total_tokens"] == 123
    evs = run["events"]
    assert len(evs) == 2
    llm_ev, tool_ev = evs[0], evs[1]
    assert llm_ev["etype"] == "llm" and llm_ev["name"] == "deepseek"
    assert llm_ev["status"] == "ok" and "调用工具" in llm_ev["output"]
    assert llm_ev["tokens"] == 123
    assert tool_ev["etype"] == "tool" and tool_ev["name"] == "run_python"
    assert "执行结果" in tool_ev["output"]
    assert tool_ev["duration_ms"] is not None


def test_handler_error_and_flush_pending():
    rid = traces.start_run("c_t3", "xiaoshu", "u_t1")
    h = traces.TraceHandler(rid)

    async def drive():
        bad_id, hang_id = uuid.uuid4(), uuid.uuid4()
        await h.on_tool_start({"name": "bad_tool"}, "x", run_id=bad_id)
        await h.on_tool_error(ValueError("boom"), run_id=bad_id)
        # 一个只 start 没 end 的事件（模拟中断），flush 后应落库为 running
        await h.on_tool_start({"name": "hang_tool"}, "y", run_id=hang_id)

    asyncio.run(drive())
    h.flush_pending()
    traces.finish_run(rid, status="interrupted")

    run = traces.get_run(rid)
    assert run["status"] == "interrupted"
    by_name = {e["name"]: e for e in run["events"]}
    assert by_name["bad_tool"]["status"] == "error"
    assert "boom" in by_name["bad_tool"]["output"]
    assert by_name["hang_tool"]["status"] == "running"


def test_query_isolation_and_missing():
    r1 = traces.start_run("c_a", "e1", "u1")
    traces.start_run("c_b", "e1", "u1")
    assert len(traces.list_runs("c_a")) == 1
    assert traces.list_runs("c_nothing") == []
    assert traces.get_run("r_missing") is None
    assert traces.get_run(r1)["conv_id"] == "c_a"
