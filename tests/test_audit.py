"""管理端审计日志：落库、before/after 快照、筛选查询 + 端点接入回归测试。"""
import json

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app import audit, catalog


def test_audit_log_and_list():
    audit.log("create", "kb", "kb_t1",
              admin={"id": "u1", "username": "alice"},
              before=None, after={"name": "测试库"})
    audit.log("delete", "employee", "emp_t1",
              admin={"id": "u2", "username": "bob"},
              before={"name": "旧员工"})
    logs, total = audit.list_logs()
    assert total >= 2
    by_obj = {l["obj_id"]: l for l in logs}
    kb = by_obj["kb_t1"]
    assert kb["actor_name"] == "alice" and kb["action"] == "create"
    assert json.loads(kb["after"])["name"] == "测试库"
    emp = by_obj["emp_t1"]
    assert emp["actor_id"] == "u2" and emp["before"] and not emp["after"]

    # 筛选：对象类型 + 动作
    rows, t = audit.list_logs(obj_type="kb", action="create")
    assert t == 1 and rows[0]["obj_id"] == "kb_t1"
    # 分页 offset
    _, t2 = audit.list_logs(offset=total)
    assert t2 == total  # total 不受 offset 影响


def test_audit_failure_does_not_raise():
    """审计写库异常时业务不被阻断（旁路容错）。"""
    import app.audit as a

    orig = a._conn
    a._conn = lambda: (_ for _ in ()).throw(RuntimeError("db down"))
    try:
        a.log("create", "kb", "kb_x")  # 不应抛异常
    finally:
        a._conn = orig


def _client(monkeypatch):
    from app import auth
    from app.routes.admin import router as admin_router
    from app.routes.audit import router as audit_router

    app = FastAPI()
    app.include_router(admin_router)
    app.include_router(audit_router)
    app.dependency_overrides[auth.require_admin] = lambda: {
        "id": "u_admin", "username": "admin", "role": "admin"}
    monkeypatch.setattr(catalog, "backfill_ragflow_knowledge_bases", lambda: None)
    return TestClient(app)


def test_admin_endpoints_write_audit(monkeypatch):
    """员工 CRUD 端点调用后，审计日志包含操作人与 before/after 快照。"""
    client = _client(monkeypatch)

    r = client.post("/api/admin/employees", json={
        "id": "emp_audit", "name": "审计测试", "model": "openai:m",
        "backend": "state", "persona": "p", "kbs": [],
        "skills": [], "tools": [], "sops": [], "connectors": [],
    })
    assert r.status_code == 200

    r = client.put("/api/admin/employees/emp_audit", json={
        "id": "emp_audit", "name": "审计测试2", "model": "openai:m",
        "backend": "state", "persona": "p2", "kbs": [],
        "skills": [], "tools": [], "sops": [], "connectors": [],
    })
    assert r.status_code == 200

    logs, _ = audit.list_logs(obj_type="employee")
    emp_logs = [l for l in logs if l["obj_id"] == "emp_audit"]
    actions = [l["action"] for l in emp_logs]
    assert "create" in actions and "update" in actions
    upd = next(l for l in emp_logs if l["action"] == "update")
    assert upd["actor_id"] == "u_admin" and upd["actor_name"] == "admin"
    assert json.loads(upd["before"])["name"] == "审计测试"
    assert json.loads(upd["after"])["name"] == "审计测试2"

    # 查询端点（分页 + 筛选）
    r = client.get("/api/admin/audit/logs",
                   params={"obj_type": "employee", "limit": 10})
    data = r.json()
    assert data["total"] >= 2
    assert any(l["obj_id"] == "emp_audit" for l in data["logs"])

    # 删除也留痕
    r = client.delete("/api/admin/employees/emp_audit")
    assert r.status_code == 200
    logs, _ = audit.list_logs(obj_type="employee", action="delete")
    assert any(l["obj_id"] == "emp_audit" for l in logs)


def test_audit_after_is_full_state_snapshot(monkeypatch):
    """部分字段更新（如配置页只上送 connectors）时，after 仍为完整配置快照，
    与 before 同口径，避免「变更后只剩请求片段」的歧义。"""
    client = _client(monkeypatch)
    client.post("/api/admin/employees", json={
        "id": "emp_snap", "name": "快照测试", "model": "openai:m",
        "backend": "state", "persona": "p", "kbs": [],
        "skills": [], "tools": [], "sops": [], "connectors": [],
    })
    r = client.put("/api/admin/employees/emp_snap",
                   json={"connectors": ["crm", "newsnow"]})
    assert r.status_code == 200
    logs, _ = audit.list_logs(obj_type="employee")
    upd = next(l for l in logs
               if l["obj_id"] == "emp_snap" and l["action"] == "update")
    before = json.loads(upd["before"])
    after = json.loads(upd["after"])
    assert after["connectors"] == ["crm", "newsnow"]
    # after 是完整状态：未改动字段保留现值，且与 before 字段集一致
    assert after["model"] == before["model"] == "openai:m"
    assert after["persona"] == before["persona"] == "p"
    assert set(before.keys()) == set(after.keys())


def test_login_events_audited(monkeypatch):
    """登录成功/失败、自助改密均落审计；限流拒绝不写审计。"""
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from app import auth as auth_mod
    from app.routes.auth import router as auth_router

    catalog.create_user("login_t", auth_mod.hash_password("secret123"),
                        role="user", user_id="u_login_t")
    app = FastAPI()
    app.include_router(auth_router)
    client = TestClient(app)

    # 密码错误 → login_failed：obj_id/actor 为尝试的用户名，after 含原因
    r = client.post("/api/auth/login",
                    json={"username": "login_t", "password": "wrong-pass"})
    assert r.status_code == 401
    logs, _ = audit.list_logs(action="login_failed")
    f = logs[0]
    assert f["obj_id"] == "login_t" and f["actor_name"] == "login_t"
    assert json.loads(f["after"])["reason"] == "用户名或密码错误"

    # 登录成功 → login：actor 为真实用户
    r = client.post("/api/auth/login",
                    json={"username": "login_t", "password": "secret123"})
    assert r.status_code == 200
    ok = next(l for l in audit.list_logs(action="login")[0]
              if l["obj_id"] == "u_login_t")
    assert ok["actor_id"] == "u_login_t" and ok["ip"]

    # 自助改密 → user_password 审计，不记密码内容
    tok = r.json()["token"]
    r = client.post("/api/auth/change-password",
                    json={"old_password": "secret123", "new_password": "newpass456"},
                    headers={"Authorization": f"Bearer {tok}"})
    assert r.status_code == 200
    pw_logs = [l for l in audit.list_logs(obj_type="user_password")[0]
               if l["actor_id"] == "u_login_t"]
    assert pw_logs
    assert "newpass456" not in (pw_logs[0]["after"] or "")
    assert "newpass456" not in (pw_logs[0]["before"] or "")

    # 限流拒绝（5 次失败后）→ 不再新增审计写入，防爆破流量放大
    from app.routes import auth as auth_routes
    key = "testclient|login_t"
    auth_routes._LOGIN_FAILS[key] = [__import__("time").time()] * 5
    before_count = audit.list_logs(action="login_failed")[1]
    r = client.post("/api/auth/login",
                    json={"username": "login_t", "password": "x"})
    assert r.status_code == 429
    assert audit.list_logs(action="login_failed")[1] == before_count


def test_audit_user_snapshot_excludes_password_hash(monkeypatch):
    """用户变更的审计快照不得包含 password_hash。"""
    from app import auth as auth_mod
    catalog.create_user("audit_target", auth_mod.hash_password("x"),
                        role="user", user_id="u_audit_t")
    client = _client(monkeypatch)
    r = client.put("/api/admin/users/u_audit_t", json={"role": "admin"})
    assert r.status_code == 200
    logs, _ = audit.list_logs(obj_type="user")
    snap = next(l for l in logs if l["obj_id"] == "u_audit_t")
    assert "password_hash" not in (snap["before"] or "")
    assert "password_hash" not in (snap["after"] or "")
