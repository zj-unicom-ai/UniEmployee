"""使用真实 Deep Agents 图验证技能重载、固定技能、工具门控及历史展示。"""
import asyncio

import pytest
from deepagents import create_deep_agent
from deepagents.backends import CompositeBackend, StateBackend, StoreBackend
from deepagents.backends.utils import create_file_data
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from langchain_core.tools import tool
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.store.memory import InMemoryStore
from pydantic import PrivateAttr

from app import runtime
from app.skill_runtime import BusinessSkillsMiddleware, split_skill_tools, validate_pinned_skills
from app.streaming import reconstruct


class RecordingModel(BaseChatModel):
    _responses: list = PrivateAttr(default_factory=list)
    _tools: list = PrivateAttr(default_factory=list)
    _calls: list = PrivateAttr(default_factory=list)

    def __init__(self, responses):
        super().__init__()
        self._responses = list(responses)

    @property
    def _llm_type(self):
        return "business-skills-test"

    def bind_tools(self, tools, **kwargs):
        self._tools = [t.get("name") if isinstance(t, dict) else t.name for t in tools]
        return self

    def _generate(self, messages, **kwargs):
        self._calls.append((list(self._tools), list(messages)))
        return ChatResult(generations=[ChatGeneration(message=self._responses.pop(0))])

    async def _agenerate(self, messages, **kwargs):
        return self._generate(messages, **kwargs)


def skill_file(tmp_path, name="impact", description="旧触发条件"):
    directory = tmp_path / name
    directory.mkdir(exist_ok=True)
    (directory / "SKILL.md").write_text(
        f"---\nname: {name}\ndescription: {description}\nmetadata:\n  include_tools: impact_lookup\n---\n\n# 故障影响分析\n\n## 规程\n内部规程正文\n")
    return directory


@tool
def impact_lookup() -> str:
    """查询故障影响。"""
    return "已核实影响范围"


def test_thread_reload_pin_and_tool_disclosure(tmp_path, monkeypatch):
    directory = skill_file(tmp_path)
    assigned = {"impact": str(directory)}
    monkeypatch.setattr(runtime.catalog, "get_skill_dirs_for_employee", lambda *args: dict(assigned))
    model = RecordingModel([
        AIMessage(content="普通回答"),
        AIMessage(content="", tool_calls=[{"name": "impact_lookup", "args": {}, "id": "lookup"}]),
        AIMessage(content="分析完成"),
        AIMessage(content="新描述已生效"),
        AIMessage(content="技能已移除"),
    ])
    store = InMemoryStore()
    monkeypatch.setattr(runtime, "_store", store)
    backend = CompositeBackend(default=StateBackend(), routes={
        "/skills/": StoreBackend(namespace=lambda rt: ("u1", "emp"))})
    middleware = BusinessSkillsMiddleware(employee_id="emp", user_id="u1", backend=backend,
                                          tools=[impact_lookup])
    agent = create_deep_agent(model=model, backend=backend, store=store,
                              checkpointer=InMemorySaver(), skills=["/skills/"],
                              middleware=[middleware])
    config = {"configurable": {"thread_id": "existing-thread"}}

    async def run():
        await runtime.sync_skills_to_store("emp", "u1")
        first = await agent.ainvoke({"messages": [HumanMessage(content="你好")]}, config)
        first_revision = first["business_skills_revision"]
        assert "impact_lookup" not in model._calls[0][0]
        second = await agent.ainvoke({"messages": [HumanMessage(content="评估故障")],
                                     "pinned_skills": ["impact"]}, config)
        assert "impact_lookup" in model._calls[1][0]
        assert any(isinstance(m, ToolMessage) and "已核实" in m.content for m in second["messages"])
        assert any(m.additional_kwargs.get("lc_source") == "pinned_skill" for m in second["messages"])
        history = reconstruct(second["messages"])
        assert [t["content"] for t in history if t["role"] == "user"] == ["你好", "评估故障"]

        skill_file(tmp_path, description="新触发条件")
        await runtime.sync_skills_to_store("emp", "u1")
        third = await agent.ainvoke({"messages": [HumanMessage(content="继续")]}, config)
        assert third["business_skills_revision"] != first_revision
        assert (await agent.aget_state(config)).values["skills_metadata"][0]["description"] == "新触发条件"
        system = str(model._calls[-1][1][0].content)
        assert "新触发条件" in system and "旧触发条件" not in system
        assert "内部规程正文" not in system

        assigned.clear()
        await runtime.sync_skills_to_store("emp", "u1")
        fourth = await agent.ainvoke({"messages": [HumanMessage(content="再查询")]}, config)
        assert (await agent.aget_state(config)).values["skills_metadata"] == []
        assert "impact_lookup" not in model._calls[-1][0]
        assert await store.aget(("u1", "emp"), "/impact/SKILL.md") is None
        assert len([m for m in fourth["messages"] if isinstance(m, AIMessage)]) == 5
    asyncio.run(run())


def test_skill_tool_gate_rejects_call_before_read(tmp_path, monkeypatch):
    directory = skill_file(tmp_path)
    monkeypatch.setattr(runtime.catalog, "get_skill_dirs_for_employee", lambda *args: {"impact": str(directory)})
    store = InMemoryStore()
    monkeypatch.setattr(runtime, "_store", store)
    backend = CompositeBackend(default=StateBackend(), routes={
        "/skills/": StoreBackend(namespace=lambda rt: ("u1", "emp"))})
    model = RecordingModel([
        AIMessage(content="", tool_calls=[{"name": "impact_lookup", "args": {}, "id": "early"}]),
        AIMessage(content="", tool_calls=[{"name": "read_file", "args": {"file_path": "/skills/impact/SKILL.md"}, "id": "read"}]),
        AIMessage(content="", tool_calls=[{"name": "impact_lookup", "args": {}, "id": "allowed"}]),
        AIMessage(content="完成"),
    ])
    agent = create_deep_agent(model=model, backend=backend, store=store,
                              skills=["/skills/"], middleware=[BusinessSkillsMiddleware(
                                  employee_id="emp", user_id="u1", backend=backend, tools=[impact_lookup])])
    async def run():
        await runtime.sync_skills_to_store("emp", "u1")
        result = await agent.ainvoke({"messages": [HumanMessage(content="故障分析")]})
        outputs = {m.tool_call_id: m for m in result["messages"] if isinstance(m, ToolMessage)}
        assert outputs["early"].status == "error"
        assert "已核实" in outputs["allowed"].content
        assert "impact_lookup" not in model._calls[0][0]
        assert "impact_lookup" in model._calls[2][0]
    asyncio.run(run())


def test_selection_uses_effective_user_skills(tmp_path, monkeypatch):
    own = skill_file(tmp_path, "own")
    other = skill_file(tmp_path, "other")
    monkeypatch.setattr(runtime.catalog, "get_skill_dirs_for_employee",
                        lambda emp, user: {"own": str(own)} if user == "u1" else {"other": str(other)})
    assert validate_pinned_skills("emp", "u1", ["own", "own"]) == ["own"]
    with pytest.raises(ValueError):
        validate_pinned_skills("emp", "u1", ["other"])


def test_binding_preserves_approval_and_global_tools():
    @tool
    def get_current_time() -> str:
        """当前时间。"""
        return "now"
    snapshot = [{"include_tools": ["impact_lookup", "get_current_time", "unauthorized_tool"]}]
    always, bound = split_skill_tools([impact_lookup, get_current_time], snapshot)
    assert always == [get_current_time]
    assert bound == [impact_lookup]
    always, bound = split_skill_tools([impact_lookup], snapshot, approval_tools={"impact_lookup"})
    assert always == [impact_lookup] and bound == []


def test_recovery_ignores_pinned_instruction_for_report_turn(monkeypatch):
    from app import report_artifacts
    calls = []
    monkeypatch.setattr(report_artifacts, "archive_inline_reports",
                        lambda content, user, conv, turn: calls.append(turn) or [])
    messages = [HumanMessage(content="用户问题"), HumanMessage(content="内部规程", additional_kwargs={
        "lc_source": "pinned_skill"}), AIMessage(content="报告")]
    report_artifacts.archive_assistant_reports(messages, "u1", "conv")
    assert calls == [1]


def test_message_endpoint_validates_selection_before_starting_run(tmp_path, monkeypatch):
    from fastapi import HTTPException
    from app import conversations, agent_runs
    from app.auth_context import AuthContext
    from app.models import MessageIn
    from app.routes.conversations import send_message, list_employee_skills

    directory = skill_file(tmp_path)
    monkeypatch.setattr(runtime.catalog, "get_skill_dirs_for_employee", lambda *args: {"impact": str(directory)})
    context = AuthContext(user_id="u1", username="u1", tenant_id="t1", role="admin",
                          org_id=None, org_ids=frozenset(), permissions=frozenset({"*"}))
    conversations.create("selected-skill", "emp", user_id="u1", tenant_id="t1")
    agent_runs.init_tables()
    captured = []
    monkeypatch.setattr(agent_runs, "launch", lambda run_id, input_, **kw: captured.append(input_))
    async def subscribe(*args):
        if False:
            yield ""
    monkeypatch.setattr(agent_runs, "subscribe", subscribe)

    with pytest.raises(HTTPException) as denied:
        asyncio.run(send_message("selected-skill", MessageIn(message="测试", pinned_skills=["other"]),
                                  context=context))
    assert denied.value.status_code == 400
    assert captured == []
    assert conversations.get("selected-skill")["message_count"] == 0
    options = asyncio.run(list_employee_skills("emp", context=context))
    assert options == [{"name": "impact", "title": "故障影响分析", "description": "旧触发条件"}]
    asyncio.run(send_message("selected-skill", MessageIn(message="测试", pinned_skills=["impact"]),
                             context=context))
    assert captured[0]["pinned_skills"] == ["impact"]


def test_sync_removes_more_than_store_default_page(tmp_path, monkeypatch):
    store = InMemoryStore()
    monkeypatch.setattr(runtime, "_store", store)
    monkeypatch.setattr(runtime.catalog, "get_skill_dirs_for_employee", lambda *args: {})
    async def run():
        for index in range(105):
            await store.aput(("u1", "emp"), f"/old-{index}/SKILL.md", create_file_data("old"))
        await store.aput(("u1", "emp"), "/AGENTS.md", create_file_data("personal memory"))
        await runtime.sync_skills_to_store("emp", "u1")
        remaining = await store.asearch(("u1", "emp"), limit=200)
        assert [item.key for item in remaining] == ["/AGENTS.md"]
    asyncio.run(run())


def test_content_hot_reload_keeps_graph_but_binding_change_recompiles_variant(tmp_path, monkeypatch):
    directory = skill_file(tmp_path)
    monkeypatch.setattr(runtime.catalog, "get_skill_dirs_for_employee", lambda *args: {"impact": str(directory)})
    monkeypatch.setattr(runtime.catalog, "get_effective_config", lambda *args: {
        "id": "emp", "name": "测试员工", "model": "test", "persona": "测试", "skills": ["impact"],
        "skill_dirs": {"impact": str(directory)}})
    monkeypatch.setattr(runtime, "_store", None)
    monkeypatch.setattr(runtime, "_agents", {})
    monkeypatch.setattr(runtime, "_mcp_clients", {})
    monkeypatch.setattr(runtime, "_skill_bindings", {})
    monkeypatch.setattr(runtime, "_retired_mcp_clients", [])
    compiled = []
    async def compile_agent(*args, **kwargs):
        graph, client = object(), object()
        compiled.append(graph)
        return graph, [], client
    monkeypatch.setattr(runtime, "compile_agent", compile_agent)
    async def run():
        first, _ = await runtime.get_agent("emp", "u1", model_override="model-a")
        other, _ = await runtime.get_agent("emp", "u1", model_override="model-b")
        skill_file(tmp_path, description="新的触发条件")
        current, _ = await runtime.get_agent("emp", "u1", model_override="model-a")
        assert current is first and len(compiled) == 2
        path = directory / "SKILL.md"
        path.write_text(path.read_text().replace("include_tools: impact_lookup", "include_tools: impact_lookup extra_lookup"))
        replacement, _ = await runtime.get_agent("emp", "u1", model_override="model-a")
        assert replacement is not first and len(compiled) == 3
        assert runtime._agents["emp|u1|m:model-b"][0] is other
        assert len(runtime._retired_mcp_clients) == 1
    asyncio.run(run())
