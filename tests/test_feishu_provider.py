import asyncio
from types import SimpleNamespace

from app.im.contracts import OutboundMessage
from app.im.credentials import ChannelCredential
from app.im.providers.feishu import FeishuProvider, normalize_message


def msg(**kwargs):
    base = dict(
        raw_content_type="text",
        chat_type="p2p",
        message_id="om_1",
        chat_id="oc_1",
        sender_id="ou_1",
        content_text="hello",
        mentioned_bot=False,
    )
    base.update(kwargs)
    return SimpleNamespace(**base)


def raw_event(*, message_id="om_1", tenant_key="tenant_from_feishu", event_id="evt_1"):
    return {
        "header": {"tenant_key": tenant_key, "event_id": event_id},
        "event": {"message": {"message_id": message_id}},
    }


def provider(on_message, *, tenant_key=""):
    return FeishuProvider(
        ChannelCredential(
            channel_id="ch",
            app_id="cli",
            app_secret="secret",
            tenant_key=tenant_key,
        ),
        on_message=on_message,
    )


def test_normalize_private_text():
    result = normalize_message(msg(), channel_id="ch", app_id="cli", tenant_key="t")
    assert result is not None
    assert result.text == "hello"
    assert result.chat_type == "p2p"


def test_group_requires_bot_mention():
    assert normalize_message(
        msg(chat_type="group"), channel_id="ch", app_id="cli", tenant_key="t"
    ) is None
    result = normalize_message(
        msg(chat_type="group", mentioned_bot=True),
        channel_id="ch",
        app_id="cli",
        tenant_key="t",
    )
    assert result is not None


def test_non_text_and_topic_are_rejected():
    assert normalize_message(
        msg(raw_content_type="image"),
        channel_id="ch",
        app_id="cli",
        tenant_key="t",
    ) is None
    assert normalize_message(
        msg(chat_type="topic"), channel_id="ch", app_id="cli", tenant_key="t"
    ) is None


def test_provider_derives_external_tenant_from_raw_event():
    async def scenario():
        received = []

        async def on_message(message):
            received.append(message)

        instance = provider(on_message)
        instance._loop = asyncio.get_running_loop()
        instance._capture_raw_event(raw_event())
        instance._receive(msg())
        await asyncio.sleep(0)
        return received

    received = asyncio.run(scenario())
    assert len(received) == 1
    assert received[0].tenant_key == "tenant_from_feishu"
    assert received[0].event_id == "evt_1"


def test_provider_keeps_configured_tenant_as_compatibility_fallback():
    async def scenario():
        received = []

        async def on_message(message):
            received.append(message)

        instance = provider(on_message, tenant_key="configured_tenant")
        instance._loop = asyncio.get_running_loop()
        instance._receive(msg())
        await asyncio.sleep(0)
        return received

    received = asyncio.run(scenario())
    assert received[0].tenant_key == "configured_tenant"


def test_provider_drops_message_without_external_tenant(caplog):
    async def scenario():
        received = []

        async def on_message(message):
            received.append(message)

        instance = provider(on_message)
        instance._loop = asyncio.get_running_loop()
        instance._receive(msg())
        await asyncio.sleep(0)
        return received

    received = asyncio.run(scenario())
    assert received == []
    assert "provider tenant unavailable" in caplog.text


def test_raw_event_metadata_is_consumed_once():
    async def on_message(message):
        return None

    instance = provider(on_message)
    instance._capture_raw_event(raw_event())

    assert instance._take_event_metadata("om_1") == (
        "tenant_from_feishu",
        "evt_1",
    )
    assert instance._take_event_metadata("om_1") is None


def test_provider_sends_agent_reply_as_markdown_post():
    async def scenario():
        calls = []

        class FakeChannel:
            async def send(self, receive_id, payload, options):
                calls.append((receive_id, payload, options))
                return SimpleNamespace(message_id="om_reply")

        async def on_message(message):
            return None

        instance = provider(on_message)
        instance.channel = FakeChannel()
        result = await instance.send(OutboundMessage(
            channel_id="ch",
            receive_id="oc_1",
            receive_id_type="chat_id",
            reply_to_message_id="om_1",
            text="## 处理结果\n\n- 已完成\n- 无异常",
        ))
        return calls, result

    calls, result = asyncio.run(scenario())
    assert result.message_id == "om_reply"
    assert calls == [(
        "oc_1",
        {"markdown": "## 处理结果\n\n- 已完成\n- 无异常"},
        {"receive_id_type": "chat_id", "reply_to": "om_1"},
    )]
