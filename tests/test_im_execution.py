import asyncio
import sys
import types

from app.im.context import ActorContext
from app.im.execution import collect_text, run_agent_events


def _ctx():
    return ActorContext.isolated_feishu(
        app_id="cli_test", tenant_key="tenant_test", sender_open_id="ou_user",
        chat_id="oc_chat", chat_type="group",
    )


def test_run_agent_events_uses_isolated_subject(monkeypatch):
    seen = {}

    async def fake_stream(conv_id, input_, **kwargs):
        seen.update(kwargs)
        yield 'data: {"type":"token","content":"你好"}\n\n'
        yield 'data: {"type":"message_end","conversation_id":"c1"}\n\n'

    fake_module = types.ModuleType("app.streaming")
    fake_module._stream_run = fake_stream
    monkeypatch.setitem(sys.modules, "app.streaming", fake_module)
    async def run():
        return await collect_text(run_agent_events("c1", {"messages": []}, context=_ctx()))
    text, terminal = asyncio.run(run())

    assert text == "你好"
    assert terminal["type"] == "message_end"
    assert seen["user_id"] == _ctx().subject_id
    assert seen["role"] == "user"


def test_collect_text_keeps_error_terminal():
    async def events():
        yield {"type": "token", "content": "部分"}
        yield {"type": "error", "error_code": "timeout"}

    text, terminal = asyncio.run(collect_text(events()))
    assert text == "部分"
    assert terminal == {"type": "error", "error_code": "timeout"}
