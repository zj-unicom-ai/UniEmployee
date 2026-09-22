"""钉钉 Stream 模式 Provider（WebSocket 长连接，零新依赖）。

协议依据（钉钉官方 `dingtalk-stream-sdk-python` 的 `dingtalk_stream/stream.py`
与 `frames.py`，以及 openclaw 官方钉钉插件的连接层实现）：

1. ``POST /v1.0/gateway/connections/open`` 换取 ``{endpoint, ticket}``；
2. ``{endpoint}?ticket={ticket}`` 建立 WebSocket；
3. 服务端推 ``CALLBACK`` 帧，**必须在 60 秒内 ack**，否则服务端重推；
4. 重推时 ``headers.messageId`` 会变、``data.msgId`` 不变，因此幂等键必须是
   ``msgId``（由 Inbox 的 ``(channel_id, provider_message_id)`` 唯一约束兜住）；
5. 出站是把回复 ``POST`` 回入站消息携带的临时 ``sessionWebhook``。

与飞书的关键差异：入站与出站都**不需要 access token**（网关握手直接用
clientId/clientSecret，sessionWebhook 自带会话鉴权），因此本 Provider 不做
token 管理；主动推送（非回复）不在首版范围内。
"""

from __future__ import annotations

import asyncio
import json
import logging
import random
import socket
import time
import uuid
from collections import OrderedDict
from collections.abc import Awaitable, Callable, Mapping
from typing import Any
from urllib.parse import quote_plus

from app.im.contracts import NormalizedInbound, OutboundMessage
from app.im.credentials import ChannelCredential

logger = logging.getLogger("app.im.dingtalk")

InboundHandler = Callable[[NormalizedInbound], Awaitable[None]]
StatusHandler = Callable[[str, str | None], None]

OPENAPI_BASE = "https://api.dingtalk.com"
OPEN_CONNECTION_API = f"{OPENAPI_BASE}/v1.0/gateway/connections/open"
TOPIC_ROBOT = "/v1.0/im/bot/messages/get"
TOPIC_SYSTEM_DISCONNECT = "disconnect"

ACK_STATUS_OK = 200
CONVERSATION_TYPE_P2P = "1"
CONVERSATION_TYPE_GROUP = "2"

_HTTP_TIMEOUT_SECONDS = 10.0
_CONNECT_READY_TIMEOUT_SECONDS = 15.0
_MAX_FRAME_BYTES = 4 * 1024 * 1024
_RECONNECT_BASE_DELAY_SECONDS = 1.0
_RECONNECT_MAX_DELAY_SECONDS = 30.0
_RECONNECT_JITTER_SECONDS = 0.5

# 协议层去重：只拦同一次投递的重复回调。真正的重推由 Inbox 的 msgId 唯一约束拦截。
_PROTOCOL_DEDUP_MAX_ITEMS = 2048
_PROTOCOL_DEDUP_TTL_SECONDS = 300.0


class DingtalkError(RuntimeError):
    """钉钉链路错误；``status_code`` 供 Worker 的「是否可重试」分类复用。"""

    def __init__(
        self, message: str, *, status_code: int | None = None, error_code: str | None = None
    ):
        super().__init__(message)
        self.status_code = status_code
        self.error_code = error_code


class DingtalkDeliveryError(DingtalkError):
    """出站投递失败。"""


def _as_mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _clean(value: Any) -> str:
    return str(value or "").strip()


def _text_content(data: Mapping[str, Any]) -> str:
    text = data.get("text")
    if isinstance(text, Mapping):
        return str(text.get("content") or "")
    if isinstance(text, str):
        return text
    return ""


def _resolved_tenant_key(data: Mapping[str, Any], header_corp_id: Any, fallback: str) -> str:
    """钉钉侧企业标识：优先入站机器人所属组织，其次事件头，最后已存凭证。"""
    for candidate in (data.get("chatbotCorpId"), header_corp_id, fallback):
        value = _clean(candidate)
        if value:
            return value
    return ""


def normalize_message(
    data: Mapping[str, Any],
    *,
    channel_id: str,
    app_id: str,
    tenant_key: str,
    header_event_id: str | None = None,
    header_corp_id: str | None = None,
) -> NormalizedInbound | None:
    """只接收文本消息；群聊必须显式 @ 机器人，其余一律丢弃。"""
    message_type = _clean(data.get("msgtype"))
    if message_type != "text":
        logger.debug("DingTalk message ignored: unsupported msgtype=%s", message_type or None)
        return None

    message_id = _clean(data.get("msgId"))
    chat_id = _clean(data.get("conversationId"))
    chat_type = {
        CONVERSATION_TYPE_P2P: "p2p",
        CONVERSATION_TYPE_GROUP: "group",
    }.get(_clean(data.get("conversationType")))
    if chat_type is None:
        logger.debug(
            "DingTalk message ignored: unsupported conversationType=%s message=%s",
            data.get("conversationType"),
            message_id or None,
        )
        return None

    sender_id = _clean(data.get("senderStaffId")) or _clean(data.get("senderId"))
    chatbot_user_id = _clean(data.get("chatbotUserId"))
    if chatbot_user_id and sender_id == chatbot_user_id:
        logger.debug("DingTalk message ignored: robot self message=%s", message_id or None)
        return None

    if chat_type == "group" and not bool(data.get("isInAtList")):
        # 与飞书一致：群聊只有被 @ 时才响应，不申请读取群内全部消息的权限。
        logger.debug("DingTalk group message ignored: bot not mentioned message=%s", message_id or None)
        return None

    if not all((message_id, chat_id, sender_id)):
        logger.warning(
            "DingTalk message dropped: missing identifiers message=%s chat=%s sender=%s",
            message_id or None,
            chat_id or None,
            sender_id or None,
        )
        return None

    provider_tenant_key = _resolved_tenant_key(data, header_corp_id, tenant_key)
    if not provider_tenant_key:
        # chatbotCorpId 在机器人消息里必然存在；万一缺失也不能静默丢弃，
        # 退化为按应用隔离，避免把不同企业的会话混进同一记忆主体。
        provider_tenant_key = f"app:{app_id}"
        logger.warning(
            "DingTalk provider tenant unavailable, falling back to app scope channel=%s message=%s",
            channel_id,
            message_id,
        )

    session_webhook = _clean(data.get("sessionWebhook"))
    replied = _as_mapping(data.get("repliedMsg"))
    parent_id = _clean(replied.get("msgId")) or None

    return NormalizedInbound(
        provider="dingtalk",
        channel_id=channel_id,
        app_id=app_id,
        tenant_key=provider_tenant_key,
        event_id=_clean(header_event_id) or message_id,
        message_id=message_id,
        chat_id=chat_id,
        chat_type=chat_type,
        # 钉钉没有 open_id 概念，用 senderStaffId 对齐「外部用户标识」语义。
        sender_open_id=sender_id,
        text=_text_content(data),
        root_id=None,
        parent_id=parent_id,
        reply_target=session_webhook or None,
        reply_target_type="session_webhook",
    )


def _markdown_title(text: str, fallback: str = "数字员工") -> str:
    """钉钉 markdown 需要一个纯文本标题，用于通知栏展示。"""
    for line in text.splitlines():
        stripped = line.strip().lstrip("#>-* \t").strip()
        if stripped:
            return stripped[:20]
    return fallback


class DingtalkProvider:
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
        # registry 用 ``provider.channel is not None`` 判断是否需要走关闭流程。
        self.channel: Any | None = None
        self._http: Any | None = None
        self._supervisor_task: asyncio.Task | None = None
        self._stop = asyncio.Event()
        self._loop: asyncio.AbstractEventLoop | None = None
        self._recent: OrderedDict[str, float] = OrderedDict()
        # 持引用，避免派发出去的入站任务被 GC 提前回收。
        self._inflight: set[asyncio.Task] = set()

    def _notify_status(self, status: str, error: str | None = None) -> None:
        if self.on_status is not None:
            self.on_status(status, error)

    # ------------------------------------------------------------------ 去重

    def _prune_recent(self, now: float) -> None:
        expires_before = now - _PROTOCOL_DEDUP_TTL_SECONDS
        while self._recent:
            _, captured_at = next(iter(self._recent.items()))
            if captured_at >= expires_before:
                break
            self._recent.popitem(last=False)
        while len(self._recent) > _PROTOCOL_DEDUP_MAX_ITEMS:
            self._recent.popitem(last=False)

    def _seen_recently(self, key: str) -> bool:
        now = time.monotonic()
        self._prune_recent(now)
        if key in self._recent:
            self._recent.move_to_end(key)
            return True
        self._recent[key] = now
        return False

    # ------------------------------------------------------------ 连接握手

    async def _open_connection(self) -> Mapping[str, Any]:
        if self._http is None:
            raise RuntimeError("钉钉 HTTP 客户端尚未初始化")
        body = {
            "clientId": self.credential.app_id,
            "clientSecret": self.credential.app_secret,
            "subscriptions": [{"type": "CALLBACK", "topic": TOPIC_ROBOT}],
            "ua": "uniemployee-dingtalk/1.0",
            "localIp": _local_ip(),
        }
        try:
            response = await self._http.post(OPEN_CONNECTION_API, json=body)
            response.raise_for_status()
            payload = response.json()
        except Exception as exc:
            # 不把请求体或凭证写进日志。
            raise DingtalkError(
                f"钉钉网关握手失败：{type(exc).__name__}: {exc}",
                status_code=getattr(getattr(exc, "response", None), "status_code", None),
            ) from exc
        if not isinstance(payload, Mapping):
            raise DingtalkError("钉钉网关返回了非预期结构", status_code=502)
        return payload

    async def _dial(self, connection: Mapping[str, Any], timeout: float) -> Any:
        try:
            import websockets
        except ImportError as exc:  # pragma: no cover - 部署依赖检查
            raise RuntimeError("未安装 websockets") from exc

        endpoint = _clean(connection.get("endpoint"))
        ticket = _clean(connection.get("ticket"))
        if not endpoint or not ticket:
            raise DingtalkError("钉钉网关未返回可用的长连接地址", status_code=502)

        uri = f"{endpoint}?ticket={quote_plus(ticket)}"
        return await websockets.connect(
            uri,
            open_timeout=timeout,
            # 用 websockets 自带 ping 做存活探测；超时会抛 ConnectionClosed，
            # 由 _supervise 的统一重连逻辑接管，避免两套心跳互相打架。
            ping_interval=20,
            ping_timeout=20,
            close_timeout=5,
            max_size=_MAX_FRAME_BYTES,
        )

    async def _open_once(self, *, timeout: float) -> None:
        connection = await self._open_connection()
        websocket = await self._dial(connection, timeout)
        await self._close_socket()
        self.channel = websocket

    async def _close_socket(self) -> None:
        websocket, self.channel = self.channel, None
        if websocket is None:
            return
        try:
            await websocket.close()
        except Exception:
            logger.debug("DingTalk websocket close failed", exc_info=True)

    async def connect(self, timeout: float = 30) -> None:
        """完成首次握手后返回；后续重连由内部 Supervisor 自我维持。"""
        import httpx

        self._loop = asyncio.get_running_loop()
        self._stop.clear()
        self._notify_status("connecting")
        self._http = httpx.AsyncClient(
            timeout=_HTTP_TIMEOUT_SECONDS,
            # 与飞书一致：默认直连，代理必须显式配置，避免环境变量劫持出站。
            trust_env=False,
        )
        try:
            await self._open_once(timeout=timeout)
        except Exception:
            await self._shutdown_transport()
            raise
        self._supervisor_task = asyncio.create_task(
            self._supervise(), name=f"dingtalk-supervisor-{self.credential.channel_id}"
        )
        self._notify_status("connected")

    async def _shutdown_transport(self) -> None:
        await self._close_socket()
        if self._http is not None:
            try:
                await self._http.aclose()
            except Exception:
                logger.debug("DingTalk http client close failed", exc_info=True)
            self._http = None

    def _reconnect_delay(self, attempt: int) -> float:
        exponential = _RECONNECT_BASE_DELAY_SECONDS * (2 ** min(max(attempt, 0), 16))
        jitter = random.uniform(0, _RECONNECT_JITTER_SECONDS)
        return min(exponential + jitter, _RECONNECT_MAX_DELAY_SECONDS)

    async def _sleep_or_stop(self, seconds: float) -> bool:
        try:
            await asyncio.wait_for(self._stop.wait(), timeout=seconds)
            return True
        except TimeoutError:
            return False

    async def _supervise(self) -> None:
        attempt = 0
        while not self._stop.is_set():
            try:
                await self._read_until_closed()
                if self._stop.is_set():
                    return
                self._notify_status("reconnecting", "钉钉服务端关闭了长连接")
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                if self._stop.is_set():
                    return
                self._notify_status("reconnecting", f"{type(exc).__name__}: {exc}")

            if await self._sleep_or_stop(self._reconnect_delay(attempt)):
                return
            attempt = min(attempt + 1, 16)

            try:
                await self._open_once(timeout=_CONNECT_READY_TIMEOUT_SECONDS)
            except Exception as exc:
                logger.warning(
                    "DingTalk reconnect failed channel=%s error=%s",
                    self.credential.channel_id,
                    exc,
                )
                continue
            attempt = 0
            self._notify_status("connected")

    async def _read_until_closed(self) -> None:
        websocket = self.channel
        if websocket is None:
            raise RuntimeError("钉钉长连接不存在")
        async for raw in websocket:
            text = raw.decode("utf-8", errors="replace") if isinstance(raw, bytes) else raw
            await self._handle_frame(text)

    # -------------------------------------------------------------- 帧处理

    async def _send_ack(self, message_id: str) -> None:
        websocket = self.channel
        if websocket is None or not message_id:
            return
        frame = {
            "code": ACK_STATUS_OK,
            "headers": {"messageId": message_id, "contentType": "application/json"},
            "message": "",
            "data": json.dumps({"success": True}),
        }
        try:
            await websocket.send(json.dumps(frame))
        except Exception:
            # ack 失败说明连接已坏；交给 Supervisor 重连，服务端会重推本次消息。
            logger.warning("DingTalk ack failed message=%s", message_id)

    async def _handle_frame(self, text: str) -> None:
        try:
            payload = json.loads(text)
        except Exception:
            logger.warning("DingTalk frame dropped: invalid JSON")
            return
        if not isinstance(payload, Mapping):
            return

        frame_type = _clean(payload.get("type")).upper()
        headers = _as_mapping(payload.get("headers"))
        message_id = _clean(headers.get("messageId"))

        if frame_type == "SYSTEM":
            if _clean(headers.get("topic")) == TOPIC_SYSTEM_DISCONNECT:
                # 钉钉在负载均衡 / 实例切换时会主动下发 disconnect，属于协议机制
                # 而非故障，需要立刻重连（不退避）。
                logger.info(
                    "DingTalk disconnect topic received channel=%s", self.credential.channel_id
                )
                await self._close_socket()
            return

        if frame_type != "CALLBACK":
            return

        # 60 秒 ack 硬约束：必须在任何解析/落库之前确认，AI 处理绝不能挡在这里。
        await self._send_ack(message_id)

        if _clean(headers.get("topic")) != TOPIC_ROBOT:
            logger.debug("DingTalk callback ignored: topic=%s", headers.get("topic"))
            return

        # 协议层去重：同一次投递的重复回调。真正的重推（messageId 变化）
        # 由 Inbox 的 msgId 唯一约束拦截。
        if message_id and self._seen_recently(message_id):
            logger.debug("DingTalk duplicate callback skipped message=%s", message_id)
            return

        data = payload.get("data")
        if isinstance(data, str):
            try:
                data = json.loads(data)
            except Exception:
                logger.warning("DingTalk callback data is not valid JSON message=%s", message_id or None)
                return
        if not isinstance(data, Mapping):
            logger.warning("DingTalk callback data is not an object message=%s", message_id or None)
            return

        normalized = normalize_message(
            data,
            channel_id=self.credential.channel_id,
            app_id=self.credential.app_id,
            tenant_key=self.credential.tenant_key,
            header_event_id=_clean(headers.get("eventId")) or None,
            header_corp_id=_clean(headers.get("eventCorpId")) or None,
        )
        if normalized is None:
            return
        task = asyncio.create_task(self.on_message(normalized))
        self._inflight.add(task)
        task.add_done_callback(self._inflight.discard)

    async def disconnect(self) -> None:
        self._stop.set()
        task, self._supervisor_task = self._supervisor_task, None
        if task is not None:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
        await self._shutdown_transport()
        self._recent.clear()

    # ---------------------------------------------------------------- 出站

    async def send(self, message: OutboundMessage) -> Any:
        target = _clean(message.receive_id)
        if not target.startswith(("http://", "https://")):
            # 钉钉 Stream 模式的回复只能回到入站消息携带的 sessionWebhook。
            raise DingtalkDeliveryError(
                "钉钉回复需要入站消息携带的 sessionWebhook，当前投递目标不是有效 URL",
                status_code=400,
            )
        if self._http is None:
            raise RuntimeError("钉钉频道尚未连接")

        body = {
            # 钉钉原生支持 markdown，不需要像飞书那样转 post 富文本。
            "msgtype": "markdown",
            "markdown": {"title": _markdown_title(message.text), "text": message.text},
        }
        try:
            response = await self._http.post(target, json=body)
            response.raise_for_status()
            payload = response.json()
        except Exception as exc:
            raise DingtalkDeliveryError(
                f"钉钉投递失败：{type(exc).__name__}: {exc}",
                status_code=getattr(getattr(exc, "response", None), "status_code", None),
            ) from exc

        payload = payload if isinstance(payload, Mapping) else {}
        errcode = payload.get("errcode")
        if errcode not in (None, 0):
            # sessionWebhook 过期、机器人被移出会话等都属于不可重试；
            # 标成 400 会让 Outbox 直接进入 dead，等待管理员手工重放。
            raise DingtalkDeliveryError(
                f"钉钉返回错误：errcode={errcode} errmsg={_clean(payload.get('errmsg'))}",
                status_code=400,
                error_code=str(errcode),
            )

        provider_message_id = (
            _clean(payload.get("processQueryKey"))
            or _clean(payload.get("messageId"))
            # sessionWebhook 常只回 {"errcode":0}；用入站 msgId 作为可追溯的回执标识。
            or _clean(message.reply_to_message_id)
            or f"dingtalk-{uuid.uuid4().hex}"
        )
        return DeliveryReceipt(
            message_id=provider_message_id,
            raw=dict(payload),
        )


class DeliveryReceipt:
    """出站回执；字段名刻意与 Worker 的容错提取逻辑对齐。"""

    __slots__ = ("message_id", "raw")

    def __init__(self, *, message_id: str, raw: dict[str, Any] | None = None):
        self.message_id = message_id
        self.raw = raw or {}


def _local_ip() -> str:
    """取本机出口 IPv4；失败时退化为回环地址，不影响握手。"""
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as probe:
            probe.settimeout(0.5)
            probe.connect(("114.114.114.114", 80))
            return probe.getsockname()[0]
    except Exception:
        return "127.0.0.1"
