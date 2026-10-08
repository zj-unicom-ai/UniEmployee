"""自动化运行身份、员工授权和租户边界回归。"""

import asyncio
import sqlite3

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app import auth, automations, catalog, conversations, streaming
from app.routes.automations import router


def _user(user_id: str, tenant_id: str = "default", role: str = "user",
          *, assigned: tuple[str, ...] = ("xiaoshu",), status: str = "active") -> dict:
    catalog.create_employee({"id": "xiaoshu", "name": "测试员工"})
    catalog.create_user(user_id, "!test-only", role=role, tenant_id=tenant_id,
                        user_id=user_id)
    if status != "active":
        catalog.update_user(user_id, status=status)
    for employee_id in assigned:
        catalog.assign_employee(user_id, employee_id, granted_by="test")
    return catalog.get_user(user_id)


def _client(user: dict) -> TestClient:
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[auth.get_current_user_or_fallback] = lambda: user
    return TestClient(app)


def _automation(*, tenant_id="tenant-a", run_as="u_runner", created_by="u_creator"):
    return automations.create(
        name="隔离测试任务", trigger_type="cron", employee_id="xiaoshu",
        prompt="执行隔离测试", cron_expr="0 9 * * *", run_as=run_as,
        tenant_id=tenant_id, created_by=created_by,
    )


def test_create_rejects_inactive_cross_tenant_and_unassigned_run_as(monkeypatch):
    actor = _user("u_admin", "tenant-a", "admin")
    _user("u_other_tenant", "tenant-b")
    _user("u_unassigned", "tenant-a", assigned=())
    _user("u_disabled", "tenant-a", status="disabled")
    monkeypatch.setattr("app.routes.automations.runtime.discover_employees",
                        lambda: [{"id": "xiaoshu"}])
    client = _client(actor)

    def create(run_as):
        return client.post("/api/automations", json={
            "name": "身份校验", "trigger_type": "cron", "cron_expr": "0 9 * * *",
            "employee_id": "xiaoshu", "prompt": "运行", "run_as": run_as,
        })

    assert create("u_other_tenant").status_code == 400
    assert create("u_unassigned").status_code == 400
    assert create("u_disabled").status_code == 400
    assert create("u_missing").status_code == 400
    accepted = create("u_admin")
    assert accepted.status_code == 200
    assert "secret" not in accepted.json()
    assert client.put(f"/api/automations/{accepted.json()['id']}",
                      json={"run_as": "u_other_tenant"}).status_code == 400


def test_automation_management_is_tenant_scoped():
    tenant_a_admin = _user("u_tenant_a_admin", "tenant-a", "admin")
    _user("u_tenant_b_runner", "tenant-b")
    other = _automation(tenant_id="tenant-b", run_as="u_tenant_b_runner",
                        created_by="u_tenant_b_admin")
    execution, _ = automations.create_execution(
        other["id"], "manual", "tenant-b-run", tenant_id="tenant-b",
        trigger_actor="u_tenant_b_admin", run_as_principal="u_tenant_b_runner")
    client = _client(tenant_a_admin)

    listed = client.get("/api/automations")
    hidden = client.post(f"/api/automations/{other['id']}/run")
    deleted = client.delete(f"/api/automations/{other['id']}")
    executions = client.get(f"/api/automations/{other['id']}/executions")
    updated = client.put(f"/api/automations/{other['id']}", json={"name": "越权"})
    leaked_execution = automations.get_execution(
        execution["id"], automation_id=other["id"], tenant_id="tenant-a")

    assert listed.status_code == 200
    assert all(item["id"] != other["id"] for item in listed.json()["items"])
    assert hidden.status_code == deleted.status_code == executions.status_code == updated.status_code == 404
    assert leaked_execution is None
    assert automations.get(other["id"], tenant_id="tenant-b") is not None


def test_execution_passes_tenant_context_and_clamps_admin_to_user(monkeypatch):
    _user("u_creator", "tenant-a", "admin")
    _user("u_runner", "tenant-a", "admin")
    captured = {}

    async def fake_stream(conv_id, input_, **kwargs):
        captured.update(kwargs)
        yield 'data: {"type":"token","content":"完成"}\n\n'

    monkeypatch.setattr(streaming, "_stream_run", fake_stream)
    auto = _automation()

    result = asyncio.run(automations.execute(
        auto, trigger="manual", trigger_actor="u_trigger"))
    execution = automations.get_execution(result["execution_id"])
    conv = conversations.get(result["conversation_id"])

    assert result["status"] == "ok"
    assert captured["tenant_id"] == "tenant-a"
    assert captured["role"] == "user"
    assert captured["auth_context"]["user_id"] == "u_runner"
    assert captured["auth_context"]["tenant_id"] == "tenant-a"
    assert captured["auth_context"]["role"] == "user"
    assert "*" not in captured["auth_context"]["permissions"]
    assert conv["tenant_id"] == "tenant-a"
    assert execution["tenant_id"] == "tenant-a"
    assert execution["trigger_actor"] == "u_trigger"
    assert execution["run_as_principal"] == "u_runner"
    assert automations.get(auto["id"])["created_by"] == "u_creator"


def test_execution_rechecks_disabled_user_and_assignment_before_streaming(monkeypatch):
    runner = _user("u_revoked_runner", "tenant-a")
    calls = 0

    async def fake_stream(*args, **kwargs):
        nonlocal calls
        calls += 1
        yield 'data: {"type":"token","content":"不应运行"}\n\n'

    monkeypatch.setattr(streaming, "_stream_run", fake_stream)
    auto = _automation(run_as=runner["id"])
    catalog.unassign_employee(runner["id"], "xiaoshu")

    result = asyncio.run(automations.execute(auto, trigger="manual"))
    execution = automations.get_execution(result["execution_id"])

    assert result["status"] == "error"
    assert calls == 0
    assert result["conversation_id"] == ""
    assert execution["status"] == "error"
    assert "身份" in execution["error"] or "授权" in execution["error"]
    assert conversations.list_for(user_id=runner["id"], tenant_id="tenant-a") == []


def test_execution_rejects_user_disabled_after_task_creation(monkeypatch):
    runner = _user("u_disabled_runner", "tenant-a")
    calls = 0

    async def fake_stream(*args, **kwargs):
        nonlocal calls
        calls += 1
        yield 'data: {"type":"token","content":"不应运行"}\n\n'

    monkeypatch.setattr(streaming, "_stream_run", fake_stream)
    auto = _automation(run_as=runner["id"])
    catalog.update_user(runner["id"], status="disabled")

    result = asyncio.run(automations.execute(auto, trigger="manual"))

    assert result["status"] == "error"
    assert calls == 0
    assert conversations.list_for(user_id=runner["id"], tenant_id="tenant-a") == []


def test_legacy_automation_schema_migrates_tenant_and_execution_identity(tmp_path, monkeypatch):
    monkeypatch.setenv("ENTERPRISE_TENANT_ID", "tenant-main")
    legacy_db = tmp_path / "legacy-automations.db"
    con = sqlite3.connect(legacy_db)
    con.row_factory = sqlite3.Row
    con.executescript("""
        CREATE TABLE automations (id TEXT PRIMARY KEY, run_as TEXT, created_at TEXT);
        INSERT INTO automations VALUES ('auto_old', 'u_old_runner', '2026-01-01');
        CREATE TABLE automation_executions (
            id TEXT PRIMARY KEY, automation_id TEXT, status TEXT, created_at TEXT
        );
        INSERT INTO automation_executions VALUES ('run_old', 'auto_old', 'ok', '2026-01-01');
    """)

    con.close()

    monkeypatch.setattr("app.conversations.DB", legacy_db)
    auto = automations.get("auto_old")
    execution = automations.get_execution("run_old")

    assert auto["tenant_id"] == "tenant-main"
    assert execution["tenant_id"] == "tenant-main"
    assert execution["trigger_actor"] == "system:legacy"
    assert execution["run_as_principal"] == "u_old_runner"
