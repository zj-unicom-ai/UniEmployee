"""安全加固回归（第一批）：
1. 封 X-User-Id 匿名回落 —— 无 token 冒充任意用户必须 401；
2. /api/debug/memory 收权 admin；
3. 登录失败返回 HTTP 401（不再是 200+error）；
4. 登录限流：同 IP+用户名 60s 内失败 >=5 次返回 429；
5. 改密接口 + must_change_password 流程。
依赖服务在 8787 运行（与其他 API 层测试一致）。"""
import json
import socket
import time
import uuid

import pytest
import urllib.error
import urllib.request

BASE = "http://localhost:8787"


def _port_open(port=8787):
    s = socket.socket(); s.settimeout(1)
    try:
        s.connect(("localhost", port)); s.close(); return True
    except OSError:
        return False


pytestmark = pytest.mark.skipif(not _port_open(), reason="服务未在 8787 运行")


def _req(path, method="GET", token=None, body=None, headers=None):
    h = {"Content-Type": "application/json"}
    if token:
        h["Authorization"] = "Bearer " + token
    if headers:
        h.update(headers)
    data = json.dumps(body).encode() if body else None
    r = urllib.request.Request(BASE + path, data=data, method=method, headers=h)
    try:
        resp = urllib.request.urlopen(r); return resp.status, resp.read().decode()
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode()


def _login(u, p):
    s, b = _req("/api/auth/login", "POST", body={"username": u, "password": p})
    return s, json.loads(b)


def _admin_token():
    s, d = _login("admin", "admin123")
    assert s == 200, d
    return d["token"]


# ---- 1. X-User-Id 冒充必须被封 ----

def test_x_user_id_spoof_rejected():
    """无 token、仅带 X-User-Id 头访问会话接口 → 401（此前可越权读任意用户会话）。"""
    for path in ("/api/conversations", "/api/conversations?page=1"):
        st, body = _req(path, headers={"X-User-Id": "u_20260725080257"})
        assert st == 401, f"{path} 仍可被 X-User-Id 冒充！status={st} body={body[:200]}"


def test_no_auth_rejected():
    """完全匿名访问会话接口 → 401。"""
    st, _ = _req("/api/conversations")
    assert st == 401


# ---- 2. debug 接口收权 ----

def test_debug_memory_requires_admin():
    # 匿名 → 401
    st, _ = _req("/api/debug/memory")
    assert st == 401
    # 普通用户 → 403
    s, d = _login("zhang", "z123")
    assert s == 200
    st2, _ = _req("/api/debug/memory", token=d["token"])
    assert st2 == 403, "普通用户不应能 dump 记忆"
    # admin → 200
    st3, _ = _req("/api/debug/memory", token=_admin_token())
    assert st3 == 200


# ---- 3. 登录失败 401 ----

def test_login_wrong_password_401():
    st, body = _req("/api/auth/login", "POST",
                    body={"username": "admin", "password": "wrong-pass-xyz"})
    assert st == 401, f"登录失败应返回 401，实际 {st}: {body[:200]}"


# ---- 4. 登录限流 ----

def test_login_rate_limit():
    """对一个随机用户名连续失败 5 次后，第 6 次应 429（按 IP+用户名 组合限流，
    随机用户名避免污染其他测试）。"""
    uname = "nouser_" + uuid.uuid4().hex[:8]
    for i in range(5):
        st, _ = _req("/api/auth/login", "POST",
                     body={"username": uname, "password": "x"})
        assert st == 401
    st6, body = _req("/api/auth/login", "POST",
                     body={"username": uname, "password": "x"})
    assert st6 == 429, f"第 6 次失败尝试应被限流(429)，实际 {st6}: {body[:200]}"


# ---- 5. 改密流程 ----

def test_change_password_flow():
    """建临时用户 → 登录 → 错误原密码 401 / 短密码 400 → 正确改密 → 新密码可登录。"""
    admin_tok = _admin_token()
    uname = "sec_" + uuid.uuid4().hex[:8]
    st, body = _req("/api/admin/users", "POST", token=admin_tok,
                    body={"username": uname, "password": "oldpass123", "role": "user"})
    assert st == 200, body

    s, d = _login(uname, "oldpass123")
    assert s == 200
    tok = d["token"]

    # 错误原密码
    st1, _ = _req("/api/auth/change-password", "POST", token=tok,
                  body={"old_password": "wrong", "new_password": "newpass456"})
    assert st1 == 401
    # 新密码太短
    st2, _ = _req("/api/auth/change-password", "POST", token=tok,
                  body={"old_password": "oldpass123", "new_password": "short"})
    assert st2 == 400
    # 正确改密
    st3, body3 = _req("/api/auth/change-password", "POST", token=tok,
                      body={"old_password": "oldpass123", "new_password": "newpass456"})
    assert st3 == 200, body3
    # 旧密码失效、新密码可登录，且 must_change_password 已清
    s4, _ = _login(uname, "oldpass123")
    assert s4 == 401
    s5, d5 = _login(uname, "newpass456")
    assert s5 == 200
    assert not d5.get("must_change_password")

    # 清理：软删临时用户
    uid = d["user"]["id"]
    _req(f"/api/admin/users/{uid}", "DELETE", token=admin_tok)


def test_admin_login_flags_must_change_password():
    """admin 仍用默认密码 admin123 → 登录响应应带 must_change_password=True。"""
    s, d = _login("admin", "admin123")
    assert s == 200
    assert d.get("must_change_password") is True, \
        "admin 默认密码未被标记强制改密（flag_default_admin_password 未生效？）"
