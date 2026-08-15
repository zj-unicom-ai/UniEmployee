"""子代理配置/编译链路回归测试：EmployeeSpec、catalog 持久化、编译器装配。"""

import asyncio
import json
from pathlib import Path
from types import SimpleNamespace

from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

from app import catalog, compiler, runtime, traces
from app.spec import EmployeeSpec, load_spec
from app.streaming import _stream_run, conv_emp_map, reconstruct

PROJECT_ROOT = Path(__file__).resolve().parent.parent
XIAOXIAO_YAML = PROJECT_ROOT / "backend" / "employees" / "xiaoxiao.yaml"


def test_load_spec_parses_subagents():
    spec = load_spec(str(XIAOXIAO_YAML))
    assert len(spec.subagents) == 1
    agent = spec.subagents[0]
    assert agent["name"] == "research-agent"
    assert "kb_search" in agent["tools"]


def test_catalog_persists_subagents():
    catalog.create_employee({
        "id": "emp_sub1", "name": "子代理测试", "role": "测试",
        "model": "dummy-model", "persona": "测试人设",
        "subagents": [{"name": "researcher", "description": "调研",
                       "system_prompt": "只做调研", "tools": ["bocha_search"]}],
        "subagent_policy": "调研类任务必须委派",
    })
    cfg = catalog.get_employee_config("emp_sub1")
    assert cfg["subagents"][0]["name"] == "researcher"
    assert cfg["subagent_policy"] == "调研类任务必须委派"


def test_backfill_subagents_for_existing_seed_employee():
    catalog.create_employee({
        "id": "xiaoxiao", "name": "客户经理", "role": "客户经理",
        "model": "dummy-model", "persona": "测试",
    })
    assert catalog.get_employee_config("xiaoxiao")["subagents"] == []
    catalog.backfill_subagents_if_empty()
    cfg = catalog.get_employee_config("xiaoxiao")
    assert cfg["subagents"] and cfg["subagents"][0]["name"] == "research-agent"
    assert "research-agent" in cfg["subagent_policy"]


def test_compiler_passes_assembled_subagents(monkeypatch):
    captured = {}

    class FakeAgent:
        pass

    def fake_create_deep_agent(**kwargs):
        captured.update(kwargs)
        return FakeAgent()

    monkeypatch.setattr(compiler, "create_deep_agent", fake_create_deep_agent)
    spec = EmployeeSpec(
        id="emp_sub2", name="子代理编译", role="测试",
        model="dummy-model", persona="测试人设",
        subagents=[{
            "name": "researcher",
            "description": "调研子代理",
            "system_prompt": "只做调研并返回结论",
            "tools": ["bocha_search"],
        }],
        subagent_policy="调研类任务必须先委派 researcher",
    )
    asyncio.run(compiler.compile_agent(spec, checkpointer=None, store=None))

    subagents = captured["subagents"]
    assert len(subagents) == 1
    assert subagents[0]["name"] == "researcher"
    assert subagents[0]["model"] == "dummy-model"
    tool_names = {t.name for t in subagents[0]["tools"]}
    assert "bocha_search" in tool_names
    assert "get_current_time" in tool_names
    assert "子代理委派" in captured["system_prompt"]
    assert "researcher" in captured["system_prompt"]
    assert "调研类任务必须先委派 researcher" in captured["system_prompt"]


def test_stream_run_emits_subagent_events(monkeypatch):
    """v2 流式链路：task 工具调用发 started，ToolMessage 发 completed。"""
    conv_id = "c_sub_test"
    conv_emp_map[conv_id] = "xiaoxiao"

    class FakeAgent:
        async def astream(self, *args, **kwargs):
            yield {
                "type": "updates",
                "data": {
                    "model": {
                        "messages": [AIMessage(
                            content="",
                            tool_calls=[{
                                "name": "task",
                                "args": {"subagent_type": "research-agent", "description": "调研"},
                                "id": "call_1",
                                "type": "tool_call",
                            }],
                        )],
                    }
                },
            }
            yield {
                "type": "updates",
                "data": {
                    "tools": {
                        "messages": [ToolMessage(
                            content="子代理结果：A 产品适合", name="task", tool_call_id="call_1",
                        )],
                    }
                },
            }

    async def fake_get_agent(*args, **kwargs):
        return FakeAgent(), []

    async def noop_async(*args, **kwargs):
        pass

    def noop_sync(*args, **kwargs):
        return None

    monkeypatch.setattr(runtime, "get_agent", fake_get_agent)
    monkeypatch.setattr(runtime, "ensure_user_memory", noop_async)
    monkeypatch.setattr(traces, "start_run", lambda *a, **k: "r1")
    monkeypatch.setattr(traces, "TraceHandler",
                        lambda run_id: SimpleNamespace(flush_pending=noop_sync))
    monkeypatch.setattr(traces, "finish_run", noop_sync)

    events = []

    async def collect():
        async for line in _stream_run(
            conv_id, {"messages": [{"role": "user", "content": "调研"}]}, user_id="u1"
        ):
            events.append(json.loads(line[6:].strip()))

    asyncio.run(collect())
    subs = [e for e in events if e["type"] == "subagent"]
    assert [(s["name"], s["status"]) for s in subs] == [
        ("research-agent", "started"),
        ("research-agent", "completed"),
    ]
    assert subs[-1]["output"] == "子代理结果：A 产品适合"


def test_reconstruct_matches_tool_result_by_id_when_results_out_of_order():
    """#8：并行 ToolMessage 乱序返回时，结果按 tool_call_id 对应，不按顺序匹配。"""
    turns = reconstruct([
        HumanMessage(content="并行查一下"),
        AIMessage(content="", tool_calls=[
            {"name": "run_python", "args": {"code": "print(1)"}, "id": "call_a", "type": "tool_call"},
            {"name": "bocha_search", "args": {"query": "x"}, "id": "call_b", "type": "tool_call"},
        ]),
        ToolMessage(content="搜索命中", name="bocha_search", tool_call_id="call_b"),
        ToolMessage(content="1", name="run_python", tool_call_id="call_a"),
    ])
    tool_calls = turns[1]["tool_calls"]
    assert tool_calls[0]["id"] == "call_a"
    assert tool_calls[0]["result"] == "1"
    assert tool_calls[1]["id"] == "call_b"
    assert tool_calls[1]["result"] == "搜索命中"
