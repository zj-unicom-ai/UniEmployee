"""用户分配权限的服务端回归测试。"""

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app import approvals, auth, catalog, conversations, runtime
from app.routes.conversations import router as conversations_router
from app.routes.user import router as user_router
from app.streaming import conv_emp_map, conv_owner_map


def _seed_employee(emp_id: str = "emp_sec") -> str:
    catalog.upsert_skill("base_skill", "基础技能", "", "skills/base")
    catalog.create_employee({
        "id": emp_id,
        "name": "权限测试员工",
        "role": "测试",
        "model": "dummy-model",
        "persona": "测试",
        "skills": ["base_skill"],
        "tools": ["base_tool"],
        "kbs": [],
        "sops": [],
        "connectors": [],
    })
    return emp_id


def _client(user: dict) -> TestClient:
    app = FastAPI()
    app.include_router(user_router)
    app.include_router(conversations_router)
    app.dependency_overrides[auth.get_current_user] = lambda: user
    app.dependency_overrides[auth.get_current_user_or_fallback] = lambda: user
    return TestClient(app)


def test_user_overrides_cannot_add_ungranted_resources():
    emp_id = _seed_employee()
    catalog.create_user("alice", "x", user_id="u_alice")
    catalog.assign_employee("u_alice", emp_id)

    r = _client({"id": "u_alice", "role": "user", "username": "alice"}).put(
        f"/api/me/employees/{emp_id}/overrides",
        json={
            "overrides": {
                "add": {
                    "skills": ["base_skill", "not_granted_skill"],
                    "tools": ["ontology_write"],
                },
                "remove": {"skills": ["base_skill"]},
            }
        },
    )

    assert r.status_code == 400
    assert "未授权资源" in r.json()["detail"]
    assert catalog.get_assignment("u_alice", emp_id)["overrides"] == {}


def test_user_overrides_can_remove_and_readd_base_resources():
    emp_id = _seed_employee()
    catalog.create_user("alice", "x", user_id="u_alice")
    catalog.assign_employee("u_alice", emp_id)
    client = _client({"id": "u_alice", "role": "user", "username": "alice"})

    r = client.put(
        f"/api/me/employees/{emp_id}/overrides",
        json={"overrides": {"remove": {"skills": ["base_skill"]}}},
    )
    assert r.status_code == 200
    assert r.json()["overrides"]["remove"]["skills"] == ["base_skill"]

    r = client.put(
        f"/api/me/employees/{emp_id}/overrides",
        json={"overrides": {"add": {"skills": ["base_skill"]}}},
    )
    assert r.status_code == 200
    assert r.json()["overrides"]["add"]["skills"] == ["base_skill"]


def test_revoked_assignment_cannot_continue_existing_conversation(monkeypatch):
    emp_id = _seed_employee()
    catalog.create_user("alice", "x", user_id="u_alice")
    catalog.assign_employee("u_alice", emp_id)
    conversations.create("c_revoke", emp_id, user_id="u_alice")
    conv_emp_map["c_revoke"] = emp_id
    conv_owner_map["c_revoke"] = "u_alice"

    async def fail_if_called(*args, **kwargs):
        raise AssertionError("revoked conversation should not start runtime")

    monkeypatch.setattr(runtime, "get_agent", fail_if_called)
    catalog.unassign_employee("u_alice", emp_id)

    r = _client({"id": "u_alice", "role": "user", "username": "alice"}).post(
        "/api/conversations/c_revoke/messages",
        json={"message": "还可以继续吗", "attachments": []},
    )

    assert r.status_code == 403
    assert "未分配" in r.json()["detail"]


def test_revoked_assignment_cannot_resume_pending_approval(monkeypatch):
    emp_id = _seed_employee()
    catalog.create_user("alice", "x", user_id="u_alice")
    catalog.assign_employee("u_alice", emp_id)
    conversations.create("c_approval_revoke", emp_id, user_id="u_alice")
    approval = approvals.create(
        "c_approval_revoke", emp_id, "base_tool", {},
        user_id="u_alice",
    )

    async def fail_if_called(*args, **kwargs):
        raise AssertionError("revoked approval should not resume runtime")

    monkeypatch.setattr(runtime, "get_agent", fail_if_called)
    catalog.unassign_employee("u_alice", emp_id)

    r = _client({"id": "u_alice", "role": "user", "username": "alice"}).post(
        f"/api/approvals/{approval['approval_id']}/decision",
        json={"decision": "approve"},
    )

    assert r.status_code == 403
    assert approvals.get(approval["approval_id"])["status"] == "pending"
