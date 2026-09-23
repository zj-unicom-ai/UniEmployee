"""企业微信智能机器人 Provider（WebSocket 长连接，零新增依赖、零 HTTP 出站）。

协议依据（企业微信开发者中心《智能机器人长连接》与《回复消息》，以及官方 SDK
``@wecom/aibot-node-sdk`` 1.0.7 的 ``src/ws.ts`` / ``src/types/api.ts``，
2026-09-23 核实）：

1. 连接 ``wss://openws.work.weixin.qq.com``，连上后发 ``aibot_subscribe``
   （body 为 ``bot_id`` / ``secret``）完成身份校验；
2. 保活是**应用层**心跳：每 30 秒发 ``{"cmd": "ping", "headers": {"req_id": …}}``，
   收到回执才算连接健康（官方 SDK 连续 2 次未收到回执即判定死连接并重连）；
3. 服务端推 ``aibot_msg_callback``（消息）与 ``aibot_event_callback``（事件），
   ``headers.req_id`` 是**本次回调的回复凭据**，回复时必须原样透传；
4. 出站不是往独立 URL 投递，而是**在同一条长连接上**发
   ``{"cmd": "aibot_respond_msg", "headers": {"req_id": 入站那个}, "body": {…}}``；
5. 服务端对每帧回复都回执，同一次回调的所有流式刷新**共用**同一个 ``req_id`` 与
   ``stream.id``。

与飞书/钉钉的关键差异（这些是本次改造的真正工作量）：

- **没有 HTTP 出站**：飞书写 OpenAPI、钉钉 POST 临时 sessionWebhook，企微全程只有
  一条 WebSocket。所以本 Provider 不引入 httpx、不做 token 管理，出站就是发帧；
- **回复目标不是持久标识**：``reply_target`` 是本次回调的 ``req_id``
  （``reply_target_type == "req_id"``），用完即废 —— 靠 ``_reply_contexts``
  记住它属于哪个会话，见 ``send()``；
- **5 秒首回复硬窗口**：收到回调后 5 秒内必须发出第一帧，且错过就**永远回不了**。
  所以占位流在 Provider 侧就推出去（``_prestart_stream``），不等 Worker 排程；
  但**它必须在独立任务里等回执**：回执只能由读循环 ``recv`` 进来，在读循环的调用栈
  里 await 发送就是「等自己」，必然超时（真机踩过：双气泡，见 ``_send_reply``）；
- **单机器人单连接**：新订阅会踢掉旧连接，被踢时服务端推 ``disconnected_event``。
  收到它的连接**不重连**（官方 SDK 同样处理），否则多副本部署会互踢成死循环。
"""

from __future__ import annotations

import asyncio
import json
import logging
import random
import time
import uuid
from collections import OrderedDict
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from typing import Any

from app.im.cards import (
    WORKING_TEXT,
    ThrottlePolicy,
    card_enabled,
    card_level,
    policy_for,
)
from app.im.cards.wecom import WecomCardSession, clamp_stream_bytes
from app.im.contracts import NormalizedInbound, OutboundMessage
from app.im.credentials import ChannelCredential

logger = logging.getLogger("app.im.wecom")

InboundHandler = Callable[[NormalizedInbound], Awaitable[None]]
StatusHandler = Callable[[str, str | None], None]

WS_URL = "wss://openws.work.weixin.qq.com"

# 开发者 -> 企业微信
CMD_SUBSCRIBE = "aibot_subscribe"
CMD_HEARTBEAT = "ping"
CMD_RESPONSE = "aibot_respond_msg"
CMD_SEND_MSG = "aibot_send_msg"
# 企业微信 -> 开发者
CMD_CALLBACK = "aibot_msg_callback"
CMD_EVENT_CALLBACK = "aibot_event_callback"

# 有新连接顶替时服务端下发的断开事件。它**不是故障**，是协议机制。
EVENT_DISCONNECTED = "disconnected_event"

CHATTYPE_SINGLE = "single"
CHATTYPE_GROUP = "group"
CHAT_TYPE_MAP: dict[str, str] = {CHATTYPE_SINGLE: "p2p", CHATTYPE_GROUP: "group"}

# reply_target_type 的新取值：出站目标是"某次回调的回复凭据"而不是会话 ID。
REPLY_TARGET_TYPE = "req_id"

HEARTBEAT_SECONDS = 30.0
HEARTBEAT_MAX_MISSED = 2
REPLY_ACK_TIMEOUT_SECONDS = 8.0

_CONNECT_READY_TIMEOUT_SECONDS = 15.0
_MAX_FRAME_BYTES = 4 * 1024 * 1024
_RECONNECT_BASE_DELAY_SECONDS = 1.0
_RECONNECT_MAX_DELAY_SECONDS = 30.0
_RECONNECT_JITTER_SECONDS = 0.5

# 协议层去重：只拦同一次投递的重复回调。真正的重推由 Inbox 的 msgid 唯一约束拦截。
_PROTOCOL_DEDUP_MAX_ITEMS = 2048
_PROTOCOL_DEDUP_TTL_SECONDS = 300.0

# 预热会话 / 回复上下文 / 回复锁的保留上限。三者都是"按 req_id 记账"的短命数据，
# 不设上限会在长跑进程里无界增长。
_PENDING_SESSION_MAX_ITEMS = 256
_REPLY_CONTEXT_MAX_ITEMS = 512
_REPLY_LOCK_MAX_ITEMS = 512


class WecomError(RuntimeError):
    """企微链路错误；``status_code`` 供 Worker 的「是否可重试」分类复用。"""

    def __init__(
        self,
        message: str,
        *,
        status_code: int | None = None,
        error_code: str | None = None,
        frame_sent: bool = False,
    ):
        super().__init__(message)
        self.status_code = status_code
        self.error_code = error_code
        # 帧是否已经写到长连接上（与「是否收到回执」是两件事）。
        #
        # 这个区分是必需的：企微的流式气泡由**首帧**隐式创建，所以「帧已发出、
        # 回执没等到」意味着**用户侧多半已经多了一条气泡**。调用方据此决定要不要
        # 继续复用这条流（避免留下永久停在「正在处理」的孤儿气泡），而不是当成
        # 什么都没发生。503（连接不存在）时帧没出去，才是真的没有气泡。
        self.frame_sent = frame_sent


class WecomDeliveryError(WecomError):
    """出站投递失败。"""


def _as_mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _clean(value: Any) -> str:
    return str(value or "").strip()


def _new_req_id(prefix: str) -> str:
    """生成请求 ID，格式对齐官方 SDK：``{prefix}_{毫秒时间戳}_{8 位随机}``。

    前缀不是装饰：服务端在响应帧里原样透传 req_id，而响应帧**可能不带 cmd**
    （官方 SDK 注释："认证/心跳响应时可能为空"），官方实现正是靠这个前缀区分
    订阅 / 心跳 / 回复三类响应的（见其 ``ws.ts`` 的 ``handleFrame``）。
    跟随它的格式可以避免服务端将来按前缀校验时踩空。
    """
    return f"{prefix}_{int(time.time() * 1000)}_{uuid.uuid4().hex[:8]}"


def _text_content(body: Mapping[str, Any]) -> str:
    text = body.get("text")
    if isinstance(text, Mapping):
        return str(text.get("content") or "")
    if isinstance(text, str):
        return text
    return ""


def normalize_message(
    body: Mapping[str, Any],
    *,
    req_id: str,
    channel_id: str,
    app_id: str,
    tenant_key: str,
) -> NormalizedInbound | None:
    """把企微消息回调体标准化；非文本或缺少回复凭据时返回 ``None``。

    群聊的 @ 过滤**不在这里做**：企微只在被 @ 时才产生群聊消息回调
    （官方《长连接》原文："用户在群聊中@机器人或向机器人发送单聊消息时"），
    所以不需要像钉钉那样判 ``isInAtList``。正文里带的前缀 ``@机器人名``
    留给 M3 处理。
    """
    msg_type = _clean(body.get("msgtype"))
    if msg_type != "text":
        logger.debug("WeCom message ignored: unsupported msgtype=%s", msg_type or None)
        return None

    message_id = _clean(body.get("msgid"))
    if not message_id:
        logger.warning("WeCom message dropped: missing msgid")
        return None

    raw_chat_type = _clean(body.get("chattype"))
    chat_type = CHAT_TYPE_MAP.get(raw_chat_type)
    if chat_type is None:
        logger.debug(
            "WeCom message ignored: unsupported chattype=%s message=%s",
            raw_chat_type or None,
            message_id,
        )
        return None

    sender_id = _clean(_as_mapping(body.get("from")).get("userid"))
    # 单聊回调**不返回 chatid**（官方字段说明："会话 ID，仅群聊类型时返回"），
    # 用发送者 userid 当会话标识 —— 主动推送（aibot_send_msg）的 chatid 字段在
    # 单聊场景本就要填 userid，所以这个归一让出站能直接复用同一个值。
    chat_id = _clean(body.get("chatid")) or sender_id
    if not chat_id or not sender_id:
        logger.warning(
            "WeCom message dropped: missing sender or conversation message=%s", message_id
        )
        return None

    if not req_id:
        # req_id 是回复凭据。没有它这条消息永远回不了，收进 Inbox 只会得到一条
        # 注定失败的死信。
        logger.warning("WeCom message dropped: missing reply req_id message=%s", message_id)
        return None

    # 企微回调里没有企业标识（`from.corpid` 只在事件回调里，且企业内部机器人不返回），
    # 用回调自带的机器人 ID 作租户边界 —— 一个频道一个机器人，隔离粒度与飞书/钉钉一致。
    provider_tenant_key = _clean(body.get("aibotid")) or _clean(tenant_key) or f"app:{app_id}"

    return NormalizedInbound(
        provider="wecom",
        channel_id=channel_id,
        app_id=app_id,
        tenant_key=provider_tenant_key,
        event_id=message_id,
        message_id=message_id,
        chat_id=chat_id,
        chat_type=chat_type,
        # 企微没有 open_id 概念，用 from.userid 对齐「外部用户标识」语义。
        # 注意：非超管创建的机器人拿到的可能是**加密 userid**，我们只当外部标识用，
        # 不做通讯录反查（要拿明文得走「自建应用与智能机器人的对接」）。
        sender_open_id=sender_id,
        text=_text_content(body),
        reply_target=req_id,
        reply_target_type=REPLY_TARGET_TYPE,
    )


@dataclass(slots=True)
class _ReplyContext:
    """一次入站回调的回复上下文。

    企微的 ``reply_target`` 是**用完即废**的 req_id，不像飞书的 chat_id 那样持久，
    所以必须把「这个 req_id 属于哪个会话」记下来：内容超长要补发时，主动推送只能
    靠它找到收件人；而同一个 req_id 只允许 respond 一次（气泡 finish 后即锁定），
    第二次起必须改走主动推送。
    """

    chat_id: str
    chat_type: str
    sender_id: str
    responded: bool = False


class WecomProvider:
    """一个频道一个实例，由 Supervisor 管理连接和收发生命周期。"""

    # 与 ``providers.PROVIDERS`` 的键一致。卡片档位这类「按渠道取值」的配置靠它
    # 定位，所以改名要同步改那边（有测试守着这条一致性）。
    PROVIDER_ID = "wecom"

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
        self._supervisor_task: asyncio.Task | None = None
        self._heartbeat_task: asyncio.Task | None = None
        self._stop = asyncio.Event()
        self._recent: OrderedDict[str, float] = OrderedDict()
        # 持引用，避免派发出去的入站任务被 GC 提前回收。
        self._inflight: set[asyncio.Task] = set()
        self._pending_replies: dict[str, asyncio.Future] = {}
        self._reply_locks: dict[str, asyncio.Lock] = {}
        self._pending_sessions: OrderedDict[str, WecomCardSession] = OrderedDict()
        self._reply_contexts: OrderedDict[str, _ReplyContext] = OrderedDict()
        self._last_heartbeat_req_id = ""
        self._missed_heartbeat_acks = 0
        # 服务端因「新连接顶替」而断开：这是协议机制不是故障，明确不重连。
        self._taken_over = False

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

    # ------------------------------------------------------------ 连接与握手

    async def _dial(self, timeout: float) -> Any:
        try:
            import websockets
        except ImportError as exc:  # pragma: no cover - 部署依赖检查
            raise RuntimeError("未安装 websockets") from exc

        return await websockets.connect(
            WS_URL,
            open_timeout=timeout,
            # 保活交给**应用层**心跳（cmd=ping，30 秒一次，见 _heartbeat_loop）：
            # 官方 SDK 就是这么做的，它只被动响应服务端的协议层 ping。
            # 关掉 websockets 自带的协议层心跳，避免两套保活各自的超时互相打断。
            ping_interval=None,
            close_timeout=5,
            max_size=_MAX_FRAME_BYTES,
        )

    async def _subscribe(self, timeout: float) -> None:
        """发送订阅帧并等它的回执；被拒或超时都抛 ``WecomError``。

        这里**自己**读 socket 而不是让读循环代劳：订阅是连接可用的前置条件，
        在它完成前不能让 `_supervise` 的读循环跑起来（否则收不到"连接已就绪"
        这个信号，重连也会变成"TCP 连上了但没订阅"的假象）。
        """
        websocket = self.channel
        if websocket is None:
            raise WecomError("企业微信长连接尚未建立", status_code=503)

        req_id = _new_req_id(CMD_SUBSCRIBE)
        frame = {
            "cmd": CMD_SUBSCRIBE,
            "headers": {"req_id": req_id},
            # Secret 只出现在这一帧里，任何日志都不落它。
            "body": {"bot_id": self.credential.app_id, "secret": self.credential.app_secret},
        }
        await websocket.send(json.dumps(frame))

        deadline = time.monotonic() + timeout
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise WecomError("企业微信长连接订阅超时", status_code=504)
            raw = await asyncio.wait_for(websocket.recv(), timeout=remaining)
            text = raw.decode("utf-8", errors="replace") if isinstance(raw, bytes) else raw
            try:
                payload = json.loads(text)
            except Exception:
                logger.warning("WeCom frame dropped during subscribe: invalid JSON")
                continue
            if not isinstance(payload, Mapping):
                continue

            headers = _as_mapping(payload.get("headers"))
            if _clean(headers.get("req_id")) != req_id:
                # 订阅还没回执就来别的帧（理论上不会），仍按正常逻辑处理，不丢。
                await self._dispatch(payload)
                continue

            errcode = payload.get("errcode")
            if errcode not in (0, None):
                raise WecomError(
                    f"企业微信拒绝订阅：errcode={errcode} errmsg={_clean(payload.get('errmsg'))}",
                    status_code=400,
                    error_code=str(errcode),
                )
            return

    async def _open_once(self, *, timeout: float) -> None:
        websocket = await self._dial(timeout)
        await self._close_socket()
        self.channel = websocket
        self._missed_heartbeat_acks = 0
        try:
            await self._subscribe(timeout=timeout)
        except Exception:
            await self._close_socket()
            raise
        self._start_heartbeat()

    async def _close_socket(self) -> None:
        self._stop_heartbeat()
        websocket, self.channel = self.channel, None
        # 唤醒所有等待回执的调用方，别让它们挂到超时。
        for waiter in list(self._pending_replies.values()):
            if not waiter.done():
                waiter.set_exception(
                    WecomDeliveryError("企业微信长连接已断开", status_code=503)
                )
        self._pending_replies.clear()
        self._reply_locks.clear()
        if websocket is None:
            return
        try:
            await websocket.close()
        except Exception:
            logger.debug("WeCom websocket close failed", exc_info=True)

    async def connect(self, timeout: float = 30) -> None:
        """完成连接与订阅后返回；后续重连由内部 Supervisor 自我维持。"""
        self._stop.clear()
        # 人工重连要重新开始：上一次的"被顶替"状态不能阻止这次连接。
        self._taken_over = False
        self._notify_status("connecting")
        try:
            await self._open_once(timeout=timeout)
        except Exception:
            await self._shutdown_transport()
            raise
        self._supervisor_task = asyncio.create_task(
            self._supervise(), name=f"wecom-supervisor-{self.credential.channel_id}"
        )
        self._notify_status("connected")

    async def _shutdown_transport(self) -> None:
        """企微没有独立的 HTTP 客户端，收尾只有关闭长连接。"""
        await self._close_socket()

    # ---------------------------------------------------------------- 心跳

    def _start_heartbeat(self) -> None:
        self._stop_heartbeat()
        self._heartbeat_task = asyncio.create_task(
            self._heartbeat_loop(), name=f"wecom-heartbeat-{self.credential.channel_id}"
        )

    def _stop_heartbeat(self) -> None:
        task, self._heartbeat_task = self._heartbeat_task, None
        if task is not None and not task.done():
            task.cancel()

    async def _heartbeat_loop(self) -> None:
        """30 秒一次应用层心跳；连续未回执即判连接已死并交给重连逻辑。"""
        while not self._stop.is_set():
            if await self._sleep_or_stop(HEARTBEAT_SECONDS):
                return
            if self._taken_over:
                # 被新连接顶替后心跳没有意义（服务端已把我们断开）。
                return
            if self._missed_heartbeat_acks >= HEARTBEAT_MAX_MISSED:
                logger.warning(
                    "WeCom heartbeat unacknowledged %s times, reconnecting channel=%s",
                    self._missed_heartbeat_acks,
                    self.credential.channel_id,
                )
                # 关掉 socket 让读循环退出，重连交给 _supervise 统一处理。
                await self._close_socket()
                return
            try:
                await self._send_heartbeat()
            except Exception as exc:
                logger.debug("WeCom heartbeat send failed error=%s", exc)

    async def _send_heartbeat(self) -> None:
        """发一次应用层心跳并记账；未收到回执的计数在这里递增。

        独立成一个方法是为了可测：`_heartbeat_loop` 里 30 秒的等待在单元测试中
        没法跑，但"帧长什么样、计数怎么走"是协议正确性的一部分。
        """
        self._last_heartbeat_req_id = _new_req_id(CMD_HEARTBEAT)
        self._missed_heartbeat_acks += 1
        await self._send_frame(
            {"cmd": CMD_HEARTBEAT, "headers": {"req_id": self._last_heartbeat_req_id}}
        )

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
                if self._taken_over:
                    # 单机器人单连接：抢回来也会被再次踢掉，所以明确停下并如实报状态，
                    # 让管理员看到"另一个实例在跑"而不是无限互踢。
                    self._notify_status(
                        "failed", "企业微信长连接已被同一机器人的新连接顶替"
                    )
                    return
                self._notify_status("reconnecting", "企业微信服务端关闭了长连接")
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                if self._stop.is_set():
                    return
                if self._taken_over:
                    self._notify_status(
                        "failed", "企业微信长连接已被同一机器人的新连接顶替"
                    )
                    return
                self._notify_status("reconnecting", f"{type(exc).__name__}: {exc}")

            if await self._sleep_or_stop(self._reconnect_delay(attempt)):
                return
            attempt = min(attempt + 1, 16)

            try:
                await self._open_once(timeout=_CONNECT_READY_TIMEOUT_SECONDS)
            except Exception as exc:
                logger.warning(
                    "WeCom reconnect failed channel=%s error=%s",
                    self.credential.channel_id,
                    exc,
                )
                continue
            attempt = 0
            self._notify_status("connected")

    async def _read_until_closed(self) -> None:
        websocket = self.channel
        if websocket is None:
            raise RuntimeError("企业微信长连接不存在")
        async for raw in websocket:
            text = raw.decode("utf-8", errors="replace") if isinstance(raw, bytes) else raw
            await self._dispatch_text(text)

    # -------------------------------------------------------------- 帧处理

    async def _send_frame(self, frame: Mapping[str, Any]) -> None:
        websocket = self.channel
        if websocket is None:
            raise WecomDeliveryError("企业微信长连接尚未建立", status_code=503)
        await websocket.send(json.dumps(frame, ensure_ascii=False))

    async def _dispatch_text(self, text: str) -> None:
        try:
            payload = json.loads(text)
        except Exception:
            logger.warning("WeCom frame dropped: invalid JSON")
            return
        if not isinstance(payload, Mapping):
            return
        await self._dispatch(payload)

    async def _dispatch(self, payload: Mapping[str, Any]) -> None:
        cmd = _clean(payload.get("cmd"))
        headers = _as_mapping(payload.get("headers"))
        req_id = _clean(headers.get("req_id"))

        if cmd == CMD_CALLBACK:
            await self._handle_callback(payload, req_id=req_id)
            return
        if cmd == CMD_EVENT_CALLBACK:
            await self._handle_event(payload)
            return

        # 其余都是响应帧（订阅 / 心跳 / 回复回执）。响应帧可能**不带 cmd**，
        # 所以只能靠 req_id 归类 —— 这也是我们自己发的 req_id 要带前缀的原因。
        if req_id and req_id == self._last_heartbeat_req_id:
            self._missed_heartbeat_acks = 0
            return

        waiter = self._pending_replies.get(req_id)
        if waiter is not None and not waiter.done():
            waiter.set_result(dict(payload))
            return

        logger.debug("WeCom unknown frame ignored cmd=%s", cmd or None)

    async def _handle_callback(self, payload: Mapping[str, Any], *, req_id: str) -> None:
        body = _as_mapping(payload.get("body"))
        message_id = _clean(body.get("msgid"))

        # 协议层去重：同一次投递的重复回调。真正的重推由 Inbox 的 msgid 唯一约束拦截。
        if message_id and self._seen_recently(message_id):
            logger.debug("WeCom duplicate callback skipped message=%s", message_id)
            return

        normalized = normalize_message(
            body,
            req_id=req_id,
            channel_id=self.credential.channel_id,
            app_id=self.credential.app_id,
            tenant_key=self.credential.tenant_key,
        )
        if normalized is None:
            return

        self._remember_reply_context(normalized)
        # 抢 5 秒硬窗口：占位流要先于入队推出。
        #
        # 但**绝不能在这里 await 它**：本函数位于读循环的调用栈上，而占位流要等
        # 服务端回执，回执又只能由读循环自己 ``recv`` 进来 —— 那就是在等自己。
        # 实测 100% 复现：帧发了、用户看到了气泡、回执永远收不到（8 秒超时）、
        # 会话登记失败，Worker 只好另开一条流 ⇒ 用户侧两条「正在处理，请稍候…」，
        # 第一条永久残留。所以整段「预热 + 入队」交给独立任务，读循环立刻回 recv。
        # 「预热先于入队」的顺序保证移到了 _accept_message 内部。
        task = asyncio.create_task(self._accept_message(normalized))
        self._inflight.add(task)
        task.add_done_callback(self._inflight.discard)
        # 返回任务只为测试与观测（真实调用方是读循环，不 await 它）。
        return task

    async def _accept_message(self, normalized: NormalizedInbound) -> None:
        """独立任务里执行「预热占位流 → 入队」，顺序不可颠倒。

        顺序是硬约束：Worker 的 ``create_card_session`` 靠 ``_take_session(req_id)``
        复用预热出来的流，预热没登记就取不到 —— 那就是双气泡的另一半成因。
        这里已经脱离读循环，所以 ``prestart`` 可以正常等回执。
        """
        await self._prestart_stream(normalized)
        try:
            await self.on_message(normalized)
        except Exception:
            # 独立任务的异常没人接，必须自己记，否则入队失败会完全静默。
            logger.exception(
                "WeCom inbound enqueue failed channel=%s message=%s",
                self.credential.channel_id,
                normalized.event_id,
            )

    async def _handle_event(self, payload: Mapping[str, Any]) -> None:
        body = _as_mapping(payload.get("body"))
        event = _as_mapping(body.get("event"))
        event_type = _clean(event.get("eventtype"))
        if event_type == EVENT_DISCONNECTED:
            logger.warning(
                "WeCom connection taken over by a new one channel=%s",
                self.credential.channel_id,
            )
            # 标记后主动断开：读循环退出，_supervise 见到标记就不再重连。
            self._taken_over = True
            await self._close_socket()
            return
        # enter_chat（欢迎语）、template_card_event、feedback_event 属于 M3 范围。
        logger.debug("WeCom event ignored eventtype=%s", event_type or None)

    # ------------------------------------------------------------ 回复上下文

    def _remember_reply_context(self, message: NormalizedInbound) -> None:
        req_id = _clean(message.reply_target)
        if not req_id:
            return
        self._reply_contexts[req_id] = _ReplyContext(
            chat_id=message.chat_id,
            chat_type=message.chat_type,
            sender_id=message.sender_open_id,
        )
        while len(self._reply_contexts) > _REPLY_CONTEXT_MAX_ITEMS:
            self._reply_contexts.popitem(last=False)

    def _remember_session(self, session: WecomCardSession) -> None:
        self._pending_sessions[session.req_id] = session
        while len(self._pending_sessions) > _PENDING_SESSION_MAX_ITEMS:
            self._pending_sessions.popitem(last=False)

    def _take_session(self, req_id: str) -> WecomCardSession | None:
        session = self._pending_sessions.pop(req_id, None)
        # 已被 Worker 收尾/放弃的会话不再交出，避免复用已锁定的流。
        if session is None or session.finalized:
            return None
        return session

    async def _prestart_stream(self, message: NormalizedInbound) -> None:
        """在收到回调的**同一步**内推出占位流，抢 5 秒首回复硬窗口。

        这是企微与飞书/钉钉最重要的时序差异：那条链路是「入队 -> 轮询 claim ->
        开卡片」，平时几十毫秒，但 inbox 积压时会排队越过 5 秒 —— 而企微错过窗口
        就**永远回不了这条消息**。所以窗口由 Provider 自己闭环，与 Worker 排程解耦。

        失败不阻断入队：Worker 会退回卡片开流或文本回复，只是失去这份确定性。

        ⚠️ **调用方必须已经脱离读循环**（实际路径：``_handle_callback`` 把它丢进
        ``_accept_message`` 独立任务）。本函数会等回执，而回执只能由读循环投递 ——
        在读循环的调用栈里调用它就是等自己，必然超时（真机踩过，见 ``_send_reply``）。
        """
        if self.channel is None or not card_enabled():
            return
        req_id = _clean(message.reply_target)
        if not req_id:
            return
        session: WecomCardSession | None = None
        try:
            session = WecomCardSession(
                send_reply=self._send_reply,
                req_id=req_id,
                chat_id=message.chat_id,
                chat_type=message.chat_type,
                policy=policy_for(card_level(self.PROVIDER_ID)),
            )
            await session.prestart(WORKING_TEXT)
        except WecomDeliveryError as exc:
            if session is not None and exc.frame_sent:
                # 帧发出去了、回执没等到 ⇒ 企微的流由首帧**隐式创建**，所以用户侧
                # 那条气泡多半已经出现。必须把会话登记下来交给 Worker 复用，否则
                # Worker 会另开一条流，而这条就永久停在「正在处理，请稍候…」。
                # 代价：万一流其实没创建成功，Worker 收尾会拿到 errcode 并退回文本补发
                # （finalize 失败 → delivered_by_card=False → Outbox 文本兜底）。
                logger.warning(
                    "WeCom placeholder stream ack missing (frame sent, will reuse stream)"
                    " channel=%s error=%s",
                    self.credential.channel_id,
                    exc,
                )
                self._remember_session(session)
                return
            logger.warning(
                "WeCom placeholder stream failed channel=%s error=%s",
                self.credential.channel_id,
                exc,
            )
            return
        except Exception as exc:
            logger.warning(
                "WeCom placeholder stream failed channel=%s error=%s",
                self.credential.channel_id,
                exc,
            )
            return
        self._remember_session(session)

    # ------------------------------------------------------------ 回复发送

    def _reply_lock(self, req_id: str) -> asyncio.Lock:
        lock = self._reply_locks.get(req_id)
        if lock is None:
            if len(self._reply_locks) >= _REPLY_LOCK_MAX_ITEMS:
                # 只回收**当前空闲**的锁：被持有的锁不能替换，否则同一 req_id 会同时
                # 存在两把锁、串行保证失效（宁可多留几把，也不要破坏正确性）。
                for key in [
                    key for key, value in self._reply_locks.items() if not value.locked()
                ]:
                    self._reply_locks.pop(key, None)
            lock = self._reply_locks[req_id] = asyncio.Lock()
        return lock

    async def _send_reply(
        self,
        req_id: str,
        body: Mapping[str, Any],
        *,
        cmd: str = CMD_RESPONSE,
        timeout: float | None = None,
    ) -> dict[str, Any]:
        """在同一 req_id 上**串行**发一帧并等回执，返回回执帧。

        串行是必需的：同一 req_id 的回复回执里只有 req_id 与 errcode，**没有可区分
        的帧标识**，并发发送就无法把回执与帧配对。官方 SDK 用 per-req_id 发送队列
        实现同一语义（其 ``ws.ts`` 的 ``sendReply`` / ``processReplyQueue``）。

        ⚠️ **调用方绝不能位于读循环的调用栈上。** 回执只能由读循环 ``recv`` 进来，
        所以「在读循环里 await 本函数」是**等自己**——必然 8 秒超时。真实事故：
        ``_prestart_stream`` 曾在 ``_handle_callback`` 里被直接 await，于是占位流
        的帧发出去了（用户看到气泡）、回执永远收不到、会话登记失败，Worker 只好
        另开一条流，用户侧表现为**两条「正在处理，请稍候…」，第一条永不消失**。
        需要抢窗口的调用方请走 ``_handle_callback`` 的独立任务路径。
        """
        # 默认超时在函数体内解析：写成默认参数会在定义时绑定，改不了也测不了。
        if timeout is None:
            timeout = REPLY_ACK_TIMEOUT_SECONDS
        lock = self._reply_lock(req_id)
        async with lock:
            waiter: asyncio.Future = asyncio.get_running_loop().create_future()
            self._pending_replies[req_id] = waiter
            frame_sent = False
            try:
                await self._send_frame(
                    {"cmd": cmd, "headers": {"req_id": req_id}, "body": dict(body)}
                )
                frame_sent = True
                payload = await asyncio.wait_for(waiter, timeout=timeout)
            except TimeoutError as exc:
                # 回执超时多半是连接已坏，标成可重试（504）—— 代价是极端情况下可能
                # 重复投递一条；若直接判死，网络抖动就会变成用户永久收不到结果。
                # frame_sent 一并带出：流式首帧会**隐式创建**气泡，调用方要靠它
                # 判断用户侧是否已经多了一条（见 WecomError.frame_sent 的注释）。
                raise WecomDeliveryError(
                    "企业微信回复未收到回执", status_code=504, frame_sent=frame_sent
                ) from exc
            except WecomDeliveryError:
                raise
            except Exception as exc:
                raise WecomDeliveryError(
                    f"企业微信回复发送失败：{type(exc).__name__}: {exc}",
                    status_code=503,
                    frame_sent=frame_sent,
                ) from exc
            finally:
                if self._pending_replies.get(req_id) is waiter:
                    self._pending_replies.pop(req_id, None)

        errcode = payload.get("errcode")
        if errcode not in (0, None):
            # errcode 非 0 属于业务拒绝（凭据失效、会话不存在…），重试无用，
            # 标 400 让 Outbox 直接进 dead 等管理员处理。
            raise WecomDeliveryError(
                f"企业微信返回错误：errcode={errcode} errmsg={_clean(payload.get('errmsg'))}",
                status_code=400,
                error_code=str(errcode),
            )
        return payload

    async def _send_active(
        self, *, context: _ReplyContext | None, fallback_target: str, text: str
    ) -> Any:
        """主动推送（``aibot_send_msg``）：不依赖某次回调，24 小时内有效。

        接收方字段名就是 ``chatid`` —— 群聊填会话 ID，单聊填 userid，两者同字段
        （官方 SDK 的 ``sendMessage('userid_or_chatid', …)`` 即此意）。我们的
        ``chat_id`` 在归一化时已把单聊折成 userid，所以直接复用。
        """
        chat_id = context.chat_id if context is not None else fallback_target
        if not chat_id:
            raise WecomDeliveryError("企业微信主动推送缺少会话标识", status_code=400)
        content, _ = clamp_stream_bytes(text)
        payload = await self._send_reply(
            _new_req_id(CMD_SEND_MSG),
            {"chatid": chat_id, "msgtype": "markdown", "markdown": {"content": content}},
            cmd=CMD_SEND_MSG,
        )
        return DeliveryReceipt(message_id=f"wecom-{uuid.uuid4().hex}", raw=payload)

    async def send(self, message: OutboundMessage) -> Any:
        """出站。回复语义由 ``receive_id_type`` 表达。

        - ``req_id``：这是某次入站回调的回复通道。**每个 req_id 只允许 respond 一次**
          （气泡一旦 ``finish=true`` 就锁定），所以第二次起自动降级为主动推送 ——
          Worker 的「卡片被截断后补发文本」正好走这条路，**不需要为企微改 Worker**，
          也符合 ``contracts.py`` "回复目标语义由 Provider 决定"的约定。
        - 其它取值：直接按会话/用户主动推送。
        """
        text = message.text or ""
        receive_id = _clean(message.receive_id)
        receive_id_type = _clean(message.receive_id_type) or "chat_id"

        if receive_id_type == REPLY_TARGET_TYPE and receive_id:
            context = self._reply_contexts.get(receive_id)
            if context is not None and not context.responded:
                context.responded = True
                content, _ = clamp_stream_bytes(text)
                payload = await self._send_reply(
                    receive_id,
                    {"msgtype": "markdown", "markdown": {"content": content}},
                )
                return DeliveryReceipt(
                    # 回执帧里没有消息 ID，用入站 msgid 保可追溯性（同钉钉）。
                    message_id=_clean(message.reply_to_message_id)
                    or f"wecom-{uuid.uuid4().hex}",
                    raw=payload,
                )
            return await self._send_active(
                context=context, fallback_target=receive_id, text=text
            )

        return await self._send_active(context=None, fallback_target=receive_id, text=text)

    async def disconnect(self) -> None:
        self._stop.set()
        task, self._supervisor_task = self._supervisor_task, None
        if task is not None:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
        await self._shutdown_transport()
        self._recent.clear()
        self._pending_sessions.clear()
        self._reply_contexts.clear()

    # ---------------------------------------------------------------- 卡片

    def card_space(self, payload: Mapping[str, Any]) -> tuple[str, str] | None:
        """企微的流式消息不需要投放场域，恒返回 ``None``。

        保留这个方法是为了让「这个渠道要不要场域」在代码里有个明确答案：
        钉钉需要（``IM_ROBOT`` / ``IM_GROUP`` + spaceId），企微不需要。
        """
        return None

    def create_card_session(
        self,
        *,
        payload: Mapping[str, Any],
        template_id: str,
        policy: ThrottlePolicy,
        reply_to: str | None = None,
    ) -> WecomCardSession | None:
        """交出这条消息的流式会话；连接未就绪或缺回复凭据时返回 ``None``。

        返回 ``None`` 表示「这条消息走文本回复」，由 Worker 处理 —— 这是能力协商，
        不是错误，所以只记 debug。

        ``template_id`` 有意不校验：企微的流式消息**不需要预先建模板**（与飞书一致、
        与钉钉不同），要求模板只会把钉钉的限制泄漏过来。``reply_to`` 同理只为与工厂
        契约一致而保留 —— Worker 对所有渠道用同一组关键字调用，少一个参数就抛
        ``TypeError``，而那是**整条消息失败**而不是降级成文本。
        """
        del template_id, reply_to  # 见 docstring：两者对企微都不适用。
        if self.channel is None:
            return None
        req_id = _clean(payload.get("reply_target"))
        if not req_id:
            return None

        session = self._take_session(req_id)
        if session is not None:
            # Provider 已在收到回调时抢建了占位流（_prestart_stream），直接交给
            # Worker 接管；它对 session.open() 的调用会因已开流而空操作。
            return session

        # 预热没成功（卡片总开关刚打开、或预热那一下连接抖动）：现场建一个，
        # 放弃 5 秒窗口的确定性，但至少让卡片路径仍然可用。
        return WecomCardSession(
            send_reply=self._send_reply,
            req_id=req_id,
            chat_id=_clean(payload.get("chat_id")),
            chat_type=_clean(payload.get("chat_type")),
            policy=policy,
        )


class DeliveryReceipt:
    """出站回执；字段名刻意与 Worker 的容错提取逻辑对齐。"""

    __slots__ = ("message_id", "raw")

    def __init__(self, *, message_id: str, raw: dict[str, Any] | None = None):
        self.message_id = message_id
        self.raw = raw or {}
