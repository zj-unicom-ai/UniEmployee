"""Analyst 全局配置与员工资源绑定的权限回归测试。"""

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app import auth, catalog, runtime
from app.catalog.db import _conn
from app.routes.analyst import router


def _client(monkeypatch, user: dict) -> TestClient:
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[auth.get_current_user] = lambda: user
    monkeypatch.setattr(runtime, "invalidate", lambda _employee_id: None)
    return TestClient(app)


def _seed_resources():
    con = _conn()
    con.execute(
        "INSERT INTO knowledge_bases(id,name,description,ragflow_dataset_id) "
        "VALUES(?,?,?,?)",
        ("kb_perm", "权限测试知识库", "测试", "dataset_perm"),
    )
    con.execute(
        "INSERT INTO connectors(id,name,description,config) VALUES(?,?,?,?)",
        ("conn_perm", "权限测试连接器", "测试", '{"command":"secret-command",'
         '"env":{"TOKEN":"secret"}}'),
    )
    con.commit()
    con.close()


def test_normal_user_cannot_mutate_global_analyst_config(monkeypatch):
    user = {"id": "u_user", "username": "user", "role": "user"}
    client = _client(monkeypatch, user)

    assert client.post("/api/analyst/terminologies", json={
        "word": "越权术语",
    }).status_code == 403
    assert client.post("/api/analyst/sql-examples", json={
        "question": "越权示例", "sql_text": "SELECT 1",
    }).status_code == 403
    assert client.get("/api/analyst/kbs").status_code == 403
    assert client.get("/api/analyst/connectors/bound").status_code == 403
    assert client.post("/api/analyst/kbs/kb_perm").status_code == 403
    assert client.post("/api/analyst/connectors/conn_perm").status_code == 403

    con = _conn()
    assert con.execute(
        "SELECT COUNT(*) AS c FROM terminologies WHERE word=?",
        ("越权术语",)).fetchone()["c"] == 0
    assert con.execute(
        "SELECT COUNT(*) AS c FROM sql_examples WHERE question=?",
        ("越权示例",)).fetchone()["c"] == 0
    assert con.execute(
        "SELECT COUNT(*) AS c FROM employee_kbs WHERE employee_id=? AND kb_id=?",
        ("xiaoshu", "kb_perm")).fetchone()["c"] == 0
    assert con.execute(
        "SELECT COUNT(*) AS c FROM employee_connectors "
        "WHERE employee_id=? AND connector_id=?",
        ("xiaoshu", "conn_perm")).fetchone()["c"] == 0
    con.close()


def test_admin_can_manage_and_connector_config_is_not_exposed(monkeypatch):
    _seed_resources()
    admin = {"id": "u_admin", "username": "admin", "role": "admin"}
    client = _client(monkeypatch, admin)

    term = client.post("/api/analyst/terminologies", json={
        "word": "企业客户", "description": "B2B 客户",
    })
    assert term.status_code == 200
    assert client.put(
        f"/api/analyst/terminologies/{term.json()['id']}",
        json={"description": "企业客户定义"},
    ).status_code == 200

    example = client.post("/api/analyst/sql-examples", json={
        "question": "本月收入", "sql_text": "SELECT 1",
    })
    assert example.status_code == 200

    assert client.post("/api/analyst/kbs/kb_perm").status_code == 200
    assert client.post("/api/analyst/connectors/conn_perm").status_code == 200
    bound = client.get("/api/analyst/connectors/bound")
    assert bound.status_code == 200
    assert bound.json()[0]["id"] == "conn_perm"
    assert "config" not in bound.json()[0]

    # 不存在的资源不能写入孤儿绑定记录。
    assert client.post("/api/analyst/kbs/not_exists").status_code == 404
    assert client.post("/api/analyst/connectors/not_exists").status_code == 404
