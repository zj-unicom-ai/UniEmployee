from types import SimpleNamespace

from app.im.providers.feishu import normalize_message


def msg(**kwargs):
    base = dict(raw_content_type="text", chat_type="p2p", message_id="om_1",
                chat_id="oc_1", sender_id="ou_1", content_text="hello",
                mentioned_bot=False)
    base.update(kwargs)
    return SimpleNamespace(**base)


def test_normalize_private_text():
    result = normalize_message(msg(), channel_id="ch", app_id="cli", tenant_key="t")
    assert result is not None
    assert result.text == "hello"
    assert result.chat_type == "p2p"


def test_group_requires_bot_mention():
    assert normalize_message(msg(chat_type="group"), channel_id="ch", app_id="cli", tenant_key="t") is None
    result = normalize_message(msg(chat_type="group", mentioned_bot=True), channel_id="ch", app_id="cli", tenant_key="t")
    assert result is not None


def test_non_text_and_topic_are_rejected():
    assert normalize_message(msg(raw_content_type="image"), channel_id="ch", app_id="cli", tenant_key="t") is None
    assert normalize_message(msg(chat_type="topic"), channel_id="ch", app_id="cli", tenant_key="t") is None

