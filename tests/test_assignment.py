"""数字员工分配 + 用户级覆盖（模板化）回归测试。需服务在 8787 运行。

覆盖：
- 管理员分配/取消分配；普通用户不能分配（403）
- 普通用户 /api/employees 只看见已分配
- 未分配用户开会话被拒
- 覆盖 add/remove 合并正确（基础不变、有效变化）
- A 用户的覆盖不影响 B 用户（隔离）
- 管理员走纯模板（不过滤）

注意：管理类 URL 用 user_id（与前端一致），普通用户端点用 token 自带身份。
"""
import json
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
def env():
    admin = _login("admin", "admin123")
    ids, toks = {}, {}
    for name, pw in [("ast_a", "a123"), ("ast_b", "b123"), ("ast_c", "c123")]:
        r = _req("/api/admin/users", "POST", token=admin,
                 body={"username": name, "password": pw, "role": "user"})
        uid = json.loads(r[1]).get("id")
        if not uid:  # 已存在则查列表取 id
            lst = json.loads(_req("/api/admin/users", token=admin)[1])
            uid = next(u["id"] for u in lst if u["username"] == name)
        ids[name] = uid
        toks[name] = _login(name, pw)
    # 清理历史分配，保证幂等
    for uid in ids.values():
        lst = json.loads(_req(f"/api/admin/users/{uid}/employees", token=admin)[1])
        for e in lst.get("employees", []):
            if e["granted"]:
                _req(f"/api/admin/users/{uid}/employees/{e['employee_id']}",
                     "DELETE", token=admin)
    return {"admin": admin, "ids": ids,
            "a": toks["ast_a"], "b": toks["ast_b"], "c": toks["ast_c"],
            "emp": "unicom-presale"}


def _assign(env, username, emp):
    _req(f"/api/admin/users/{env['ids'][username]}/employees", "POST",
         token=env["admin"], body={"employee_id": emp})


def _unassign(env, username, emp):
    _req(f"/api/admin/users/{env['ids'][username]}/employees/{emp}",
         "DELETE", token=env["admin"])


def test_admin_assign_and_list(env):
    _assign(env, "ast_a", env["emp"])
    s, b = _req(f"/api/admin/users/{env['ids']['ast_a']}/employees", token=env["admin"])
    data = json.loads(b)
    row = next(x for x in data["employees"] if x["employee_id"] == env["emp"])
    assert row["granted"] is True


def test_user_cannot_assign(env):
    s, _ = _req(f"/api/admin/users/{env['ids']['ast_b']}/employees", "POST",
                token=env["a"], body={"employee_id": env["emp"]})
    assert s == 403  # 普通用户不能分配


def test_user_sees_only_assigned(env):
    # ast_a 已分配 unicom-presale；ast_c 未分配 → 空
    s, b = _req("/api/employees", token=env["a"])
    assert env["emp"] in [e["id"] for e in json.loads(b)]
    s, b = _req("/api/employees", token=env["c"])
    assert json.loads(b) == []


def test_unassigned_cannot_open_conversation(env):
    s, b = _req(f"/api/employees/{env['emp']}/conversations", "POST", token=env["c"])
    assert "error" in json.loads(b)  # 拒绝，无 conversation_id


def test_override_merge_and_isolation(env):
    a, b, admin, emp = env["a"], env["b"], env["admin"], env["emp"]
    _assign(env, "ast_a", emp)
    _assign(env, "ast_b", emp)
    # 基础能力
    base = json.loads(_req(f"/api/me/employees/{emp}", token=a)[1])["base"]
    assert "unicom-presale-faq" in base["skills"]
    assert "data-analysis" not in base["skills"]  # unicom-presale 模板无此技能
    # A 附加 data-analysis，移除 unicom-presale-faq
    ov = {"add": {"skills": ["data-analysis"]}, "remove": {"skills": ["unicom-presale-faq"]}}
    s, body = _req(f"/api/me/employees/{emp}/overrides", "PUT", token=a, body={"overrides": ov})
    assert json.loads(body).get("ok") is True
    eff_a = json.loads(_req(f"/api/me/employees/{emp}", token=a)[1])["effective"]
    assert "data-analysis" in eff_a["skills"]
    assert "unicom-presale-faq" not in eff_a["skills"]
    # 基础能力恒定不变
    base2 = json.loads(_req(f"/api/me/employees/{emp}", token=a)[1])["base"]
    assert "unicom-presale-faq" in base2["skills"]
    # 隔离：B 不应受 A 影响
    eff_b = json.loads(_req(f"/api/me/employees/{emp}", token=b)[1])["effective"]
    assert "data-analysis" not in eff_b["skills"], "A 的覆盖不应影响 B"
    assert "unicom-presale-faq" in eff_b["skills"], "B 仍保留模板基础"


def test_admin_uses_pure_template(env):
    admin, emp = env["admin"], env["emp"]
    s, b = _req("/api/employees", token=admin)
    assert emp in [e["id"] for e in json.loads(b)]  # 管理员不过滤
    s, b = _req("/api/me/employees", token=admin)
    assert isinstance(json.loads(b), list)


def test_admin_unassign(env):
    _assign(env, "ast_a", env["emp"])
    _unassign(env, "ast_a", env["emp"])
    s, b = _req("/api/employees", token=env["a"])
    assert env["emp"] not in [e["id"] for e in json.loads(b)]
