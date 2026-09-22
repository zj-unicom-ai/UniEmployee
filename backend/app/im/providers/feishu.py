"""飞书 Channel SDK Provider（WebSocket 长连接）。"""

from __future__ import annotations

import asyncio
import logging
import time
from collections import OrderedDict
from collections.abc import Awaitable, Callable, Mapping
from typing import Any

from app.im.contracts import NormalizedInbound, OutboundMessage
from app.im.credentials import ChannelCredential

logger = logging.getLogger("app.im.feishu")
InboundHandler = Callable[[NormalizedInbound], Awaitable[None]]
StatusHandler = Callable[[str, str | None], None]

_EVENT_METADATA_TTL_SECONDS = 300.0
_EVENT_METADATA_MAX_ITEMS = 2048

# ---------------------------------------------------------------- SDK 缺陷绕行

_SDK_LOOP_PATCHED = False


def _pin_sdk_event_loop() -> None:
    """让 lark-channel-sdk 的 WebSocket 用一张连接自己的事件循环。

    背景（2026-09-22 真机对照实验确认，见 ``docs/飞书流式与等待回复调研.md``）：

    ``lark_channel/ws/client.py`` 在**模块级**把事件循环存进了全局变量::

        try:
            loop = asyncio.get_event_loop()
        except RuntimeError:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)

    而 ``Client.start()`` 直接对这个全局 ``loop`` 调 ``run_until_complete``，
    并且它是被 ``start_background()`` 丢进**线程池**里执行的
    （``loop.run_in_executor(None, self.start)``）。这就要求那个全局循环必须是
    「归该线程所用、且未在运行」的循环。

    问题出在全局变量是**首次导入时**求值的：

    - 我们的 Provider 在协程里才 ``from lark_channel import ...``，此刻 uvicorn
      的主循环正在运行，``get_event_loop()`` 返回的正是它 → ``start()`` 抛
      ``RuntimeError: This event loop is already running``，长连接永远连不上。
    - 这个全局又是**进程级**的，所以先跑起来的那个频道会把循环一直占住
      （``_select()`` 永不返回），同一进程里的其他飞书频道也全部连不上。

    对照实验（同一份凭据、同一个进程）：

    ``在事件循环内导入`` → ``This event loop is already running``
    ``在事件循环启动前导入`` → 该错误消失

    所以这里给每个 ``Client`` 实例绑一张自己的循环，并在每次 ``start()`` 前
    把它指给全局。属于对第三方缺陷的**定点绕行**：SDK 一旦改成 ``self.loop``
    或把全局去掉，这段就该删。整个过程对失败免疫 —— 补丁没打上只是回到原状。
    """
    global _SDK_LOOP_PATCHED
    if _SDK_LOOP_PATCHED:
        return
    try:
        from lark_channel.ws import client as lark_ws_client
    except Exception:  # pragma: no cover - SDK 缺失时由 _build_channel 负责报错
        return

    original_start = getattr(lark_ws_client.Client, "start", None)
    if original_start is None:  # pragma: no cover - SDK 内部结构变化
        logger.warning("飞书 SDK 事件循环绕行未生效：Client.start 不存在")
        return

    def start_with_own_loop(self: Any) -> None:
        loop = getattr(self, "_uniemployee_loop", None)
        if loop is None or loop.is_closed():
            loop = asyncio.new_event_loop()
            self._uniemployee_loop = loop
        # original_start 里引用的是模块全局名字，所以赋值必须发生在调用之前。
        lark_ws_client.loop = loop
        return original_start(self)

    lark_ws_client.Client.start = start_with_own_loop
    _SDK_LOOP_PATCHED = True
    logger.info("飞书 SDK 事件循环已改为按连接独立绑定（绕行 lark-channel-sdk 的模块级 loop）")


def normalize_message(
    message: Any,
    *,
    channel_id: str,
    app_id: str,
    tenant_key: str,
    event_id: str | None = None,
) -> NormalizedInbound | None:
    """仅接收文本单聊和群聊 @ 消息，其余类型由 Provider 丢弃。"""
    content_type = getattr(message, "raw_content_type", None)
    chat_type = getattr(message, "chat_type", None)
    message_id = getattr(message, "message_id", None) or getattr(message, "id", None)

    if content_type != "text" or chat_type not in {"p2p", "group"}:
        logger.debug(
            "Feishu message ignored: unsupported type message=%s content_type=%s chat_type=%s",
            message_id,
            content_type,
            chat_type,
        )
        return None
    if chat_type == "group" and not bool(getattr(message, "mentioned_bot", False)):
        logger.debug(
            "Feishu group message ignored: bot not mentioned message=%s",
            message_id,
        )
        return None

    chat_id = getattr(message, "chat_id", None)
    sender_id = getattr(message, "sender_id", None)
    if not all((message_id, chat_id, sender_id)):
        logger.warning(
            "Feishu message dropped: missing identifiers message=%s chat=%s sender=%s",
            message_id,
            chat_id,
            sender_id,
        )
        return None

    # tenant_key 是飞书侧的外部租户标识，不是 UniEmployee 内部租户。
    provider_tenant_key = tenant_key or getattr(message, "tenant_key", None)
    if not provider_tenant_key:
        logger.warning(
            "Feishu message dropped: provider tenant unavailable message=%s channel=%s",
            message_id,
            channel_id,
        )
        return None

    return NormalizedInbound(
        provider="feishu",
        channel_id=channel_id,
        app_id=app_id,
        tenant_key=provider_tenant_key,
        event_id=event_id or getattr(message, "event_id", None) or message_id,
        message_id=message_id,
        chat_id=chat_id,
        chat_type=chat_type,
        sender_open_id=sender_id,
        text=str(getattr(message, "content_text", "") or ""),
        root_id=getattr(message, "root_id", None),
        parent_id=(
            getattr(message, "parent_id", None)
            or getattr(message, "reply_to_message_id", None)
        ),
    )


class FeishuProvider:
    """一个频道一个实例，由 Supervisor 管理连接和收发生命周期。"""

    def __init__(
        self,
        credential: ChannelCredential,
        *,
        on_message: InboundHandler,
        on_status: StatusHandler | None = None,
    ):
        self.credential = credential
        self.on_message = on_message
        self.on_status = on_status
        self.channel: Any | None = None
        self._loop: asyncio.AbstractEventLoop | None = None
        self._event_metadata: OrderedDict[str, tuple[str, str, float]] = OrderedDict()

    def _notify_status(self, status: str, error: str | None = None) -> None:
        if self.on_status is not None:
            self.on_status(status, error)

    def _build_channel(self) -> Any:
        try:
            from lark_channel import (
                FeishuChannel,
                InboundConfig,
                LogLevel,
                PolicyConfig,
                TransportConfig,
            )
        except ImportError as exc:  # pragma: no cover - 部署依赖检查
            raise RuntimeError("未安装 lark-channel-sdk") from exc

        # 必须在建连之前：SDK 的 WS 客户端把事件循环存成了模块级全局。
        _pin_sdk_event_loop()

        return FeishuChannel(
            app_id=self.credential.app_id,
            app_secret=self.credential.app_secret,
            log_level=LogLevel.WARNING,
            transport=TransportConfig(kind="ws", trust_env_proxy=False),
            # raw 镜像先于正规化消息触发，只用于保存已验签的事件头元数据。
            inbound=InboundConfig(emit_raw_events=True),
            policy=PolicyConfig(
                dm_policy="open",
                group_policy="open",
                require_mention=True,
                respond_to_mention_all=False,
            ),
        )

    def _prune_event_metadata(self, now: float) -> None:
        expires_before = now - _EVENT_METADATA_TTL_SECONDS
        while self._event_metadata:
            _, (_, _, captured_at) = next(iter(self._event_metadata.items()))
            if captured_at >= expires_before:
                break
            self._event_metadata.popitem(last=False)
        while len(self._event_metadata) > _EVENT_METADATA_MAX_ITEMS:
            self._event_metadata.popitem(last=False)

    def _capture_raw_event(self, payload: Any) -> None:
        """缓存飞书原始事件头，供随后到达的正规化消息关联。"""
        if not isinstance(payload, Mapping):
            return
        header = payload.get("header")
        event = payload.get("event")
        if not isinstance(header, Mapping) or not isinstance(event, Mapping):
            return
        message = event.get("message")
        if not isinstance(message, Mapping):
            return

        message_id = str(message.get("message_id") or "").strip()
        provider_tenant_key = str(header.get("tenant_key") or "").strip()
        event_id = str(header.get("event_id") or message_id).strip()
        if not message_id or not provider_tenant_key:
            logger.warning(
                "Feishu raw event missing provider metadata message=%s event=%s",
                message_id or None,
                event_id or None,
            )
            return

        now = time.monotonic()
        self._event_metadata[message_id] = (provider_tenant_key, event_id, now)
        self._event_metadata.move_to_end(message_id)
        self._prune_event_metadata(now)

    def _take_event_metadata(self, message_id: str | None) -> tuple[str, str] | None:
        now = time.monotonic()
        self._prune_event_metadata(now)
        if not message_id:
            return None
        metadata = self._event_metadata.pop(message_id, None)
        if metadata is None:
            return None
        provider_tenant_key, event_id, captured_at = metadata
        if captured_at < now - _EVENT_METADATA_TTL_SECONDS:
            return None
        return provider_tenant_key, event_id

    def _receive(self, message: Any) -> None:
        message_id = getattr(message, "message_id", None) or getattr(message, "id", None)
        metadata = self._take_event_metadata(message_id)
        provider_tenant_key = self.credential.tenant_key
        event_id = None
        if metadata is not None:
            provider_tenant_key, event_id = metadata

        normalized = normalize_message(
            message,
            channel_id=self.credential.channel_id,
            app_id=self.credential.app_id,
            tenant_key=provider_tenant_key,
            event_id=event_id,
        )
        if normalized is None:
            return
        loop = self._loop
        if loop and not loop.is_closed():
            loop.call_soon_threadsafe(
                asyncio.create_task,
                self.on_message(normalized),
            )

    async def connect(self, timeout: float = 30) -> None:
        self._loop = asyncio.get_running_loop()
        self._notify_status("connecting")
        self.channel = self._build_channel()
        # SDK 负责验签、ACK、去重和重连；raw 回调只提取事件头元数据。
        self.channel.on("raw", self._capture_raw_event)
        self.channel.on("message", self._receive)
        self.channel.on(
            "reconnecting",
            lambda *args: self._notify_status("reconnecting"),
        )
        self.channel.on(
            "reconnected",
            lambda *args: self._notify_status("connected"),
        )
        self.channel.on(
            "error",
            lambda error: self._notify_status(
                "reconnecting", f"{type(error).__name__}: {error}"
            ),
        )
        await self.channel.connect_until_ready(timeout=timeout)
        self._notify_status("connected")

    async def disconnect(self) -> None:
        if self.channel is not None:
            await self.channel.disconnect()
            self.channel = None
        self._event_metadata.clear()

    async def send(self, message: OutboundMessage) -> Any:
        if self.channel is None:
            raise RuntimeError("飞书频道尚未连接")
        options = {"receive_id_type": message.receive_id_type}
        if message.reply_to_message_id:
            options["reply_to"] = message.reply_to_message_id
        return await self.channel.send(
            message.receive_id,
            # 智能体输出天然包含标题、列表和代码块；交给 Channel SDK
            # 转换为飞书 post 富文本。SDK 在格式被拒绝时会降级为纯文本。
            {"markdown": message.text},
            options,
        )
