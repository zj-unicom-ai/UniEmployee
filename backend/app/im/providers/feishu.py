"""飞书 Channel SDK Provider（WebSocket 长连接）。"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from typing import Any

from app.im.contracts import NormalizedInbound, OutboundMessage
from app.im.credentials import ChannelCredential

logger = logging.getLogger("app.im.feishu")
InboundHandler = Callable[[NormalizedInbound], Awaitable[None]]


def normalize_message(message: Any, *, channel_id: str, app_id: str,
                      tenant_key: str) -> NormalizedInbound | None:
    """仅接收文本单聊和群聊 @ 消息，其他类型由 Provider 丢弃。"""
    content_type = getattr(message, "raw_content_type", None)
    chat_type = getattr(message, "chat_type", None)
    if content_type != "text" or chat_type not in {"p2p", "group"}:
        return None
    if chat_type == "group" and not bool(getattr(message, "mentioned_bot", False)):
        return None
    message_id = getattr(message, "message_id", None) or getattr(message, "id", None)
    chat_id = getattr(message, "chat_id", None)
    sender_id = getattr(message, "sender_id", None)
    if not all((message_id, chat_id, sender_id)):
        return None
    resolved_tenant = getattr(message, "tenant_key", None) or tenant_key
    if not resolved_tenant:
        return None
    return NormalizedInbound(
        provider="feishu", channel_id=channel_id, app_id=app_id,
        tenant_key=resolved_tenant, event_id=getattr(message, "event_id", None) or message_id,
        message_id=message_id, chat_id=chat_id, chat_type=chat_type,
        sender_open_id=sender_id, text=str(getattr(message, "content_text", "") or ""),
        root_id=getattr(message, "root_id", None),
        parent_id=getattr(message, "parent_id", None) or getattr(message, "reply_to_message_id", None),
    )


class FeishuProvider:
    """一个频道一个实例；由 Supervisor 管理 connect/disconnect。"""

    def __init__(self, credential: ChannelCredential, *, on_message: InboundHandler):
        self.credential = credential
        self.on_message = on_message
        self.channel: Any | None = None
        self._loop: asyncio.AbstractEventLoop | None = None

    def _build_channel(self) -> Any:
        try:
            from lark_channel import FeishuChannel, PolicyConfig, TransportConfig
        except ImportError as exc:  # pragma: no cover - 部署依赖检查
            raise RuntimeError("未安装 lark-channel-sdk") from exc
        return FeishuChannel(
            app_id=self.credential.app_id,
            app_secret=self.credential.app_secret,
            transport=TransportConfig(kind="ws", trust_env_proxy=False),
            policy=PolicyConfig(
                dm_policy="open", group_policy="open", require_mention=True,
                respond_to_mention_all=False,
            ),
        )

    def _receive(self, message: Any) -> None:
        normalized = normalize_message(
            message, channel_id=self.credential.channel_id,
            app_id=self.credential.app_id, tenant_key=self.credential.tenant_key,
        )
        if normalized is None:
            return
        loop = self._loop
        if loop and not loop.is_closed():
            loop.call_soon_threadsafe(asyncio.create_task, self.on_message(normalized))

    async def connect(self, timeout: float = 30) -> None:
        self._loop = asyncio.get_running_loop()
        self.channel = self._build_channel()
        # SDK 自己负责 ACK 和重连；业务回调仅入队，不在此处等待模型。
        self.channel.on("message", self._receive)
        await self.channel.connect_until_ready(timeout=timeout)

    async def disconnect(self) -> None:
        if self.channel is not None:
            await self.channel.disconnect()
            self.channel = None

    async def send(self, message: OutboundMessage) -> Any:
        if self.channel is None:
            raise RuntimeError("飞书频道尚未连接")
        options = {"receive_id_type": message.receive_id_type}
        if message.reply_to_message_id:
            options["reply_to"] = message.reply_to_message_id
        return await self.channel.send(
            message.receive_id, {"text": message.text}, options,
        )
