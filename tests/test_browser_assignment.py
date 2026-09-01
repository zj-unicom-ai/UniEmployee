"""前端回归：数字员工分配 + 我的调整（playwright headless chromium）。

验证：
- 普通用户对话页只显示已分配员工，"我的调整"按钮可见
- "我的调整"弹窗可附加技能并保存（覆盖仅作用自己）
- 管理员在用户管理页可勾选分配/取消分配，且实时生效

依赖：服务在 8787 运行，初始 admin/admin123 存在。
"""
import json
import socket

import pytest
import urllib.error
import urllib.request
from playwright.sync_api import sync_playwright

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
        resp = urllib.request.urlopen(r); return resp.status, resp.read().decode()
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode()


def _login_token(u, p):
    s, b = _req("/api/auth/login", "POST", body={"username": u, "password": p})
    return json.loads(b).get("token")


def _seed_user(token, name, pw):
    _req("/api/admin/users", "POST", token=token, body={"username": name, "password": pw, "role": "user"})


def _user_id(token, username):
    """管理类 URL 用 user_id（与前端一致），这里按用户名查回 id。"""
    lst = json.loads(_req("/api/admin/users", token=token)[1])
    return next(u["id"] for u in lst if u["username"] == username)


def _browser_login(pg, token, user):
    pg.goto(BASE + "/")
    pg.evaluate(
        "(a)=>{localStorage.setItem('dwpt_token',a[0]);localStorage.setItem('dwpt_user',JSON.stringify(a[1]));}",
        [token, user])


def test_regular_user_chat_shows_assigned_and_can_tune():
    admin = _login_token("admin", "admin123")
    zhang = _login_token("zhang", "z123")
    zid = _user_id(admin, "zhang")
    # 确保 zhang 已分配 unicom-presale（保险起见重新分配）
    _req(f"/api/admin/users/{zid}/employees", "POST", token=admin, body={"employee_id": "unicom-presale"})

    with sync_playwright() as p:
        br = p.chromium.launch(headless=True); pg = br.new_page()
        # 取 zhang 的 user 对象（用于写 localStorage）
        me = json.loads(_req("/api/auth/me", token=zhang)[1])
        _browser_login(pg, zhang, me)
        pg.goto(BASE + "/chat.html"); pg.wait_for_timeout(2500)

        # 选择器应含 unicom-presale（option value 为员工 id），且"我的调整"可见（普通用户）
        vals = pg.locator("#empselect option").evaluate_all("els => els.map(e => e.value)")
        assert "unicom-presale" in vals, "未显示已分配的 unicom-presale"
        assert pg.locator("#tuneBtn").is_visible(), "普通用户应看到'我的调整'"
        # 显式选中，避免"我的调整"作用到默认的第一个员工
        pg.select_option("#empselect", "unicom-presale"); pg.wait_for_timeout(1500)

        # 打开"我的调整"，勾选 data-analysis 并保存
        pg.locator("#tuneBtn").click(); pg.wait_for_timeout(500)
        assert pg.locator("#tuneModal").is_visible()
        chk = pg.locator('.tune-chk[data-id="data-analysis"]')
        assert chk.count() == 1, "应出现 data-analysis 可选项"
        chk.check()
        pg.locator("#tuneSave").click(); pg.wait_for_timeout(600)

        # 验证覆盖已生效（仅 zhang 自己）
        eff = json.loads(_req(f"/api/me/employees/unicom-presale", token=zhang)[1])["effective"]
        assert "data-analysis" in eff["skills"], "附加技能未生效"
        br.close()


def test_admin_assignment_ui_grants_and_revokes():
    admin = _login_token("admin", "admin123")
    zhang = _login_token("zhang", "z123")
    zid = _user_id(admin, "zhang")
    _req(f"/api/admin/users/{zid}/employees", "POST", token=admin, body={"employee_id": "unicom-presale"})
    try:
        with sync_playwright() as p:
            br = p.chromium.launch(headless=True); pg = br.new_page()
            me = json.loads(_req("/api/auth/me", token=admin)[1])
            _browser_login(pg, admin, me)
            pg.goto(BASE + "/users.html"); pg.wait_for_timeout(1500)

            # 找到 zhang 行，点"分配"
            row = pg.locator("#rows tr", has_text="zhang")
            row.locator("button", has_text="分配").click()
            pg.wait_for_timeout(500)
            assert pg.locator("#modal").is_visible(), "分配弹窗未打开"
            # 取消勾选 unicom-presale 并保存
            pg.locator('.asg-chk[data-emp="unicom-presale"]').uncheck()
            pg.locator("#mSave").click(); pg.wait_for_timeout(700)

            # zhang 不再分配 unicom-presale
            emps = [e["id"] for e in json.loads(_req("/api/employees", token=zhang)[1])]
            assert "unicom-presale" not in emps, "取消分配未生效"
            br.close()
    finally:
        # 还原 zhang 的分配，保持 demo 状态
        _req(f"/api/admin/users/{zid}/employees", "POST", token=admin, body={"employee_id": "unicom-presale"})
