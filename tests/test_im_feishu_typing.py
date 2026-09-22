"""等待态：给用户那条消息加一个 Typing 表情回应，处理完移除。

这是 OpenClaw 的做法，也是我们原先漏掉的一环。价值在于它**不是一条消息** ——
而是对既有消息的一次操作，所以：

- 不会留下「已收到，正在处理」那种永不消失的提示（我们的老问题）；
- 不占群里的消息位；
- 卡片要先建卡再发送，而表情回应几乎瞬间可见，是最早的反馈信号。

风险是忘记移除：reaction 是**持久**的，会一直挂在用户消息下面。所以这里重点
覆盖「异常路径也必须撤掉」。
"""

import asyncio
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from app.im import worker
from app.im.cards import feishu as card_link
from app.im.credentials import ChannelCredential
from app.im.providers.feishu import FeishuProvider


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


def _inbox_row(*, created_at: str | None = None) -> dict:
    return {
        "id": "inbox_1",
        "channel_id": "chan_1",
        "provider_message_id": "om_user_1",
        "created_at": created_at or _now_iso(),
        "payload": {
            "provider": "feishu",
            "app_id": "app_1",
            "tenant_key": "corp_1",
            "chat_id": "oc_1",
            "chat_type": "p2p",
            "sender_open_id": "ou_1",
            "text": "你好",
        },
    }


# ---------------------------------------------------------------- Worker 层


class TypingProvider:
    """支持等待态的假 Provider。"""

    def __init__(self, *, start_result=None, start_error=None):
        self.calls: list = []
        self._start_result = start_result if start_result is not None else {"reaction_id": "r_1"}
        self._start_error = start_error

    async def start_typing(self, *, message_id):
        self.calls.append(("start", message_id))
        if self._start_error is not None:
            raise self._start_error
        return self._start_result

    async def stop_typing(self, handle):
        self.calls.append(("stop", handle))

    async def send(self, message):
        self.calls.append(("send", message.text))
        return SimpleNamespace(message_id="om_1")


class PlainProvider:
    """不支持等待态的假 Provider（比如钉钉当前的样子）。"""

    def __init__(self):
        self.calls: list = []

    async def send(self, message):
        self.calls.append(("send", message.text))
        return SimpleNamespace(message_id="om_1")


def _patch_jobs(monkeypatch, row: dict) -> None:
    monkeypatch.setattr(worker.jobs, "claim_inbox", lambda *a, **k: row)
    monkeypatch.setattr(
        worker.jobs, "get_or_create_thread", lambda *a, **k: ({"conv_id": "conv_1"}, False)
    )
    monkeypatch.setattr(worker.jobs, "create_outbox", lambda *a, **k: None)
    monkeypatch.setattr(worker.jobs, "finish_inbox", lambda *a, **k: None)
    monkeypatch.setattr(worker.jobs, "create_card_session", lambda **k: None)
    monkeypatch.setattr(worker.jobs, "finish_card_session", lambda *a, **k: None)


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    monkeypatch.delenv("IM_CARD_ENABLED", raising=False)
    monkeypatch.delenv("IM_PROGRESS_NOTICE", raising=False)
    monkeypatch.delenv("IM_TYPING_REACTION", raising=False)


def _events(order: list):
    async def _run(*args, **kwargs):
        order.append("execute")
        yield {"type": "token", "content": "答案"}

    return _run


def test_typing_wraps_execution(monkeypatch):
    row = _inbox_row()
    order: list = []
    provider = TypingProvider()
    _patch_jobs(monkeypatch, row)
    monkeypatch.setattr(worker, "run_agent_events", _events(order))

    assert asyncio.run(
        worker.process_inbox_once(provider=provider, channel_id="chan_1", employee_id="xiaoshu")
    ) is True

    # 先加回应（最早可见的反馈），执行，最后撤掉。
    assert provider.calls[0] == ("start", "om_user_1")
    assert provider.calls[-1][0] == "stop"
    assert order == ["execute"]
    # 撤掉时带上了 start 返回的句柄，否则删不掉。
    assert provider.calls[-1][1] == {"reaction_id": "r_1"}


def _typing_calls(provider) -> list:
    """只看等待态相关调用；无卡片时 Worker 还会发一条文本提示，与这里无关。"""
    return [call for call in provider.calls if call[0] in {"start", "stop"}]


def test_typing_removed_even_when_execution_fails(monkeypatch):
    row = _inbox_row()
    provider = TypingProvider()
    _patch_jobs(monkeypatch, row)

    async def _boom(*args, **kwargs):
        yield {"type": "token", "content": "部分"}
        raise RuntimeError("执行炸了")

    monkeypatch.setattr(worker, "run_agent_events", _boom)

    assert asyncio.run(
        worker.process_inbox_once(provider=provider, channel_id="chan_1", employee_id="xiaoshu")
    ) is False

    # 失败路径同样要撤掉：留着就是一个永远转圈的 Typing。
    assert [call[0] for call in _typing_calls(provider)] == ["start", "stop"]


def test_typing_skipped_for_stale_message(monkeypatch):
    """很旧的消息不加回应 —— 否则用户会在历史消息下看到一个凭空冒出的 Typing。"""
    old = (datetime.now(timezone.utc) - timedelta(seconds=600)).isoformat(timespec="milliseconds")
    row = _inbox_row(created_at=old)
    order: list = []
    provider = TypingProvider()
    _patch_jobs(monkeypatch, row)
    monkeypatch.setattr(worker, "run_agent_events", _events(order))

    asyncio.run(
        worker.process_inbox_once(provider=provider, channel_id="chan_1", employee_id="xiaoshu")
    )

    assert _typing_calls(provider) == []


def test_typing_start_failure_does_not_block_reply(monkeypatch):
    row = _inbox_row()
    order: list = []
    provider = TypingProvider(start_error=RuntimeError("接口 403"))
    _patch_jobs(monkeypatch, row)
    monkeypatch.setattr(worker, "run_agent_events", _events(order))

    assert asyncio.run(
        worker.process_inbox_once(provider=provider, channel_id="chan_1", employee_id="xiaoshu")
    ) is True

    # 等待态是锦上添花，失败了也要照常回复；没有句柄就不该去删（删不掉也删不干净）。
    assert [call[0] for call in _typing_calls(provider)] == ["start"]
    assert any(call[0] == "send" for call in provider.calls)


def test_provider_without_typing_capability_is_ignored(monkeypatch):
    row = _inbox_row()
    order: list = []
    provider = PlainProvider()
    _patch_jobs(monkeypatch, row)
    monkeypatch.setattr(worker, "run_agent_events", _events(order))

    assert asyncio.run(
        worker.process_inbox_once(provider=provider, channel_id="chan_1", employee_id="xiaoshu")
    ) is True

    assert provider.calls == [("send", worker.PROGRESS_NOTICE_TEXT)]


# ---------------------------------------------------------------- Provider 层


class FakeResponse:
    def __init__(self, status_code: int = 200, payload=None):
        self.status_code = status_code
        self._payload = {"code": 0} if payload is None else payload

    def json(self):
        return self._payload


class FakeHttp:
    def __init__(self, responses=None):
        self.requests: list[tuple[str, str, dict]] = []
        self._responses = list(responses or [])

    async def post(self, url, json=None, headers=None):
        self.requests.append(("POST", url, json))
        return self._take()

    async def delete(self, url, headers=None):
        self.requests.append(("DELETE", url, {}))
        return self._take()

    def _take(self):
        return self._responses.pop(0) if self._responses else FakeResponse()


def _provider(http) -> FeishuProvider:
    provider = FeishuProvider(
        ChannelCredential(
            channel_id="chan_1", app_id="app_1", tenant_key="corp_1", app_secret="secret"
        ),
        on_message=lambda message: None,
    )
    provider._http = http
    return provider


def _token_response() -> FakeResponse:
    return FakeResponse(payload={"code": 0, "tenant_access_token": "tok", "expire": 7200})


@pytest.fixture(autouse=True)
def _reset_token_cache():
    card_link.reset_token_cache()
    yield
    card_link.reset_token_cache()


def test_feishu_start_typing_adds_reaction():
    http = FakeHttp([_token_response(), FakeResponse(payload={"code": 0, "data": {"reaction_id": "r_9"}})])
    provider = _provider(http)

    handle = asyncio.run(provider.start_typing(message_id="om_1"))

    method, url, body = http.requests[-1]
    assert method == "POST"
    assert url.endswith("/im/v1/messages/om_1/reactions")
    assert body == {"reaction_type": {"emoji_type": "Typing"}}
    assert handle == {"message_id": "om_1", "reaction_id": "r_9"}


def test_feishu_stop_typing_removes_reaction():
    http = FakeHttp([_token_response(), FakeResponse(payload={"code": 0})])
    provider = _provider(http)

    asyncio.run(provider.stop_typing({"message_id": "om_1", "reaction_id": "r_9"}))

    method, url, _ = http.requests[-1]
    assert method == "DELETE"
    assert url.endswith("/im/v1/messages/om_1/reactions/r_9")


def test_feishu_typing_failure_is_silent():
    http = FakeHttp([_token_response(), FakeResponse(403, {"code": 99991672})])
    provider = _provider(http)

    assert asyncio.run(provider.start_typing(message_id="om_1")) is None


def test_feishu_typing_can_be_disabled_by_env(monkeypatch):
    monkeypatch.setenv("IM_TYPING_REACTION", "0")
    http = FakeHttp([_token_response()])
    provider = _provider(http)

    assert asyncio.run(provider.start_typing(message_id="om_1")) is None
    assert http.requests == []


def test_feishu_stop_typing_without_handle_is_noop():
    http = FakeHttp()
    provider = _provider(http)

    asyncio.run(provider.stop_typing(None))

    assert http.requests == []


def test_feishu_stop_typing_failure_does_not_raise():
    http = FakeHttp([_token_response(), FakeResponse(500, {"code": 200120})])
    provider = _provider(http)

    asyncio.run(provider.stop_typing({"message_id": "om_1", "reaction_id": "r_9"}))


def test_feishu_card_session_needs_no_template():
    """飞书不需要模板 —— 卡片 JSON 在代码里构造。"""
    provider = _provider(FakeHttp())

    session = provider.create_card_session(
        payload={"chat_id": "oc_1", "chat_type": "p2p"},
        template_id="",
        policy=None,
        reply_to="om_1",
    )

    assert session is not None
    assert session.card_id == ""


def test_feishu_card_session_requires_http_and_target():
    provider = _provider(None)

    assert provider.create_card_session(
        payload={"chat_id": "oc_1"}, template_id="", policy=None
    ) is None

    provider = _provider(FakeHttp())
    assert provider.create_card_session(
        payload={"chat_type": "p2p"}, template_id="", policy=None
    ) is None
