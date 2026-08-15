"""前端回归：执行过程（trace）查看页（playwright headless chromium）。

验证：
- trace.html 能列出某会话的运行记录（runcard）
- 点击 run 展示事件时间线（LLM/工具事件、状态摘要）
- 无权会话/缺参数时给出提示而非白屏

依赖：服务在 8787 运行，zhang/z123 存在且至少有一条带 trace 的会话
（trace 功能上线后发过消息即有）。
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
    return json.loads(_req("/api/auth/login", "POST", body={"username": u, "password": p})[1]).get("token")


def _conv_with_trace(token):
    """找 zhang 名下第一条有 trace run 的会话。"""
    convs = json.loads(_req("/api/conversations", token=token)[1])
    for c in convs:
        d = json.loads(_req(f"/api/conversations/{c['conv_id']}/traces", token=token)[1])
        if d.get("runs"):
            return c["conv_id"]
    return None


def test_trace_page_shows_runs_and_events():
    zhang = _login_token("zhang", "z123")
    conv = _conv_with_trace(zhang)
    if not conv:
        pytest.skip("zhang 名下暂无带 trace 的会话")
    me = json.loads(_req("/api/auth/me", token=zhang)[1])

    with sync_playwright() as p:
        br = p.chromium.launch(headless=True); pg = br.new_page()
        pg.goto(BASE + "/")
        pg.evaluate(
            "(a)=>{localStorage.setItem('dwpt_token',a[0]);localStorage.setItem('dwpt_user',JSON.stringify(a[1]));}",
            [zhang, me])
        pg.goto(f"{BASE}/trace.html?conv={conv}"); pg.wait_for_timeout(1500)

        # 左侧至少一张 run 卡片，且第一张自动选中
        assert pg.locator(".runcard").count() >= 1, "未显示运行记录"
        assert pg.locator(".runcard.on").count() == 1, "首条 run 未自动选中"
        # 右侧摘要与事件时间线渲染
        assert pg.locator(".summary").is_visible(), "运行摘要未渲染"
        assert pg.locator(".ev").count() >= 1, "事件时间线为空"
        # 展开第一个事件应显示输入/输出
        pg.locator(".ev").first.click(); pg.wait_for_timeout(300)
        assert pg.locator(".ev.open .ev-body").first.is_visible(), "事件详情未展开"
        br.close()


def test_trace_page_handles_missing_conv():
    zhang = _login_token("zhang", "z123")
    me = json.loads(_req("/api/auth/me", token=zhang)[1])
    with sync_playwright() as p:
        br = p.chromium.launch(headless=True); pg = br.new_page()
        pg.goto(BASE + "/")
        pg.evaluate(
            "(a)=>{localStorage.setItem('dwpt_token',a[0]);localStorage.setItem('dwpt_user',JSON.stringify(a[1]));}",
            [zhang, me])
        pg.goto(f"{BASE}/trace.html?conv=c_not_exists"); pg.wait_for_timeout(1200)
        body = pg.locator("#runs").inner_text()
        assert "会话不存在" in body or "无权" in body, "无效会话应有明确提示"
        br.close()
