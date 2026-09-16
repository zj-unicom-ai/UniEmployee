"""健康检查端点回归：liveness 不依赖外部服务，readiness 依赖失败返回 503。"""

from fastapi.testclient import TestClient

from app import db as dblayer
from app.main import app


def test_livez_does_not_probe_dependencies(monkeypatch):
    def fail_ping(_name: str):
        raise AssertionError("/livez 不应探测数据库")

    monkeypatch.setattr(dblayer, "ping", fail_ping)
    resp = TestClient(app).get("/livez")

    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ok"
    assert "databases" not in body


def test_readyz_returns_503_when_database_degraded(monkeypatch):
    def fake_ping(name: str):
        if name == "catalog.db":
            raise RuntimeError("boom")

    monkeypatch.setattr(dblayer, "ping", fake_ping)
    resp = TestClient(app).get("/readyz")

    assert resp.status_code == 503
    body = resp.json()
    assert body["status"] == "degraded"
    assert body["databases"]["catalog.db"].startswith("error: boom")


def test_health_keeps_legacy_200_when_degraded(monkeypatch):
    def fake_ping(_name: str):
        raise RuntimeError("db down")

    monkeypatch.setattr(dblayer, "ping", fake_ping)
    resp = TestClient(app).get("/health")

    assert resp.status_code == 200
    assert resp.json()["status"] == "degraded"
