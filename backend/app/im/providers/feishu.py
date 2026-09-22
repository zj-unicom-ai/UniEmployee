"""飞书 Channel SDK Provider（WebSocket 长连接）。"""

from __future__ import annotations

import asyncio
import logging
import os
import threading
import time
from collections import OrderedDict
from collections.abc import Awaitable, Callable, Mapping
from typing import Any

from app.im.cards import ThrottlePolicy
from app.im.cards.feishu import (
    API_BASE,
    FeishuCardSession,
    tenant_access_token,
)
from app.im.contracts import NormalizedInbound, OutboundMessage
from app.im.credentials import ChannelCredential

logger = logging.getLogger("app.im.feishu")
InboundHandler = Callable[[NormalizedInbound], Awaitable[None]]
StatusHandler = Callable[[str, str | None], None]

_EVENT_METADATA_TTL_SECONDS = 300.0
_EVENT_METADATA_MAX_ITEMS = 2048

_HTTP_TIMEOUT_SECONDS = 20.0

# 等待态用的表情。飞书消息表情列表里的 "Typing"，语义就是"对方正在输入"。
# 它不是一条消息、而是对**用户那条消息**的操作，所以不存在"提示一直挂着"
# 的问题，也不占群里的消息位 —— 这正是它比"发一条已收到"更好的地方。
TYPING_EMOJI = "Typing"

# 等待态开关：默认开启，置 0/false/no/off 可关闭。
ENV_TYPING_REACTION = "IM_TYPING_REACTION"


def _typing_reaction_enabled() -> bool:
    raw = os.environ.get(ENV_TYPING_REACTION, "").strip().lower()
    return raw not in {"0", "false", "no", "off"}


def _clean(value: Any) -> str:
    return str(value).strip() if value is not None else ""


# ---------------------------------------------------------------- SDK 缺陷绕行

_SDK_LOOP_PATCHED = False

# 每个线程在 start() 之前登记的"本连接的循环"。用线程本地而不是共享全局，
# 是因为后者会被并发启动的多个飞书渠道互相覆盖（见 _ContextLoop 的说明）。
_SDK_LOOP_LOCAL = threading.local()

# SDK 导入时自己求值出来的那个模块级循环，作为最终兜底：
# 上下文无法判定时退回补丁前的行为，保证"不更差"。
_SDK_FALLBACK_LOOP: Any = None


def _current_sdk_loop() -> Any:
    """解析"此刻该用哪个循环"，优先级见 :class:`_ContextLoop`。"""
    try:
        return asyncio.get_running_loop()
    except RuntimeError:
        pass
    registered = getattr(_SDK_LOOP_LOCAL, "loop", None)
    if registered is not None and not registered.is_closed():
        return registered
    return _SDK_FALLBACK_LOOP


class _ContextLoop:
    """把 SDK 的模块级 ``loop`` 换成"按调用上下文解析"的代理。

    第一版绕行（只把全局指向"本连接的循环"）漏了一件事：**全局只有一个位置**。
    两个飞书渠道并发启动时后写者覆盖前者，于是 A 连接在 ``_connect()`` 里执行
    ``loop.create_task(self._receive_message_loop(conn))`` 时读到的是 B 的循环
    ⇒ 接收循环被挂到别人的循环上、而 ``conn`` 属于 A 的循环，抛
    ``RuntimeError: got Future ... attached to a different loop``（打在
    ``conn.recv()``），**连接建好即死**。

    更麻烦的是它不抛错给 Registry（``supervisor.start()`` 已正常返回），于是既不
    重试、``status`` 还停在 ``connected`` —— 表现为"渠道是好的、消息就是收不到"。

    解析顺序（三种都指向"该连接自己的循环"）：

    1. **当前正在运行的循环**。SDK 里所有的 ``loop.create_task(...)`` 都发生在协程内
       （``_connect`` / ``_receive_message_loop`` / ``_schedule_handle_message``），
       此刻正在运行的必然就是本连接 ``run_until_complete`` 的那个 ⇒ 精确命中。
    2. **本线程登记的循环**。``start()`` 的入口与收尾
       （``loop.run_until_complete(...)``、``loop.create_task(self._ping_loop())``）
       跑在没有运行循环的线程池线程上，靠 ``start_with_own_loop`` 登记的线程本地值区分。
    3. 兜底用 SDK 导入时那个循环，使上下文无法判定时的行为与补丁前一致。
    """

    __slots__ = ()

    def __getattr__(self, name: str) -> Any:
        return getattr(_current_sdk_loop(), name)


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

    第二层问题（2026-09-22 真机确认）：全局只有**一个位置**，同进程的多个飞书渠道
    并发启动会互相覆盖，先建好的连接其接收循环被挂到别人的循环上 —— 详见
    :class:`_ContextLoop`。所以这里不是"把全局指向本连接"，而是把全局替换成一个
    **按调用上下文解析的代理**，让每个连接各拿自己的循环。

    属于对第三方缺陷的**定点绕行**：SDK 一旦改成 ``self.loop`` 或把全局去掉，
    这段就该删。整个过程对失败免疫 —— 补丁没打上只是回到原状。
    """
    global _SDK_LOOP_PATCHED, _SDK_FALLBACK_LOOP
    if _SDK_LOOP_PATCHED:
        return
    try:
        from lark_channel.ws import client as lark_ws_client
    except Exception:  # pragma: no cover - SDK 缺失时由 _build_channel 负责报错
        return

    _SDK_FALLBACK_LOOP = getattr(lark_ws_client, "loop", None)

    original_start = getattr(lark_ws_client.Client, "start", None)
    if original_start is None:  # pragma: no cover - SDK 内部结构变化
        logger.warning("飞书 SDK 事件循环绕行未生效：Client.start 不存在")
        return

    def start_with_own_loop(self: Any) -> None:
        loop = getattr(self, "_uniemployee_loop", None)
        if loop is None or loop.is_closed():
            loop = asyncio.new_event_loop()
            self._uniemployee_loop = loop
        # 登记到"本线程"，**不要**再写共享全局 —— 那正是并发覆盖的根源。
        _SDK_LOOP_LOCAL.loop = loop
        return original_start(self)

    lark_ws_client.Client.start = start_with_own_loop
    # 全局常驻代理：original_start 内所有对模块全局 loop 的引用都经它解析，
    # 每个连接各拿自己的循环，互不覆盖。
    lark_ws_client.loop = _ContextLoop()
    _SDK_LOOP_PATCHED = True
    logger.info(
        "飞书 SDK 事件循环已改为按连接独立绑定（绕行 lark-channel-sdk 的模块级 loop）"
    )


def _response_json(response: Any) -> Mapping[str, Any]:
    try:
        payload = response.json()
    except Exception:
        return {}
    return payload if isinstance(payload, Mapping) else {}


def _code(response: Any, payload: Mapping[str, Any]) -> int:
    if getattr(response, "status_code", 0) >= 400:
        return int(payload.get("code") or getattr(response, "status_code"))
    return int(payload.get("code") or 0)


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

    # 与 ``providers.PROVIDERS`` 的键一致。卡片档位这类「按渠道取值」的配置靠它
    # 定位，所以改名要同步改那边（有测试守着这条一致性）。
    PROVIDER_ID = "feishu"

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
        # 卡片与表情回应走 OpenAPI，不经 SDK 传输层，所以自备一个客户端。
        self._http: Any | None = None
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
        import httpx

        self._loop = asyncio.get_running_loop()
        self._notify_status("connecting")
        self._http = httpx.AsyncClient(
            timeout=_HTTP_TIMEOUT_SECONDS,
            # 与 SDK 传输层一致：默认直连，代理必须显式配置。
            trust_env=False,
        )
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
        if self._http is not None:
            await self._http.aclose()
            self._http = None
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

    # ------------------------------------------------------------ 卡片能力

    def create_card_session(
        self,
        *,
        payload: Mapping[str, Any],
        template_id: str = "",  # 飞书不需要模板，仅为与钉钉保持同一工厂契约
        policy: ThrottlePolicy,
        reply_to: str | None = None,
    ) -> FeishuCardSession | None:
        """构造卡片会话（尚未投放）；连接未就绪或目标不可用时返回 ``None``。

        返回 ``None`` 表示「这条消息不走卡片」，由 Worker 退回文本回复 ——
        这是能力协商，不是错误。飞书不需要模板，所以这里不看 ``template_id``：
        卡片 JSON 直接在代码里构造（见 ``app.im.cards.feishu``）。
        """
        if self._http is None:
            logger.debug("Feishu card session skipped: http client unavailable")
            return None
        receive_id = _clean(payload.get("reply_target")) or _clean(payload.get("chat_id"))
        if not receive_id:
            logger.debug("Feishu card session skipped: no receive target")
            return None
        return FeishuCardSession(
            http=self._http,
            credential=self.credential,
            receive_id=receive_id,
            receive_id_type=_clean(payload.get("reply_target_type")) or "chat_id",
            reply_to=reply_to or None,
            policy=policy,
        )

    # ------------------------------------------------------------ 等待态

    async def start_typing(self, *, message_id: str) -> Any | None:
        """给入站消息加一个 Typing 表情回应；失败返回 ``None``。

        这是"智能体正在处理"的**最早**信号：卡片要先建卡再发送，而表情回应是
        对既有消息的一次操作，几乎立刻可见。它同样不占消息位 —— 处理完就删掉。
        """
        if not _typing_reaction_enabled():
            return None
        if self._http is None or not message_id:
            return None
        try:
            token = await tenant_access_token(self._http, self.credential)
            response = await self._http.post(
                f"{API_BASE}/im/v1/messages/{message_id}/reactions",
                headers=self._auth_headers(token),
                json={"reaction_type": {"emoji_type": TYPING_EMOJI}},
            )
            payload = _response_json(response)
            reaction_id = str((payload.get("data") or {}).get("reaction_id") or "")
            if _code(response, payload) != 0 or not reaction_id:
                # 缺 im:message.reaction 权限时属预期：等待态是锦上添花，
                # 不该因此影响正式回复，所以只记 debug。
                logger.debug(
                    "Feishu typing reaction failed channel=%s code=%s",
                    self.credential.channel_id,
                    payload.get("code"),
                )
                return None
            return {"message_id": message_id, "reaction_id": reaction_id}
        except Exception as exc:
            logger.debug("Feishu typing reaction error channel=%s error=%s",
                         self.credential.channel_id, exc)
            return None

    async def stop_typing(self, handle: Any | None) -> None:
        """移除等待态；失败只记日志。

        必须尽力删掉：reaction 是**持久**的，留着就会一直挂在用户消息下面。
        """
        if not handle or self._http is None:
            return
        message_id = handle.get("message_id")
        reaction_id = handle.get("reaction_id")
        if not message_id or not reaction_id:
            return
        try:
            token = await tenant_access_token(self._http, self.credential)
            await self._http.delete(
                f"{API_BASE}/im/v1/messages/{message_id}/reactions/{reaction_id}",
                headers=self._auth_headers(token),
            )
        except Exception as exc:
            logger.warning(
                "Feishu typing reaction removal failed message=%s error=%s", message_id, exc
            )

    def _auth_headers(self, token: str) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json; charset=utf-8",
        }
