"""钉钉 Stream Provider 的协议层单元测试。

只覆盖不依赖网络的纯逻辑：入站标准化、群聊 @ 过滤、协议去重、ack 帧形状、
出站映射与注册表分派。真实长连接与 sessionWebhook 投递留在现场验证。
"""

import asyncio
import json

import pytest

from app.im import providers as providers_module
from app.im.contracts import OutboundMessage
from app.im.credentials import ChannelCredential
from app.im.providers.dingtalk import (
    ACK_STATUS_OK,
    TOPIC_ROBOT,
    DingtalkDeliveryError,
    DingtalkProvider,
    normalize_message,
)


def _credential() -> ChannelCredential:
    return ChannelCredential("chan_dt", "client_id", "corp_a", "client_secret")


def _robot_payload(**overrides):
    data = {
        "msgtype": "text",
        "text": {"content": "你好"},
        "msgId": "msg_1",
        "conversationId": "cid_1",
        "conversationType": "1",
        "senderStaffId": "staff_1",
        "senderId": "sender_1",
        "chatbotUserId": "bot_1",
        "chatbotCorpId": "corp_a",
        "sessionWebhook": "https://oapi.dingtalk.com/robot/sendBySession?session=abc",
        "sessionWebhookExpiredTime": 1_700_000_000_000,
    }
    data.update(overrides)
    return data


# --------------------------------------------------------------- 入站标准化


def test_text_p2p_message_is_normalized_with_session_webhook_target():
    message = normalize_message(
        _robot_payload(),
        channel_id="chan_dt",
        app_id="client_id",
        tenant_key="corp_stored",
    )

    assert message is not None
    assert message.provider == "dingtalk"
    assert message.chat_type == "p2p"
    assert message.sender_open_id == "staff_1"
    assert message.text == "你好"
    # 群聊与单聊都以 conversationId 作为记忆边界。
    assert message.chat_id == "cid_1"
    # 出站目标由入站消息携带，Provider 用 reply_target_type 说明语义。
    assert message.reply_target.endswith("session=abc")
    assert message.reply_target_type == "session_webhook"
    # 入站机器人所属组织优先于已存凭证，避免跨企业记忆串号。
    assert message.tenant_key == "corp_a"


def test_group_message_requires_bot_mention():
    not_mentioned = normalize_message(
        _robot_payload(conversationType="2", isInAtList=False),
        channel_id="chan_dt",
        app_id="client_id",
        tenant_key="corp_a",
    )
    assert not_mentioned is None

    mentioned = normalize_message(
        _robot_payload(conversationType="2", isInAtList=True),
        channel_id="chan_dt",
        app_id="client_id",
        tenant_key="corp_a",
    )
    assert mentioned is not None
    assert mentioned.chat_type == "group"


def test_non_text_and_unknown_conversation_types_are_dropped():
    assert normalize_message(
        _robot_payload(msgtype="picture"),
        channel_id="chan_dt",
        app_id="client_id",
        tenant_key="corp_a",
    ) is None
    assert normalize_message(
        _robot_payload(conversationType="9"),
        channel_id="chan_dt",
        app_id="client_id",
        tenant_key="corp_a",
    ) is None


def test_robot_self_message_is_dropped():
    assert normalize_message(
        _robot_payload(senderStaffId="bot_1", senderId="bot_1"),
        channel_id="chan_dt",
        app_id="client_id",
        tenant_key="corp_a",
    ) is None


def test_missing_identifiers_are_dropped():
    assert normalize_message(
        _robot_payload(msgId=""),
        channel_id="chan_dt",
        app_id="client_id",
        tenant_key="corp_a",
    ) is None


def test_tenant_key_falls_back_to_app_scope_when_absent():
    message = normalize_message(
        _robot_payload(chatbotCorpId=""),
        channel_id="chan_dt",
        app_id="client_id",
        tenant_key="",
    )

    assert message is not None
    assert message.tenant_key == "app:client_id"


# ------------------------------------------------------------ 连接与帧处理


class _FakeWebSocket:
    def __init__(self):
        self.sent: list[str] = []
        self.closed = False

    async def send(self, payload: str) -> None:
        self.sent.append(payload)

    async def close(self) -> None:
        self.closed = True


def _provider(**kwargs) -> DingtalkProvider:
    async def noop(message):
        return None

    return DingtalkProvider(_credential(), on_message=noop, **kwargs)


def test_ack_frame_matches_dingtalk_expectation():
    async def scenario():
        provider = _provider()
        socket = _FakeWebSocket()
        provider.channel = socket
        await provider._send_ack("msg_1")
        return socket.sent

    frames = asyncio.run(scenario())
    assert len(frames) == 1
    frame = json.loads(frames[0])
    assert frame["code"] == ACK_STATUS_OK
    assert frame["headers"]["messageId"] == "msg_1"
    # data 是 JSON 字符串而不是对象，这是钉钉 SDK 的实际形态。
    assert json.loads(frame["data"]) == {"success": True}


def test_callback_is_acked_before_dispatch_and_deduplicated():
    received: list[str] = []

    async def on_message(message):
        received.append(message.message_id)

    async def scenario():
        provider = DingtalkProvider(_credential(), on_message=on_message)
        socket = _FakeWebSocket()
        provider.channel = socket
        frame = json.dumps({
            "type": "CALLBACK",
            "headers": {"messageId": "cb_1", "topic": TOPIC_ROBOT},
            "data": json.dumps(_robot_payload()),
        })
        await provider._handle_frame(frame)
        # 同一次投递的重复回调必须被协议层去重拦下。
        await provider._handle_frame(frame)
        await asyncio.sleep(0)
        return socket.sent

    frames = asyncio.run(scenario())
    assert len(frames) == 2  # 两次回调都 ack，但只派发一次消息
    assert received == ["msg_1"]


def test_system_disconnect_frame_closes_socket():
    async def scenario():
        provider = _provider()
        socket = _FakeWebSocket()
        provider.channel = socket
        frame = json.dumps({
            "type": "SYSTEM",
            "headers": {"topic": "disconnect"},
        })
        await provider._handle_frame(frame)
        return provider.channel

    assert asyncio.run(scenario()) is None


def test_invalid_json_frame_is_ignored():
    async def scenario():
        provider = _provider()
        provider.channel = _FakeWebSocket()
        # 不应抛异常，也不应产生任何 ack。
        await provider._handle_frame("not-json")

    asyncio.run(scenario())


# ------------------------------------------------------------------- 出站


class _FakeResponse:
    def __init__(self, payload):
        self._payload = payload

    def raise_for_status(self) -> None:
        return None

    def json(self):
        return self._payload


class _FakeHttp:
    def __init__(self, payload):
        self.payload = payload
        self.calls: list[tuple[str, dict]] = []

    async def post(self, url, json=None):
        self.calls.append((url, json))
        return _FakeResponse(self.payload)


def test_send_posts_markdown_to_session_webhook():
    async def scenario():
        provider = _provider()
        http = _FakeHttp({"errcode": 0})
        provider._http = http
        receipt = await provider.send(OutboundMessage(
            channel_id="chan_dt",
            receive_id="https://oapi.dingtalk.com/robot/sendBySession?session=abc",
            receive_id_type="session_webhook",
            text="# 标题\n\n正文",
            reply_to_message_id="msg_1",
        ))
        return http.calls, receipt

    calls, receipt = asyncio.run(scenario())
    url, body = calls[0]
    assert url.startswith("https://oapi.dingtalk.com/")
    assert body["msgtype"] == "markdown"
    assert body["markdown"]["text"] == "# 标题\n\n正文"
    # title 是通知栏纯文本，不能带 markdown 记号。
    assert body["markdown"]["title"] == "标题"
    # sessionWebhook 常只回 errcode，回执退化为入站 msgId 保证可追溯。
    assert receipt.message_id == "msg_1"


def test_send_rejects_non_url_target():
    async def scenario():
        provider = _provider()
        provider._http = _FakeHttp({"errcode": 0})
        await provider.send(OutboundMessage(
            channel_id="chan_dt", receive_id="cid_1",
            receive_id_type="chat_id", text="hi",
        ))

    with pytest.raises(DingtalkDeliveryError) as excinfo:
        asyncio.run(scenario())
    assert excinfo.value.status_code == 400


def test_send_maps_business_error_to_non_retryable():
    async def scenario():
        provider = _provider()
        provider._http = _FakeHttp({"errcode": 300001, "errmsg": "webhook expired"})
        await provider.send(OutboundMessage(
            channel_id="chan_dt",
            receive_id="https://oapi.dingtalk.com/robot/sendBySession?session=abc",
            receive_id_type="session_webhook", text="hi",
        ))

    with pytest.raises(DingtalkDeliveryError) as excinfo:
        asyncio.run(scenario())
    # 400 让 Outbox 直接判死而不是无限重试，等管理员手工重放。
    assert excinfo.value.status_code == 400
    assert excinfo.value.error_code == "300001"


# --------------------------------------------------------- 注册表与窗口


def test_registry_dispatches_dingtalk_and_rejects_unknown_provider():
    async def noop(message):
        return None

    provider = providers_module.create_provider(
        "dingtalk", _credential(), on_message=noop
    )
    assert isinstance(provider, DingtalkProvider)

    with pytest.raises(RuntimeError, match="尚未实现"):
        providers_module.create_provider("nope", _credential(), on_message=noop)


def test_provider_labels_and_supported_set_include_dingtalk():
    assert providers_module.provider_label("dingtalk") == "钉钉"
    assert providers_module.credential_label("dingtalk") == "Client ID/Client Secret"
    assert "dingtalk" in providers_module.supported_providers()


def test_protocol_dedup_window_is_bounded():
    provider = _provider()
    for index in range(3000):
        provider._seen_recently(f"key-{index}")
    # 先裁剪后插入，因此窗口上界是常量 + 1；关键是不随消息量无界增长。
    assert len(provider._recent) <= 2049
    assert provider._seen_recently("key-2999") is True
