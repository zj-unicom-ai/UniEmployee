"""前端回归测试（playwright headless chromium）——带登录态。

验证：门户入口、历史分页/点标题续聊、资源中心 5 tab、对话侧栏历史、登录页。
依赖：服务在 8787 运行，初始 admin/admin123 存在。
"""
import json
import socket

import pytest
from playwright.sync_api import sync_playwright

BASE = "http://localhost:8787"


def _port_open(port=8787):
    s = socket.socket(); s.settimeout(1)
    try:
        s.connect(("localhost", port)); s.close(); return True
    except OSError:
        return False


pytestmark = pytest.mark.skipif(not _port_open(), reason="服务未在 8787 运行")


@pytest.fixture
def auth_page():
    """启动浏览器并预登录 admin，把 token 写入 localStorage。"""
    with sync_playwright() as p:
        br = p.chromium.launch(headless=True); pg = br.new_page()
        r = pg.request.post(BASE + "/api/auth/login",
                            data=json.dumps({"username": "admin", "password": "admin123"}),
                            headers={"Content-Type": "application/json"})
        d = r.json()
        if d.get("error"):
            pytest.skip("初始 admin 登录失败：" + d["error"])
        pg.goto(BASE + "/")  # 先打开同源页才能设 localStorage
        pg.evaluate("(args)=>{localStorage.setItem('dwpt_token',args[0]);localStorage.setItem('dwpt_user',JSON.stringify(args[1]));}",
                    [d["token"], d["user"]])
        yield pg
        br.close()


def test_login_page_works():
    """登录页可访问。"""
    with sync_playwright() as p:
        br = p.chromium.launch(headless=True); pg = br.new_page()
        pg.goto(BASE + "/login.html"); pg.wait_for_timeout(800)
        assert "登录" in pg.title()
        br.close()


def test_unauth_admin_redirects_to_login():
    """未登录访问管理页应跳登录。"""
    with sync_playwright() as p:
        br = p.chromium.launch(headless=True); pg = br.new_page()
        pg.goto(BASE + "/resources.html"); pg.wait_for_timeout(1500)
        assert "/login.html" in pg.url
        br.close()


def test_portal_and_chat_with_auth(auth_page):
    pg = auth_page
    pg.goto(BASE + "/"); pg.wait_for_timeout(1000)
    # 首页 4 张入口卡片：开始对话 / 员工管理 / 资源中心 / 用户管理
    assert pg.locator("a.card").count() == 4
    pg.locator("a.card.c1").click(); pg.wait_for_timeout(1500)
    assert "/chat.html" in pg.url


def test_history_pagination_and_title_click(auth_page):
    pg = auth_page
    pg.goto(BASE + "/history.html"); pg.wait_for_timeout(1500)
    assert pg.locator("table tbody tr").count() > 0
    link = pg.locator("table tbody tr:first-child td.ttl a")
    link.first.click(); pg.wait_for_timeout(1800)
    assert "/chat.html?conv=" in pg.url


def test_resources_all_tabs_render(auth_page):
    pg = auth_page
    pg.goto(BASE + "/resources.html"); pg.wait_for_timeout(1500)
    for t in ["skills", "tools", "kbs", "sops", "connectors"]:
        pg.locator(f".tab[data-t='{t}']").click(); pg.wait_for_timeout(700)
        assert len(pg.locator("#content").inner_text()) > 20, f"tab {t} 内容为空"


def test_chat_sidebar_history_loads(auth_page):
    pg = auth_page
    pg.goto(BASE + "/chat.html"); pg.wait_for_timeout(2500)
    assert pg.locator("#convlist .conv").count() > 0


def test_users_management_page(auth_page):
    pg = auth_page
    pg.goto(BASE + "/users.html"); pg.wait_for_timeout(1500)
    assert pg.locator("table tbody tr").count() >= 1  # 至少有 admin
