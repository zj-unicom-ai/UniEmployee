"""小网安全实操：升级、隔离执行、完整记录、导出鉴权与赛事路由。"""

import asyncio
import json
from pathlib import Path
import uuid
import zipfile

from fastapi import FastAPI
from fastapi.testclient import TestClient
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from langchain_core.outputs import ChatGeneration, LLMResult
import pytest

from app import agent_runs, auth, catalog, conversations, sandbox_mgr, traces
from app.auth_context import from_user
from app.routes.conversations import router
from app.security_tasks import export, policy, records, tools
from app.spec import EmployeeSpec


@pytest.fixture(autouse=True)
def storage(tmp_path, monkeypatch):
    for module in (records, export):
        monkeypatch.setattr(module, "DATA_DIR", tmp_path / "private")
    for module in (tools, export):
        monkeypatch.setattr(module, "WORKSPACE_DATA", tmp_path / "workspace")
    monkeypatch.setattr(traces, "DB", tmp_path / "traces.db")
    monkeypatch.delenv("NETOPS_COMPETITION_MODE", raising=False)
    monkeypatch.setattr(tools, "get_config", lambda: {"configurable": {
        "employee_id": "net-ops", "user_id": "u1", "thread_id": "c1"}})


def recorder():
    return records.SecurityRecorder("default", "u1", "c1", "r1", {"messages": ["Q1"]})


def test_upgrade_preserves_custom_persona_and_operations():
    catalog.seed_if_empty()
    catalog.update_employee("net-ops", {"persona": "管理员自定义人设"})
    catalog.backfill_netops_upgrade()
    catalog.backfill_netops_upgrade()
    cfg = catalog.get_employee_config("net-ops")
    assert cfg["persona"] == "管理员自定义人设"
    assert {"fault-impact-analysis", "security-practical"} <= set(cfg["skills"])
    assert set(policy.TOOL_NAMES) <= set(cfg["tools"])
    assert cfg["skills"].count("security-practical") == 1
    assert "create_ticket" in cfg["tools"]


def test_full_model_and_tool_records_survive_export():
    handler = recorder()
    long_result = "证据" * 4000
    messages = [SystemMessage(content="规则"), HumanMessage(content="原始题目")]
    model_id, tool_id = uuid.uuid4(), uuid.uuid4()
    response = AIMessage(content="", tool_calls=[{
        "name": "run_security_python", "args": {"code": "print(6)"}, "id": "tc1"}])

    async def capture():
        await handler.on_chat_model_start({"api_key": "do-not-record"}, [messages], run_id=model_id)
        await handler.on_llm_end(LLMResult(generations=[[ChatGeneration(message=response)]]), run_id=model_id)
        await handler.on_tool_start({"name": "run_security_python"}, "", run_id=tool_id,
                                    inputs={"code": "print(6)"}, tool_call_id="tc1")
        await handler.on_tool_end(long_result, run_id=tool_id)
    asyncio.run(capture())
    handler.write("run_finished", status="done", answer="6")
    path = export.export_conversation({"tenant_id": "default", "user_id": "u1", "conv_id": "c1"}, {}, [])
    with zipfile.ZipFile(path) as archive:
        events = [json.loads(line) for line in archive.read(f"records/{handler.path.name}").decode().splitlines()]
        assert events[1]["messages"][0][0]["content"] == "规则"
        assert events[2]["generations"][0][0]["message"]["tool_calls"] == response.tool_calls
        assert events[3]["tool_call_id"] == "tc1"
        assert events[4]["result"] == long_result
        assert json.loads(archive.read("manifest.json"))["incomplete_runs"] == []
        timing = json.loads(archive.read("timing.json"))
        assert timing["summary"]["runs"] == 1 and timing["summary"]["completed_runs"] == 1
        assert timing["runs"][0]["model_calls"] == 1 and timing["runs"][0]["tool_calls"] == 1
        assert timing["runs"][0]["by_tool"]["run_security_python"]["count"] == 1
        assert timing["runs"][0]["wall_seconds"] >= 0
        assert timing["unclosed_tool_calls"] == []
        assert "do-not-record" not in archive.read(f"records/{handler.path.name}").decode()


def test_record_write_failure_is_not_silently_ignored(monkeypatch):
    handler = recorder()
    monkeypatch.setattr(Path, "open", lambda *args, **kwargs: (_ for _ in ()).throw(OSError("disk full")))
    with pytest.raises(OSError, match="disk full"):
        asyncio.run(handler.on_tool_error(RuntimeError("failed"), run_id=uuid.uuid4()))
    assert handler.raise_error


def test_export_marks_incomplete_and_rejects_symlinks(tmp_path):
    handler = recorder()
    meta = {"tenant_id": "default", "user_id": "u1", "conv_id": "c1"}
    target = export.export_conversation(meta, {}, [])
    with zipfile.ZipFile(target) as archive:
        assert json.loads(archive.read("manifest.json"))["incomplete_runs"] == [handler.path.name]
    directory = export.WORKSPACE_DATA / "u1" / "uploads" / "c1"
    directory.mkdir(parents=True)
    secret = tmp_path / "private-file"
    secret.write_text("not part of this task")
    (directory / "link.txt").symlink_to(secret)
    with pytest.raises(ValueError, match="符号链接"):
        export.export_conversation(meta, {}, [])


def test_python_requires_sandbox_and_preserves_full_results(monkeypatch):
    monkeypatch.setattr(sandbox_mgr, "enabled", lambda: False)
    with pytest.raises(ValueError, match="不会回退"):
        tools.run_security_python.invoke({"code": "print(6)"})
    calls = []
    class Backend:
        def write(self, path, code):
            calls.append((path, code))
        def execute(self, command, *, timeout):
            calls.append(command)
            return {"output": "x" * 9000, "exit_code": 0}
    monkeypatch.setattr(sandbox_mgr, "enabled", lambda: True)
    monkeypatch.setattr(sandbox_mgr.manager, "acquire", lambda **kwargs: Backend())
    result = json.loads(tools.run_security_python.invoke({"code": "print(6)"}))
    assert result["truncated"] is True
    saved = tools.WORKSPACE_DATA / result["full_result"].removeprefix("/data/")
    assert json.loads(saved.read_text())["output"] == "x" * 9000
    assert calls[0][1] == "print(6)"
    assert (saved.parent / saved.name.replace(".result.json", ".py")).read_text() == "print(6)"


def test_answers_are_versioned_and_require_context(monkeypatch):
    args = {"question_id": "Q1", "answer": "flag{example}", "evidence": ["events.jsonl:3"]}
    first = tools.save_security_answer.invoke(args).splitlines()[0]
    second = tools.save_security_answer.invoke({**args, "answer": "corrected"}).splitlines()[0]
    assert first != second
    saved = json.loads((tools.WORKSPACE_DATA / first.removeprefix("/data/")).read_text())
    assert {k: saved[k] for k in args} == args
    assert saved["report_saved"] is False
    with pytest.raises(ValueError, match="证据不能为空"):
        tools.save_security_answer.invoke({**args, "evidence": ["  "]})
    report = tools.save_security_answer.invoke({**args, "report": "## 结论\nflag{example}"}).splitlines()
    assert len(report) == 2 and report[1].endswith(".md")
    doc = (tools.WORKSPACE_DATA / report[1].removeprefix("/data/")).read_text(encoding="utf-8")
    assert "flag{example}" in doc
    assert json.loads((tools.WORKSPACE_DATA / report[0].removeprefix("/data/")).read_text())["report_saved"]
    monkeypatch.setattr(tools, "get_config", lambda: {})
    with pytest.raises(ValueError, match="上下文"):
        tools.save_security_answer.invoke(args)


def test_official_model_never_uses_catalog_or_old_environment(monkeypatch):
    monkeypatch.setenv("OPENAI_BASE_URL", "https://old.example.invalid")
    monkeypatch.setenv("COMPETITION_MODEL", "official-model")
    monkeypatch.setenv("COMPETITION_BASE_URL", "http://127.0.0.1:9999/v1")
    monkeypatch.delenv("COMPETITION_API_KEY", raising=False)
    with pytest.raises(ValueError, match="禁止回退"):
        policy.official_model()
    monkeypatch.setenv("COMPETITION_API_KEY", "test-only-key")
    monkeypatch.setattr(policy, "init_chat_model", lambda *args, **kwargs: (args, kwargs))
    args, kwargs = policy.official_model()
    assert args == ("official-model",)
    assert kwargs["base_url"] == "http://127.0.0.1:9999/v1"
    assert kwargs["api_key"] == "test-only-key"


def test_competition_scope_and_network_policy(monkeypatch):
    spec = EmployeeSpec(id="net-ops", name="小网", model="old", persona="运营",
                        tools=["bocha_search"], mcp_servers={"external": {}}, subagents=[{"name": "other"}])
    assert policy.apply(spec) is spec
    monkeypatch.setenv("NETOPS_COMPETITION_MODE", "1")
    monkeypatch.setattr(sandbox_mgr, "enabled", lambda: False)
    with pytest.raises(ValueError, match="禁止回退宿主机"):
        policy.apply(spec)
    monkeypatch.setattr(sandbox_mgr, "enabled", lambda: True)
    restricted = policy.apply(spec)
    assert restricted.tools == policy.TOOL_NAMES + ["get_current_time"]
    assert (restricted.mcp_servers, restricted.subagents, restricted.kbs) == ({}, [], [])
    monkeypatch.setattr(conversations, "get", lambda _: {"employee_id": "net-ops"})
    assert policy.sandbox_options("c1")["network_policy"].default_action == "deny"
    assert not policy.enabled("xiaoshu")


def test_export_endpoint_checks_owner_tenant_and_active_run():
    catalog.seed_if_empty()
    conversations.create("c1", "net-ops", user_id="u1", tenant_id="default")
    agent_runs.init_tables()
    recorder().write("run_finished", status="done")
    app = FastAPI()
    app.include_router(router)
    identity = {"id": "u1", "tenant_id": "default", "role": "admin"}
    app.dependency_overrides[auth.get_auth_context] = lambda: from_user(identity)
    with TestClient(app) as client:
        response = client.get("/api/conversations/c1/security-export")
        assert response.status_code == 200
        assert response.headers["content-type"] == "application/zip"
        identity["id"] = "u2"
        assert client.get("/api/conversations/c1/security-export").status_code == 403
        identity.update(id="u1", tenant_id="other")
        assert client.get("/api/conversations/c1/security-export").status_code == 404
        identity["tenant_id"] = "default"
        agent_runs.create(conv_id="c1", tenant_id="default", user_id="u1", employee_id="net-ops")
        assert client.get("/api/conversations/c1/security-export").status_code == 409


def test_model_tool_answer_stream_and_export_chain(monkeypatch):
    """实际运行框架和工具链；模型/远端沙箱使用替身，不调用外部服务。"""
    from langchain_core.language_models.fake_chat_models import FakeMessagesListChatModel
    from langgraph.checkpoint.memory import InMemorySaver
    from langgraph.store.memory import InMemoryStore
    from langgraph.config import get_config
    from app import compiler, runtime, streaming

    class Model(FakeMessagesListChatModel):
        def bind_tools(self, tools, **kwargs):
            return self

    model = Model(responses=[
        AIMessage(content="", tool_calls=[{"id": "tc-skill", "name": "read_file",
            "args": {"file_path": "/skills/security-practical/SKILL.md"}}]),
        AIMessage(content="", tool_calls=[{"id": "tc-code", "name": "run_security_python",
                                         "args": {"code": "print(6)"}}]),
        AIMessage(content="", tool_calls=[{"id": "tc-answer", "name": "save_security_answer",
            "args": {"question_id": "Q1", "answer": "6", "evidence": ["工具执行结果"]}}]),
        AIMessage(content="Q1：失败登录次数为 6。"),
    ])
    class Backend:
        def write(self, path, code):
            assert code == "print(6)"
        def execute(self, command, *, timeout):
            return {"output": "6", "exit_code": 0}
    monkeypatch.setattr(sandbox_mgr, "enabled", lambda: True)
    monkeypatch.setattr(tools, "get_config", get_config)
    monkeypatch.setattr(sandbox_mgr.manager, "acquire", lambda **kwargs: Backend())
    monkeypatch.setattr(compiler, "_init_model", lambda _: model)
    monkeypatch.setattr(streaming, "WORKSPACE_DATA", tools.WORKSPACE_DATA)
    catalog.seed_if_empty()
    conversations.create("c1", "net-ops", user_id="u1", tenant_id="default", count=1)

    async def noop(*args):
        pass
    monkeypatch.setattr(runtime, "ensure_user_memory", noop)
    monkeypatch.setattr(streaming, "_gen_title", noop)

    async def run():
        spec = EmployeeSpec(id="net-ops", name="小网", model="test-model", persona="分析附件",
                            tools=policy.TOOL_NAMES, skills=[policy.SKILL_NAME])
        agent, stages, _ = await compiler.compile_agent(spec, InMemorySaver(), InMemoryStore())
        async def get_agent(*args, **kwargs):
            return agent, stages
        monkeypatch.setattr(runtime, "get_agent", get_agent)
        return [json.loads(event[6:]) async for event in streaming._stream_run(
            "c1", {"messages": [{"role": "user", "content": "Q1，安全实操题，统计失败登录次数"}]},
            user_id="u1", role="admin")]

    events = asyncio.run(run())
    assert not [event for event in events if event["type"] == "error"]
    assert any(event["type"] == "message_end" for event in events)
    saved = list((tools.WORKSPACE_DATA / "u1/security-tasks/c1").glob("answer-*.json"))
    assert saved, json.dumps(events, ensure_ascii=False)
    assert json.loads(saved[0].read_text())["answer"] == "6"
    exported = export.export_conversation(conversations.get("c1"), {}, conversations.list_files("c1"))
    with zipfile.ZipFile(exported) as archive:
        log = b"".join(archive.read(name) for name in archive.namelist() if name.endswith(".jsonl"))
        assert b"tc-code" in log and b"tc-answer" in log
        assert json.loads(archive.read("manifest.json"))["incomplete_runs"] == []
