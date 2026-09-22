"""执行前提示：用户发消息到员工回复之间的等待反馈。

覆盖三件事：默认发送、可显式关闭、发送失败不得影响正式回复。
"""

import asyncio
from types import SimpleNamespace

import pytest

from app.im import worker


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


class RecordingProvider:
    """记录出站动作，用来断言提示先于正式回复。"""

    def __init__(self, *, order: list, fail: bool = False) -> None:
        self.sent = []
        self._order = order
        self._fail = fail

    async def send(self, message):
        if self._fail:
            self._order.append("notice-failed")
            raise RuntimeError("sessionWebhook 已过期")
        self._order.append("notice")
        self.sent.append(message)
        return SimpleNamespace(message_id="om_notice")


async def _fake_events(*args, **kwargs):
    yield {"type": "token", "content": "答案"}


def _patch_jobs(monkeypatch, row: dict, order: list) -> None:
    monkeypatch.setattr(worker.jobs, "claim_inbox", lambda *a, **k: row)
    monkeypatch.setattr(
        worker.jobs, "get_or_create_thread", lambda *a, **k: ({"conv_id": "conv_1"}, False)
    )
    monkeypatch.setattr(
        worker.jobs,
        "create_outbox",
        lambda inbox_id, message: order.append("outbox"),
    )
    monkeypatch.setattr(worker.jobs, "finish_inbox", lambda *a, **k: None)


def test_progress_notice_sent_before_agent_execution(monkeypatch):
    row = _inbox_row()
    order: list = []
    provider = RecordingProvider(order=order)
    _patch_jobs(monkeypatch, row, order)
    monkeypatch.setattr(worker, "run_agent_events", _fake_events)
    monkeypatch.delenv("IM_PROGRESS_NOTICE", raising=False)

    assert asyncio.run(
        worker.process_inbox_once(provider=provider, channel_id="chan_1", employee_id="xiaoshu")
    ) is True

    assert len(provider.sent) == 1
    notice = provider.sent[0]
    assert notice.text == worker.PROGRESS_NOTICE_TEXT
    # 提示要复用入站携带的回复目标，而不是硬编码 chat_id。
    assert notice.receive_id == "https://example.test/hook"
    assert notice.receive_id_type == "session_webhook"
    assert notice.channel_id == "chan_1"
    # 顺序：先提示，后正式回复入队。
    assert order == ["notice", "outbox"]


def test_progress_notice_failure_does_not_block_reply(monkeypatch):
    row = _inbox_row()
    order: list = []
    provider = RecordingProvider(order=order, fail=True)
    _patch_jobs(monkeypatch, row, order)
    monkeypatch.setattr(worker, "run_agent_events", _fake_events)
    monkeypatch.delenv("IM_PROGRESS_NOTICE", raising=False)

    # 提示发不出去，但整条 Inbox 仍算处理成功，正式回复照常入队。
    assert asyncio.run(
        worker.process_inbox_once(provider=provider, channel_id="chan_1", employee_id="xiaoshu")
    ) is True
    assert order == ["notice-failed", "outbox"]


def test_progress_notice_can_be_disabled(monkeypatch):
    row = _inbox_row()
    order: list = []
    provider = RecordingProvider(order=order)
    _patch_jobs(monkeypatch, row, order)
    monkeypatch.setattr(worker, "run_agent_events", _fake_events)

    for value in ("0", "false", "no", "off", "OFF"):
        order.clear()
        provider.sent.clear()
        monkeypatch.setenv("IM_PROGRESS_NOTICE", value)
        asyncio.run(
            worker.process_inbox_once(provider=provider, channel_id="chan_1", employee_id="xiaoshu")
        )
        assert provider.sent == [], f"{value} 应关闭提示"
        assert order == ["outbox"]


@pytest.mark.parametrize("value", ["1", "true", "yes", "on", ""])
def test_progress_notice_enabled_values(monkeypatch, value):
    monkeypatch.setenv("IM_PROGRESS_NOTICE", value)
    assert worker._progress_notice_enabled() is True
