"""回归：新建对话（点“新会话”/切换员工）不应立即落库产生空历史记录；
真正写入发生在首条消息。依赖服务在 8787 运行。"""
import json
import sqlite3
import socket
from pathlib import Path

import pytest
import urllib.error
import urllib.request
from playwright.sync_api import sync_playwright

BASE = "http://localhost:8787"
DB = str(Path(__file__).resolve().parent.parent / "data" / "db" / "conversations.db")


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


def _db_count():
    c = sqlite3.connect(DB)
    n = c.execute("SELECT count(*) FROM conversations").fetchone()[0]
    c.close()
    return n


def test_new_conversation_does_not_persist_empty_record():
    """点“新会话”只生成 conv_id，不应在 conversations 表写入任何行；
    只有发出首条消息才落库。"""
    tok = _login_token("admin", "admin123")
    before = _db_count()

    # 1) 模拟前端 selectEmployee：开新会话（此时还没说话）
    st, body = _req("/api/employees/xiaosu/conversations", "POST", token=tok)
    assert st == 200, body
    conv_id = json.loads(body)["conversation_id"]
    after_new = _db_count()
    assert after_new == before, "开会话不应立即落库（产生了空历史记录）"
    # 且库里不应存在该 conv_id
    c = sqlite3.connect(DB)
    exists = c.execute("SELECT 1 FROM conversations WHERE conv_id=?", (conv_id,)).fetchone()
    c.close()
    assert exists is None, "空会话竟已写入 conversations 表"

    # 2) 发首条消息 → 此时才落库，且标题/归属正确
    st2, _ = _req(f"/api/conversations/{conv_id}/messages", "POST", token=tok,
                     body={"message": "记住我姓张，回复要简短"})
    # SSE 流式返回 200
    assert st2 == 200, "发送首条消息失败"
    after_msg = _db_count()
    assert after_msg == before + 1, "首条消息后应恰好新增 1 条历史记录"

    c = sqlite3.connect(DB); c.row_factory = sqlite3.Row
    row = c.execute("SELECT * FROM conversations WHERE conv_id=?", (conv_id,)).fetchone()
    c.close()
    assert row is not None
    assert row["employee_id"] == "xiaosu"
    assert "张" in (row["title"] or ""), "标题应由首句/模型提炼，含用户关键信息"


def test_browser_new_conv_no_sidebar_entry_until_message():
    """UI 层面：点“新会话”不会在历史侧栏新增空条目；发消息后才出现。"""
    tok = _login_token("admin", "admin123")
    me = json.loads(_req("/api/auth/me", token=tok)[1])
    with sync_playwright() as p:
        br = p.chromium.launch(headless=True); pg = br.new_page()
        pg.goto(BASE + "/")
        pg.evaluate(
            "(a)=>{localStorage.setItem('dwpt_token',a[0]);localStorage.setItem('dwpt_user',JSON.stringify(a[1]));}",
            [tok, me])
        pg.goto(BASE + "/chat.html"); pg.wait_for_timeout(2000)

        def sidebar_count():
            return pg.locator("#convlist .conv").count()

        n0 = sidebar_count()
        # 点“新会话”（顶栏按钮）
        pg.locator("header button:has-text('新会话')").click()
        pg.wait_for_timeout(800)
        assert sidebar_count() == n0, "点“新会话”后侧栏不应新增空条目"

        # 输入并发送首条消息
        pg.fill("#input", "你好，帮我查一下订单 O12345")
        pg.click("#send")
        pg.wait_for_timeout(5000)  # 等流式返回结束 + 侧栏刷新
        # 侧栏按 limit=15 截断，不能简单用 count+1；改为校验新会话（含订单号）已出现
        assert pg.locator("#convlist .conv", has_text="O12345").count() >= 1, \
            "发消息后侧栏应出现包含该消息内容的新会话"
        br.close()
