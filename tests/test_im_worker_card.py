"""卡片链路的 Worker 接入：卡片优先、逐级降级、结果不丢。

卡片是体验优化而不是结果的唯一通道，所以这里重点覆盖各种「卡片不可用」的情形：
模板没配、投放失败、收尾失败、内容超长、执行报错 —— 每一条都必须让用户拿到结果，
或者至少拿到一个明确的失败态。
"""

import asyncio
from types import SimpleNamespace

import pytest

from app.im import worker
from app.im.cards import MAX_CARD_CONTENT_CHARS, WORKING_TEXT


def _inbox_row() -> dict:
    return {
        "id": "inbox_1",
        "channel_id": "chan_1",
        "provider_message_id": "msg_1",
        "payload": {
            "provider": "dingtalk",
            "app_id": "app_1",
            "tenant_key": "corp_1",
            "chat_id": "conv_1",
            "chat_type": "p2p",
            "sender_open_id": "staff_1",
            "text": "你好",
            "reply_target": "https://example.test/hook",
            "reply_target_type": "session_webhook",
        },
    }


class FakeCard:
    """假卡片会话：记录生命周期调用，可按需让投放或收尾失败。"""

    def __init__(self, *, open_error=None, finalize_error=None):
        self.out_track_id = "track_1"
        self.update_count = 0
        self.opened_with = None
        self.pushed: list[str] = []
        self.finalized_with = None
        self.failed_with = None
        self._open_error = open_error
        self._finalize_error = finalize_error

    async def open(self, text):
        if self._open_error is not None:
            raise self._open_error
        self.opened_with = text

    async def push(self, text):
        self.pushed.append(text)
        self.update_count += 1

    async def finalize(self, text):
        if self._finalize_error is not None:
            raise self._finalize_error
        self.finalized_with = text

    async def fail(self, text):
        self.failed_with = text


class CardProvider:
    """支持卡片的假 Provider。"""

    def __init__(self, card):
        self.card = card
        self.sent: list = []
        self.template_id = None

    def create_card_session(self, *, payload, template_id, policy):
        self.template_id = template_id
        return self.card

    async def send(self, message):
        self.sent.append(message)
        return SimpleNamespace(message_id="om_1")


class PlainProvider:
    """不支持卡片的假 Provider（比如飞书）。"""

    def __init__(self):
        self.sent: list = []

    async def send(self, message):
        self.sent.append(message)
        return SimpleNamespace(message_id="om_1")


def _events_of(text: str):
    async def _events(*args, **kwargs):
        # 逐字符产出，贴近真实 token 流：on_delta 会被高频调用。
        for char in text:
            yield {"type": "token", "content": char}

    return _events


def _patch_jobs(monkeypatch, row: dict, order: list) -> None:
    monkeypatch.setattr(worker.jobs, "claim_inbox", lambda *a, **k: row)
    monkeypatch.setattr(
        worker.jobs, "get_or_create_thread", lambda *a, **k: ({"conv_id": "conv_1"}, False)
    )
    monkeypatch.setattr(
        worker.jobs, "create_outbox", lambda inbox_id, message: order.append("outbox")
    )
    monkeypatch.setattr(worker.jobs, "finish_inbox", lambda *a, **k: None)
    monkeypatch.setattr(
        worker.jobs, "create_card_session", lambda **k: order.append("card-open")
    )
    monkeypatch.setattr(
        worker.jobs,
        "finish_card_session",
        lambda inbox_id, **k: order.append(f"card:{k.get('status')}"),
    )


@pytest.fixture
def card_env(monkeypatch):
    """卡片可用：开关默认开 + 配好模板 ID。"""
    monkeypatch.setenv("DINGTALK_CARD_TEMPLATE_ID", "tpl_1")
    monkeypatch.setenv("IM_CARD_LEVEL", "staged")
    monkeypatch.delenv("IM_CARD_ENABLED", raising=False)
    monkeypatch.delenv("IM_PROGRESS_NOTICE", raising=False)


def test_card_carries_result_without_extra_text_message(monkeypatch, card_env):
    row = _inbox_row()
    order: list = []
    card = FakeCard()
    provider = CardProvider(card)
    _patch_jobs(monkeypatch, row, order)
    monkeypatch.setattr(worker, "run_agent_events", _events_of("你好呀"))

    assert asyncio.run(
        worker.process_inbox_once(provider=provider, channel_id="chan_1", employee_id="xiaoshu")
    ) is True

    # 卡片的初始文案就是「正在处理」，因此不再单独发一条文本提示。
    assert card.opened_with == WORKING_TEXT
    assert provider.sent == []
    assert card.finalized_with == "你好呀"
    assert order == ["card-open", "card:completed"]


def test_worker_forwards_every_token_to_card(monkeypatch, card_env):
    """Worker 不做节流，逐 token 转发；要不要真的发出去由卡片会话决定。"""
    row = _inbox_row()
    order: list = []
    card = FakeCard()
    provider = CardProvider(card)
    _patch_jobs(monkeypatch, row, order)
    monkeypatch.setattr(worker, "run_agent_events", _events_of("你好呀"))

    asyncio.run(
        worker.process_inbox_once(provider=provider, channel_id="chan_1", employee_id="xiaoshu")
    )

    assert card.pushed == ["你", "你好", "你好呀"]
    assert provider.template_id == "tpl_1"


def test_card_open_failure_falls_back_to_text(monkeypatch, card_env):
    row = _inbox_row()
    order: list = []
    card = FakeCard(open_error=RuntimeError("模板无权限"))
    provider = CardProvider(card)
    _patch_jobs(monkeypatch, row, order)
    monkeypatch.setattr(worker, "run_agent_events", _events_of("答案"))

    assert asyncio.run(
        worker.process_inbox_once(provider=provider, channel_id="chan_1", employee_id="xiaoshu")
    ) is True

    assert card.opened_with is None
    # 退回改动前的行为：一条文本提示 + 一条正式回复。
    assert len(provider.sent) == 1
    assert provider.sent[0].text == worker.PROGRESS_NOTICE_TEXT
    assert order == ["outbox"]


def test_finalize_failure_still_delivers_result_by_text(monkeypatch, card_env):
    row = _inbox_row()
    order: list = []
    card = FakeCard(finalize_error=RuntimeError("卡片更新 500"))
    provider = CardProvider(card)
    _patch_jobs(monkeypatch, row, order)
    monkeypatch.setattr(worker, "run_agent_events", _events_of("答案"))

    assert asyncio.run(
        worker.process_inbox_once(provider=provider, channel_id="chan_1", employee_id="xiaoshu")
    ) is True

    # 收尾失败不能让用户什么都收不到。
    assert order == ["card-open", "outbox", "card:finalize_failed"]


def test_long_result_is_truncated_on_card_and_sent_by_text(monkeypatch, card_env):
    row = _inbox_row()
    order: list = []
    card = FakeCard()
    provider = CardProvider(card)
    _patch_jobs(monkeypatch, row, order)
    monkeypatch.setattr(worker, "run_agent_events", _events_of("长" * (MAX_CARD_CONTENT_CHARS + 400)))

    assert asyncio.run(
        worker.process_inbox_once(provider=provider, channel_id="chan_1", employee_id="xiaoshu")
    ) is True

    assert len(card.finalized_with) <= MAX_CARD_CONTENT_CHARS
    # 卡片装不下，完整结果改用文本补发。
    assert order == ["card-open", "outbox", "card:truncated"]


def test_execution_error_marks_card_failed(monkeypatch, card_env):
    row = _inbox_row()
    order: list = []
    card = FakeCard()
    provider = CardProvider(card)
    _patch_jobs(monkeypatch, row, order)

    async def _boom(*args, **kwargs):
        yield {"type": "token", "content": "部分"}
        raise RuntimeError("执行炸了")

    monkeypatch.setattr(worker, "run_agent_events", _boom)

    assert asyncio.run(
        worker.process_inbox_once(provider=provider, channel_id="chan_1", employee_id="xiaoshu")
    ) is False

    # 卡片不能一直停在「输入中」。
    assert card.failed_with is not None
    assert order == ["card-open", "card:abandoned"]


def test_terminal_error_event_marks_card_failed(monkeypatch, card_env):
    row = _inbox_row()
    order: list = []
    card = FakeCard()
    provider = CardProvider(card)
    _patch_jobs(monkeypatch, row, order)

    async def _events(*args, **kwargs):
        yield {"type": "token", "content": "部分"}
        yield {"type": "error", "message": "模型超时"}

    monkeypatch.setattr(worker, "run_agent_events", _events)

    assert asyncio.run(
        worker.process_inbox_once(provider=provider, channel_id="chan_1", employee_id="xiaoshu")
    ) is False

    assert card.failed_with is not None
    assert order == ["card-open", "card:abandoned"]


def test_card_requires_template_id(monkeypatch):
    monkeypatch.delenv("DINGTALK_CARD_TEMPLATE_ID", raising=False)
    monkeypatch.delenv("IM_CARD_ENABLED", raising=False)
    monkeypatch.delenv("IM_PROGRESS_NOTICE", raising=False)
    row = _inbox_row()
    order: list = []
    card = FakeCard()
    provider = CardProvider(card)
    _patch_jobs(monkeypatch, row, order)
    monkeypatch.setattr(worker, "run_agent_events", _events_of("答案"))

    assert asyncio.run(
        worker.process_inbox_once(provider=provider, channel_id="chan_1", employee_id="xiaoshu")
    ) is True

    # 没配模板就发卡片只会得到一张空卡片，退文本更稳。
    assert card.opened_with is None
    assert order == ["outbox"]


def test_card_can_be_disabled_by_env(monkeypatch, card_env):
    monkeypatch.setenv("IM_CARD_ENABLED", "0")
    row = _inbox_row()
    order: list = []
    card = FakeCard()
    provider = CardProvider(card)
    _patch_jobs(monkeypatch, row, order)
    monkeypatch.setattr(worker, "run_agent_events", _events_of("答案"))

    asyncio.run(
        worker.process_inbox_once(provider=provider, channel_id="chan_1", employee_id="xiaoshu")
    )

    assert card.opened_with is None
    assert order == ["outbox"]


def test_provider_without_card_capability_uses_text(monkeypatch, card_env):
    """飞书这类没有卡片能力的渠道不受影响。"""
    row = _inbox_row()
    order: list = []
    provider = PlainProvider()
    _patch_jobs(monkeypatch, row, order)
    monkeypatch.setattr(worker, "run_agent_events", _events_of("答案"))

    assert asyncio.run(
        worker.process_inbox_once(provider=provider, channel_id="chan_1", employee_id="xiaoshu")
    ) is True

    assert len(provider.sent) == 1
    assert order == ["outbox"]


def test_approval_required_reaches_card(monkeypatch, card_env):
    row = _inbox_row()
    order: list = []
    card = FakeCard()
    provider = CardProvider(card)
    _patch_jobs(monkeypatch, row, order)

    async def _events(*args, **kwargs):
        yield {"type": "approval_required"}

    monkeypatch.setattr(worker, "run_agent_events", _events)

    asyncio.run(
        worker.process_inbox_once(provider=provider, channel_id="chan_1", employee_id="xiaoshu")
    )

    assert "审批" in card.finalized_with
