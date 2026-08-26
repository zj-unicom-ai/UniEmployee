"""思考内容过滤：content 内联的思考标签不进标题、不进历史消息。

背景见 PR #1：部分模型把思考过程（<thinking>...</thinking>、[思考]... 等）
内联在 content 里返回，污染标题生成与历史记录。结构化思考字段
（reasoning_content）已走独立 SSE thinking 通道，这里只处理内联文本标签。
"""

import asyncio
from types import SimpleNamespace

import pytest
from langchain_core.messages import AIMessage, HumanMessage

from app import conversations
from app.streaming import _gen_title, _strip_thinking, reconstruct, text_of


# ---------------- _strip_thinking ----------------

@pytest.mark.parametrize("src,want", [
    # 成对标签块
    ("<thinking>推理</thinking>正式回答", "正式回答"),
    ("<think>推理</think>正式回答", "正式回答"),
    ("[THINKING]推理[/THINKING]正式回答", "正式回答"),
    ("[think]推理[/think]正式回答", "正式回答"),
    ("[思考]推理[/思考]正式回答", "正式回答"),
    # 中置块 + 多块
    ("前文 <thinking>中间思考</thinking> 后文", "前文  后文"),
    ("<think>a</think>答1[思考]b[/思考]答2", "答1答2"),
    # 未闭合开头标签：截断思考整段丢弃
    ("<think>未闭合的思考", ""),
    ("[思考]未闭合", ""),
    # 大小写不敏感
    ("<THINKING>X</THINKING>答", "答"),
    # 跨行块（DOTALL）
    ("<think>第一行\n第二行</think>答", "答"),
    # 多余空行收敛
    ("a\n\n\n\nb", "a\n\nb"),
    # 无标签原样（仅去首尾空白）
    ("  正常内容  ", "正常内容"),
    ("", ""),
])
def test_strip_thinking(src, want):
    assert _strip_thinking(src) == want


def test_strip_thinking_keeps_markdown_content():
    """正文里合法的 markdown（行内代码/删除线）不受影响。

    真实库 136 处反引号全是合法代码、标签型思考 0 次——这是不按
    反引号/删除线过滤的依据（与 PR #1 的有意差异）。
    """
    inline_code = "运行 " + chr(96) + "pip install x" + chr(96) + " 安装"
    assert _strip_thinking(inline_code) == inline_code
    assert _strip_thinking("~~旧价格~~ 新价格") == "~~旧价格~~ 新价格"
    fence = chr(96) * 3 + "python\nprint(1)\n" + chr(96) * 3
    assert _strip_thinking("代码：\n" + fence) == "代码：\n" + fence


# ---------------- text_of 三分支 ----------------

def test_text_of_filters_all_branches():
    m = AIMessage(content="<think>内部</think>答案")
    assert text_of(m) == "答案"
    m2 = AIMessage(content=[{"type": "text", "text": "[思考]x[/思考]y"},
                            {"type": "image_url"}])
    assert text_of(m2) == "y"


def test_reconstruct_history_clean():
    """历史消息重构后，轮次内容不含思考标签。"""
    turns = reconstruct([
        HumanMessage(content="你好"),
        AIMessage(content="<think>用户在打招呼…</think>你好！有什么可以帮你？"),
    ])
    assert turns[1]["content"] == "你好！有什么可以帮你？"


# ---------------- _gen_title ----------------

def test_gen_title_uses_cleaned_bot_text(monkeypatch):
    """标题 prompt 不含思考内容；标题本身带思考标签也会被清理。"""
    conversations.create("c_title1", "xiaosu", title="新对话")
    seen = {}

    async def fake_ainvoke(msgs):
        seen["prompt"] = msgs[0].content
        return SimpleNamespace(content="<think>标题思考</think>“退款咨询”")

    monkeypatch.setattr(
        "app.streaming._init_model",
        lambda *_: SimpleNamespace(ainvoke=fake_ainvoke))

    asyncio.run(_gen_title("c_title1", "我要退款",
                           "<think>思考…</think>好的，为您处理退款"))

    assert "思考…" not in seen["prompt"]
    assert "为您处理退款" in seen["prompt"]
    assert conversations.get("c_title1")["title"] == "退款咨询"


def test_gen_title_all_thinking_falls_back(monkeypatch):
    """bot_text 全是思考时回退用原文，不传空串。"""
    conversations.create("c_title2", "xiaosu", title="新对话")
    seen = {}

    async def fake_ainvoke(msgs):
        seen["prompt"] = msgs[0].content
        return SimpleNamespace(content="纯思考对话")

    monkeypatch.setattr(
        "app.streaming._init_model",
        lambda *_: SimpleNamespace(ainvoke=fake_ainvoke))

    asyncio.run(_gen_title("c_title2", "你好",
                           "[思考]全是思考没有正文[/思考]"))

    assert "全是思考没有正文" in seen["prompt"]
    assert conversations.get("c_title2")["title"] == "纯思考对话"
