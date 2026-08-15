"""隔离回归测试：角色权限 + 看板按用户隔离。需服务在 8787 运行。"""
import json
import os
import socket
import urllib.error
import urllib.request

import pytest

BASE = "http://localhost:8787"


def _port_open(port=8787):
    s = socket.socket(); s.settimeout(1)
    try:
        s.connect(("localhost", port)); s.close(); return True
    except OSError:
        return False


pytestmark = pytest.mark.skipif(not _port_open(), reason="服务未在 8787 运行")


def _req(path, method="GET", token=None, body=None):
    h = {"Content-Type": "application/json"}
    if token:
        h["Authorization"] = "Bearer " + token
    data = json.dumps(body).encode() if body else None
    r = urllib.request.Request(BASE + path, data=data, method=method, headers=h)
    try:
        resp = urllib.request.urlopen(r)
        return resp.status, resp.read().decode()
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode()


def _login(u, p):
    s, b = _req("/api/auth/login", "POST", body={"username": u, "password": p})
    return json.loads(b).get("token")


@pytest.fixture(scope="module")
def users():
    """确保 admin + 两个普通用户存在，返回 token。"""
    admin = _login("admin", "admin123")
    # 创建/确保 zhang、li 存在
    for u, p in [("zhang", "z123"), ("li", "l123")]:
        _req("/api/admin/users", "POST", token=admin, body={"username": u, "password": p, "role": "user"})
    return admin, _login("zhang", "z123"), _login("li", "l123")


def test_role_admin_can_manage(users):
    admin, _, _ = users
    assert _req("/api/admin/catalog", token=admin)[0] == 200
    assert _req("/api/admin/users", token=admin)[0] == 200


def test_role_user_cannot_manage(users):
    _, zhang, _ = users
    assert _req("/api/admin/catalog", token=zhang)[0] == 403
    assert _req("/api/admin/users", token=zhang)[0] == 403


def test_role_user_can_chat(users):
    _, zhang, _ = users
    assert _req("/api/conversations", token=zhang)[0] == 200


def test_dashboard_owner_can_access(users):
    admin, _, _ = users
    aid = json.loads(_req("/api/auth/me", token=admin)[1])["id"]
    d = f"workspace/data/{aid}"; os.makedirs(d, exist_ok=True)
    open(f"{d}/_test.html", "w").write("<html>test</html>")
    assert _req(f"/api/dashboards/{aid}/_test.html", token=admin)[0] == 200


def test_dashboard_cross_user_forbidden(users):
    admin, _, li = users
    aid = json.loads(_req("/api/auth/me", token=admin)[1])["id"]
    # li 访问 admin 的看板应 403
    assert _req(f"/api/dashboards/{aid}/_test.html", token=li)[0] == 403


def test_dashboard_no_token_unauthorized(users):
    admin, _, _ = users
    aid = json.loads(_req("/api/auth/me", token=admin)[1])["id"]
    assert _req(f"/api/dashboards/{aid}/_test.html")[0] == 401


# ---- 用户删除保护 ----

def test_delete_self_forbidden(users):
    admin, _, _ = users
    aid = json.loads(_req("/api/auth/me", token=admin)[1])["id"]
    s, b = _req(f"/api/admin/users/{aid}", "DELETE", token=admin)
    assert s == 200 and "error" in b  # 不能删除当前登录的管理员


def test_delete_other_admin_when_multiple(users):
    admin, _, _ = users
    # 再建一个 admin2，admin 删它（非自己）应成功
    s, b = _req("/api/admin/users", "POST", token=admin, body={"username": "admin2", "password": "x", "role": "admin"})
    a2 = json.loads(b)["id"]
    s2, b2 = _req(f"/api/admin/users/{a2}", "DELETE", token=admin)
    assert json.loads(b2).get("ok") is True


def test_delete_normal_user_ok(users):
    admin, _, _ = users
    # 建一个临时普通用户并删除
    s, b = _req("/api/admin/users", "POST", token=admin, body={"username": "tmpuser", "password": "x", "role": "user"})
    uid = json.loads(b)["id"]
    s2, b2 = _req(f"/api/admin/users/{uid}", "DELETE", token=admin)
    assert json.loads(b2).get("ok") is True
