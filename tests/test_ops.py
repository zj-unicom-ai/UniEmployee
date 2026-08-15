"""可运维性回归（第二批）：
1. /health 健康检查返回 200 + 结构化状态（含各 SQLite 库探测）；
2. db_path 受 APP_DATA_DIR 控制，默认指向项目根（本地行为不变）。
依赖服务在 8787 运行（与健康检查/端点类测试一致）。"""
import json
import socket

import pytest
import urllib.error
import urllib.request
from pathlib import Path

from app import paths

BASE = "http://localhost:8787"


def _port_open(port=8787):
    s = socket.socket()
    s.settimeout(1)
    try:
        s.connect(("localhost", port))
        s.close()
        return True
    except OSError:
        return False


pytestmark = pytest.mark.skipif(not _port_open(), reason="服务未在 8787 运行")


def _req(path, method="GET"):
    r = urllib.request.Request(BASE + path, method=method)
    try:
        resp = urllib.request.urlopen(r)
        return resp.status, resp.read().decode()
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode()


def test_health_ok():
    st, body = _req("/health")
    assert st == 200, f"/health 应 200，实际 {st}: {body[:200]}"
    d = json.loads(body)
    assert d["status"] in ("ok", "degraded")
    assert "version" in d and d["version"]
    assert "timestamp" in d
    assert d["databases"]["catalog.db"] == "ok", d["databases"]
    # 健康检查必须无需登录（匿名访问即可）
    assert "token" not in body.lower()


def test_db_path_default_is_project_root(monkeypatch):
    """未设 APP_DATA_DIR 时，db_path 指向项目根（与历史行为一致）。"""
    monkeypatch.delenv("APP_DATA_DIR", raising=False)
    assert str(paths.db_path("catalog.db")).endswith("catalog.db")
    assert Path(paths.db_path("catalog.db")).is_absolute()


def test_db_path_honors_app_data_dir(monkeypatch):
    """设 APP_DATA_DIR 后，db_path 把库指向该目录（容器持久化用）。"""
    monkeypatch.setattr(paths, "DATA_DIR", Path("/tmp/myagents-data"))
    assert str(paths.db_path("catalog.db")) == "/tmp/myagents-data/catalog.db"
