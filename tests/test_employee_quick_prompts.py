"""员工级快捷问法配置、访问控制与上限。"""

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app import auth, catalog, runtime
from app.routes.admin import router as admin_router
from app.routes.conversations import router as conversations_router


def _employee(emp_id="emp_prompts"):
    catalog.create_employee({
        "id": emp_id, "name": "小帮手", "role": "业务助手", "model": "dummy-model",
        "persona": "测试", "skills": [], "tools": [], "kbs": [], "sops": [],
        "connectors": [],
    })
    return emp_id


def test_quick_prompts_are_persisted_and_discovered():
    emp_id = _employee()
    assert catalog.get_employee_config(emp_id)["quick_prompts"] == []
    assert catalog.update_employee_quick_prompts(emp_id, ["查本周数据", "总结客户情况"])
    assert catalog.get_full_employee(emp_id)["quick_prompts"] == ["查本周数据", "总结客户情况"]
    catalog.create_user("prompt_owner", "x", user_id="u_prompt_owner")
    catalog.assign_employee("u_prompt_owner", emp_id)
    assert catalog.get_effective_config("u_prompt_owner", emp_id)["quick_prompts"] == [
        "查本周数据", "总结客户情况",
    ]
    discovered = next(e for e in runtime.discover_employees() if e["id"] == emp_id)
    assert discovered["quick_prompts"] == ["查本周数据", "总结客户情况"]


def test_admin_can_save_up_to_three_prompts_and_cannot_exceed_limit(monkeypatch):
    emp_id = _employee()
    app = FastAPI()
    app.include_router(admin_router)
    app.dependency_overrides[auth.require_admin] = lambda: {
        "id": "u_admin", "username": "admin", "role": "admin"}
    monkeypatch.setattr(runtime, "invalidate", lambda *args, **kwargs: None)
    client = TestClient(app)

    saved = client.put(f"/api/admin/employees/{emp_id}/quick-prompts", json={
        "prompts": ["  查本周数据  ", "总结客户情况"],
    })
    assert saved.status_code == 200
    assert saved.json()["prompts"] == ["查本周数据", "总结客户情况"]

    too_many = client.put(f"/api/admin/employees/{emp_id}/quick-prompts", json={
        "prompts": ["一", "二", "三", "四"],
    })
    assert too_many.status_code == 400
    assert catalog.get_employee_config(emp_id)["quick_prompts"] == ["查本周数据", "总结客户情况"]


def test_assigned_user_can_read_prompts_but_unassigned_user_cannot():
    emp_id = _employee()
    catalog.update_employee_quick_prompts(emp_id, ["部门周报怎么做？"])
    catalog.create_user("prompt_user", "x", user_id="u_prompt")
    catalog.assign_employee("u_prompt", emp_id)

    app = FastAPI()
    app.include_router(conversations_router)
    user = {"id": "u_prompt", "username": "prompt_user", "role": "user"}
    app.dependency_overrides[auth.get_current_user] = lambda: user
    client = TestClient(app)
    assert client.get(f"/api/employees/{emp_id}/quick-prompts").json() == {
        "employee_id": emp_id, "prompts": ["部门周报怎么做？"],
    }

    app.dependency_overrides[auth.get_current_user] = lambda: {
        "id": "u_other", "username": "other", "role": "user"}
    assert client.get(f"/api/employees/{emp_id}/quick-prompts").status_code == 403
