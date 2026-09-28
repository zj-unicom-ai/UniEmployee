"""子代理 task 工具的每轮调用数与并发预算验证。"""

import asyncio
from types import SimpleNamespace

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from pydantic import PrivateAttr

from app import subagent_budget
from app.subagent_budget import SubagentBudgetMiddleware


def _request(name="task", call_id="t1"):
    return SimpleNamespace(tool_call={"name": name, "id": call_id, "args": {}}, tool=None)


def test_task_tool_enforces_max_calls_per_run(monkeypatch):
    monkeypatch.setenv("SUBAGENT_MAX_CALLS_PER_RUN", "1")
    monkeypatch.setenv("SUBAGENT_MAX_CONCURRENT_PER_RUN", "0")
    budget, token = subagent_budget.begin_run()
    middleware = SubagentBudgetMiddleware()
    calls = 0

    async def handler(request):
        nonlocal calls
        calls += 1
        return ToolMessage(content="done", tool_call_id=request.tool_call["id"])

    async def scenario():
        first = await middleware.awrap_tool_call(_request(call_id="t1"), handler)
        second = await middleware.awrap_tool_call(_request(call_id="t2"), handler)
        return first, second

    try:
        first, second = asyncio.run(scenario())
        state = subagent_budget.snapshot(budget)
    finally:
        subagent_budget.end_run(token, budget)
    assert calls == 1
    assert first.content == "done"
    assert second.status == "error" and second.name == "task" and "上限" in second.content
    assert state["calls"] == 1 and state["rejected"] == 1


def test_task_tool_limits_parallel_subagents_and_tracks_wait(monkeypatch):
    monkeypatch.setenv("SUBAGENT_MAX_CALLS_PER_RUN", "4")
    monkeypatch.setenv("SUBAGENT_MAX_CONCURRENT_PER_RUN", "1")
    monkeypatch.setenv("SUBAGENT_QUEUE_TIMEOUT_SEC", "1")
    budget, token = subagent_budget.begin_run()
    middleware = SubagentBudgetMiddleware()
    active = 0
    peak = 0

    async def handler(request):
        nonlocal active, peak
        active += 1
        peak = max(peak, active)
        await asyncio.sleep(0.02)
        active -= 1
        return ToolMessage(content="done", tool_call_id=request.tool_call["id"])

    async def scenario():
        return await asyncio.gather(*[
            middleware.awrap_tool_call(_request(call_id=f"t{i}"), handler)
            for i in range(3)
        ])

    try:
        results = asyncio.run(scenario())
        state = subagent_budget.snapshot(budget)
    finally:
        subagent_budget.end_run(token, budget)
    assert all(r.status != "error" for r in results)
    assert peak == state["peak_concurrent"] == 1
    assert state["calls"] == 3
    assert state["wait_ms_total"] > 0


def test_other_tools_are_not_limited(monkeypatch):
    monkeypatch.setenv("SUBAGENT_MAX_CALLS_PER_RUN", "1")
    budget, token = subagent_budget.begin_run()
    middleware = SubagentBudgetMiddleware()

    async def handler(request):
        return ToolMessage(content="ok", tool_call_id=request.tool_call["id"])

    try:
        result = asyncio.run(middleware.awrap_tool_call(_request("kb_search"), handler))
        assert result.content == "ok"
        assert subagent_budget.snapshot(budget)["calls"] == 0
    finally:
        subagent_budget.end_run(token, budget)


def test_compiler_installs_budget_middleware_only_when_configured(monkeypatch):
    import asyncio
    from app import compiler
    from app.spec import EmployeeSpec

    monkeypatch.setenv("SUBAGENT_MAX_CALLS_PER_RUN", "2")
    monkeypatch.setenv("SUBAGENT_MAX_CONCURRENT_PER_RUN", "1")
    captured = {}

    async def no_tools(*args, **kwargs):
        return [], None

    async def no_subagents(*args, **kwargs):
        return []

    monkeypatch.setattr(compiler, "_assemble_tools", no_tools)
    monkeypatch.setattr(compiler, "_assemble_subagents", no_subagents)
    monkeypatch.setattr(compiler, "build_backends", lambda *args, **kwargs: object())
    monkeypatch.setattr(compiler, "create_deep_agent", lambda **kwargs: captured.update(kwargs) or object())
    monkeypatch.setattr(compiler, "_init_model", lambda model: model)
    spec = EmployeeSpec(id="budget-employee", name="预算员工", model="openai:test",
                        persona="验证", tools=[], subagents=[])

    asyncio.run(compiler.compile_agent(spec, None, None, user_id="budget-user"))
    middleware = captured["middleware"]
    budget_mw = next(m for m in middleware if isinstance(m, SubagentBudgetMiddleware))
    assert budget_mw._enforce_concurrency is True


def test_deepagents_task_tool_respects_budget_in_graph(monkeypatch):
    from deepagents import create_deep_agent

    class SequenceModel(BaseChatModel):
        _responses: list = PrivateAttr(default_factory=list)

        def __init__(self, responses):
            super().__init__()
            self._responses = list(responses)

        @property
        def _llm_type(self):
            return "uniemployee-budget-test"

        def bind_tools(self, tools, **kwargs):
            return self

        def _generate(self, messages, stop=None, run_manager=None, **kwargs):
            if not self._responses:
                raise AssertionError("fake model response sequence exhausted")
            message = self._responses.pop(0)
            return ChatResult(generations=[ChatGeneration(message=message)])

        async def _agenerate(self, messages, stop=None, run_manager=None, **kwargs):
            return self._generate(messages, stop=stop, run_manager=run_manager, **kwargs)

    monkeypatch.setenv("SUBAGENT_MAX_CALLS_PER_RUN", "1")
    monkeypatch.setenv("SUBAGENT_MAX_CONCURRENT_PER_RUN", "2")
    parent_model = SequenceModel([
        AIMessage(content="", tool_calls=[
            {"name": "task", "args": {"description": "first", "subagent_type": "worker"}, "id": "task-1"},
            {"name": "task", "args": {"description": "second", "subagent_type": "worker"}, "id": "task-2"},
        ]),
        AIMessage(content="已根据可用结果完成"),
    ])
    worker_model = SequenceModel([AIMessage(content="worker result")])
    agent = create_deep_agent(
        model=parent_model,
        subagents=[{"name": "worker", "description": "test worker", "model": worker_model,
                    "tools": [], "system_prompt": "return a short result"}],
        middleware=[SubagentBudgetMiddleware()],
    )
    budget, token = subagent_budget.begin_run()

    async def scenario():
        return await agent.ainvoke({"messages": [HumanMessage(content="test delegation cap")]})

    try:
        result = asyncio.run(scenario())
        state = subagent_budget.snapshot(budget)
    finally:
        subagent_budget.end_run(token, budget)
    assert result["messages"][-1].content == "已根据可用结果完成"
    assert state["calls"] == 1
    assert state["rejected"] == 1
