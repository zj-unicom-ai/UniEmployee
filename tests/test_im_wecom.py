"""企业微信 Provider 的协议层单元测试。

覆盖不依赖网络的纯逻辑：入站标准化（单聊没有 chatid、群聊取 chatid）、
缺回复凭据时丢弃、协议去重、**5 秒占位流的时序**、订阅与心跳帧形状、
被顶替不重连、出站降级（respond → send_msg）、注册表分派。

真实长连接与企微服务端行为留在现场验证（见 docs/wecom-integration-plan.md §7
的待验证清单：req_id 有效期、企微 Markdown 差异等）。
"""

import asyncio
import json

import pytest

from app.im import providers as providers_module
from app.im.cards import policy_for
from app.im.cards import WORKING_TEXT
from app.im.contracts import OutboundMessage
from app.im.credentials import ChannelCredential
from app.im.providers import wecom as wecom_module
from app.im.providers.wecom import (
    CMD_HEARTBEAT,
    CMD_RESPONSE,
    CMD_SEND_MSG,
    CMD_SUBSCRIBE,
    EVENT_DISCONNECTED,
    REPLY_TARGET_TYPE,
    WecomDeliveryError,
    WecomError,
    WecomProvider,
    normalize_message,
)


def _credential() -> ChannelCredential:
    return ChannelCredential("chan_wc", "bot_id_1", "corp_wc", "bot_secret_1")


def _body(**overrides):
    """企微消息回调的 body（字段名照官方文档《长连接》的推送示例）。"""
    body = {
        "msgid": "msg_1",
        "aibotid": "bot_id_1",
        "chattype": "single",
        "from": {"userid": "user_1"},
        "msgtype": "text",
        "text": {"content": "你好"},
    }
    body.update(overrides)
    return body


def _callback_payload(**overrides):
    return {"cmd": "aibot_msg_callback", "headers": {"req_id": "req_1"}, "body": _body(**overrides)}


def _provider(**kwargs) -> WecomProvider:
    async def noop(message):
        return None

    return WecomProvider(_credential(), on_message=noop, **kwargs)


class _FakeWebSocket:
    """只记录发出去的帧；``close`` 只置位（订阅/心跳测试不需要真网络）。"""

    def __init__(self):
        self.sent: list[str] = []
        self.closed = False

    async def send(self, payload: str) -> None:
        self.sent.append(payload)

    async def close(self) -> None:
        self.closed = True


class _AckingWebSocket(_FakeWebSocket):
    """发帧后立即按服务端语义回执（``{headers: {req_id}, errcode}``）。

    用它替代真实长连接：企微对订阅、心跳、回复**都**回执，测试里把这层回执补上，
    就能覆盖「等回执 → 判 errcode」的完整路径。
    """

    def __init__(self, provider=None, *, errcode=0, errmsg="ok"):
        super().__init__()
        self.provider = provider
        self.errcode = errcode
        self.errmsg = errmsg

    async def send(self, payload: str) -> None:
        await super().send(payload)
        if self.provider is None:
            return
        frame = json.loads(payload)
        req_id = frame["headers"]["req_id"]
        await self.provider._dispatch(
            {"headers": {"req_id": req_id}, "errcode": self.errcode, "errmsg": self.errmsg}
        )


def _wire(provider: WecomProvider, socket=None) -> _AckingWebSocket:
    socket = socket or _AckingWebSocket()
    socket.provider = provider
    provider.channel = socket
    return socket


# --------------------------------------------------------------- 入站标准化


def test_single_chat_has_no_chatid_and_uses_sender_as_conversation():
    message = normalize_message(
        _body(),
        req_id="req_1",
        channel_id="chan_wc",
        app_id="bot_id_1",
        tenant_key="corp_stored",
    )

    assert message is not None
    assert message.provider == "wecom"
    assert message.chat_type == "p2p"
    assert message.sender_open_id == "user_1"
    # 官方字段说明：chatid「仅群聊类型时返回」，单聊必须自己折一个会话标识。
    # 取发送者 userid 还让主动推送能直接复用（该接口单聊场景本就填 userid）。
    assert message.chat_id == "user_1"
    assert message.text == "你好"
    # 回调里带的机器人 ID 比手工填的凭证更权威，用作租户边界。
    assert message.tenant_key == "bot_id_1"


def test_group_chat_uses_returned_chatid():
    message = normalize_message(
        _body(chattype="group", chatid="chat_group_1"),
        req_id="req_1",
        channel_id="chan_wc",
        app_id="bot_id_1",
        tenant_key="",
    )

    assert message is not None
    assert message.chat_type == "group"
    assert message.chat_id == "chat_group_1"


def test_reply_target_is_the_callback_req_id():
    message = normalize_message(
        _body(),
        req_id="req_abc",
        channel_id="chan_wc",
        app_id="bot_id_1",
        tenant_key="",
    )

    assert message is not None
    # 出站目标由 Provider 决定：企微是本次回调的 req_id（用完即废），
    # 不是飞书那样的持久 chat_id，也不是钉钉那样的临时 webhook URL。
    assert message.reply_target == "req_abc"
    assert message.reply_target_type == REPLY_TARGET_TYPE


def test_non_text_messages_are_dropped():
    for msgtype in ("image", "voice", "file", "video", "mixed", "event"):
        assert normalize_message(
            _body(msgtype=msgtype),
            req_id="req_1",
            channel_id="chan_wc",
            app_id="bot_id_1",
            tenant_key="",
        ) is None


def test_messages_without_reply_credential_are_dropped():
    # 没有 req_id 就永远回不了这条消息，收进 Inbox 只会得到一条必然失败的死信。
    assert normalize_message(
        _body(),
        req_id="",
        channel_id="chan_wc",
        app_id="bot_id_1",
        tenant_key="",
    ) is None


def test_messages_without_msgid_or_chattype_are_dropped():
    common = dict(req_id="req_1", channel_id="chan_wc", app_id="bot_id_1", tenant_key="")
    assert normalize_message(_body(msgid=""), **common) is None
    assert normalize_message(_body(chattype=""), **common) is None
    assert normalize_message(_body(chattype="channel"), **common) is None
    # `from` 是 Python 关键字，没法当关键字参数传，单独构造。
    missing_sender = _body()
    missing_sender["from"] = {}
    assert normalize_message(missing_sender, **common) is None


def test_tenant_key_falls_back_to_app_scope():
    message = normalize_message(
        _body(aibotid=""),
        req_id="req_1",
        channel_id="chan_wc",
        app_id="bot_id_1",
        tenant_key="",
    )

    assert message is not None
    assert message.tenant_key == "app:bot_id_1"


# ------------------------------------------------------------ 回调与帧处理


def test_callback_is_deduplicated_by_msgid():
    received: list[str] = []

    async def on_message(message):
        received.append(message.message_id)

    async def scenario():
        provider = WecomProvider(_credential(), on_message=on_message)
        _wire(provider)
        payload = _callback_payload()
        await provider._handle_callback(payload, req_id="req_1")
        await provider._handle_callback(payload, req_id="req_1")
        await asyncio.sleep(0)
        return received

    assert asyncio.run(scenario()) == ["msg_1"]


def test_placeholder_stream_is_sent_before_the_message_is_queued():
    """企微 5 秒首回复硬窗口：占位流必须在入队之前就发出去。

    这是与飞书/钉钉最本质的时序差异 —— 那条链路是「入队 → 轮询 claim → 开卡片」，
    inbox 积压时会排队越过 5 秒，而企微错过窗口就**永远回不了**这条消息。
    """

    async def scenario():
        socket = _AckingWebSocket()
        frames_seen_at_queue_time: list[int] = []

        async def on_message(message):
            # 入队回调看到的已发帧数：应当已经包含占位流那一帧。
            frames_seen_at_queue_time.append(len(socket.sent))

        provider = WecomProvider(_credential(), on_message=on_message)
        socket.provider = provider
        provider.channel = socket

        await provider._handle_callback(_callback_payload(), req_id="req_1")
        await asyncio.sleep(0)
        return socket.sent, frames_seen_at_queue_time

    frames, seen = asyncio.run(scenario())
    assert len(frames) == 1
    frame = json.loads(frames[0])
    assert frame["cmd"] == CMD_RESPONSE
    assert frame["headers"]["req_id"] == "req_1"
    assert frame["body"]["msgtype"] == "stream"
    assert frame["body"]["stream"]["finish"] is False
    assert frame["body"]["stream"]["content"] == WORKING_TEXT
    # 入队时占位流已经在路上（>=1 而不是 ==0）。
    assert seen == [1]


def test_placeholder_stream_is_skipped_when_cards_are_disabled(monkeypatch):
    async def scenario():
        provider = _provider()
        socket = _wire(provider)
        monkeypatch.setattr(wecom_module, "card_enabled", lambda: False)
        await provider._handle_callback(_callback_payload(), req_id="req_1")
        await asyncio.sleep(0)
        return socket.sent

    # 卡片总开关关掉时不预热，否则用户会看到一个永远停在「正在处理」的气泡。
    assert asyncio.run(scenario()) == []


def test_disconnected_event_stops_reconnecting():
    async def scenario():
        provider = _provider()
        socket = _wire(provider)
        payload = {
            "cmd": "aibot_event_callback",
            "headers": {"req_id": "req_ev"},
            "body": {"event": {"eventtype": EVENT_DISCONNECTED}},
        }
        await provider._handle_event(payload)
        return provider, socket

    provider, socket = asyncio.run(scenario())
    # 单机器人单连接：被新连接顶替后重连只会被再次踢掉，所以明确不重连。
    assert provider._taken_over is True
    assert socket.closed is True


def test_invalid_json_frame_is_ignored():
    async def scenario():
        provider = _provider()
        _wire(provider)
        # 不应抛异常，也不应产生任何副作用。
        await provider._dispatch_text("not-json")

    asyncio.run(scenario())


# ---------------------------------------------------------------- 握手


def test_subscribe_frame_carries_credentials_and_prefixed_req_id():
    async def scenario():
        provider = _provider()
        socket = _FakeWebSocket()
        provider.channel = socket

        async def fake_recv():
            frame = json.loads(socket.sent[-1])
            return json.dumps(
                {"headers": {"req_id": frame["headers"]["req_id"]}, "errcode": 0, "errmsg": "ok"}
            )

        socket.recv = fake_recv
        await provider._subscribe(timeout=1)
        return socket.sent

    frames = asyncio.run(scenario())
    frame = json.loads(frames[0])
    assert frame["cmd"] == CMD_SUBSCRIBE
    assert frame["body"] == {"bot_id": "bot_id_1", "secret": "bot_secret_1"}
    # req_id 前缀不是装饰：响应帧可能不带 cmd，官方 SDK 正是靠前缀归类的。
    assert frame["headers"]["req_id"].startswith(CMD_SUBSCRIBE)


def test_subscribe_rejection_raises():
    async def scenario():
        provider = _provider()
        socket = _FakeWebSocket()
        provider.channel = socket

        async def fake_recv():
            frame = json.loads(socket.sent[-1])
            return json.dumps(
                {
                    "headers": {"req_id": frame["headers"]["req_id"]},
                    "errcode": 40001,
                    "errmsg": "invalid secret",
                }
            )

        socket.recv = fake_recv
        await provider._subscribe(timeout=1)

    with pytest.raises(WecomError) as excinfo:
        asyncio.run(scenario())
    assert excinfo.value.error_code == "40001"


def test_heartbeat_frame_uses_ping_command():
    async def scenario():
        provider = _provider()
        socket = _wire(provider)
        await provider._send_heartbeat()
        return socket.sent

    frames = asyncio.run(scenario())
    frame = json.loads(frames[0])
    assert frame["cmd"] == CMD_HEARTBEAT == "ping"
    assert frame["headers"]["req_id"].startswith(CMD_HEARTBEAT)


def test_heartbeat_ack_clears_the_missed_counter():
    async def scenario():
        provider = _provider()
        _wire(provider)
        provider._last_heartbeat_req_id = "ping_1_abcd"
        provider._missed_heartbeat_acks = 2
        await provider._dispatch(
            {"headers": {"req_id": "ping_1_abcd"}, "errcode": 0, "errmsg": "ok"}
        )
        return provider._missed_heartbeat_acks

    assert asyncio.run(scenario()) == 0


def test_heartbeat_loop_closes_socket_after_missed_acks(monkeypatch):
    async def scenario():
        provider = _provider()
        socket = _wire(provider)
        monkeypatch.setattr(wecom_module, "HEARTBEAT_SECONDS", 0.01)
        provider._missed_heartbeat_acks = wecom_module.HEARTBEAT_MAX_MISSED
        await asyncio.wait_for(provider._heartbeat_loop(), timeout=1)
        return provider, socket

    provider, socket = asyncio.run(scenario())
    # 关掉 socket 让读循环退出，重连交给 _supervise 统一处理（与钉钉同构）。
    assert socket.closed is True
    assert provider.channel is None


# ---------------------------------------------------------------- 出站


def _send(provider, *, receive_id="req_1", receive_id_type=REPLY_TARGET_TYPE, text="结果"):
    return provider.send(
        OutboundMessage(
            channel_id="chan_wc",
            receive_id=receive_id,
            receive_id_type=receive_id_type,
            text=text,
            reply_to_message_id="msg_1",
        )
    )


def test_send_replies_on_the_fresh_req_id():
    async def scenario():
        provider = _provider()
        socket = _wire(provider)
        await provider._handle_callback(_callback_payload(), req_id="req_1")
        receipt = await _send(provider, text="这是结果")
        return socket.sent, receipt

    frames, receipt = asyncio.run(scenario())
    reply = json.loads(frames[-1])
    assert reply["cmd"] == CMD_RESPONSE
    assert reply["headers"]["req_id"] == "req_1"
    assert reply["body"]["msgtype"] == "markdown"
    assert reply["body"]["markdown"]["content"] == "这是结果"
    # 回执帧里没有消息 ID，用入站 msgid 保可追溯性。
    assert receipt.message_id == "msg_1"


def test_second_send_on_a_used_req_id_falls_back_to_active_push():
    """同一个 req_id 只允许 respond 一次（气泡 finish 后锁定）。

    Worker 的「卡片被截断后补发文本」正好走这条路径 —— 所以它不需要为企微改代码。
    """

    async def scenario():
        provider = _provider()
        socket = _wire(provider)
        await provider._handle_callback(_callback_payload(), req_id="req_1")
        await _send(provider, text="第一段")
        await _send(provider, text="补发的完整内容")
        return socket.sent

    frames = asyncio.run(scenario())
    first, second = json.loads(frames[-2]), json.loads(frames[-1])
    assert first["cmd"] == CMD_RESPONSE
    assert second["cmd"] == CMD_SEND_MSG
    # 主动推送的收件人字段就叫 chatid：群聊填 chatid，单聊填 userid。
    assert second["body"]["chatid"] == "user_1"
    assert second["body"]["markdown"]["content"] == "补发的完整内容"


def test_active_push_without_callback_context_uses_the_receive_id():
    async def scenario():
        provider = _provider()
        socket = _wire(provider)
        await _send(provider, receive_id="chat_group_9", receive_id_type="chat_id", text="告警")
        return socket.sent

    frames = asyncio.run(scenario())
    frame = json.loads(frames[0])
    assert frame["cmd"] == CMD_SEND_MSG
    assert frame["body"]["chatid"] == "chat_group_9"
    assert frame["headers"]["req_id"].startswith(CMD_SEND_MSG)


def test_business_error_is_mapped_to_non_retryable():
    async def scenario():
        provider = _provider()
        socket = _AckingWebSocket(errcode=40001, errmsg="invalid credential")
        provider.channel = socket
        socket.provider = provider
        await _send(provider)

    with pytest.raises(WecomDeliveryError) as excinfo:
        asyncio.run(scenario())
    # 400 让 Outbox 直接判死而不是无限重试，等管理员处理。
    assert excinfo.value.status_code == 400
    assert excinfo.value.error_code == "40001"


def test_missing_ack_is_retryable():
    async def scenario():
        provider = _provider()
        # 永不回执的 socket：模拟连接半死。
        provider.channel = _FakeWebSocket()
        await provider._send_reply("req_1", {"msgtype": "markdown"}, timeout=0.05)

    with pytest.raises(WecomDeliveryError) as excinfo:
        asyncio.run(scenario())
    # 504 可重试：网络抖动不该变成用户永久收不到结果（代价是极端情况下可能重复一条）。
    assert excinfo.value.status_code == 504


def test_send_before_connect_fails_fast():
    async def scenario():
        provider = _provider()
        await _send(provider)

    with pytest.raises(WecomDeliveryError) as excinfo:
        asyncio.run(scenario())
    assert excinfo.value.status_code == 503


# ------------------------------------------------------------ 卡片与场域


def test_card_session_hands_over_the_prestarted_stream():
    async def scenario():
        provider = _provider()
        socket = _wire(provider)
        await provider._handle_callback(_callback_payload(), req_id="req_1")
        session = provider.create_card_session(
            payload={"reply_target": "req_1", "chat_id": "user_1", "chat_type": "p2p"},
            # 企微不需要模板；传空串也不该被拒（与钉钉相反）。
            template_id="",
            policy=policy_for("stream"),
            reply_to="msg_1",
        )
        # Worker 拿到会话后一律会调 open(WORKING_TEXT)：必须幂等，不能再开一条流。
        await session.open(WORKING_TEXT)
        return session, socket.sent

    session, frames = asyncio.run(scenario())
    assert session is not None
    assert session.opened is True
    # 预热帧与 Worker 的 open 合成同一条流：id 一致且没有第二帧。
    assert len(frames) == 1
    assert session.out_track_id == json.loads(frames[0])["body"]["stream"]["id"]


def test_card_session_can_be_created_without_prestart():
    async def scenario():
        provider = _provider()
        _wire(provider)
        return provider.create_card_session(
            payload={"reply_target": "req_1", "chat_id": "user_1", "chat_type": "p2p"},
            template_id="",
            policy=policy_for("stream"),
        )

    session = asyncio.run(scenario())
    # 预热没成功时仍要能走卡片路径，只是失去了 5 秒窗口的确定性。
    assert session is not None
    assert session.opened is False


def test_finalized_session_is_not_handed_over_again():
    async def scenario():
        provider = _provider()
        _wire(provider)
        await provider._handle_callback(_callback_payload(), req_id="req_1")
        first = provider.create_card_session(
            payload={"reply_target": "req_1", "chat_id": "user_1", "chat_type": "p2p"},
            template_id="",
            policy=policy_for("stream"),
        )
        await first.finalize("done")
        second = provider.create_card_session(
            payload={"reply_target": "req_1", "chat_id": "user_1", "chat_type": "p2p"},
            template_id="",
            policy=policy_for("stream"),
        )
        return first, second

    first, second = asyncio.run(scenario())
    # 已锁定的流不能复用，否则后续帧会被服务端丢弃且无人察觉。
    assert first.finalized is True
    assert second is not None and second is not first


def test_card_space_is_not_required():
    provider = _provider()
    assert provider.card_space({"chat_type": "p2p"}) is None


# --------------------------------------------------------- 注册表与窗口


def test_registry_dispatches_wecom():
    async def noop(message):
        return None

    provider = providers_module.create_provider("wecom", _credential(), on_message=noop)
    assert isinstance(provider, WecomProvider)
    assert providers_module.provider_label("wecom") == "企业微信"
    assert providers_module.credential_label("wecom") == "Bot ID/Secret"
    assert "wecom" in providers_module.supported_providers()


def test_provider_id_matches_registry_key():
    assert WecomProvider.PROVIDER_ID == "wecom"


def test_protocol_dedup_window_is_bounded():
    provider = _provider()
    for index in range(3000):
        provider._seen_recently(f"key-{index}")
    # 先裁剪后插入，因此窗口上界是常量 + 1；关键是不随消息量无界增长。
    assert len(provider._recent) <= 2049
    assert provider._seen_recently("key-2999") is True


def test_reply_contexts_and_sessions_are_bounded():
    async def scenario():
        provider = _provider()
        _wire(provider)
        for index in range(600):
            await provider._handle_callback(_callback_payload(msgid=f"msg_{index}"), req_id=f"req_{index}")
        await asyncio.sleep(0)
        return provider

    provider = asyncio.run(scenario())
    # 两者都是"按 req_id 记账"的短命数据，不设上限会在长跑进程里无界增长。
    assert len(provider._reply_contexts) <= wecom_module._REPLY_CONTEXT_MAX_ITEMS
    assert len(provider._pending_sessions) <= wecom_module._PENDING_SESSION_MAX_ITEMS
