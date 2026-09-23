"""企业微信智能机器人的流式回复会话（长连接）。

协议依据（企业微信开发者中心《回复消息》，以及官方 SDK
``@wecom/aibot-node-sdk`` 1.0.7 的 ``src/types/api.ts`` / ``src/ws.ts``）：

- 回复与更新走**同一条长连接**，且必须透传入站回调携带的 ``req_id``；
- 流式消息用同一个 ``stream.id`` 反复推送，``content`` 是**全量**内容（不是增量），
  客户端据此整段替换该气泡；
- ``stream.content`` 上限 **20480 字节**（UTF-8），支持 Markdown；
- ``finish=true`` 后该消息锁定不可再更新；从首次推送起 10 分钟内必须结束。

与飞书/钉钉最大的不同：**没有"建卡"这一步**。飞书要先在卡片实体接口建号，钉钉要先
``createAndDeliver`` 拿 ``outTrackId``；企微的流式消息是**首次推送时由 ``stream.id``
隐式创建**的。所以 Provider 可以在收到回调的同一步就把占位内容推出去（抢 5 秒硬
窗口），Worker 随后拿到的是同一个会话对象 —— ``open()`` 检测到已开流后直接返回，
不会重复建流。这是 ``cards/__init__.py`` 里三档节流策略之外，企微特有的时序安排。
"""

from __future__ import annotations

import logging
import time
import uuid
from collections.abc import Awaitable, Callable
from typing import Any

from app.im.cards import TRUNCATED_SUFFIX, ThrottlePolicy, merge_streaming_text

logger = logging.getLogger("app.im.wecom.card")

# 流式正文的**字节**上限（官方文档：最长不超过 20480 字节，UTF-8 编码）。
#
# 这个常量刻意留在企微自己的模块里，而不是塞进 ``cards/__init__.py``：那里的
# ``MAX_CARD_CONTENT_CHARS`` 是钉钉的**字符**上限，两边量纲不同（字节 vs 字符），
# 共享会让一个渠道的限制泄漏给所有渠道 —— ``cards/__init__.py`` 的注释已经明确
# 反对过这件事（"钉钉的限制泄漏给飞书"是踩过的坑）。
WECOM_MAX_STREAM_BYTES = 20480

# 一帧回复的发送函数，由 Provider 注入：``await send_reply(req_id, body)``。
# 语义是「在长连接上发一帧并等到服务端回执」，失败抛异常。
SendReply = Callable[[str, dict[str, Any]], Awaitable[Any]]


class WecomCardError(RuntimeError):
    """企微流式回复链路错误；``status_code`` 供调用方判断是否值得重试或降级。"""

    def __init__(
        self,
        message: str,
        *,
        status_code: int | None = None,
        error_code: str | None = None,
    ):
        super().__init__(message)
        self.status_code = status_code
        self.error_code = error_code


def clamp_stream_bytes(
    text: str,
    *,
    limit: int = WECOM_MAX_STREAM_BYTES,
    with_notice: bool = True,
) -> tuple[str, bool]:
    """把正文裁到企微能承载的**字节**数；返回 ``(正文, 是否被截断)``。

    被截断时调用方应把完整内容改用主动推送补发 —— 流式气泡塞不下，但结果不能丢
    （``worker.py`` 的最终投递分支天然支持，判定权在这里）。

    ``with_notice=False`` 供执行中的中间推送使用：那时还没有"补发"这回事，
    提前显示补发提示会让人以为已经被截断了。

    按字节裁要小心 UTF-8 的多字节序列：直接 ``raw[:limit]`` 可能把一个汉字劈成
    半个，用 ``errors="ignore"`` 解码会安静地丢掉那个残码点 —— 这正是我们要的
    （宁可少一个字，也不要送出非法 UTF-8 被服务端拒帧）。
    """
    raw = text.encode("utf-8")
    if len(raw) <= limit:
        return text, False

    suffix = TRUNCATED_SUFFIX if with_notice else ""
    budget = max(limit - len(suffix.encode("utf-8")), 0)
    head = raw[:budget].decode("utf-8", errors="ignore")
    return head + suffix, True


def _new_stream_id() -> str:
    """流式消息 ID；格式与官方 SDK 的 ``generateReqId('stream')`` 对齐。"""
    return f"stream_{int(time.time() * 1000)}_{uuid.uuid4().hex[:8]}"


class WecomCardSession:
    """一条流式消息从开流到锁定的完整生命周期。

    ``push`` 是尽力而为的旁路（失败只记日志，收尾那次会把全量内容再推一遍），
    ``open`` / ``finalize`` 的失败必须让调用方知道 —— 用户拿不到结果时要能降级。
    """

    def __init__(
        self,
        *,
        send_reply: SendReply,
        req_id: str,
        chat_id: str,
        chat_type: str,
        policy: ThrottlePolicy,
        stream_id: str | None = None,
    ):
        self._send_reply = send_reply
        # 本次回调的回复凭据；同一会话的所有帧都用它。
        self.req_id = req_id
        # 群聊是 chatid，单聊是发送者 userid（由 normalize_message 归一）。
        self.chat_id = chat_id
        self.chat_type = chat_type
        self._policy = policy
        # Worker 用它登记卡片会话（jobs.create_card_session 的 out_track_id）；
        # 企微侧它就是 stream.id。
        self.out_track_id = stream_id or _new_stream_id()

        self.opened = False
        self.finalized = False
        # 已发出的中间更新次数（不含开流），用于观测与配额核账。
        self.update_count = 0
        self._last_text = ""
        self._last_push_at = 0.0

    async def open(self, initial_text: str) -> None:
        """开流。Provider 已抢先推出占位内容时这是空操作（幂等）。

        幂等是必需的：Provider 为了抢 5 秒窗口会先开流，Worker 拿到同一个会话后
        仍会按统一流程调 ``open(WORKING_TEXT)`` —— 重复开流会多出一条气泡。
        """
        if self.opened or self.finalized:
            return
        await self._emit(initial_text, finish=False)
        self.opened = True
        self._last_text = initial_text
        self._last_push_at = time.monotonic()

    async def prestart(self, text: str) -> None:
        """Provider 在收到回调的**同一步**内调用，用于抢 5 秒首回复窗口。

        与 ``open`` 同义，单独命名是为了让调用点的意图可读（见模块头与规划
        §3 差异 2）。
        """
        await self.open(text)

    def _should_push(self, text: str) -> bool:
        policy = self._policy
        limit = policy.max_updates
        if limit == 0:
            # 0 = 明确不做中间更新（两态档），只开流与收尾各一次。
            return False
        if limit is not None and self.update_count >= limit:
            # None = 不限次数；此时速率完全由 min_interval_seconds 兜住。
            return False
        if len(text) - len(self._last_text) < policy.min_delta_chars:
            return False
        return (time.monotonic() - self._last_push_at) >= policy.min_interval_seconds

    async def push(self, text: str) -> None:
        """按节流策略推送全量内容；异常只记日志，绝不打断员工执行。"""
        if not self.opened or self.finalized or not self._should_push(text):
            return
        merged = merge_streaming_text(self._last_text, text)
        try:
            # 中间推送不带「结果另发」提示：执行中还没有补发这回事。
            await self._emit(merged, finish=False, notice=False)
        except Exception as exc:
            logger.warning(
                "企业微信流式更新失败 stream=%s error=%s", self.out_track_id, exc
            )
            return
        self.update_count += 1
        self._last_text = merged
        self._last_push_at = time.monotonic()

    async def finalize(self, text: str) -> bool:
        """收尾：写入最终结果并锁定气泡；返回**内容是否被截断**。

        返回值决定 Worker 要不要再补发一次（企微走主动推送），所以它必须如实反映
        气泡里到底有没有被裁。失败则抛出去 —— 调用方要据此改用文本补发，
        不能静默丢结果。
        """
        if not self.opened:
            raise WecomCardError("流式消息尚未开始，无法收尾", status_code=500)
        _, truncated = clamp_stream_bytes(text)
        await self._emit(text, finish=True)
        self.finalized = True
        return truncated

    async def fail(self, text: str) -> None:
        """把气泡收成失败态；失败本身不再向上抛。"""
        if not self.opened or self.finalized:
            return
        try:
            await self._emit(text, finish=True, notice=False)
        except Exception as exc:
            logger.warning(
                "企业微信失败态更新失败 stream=%s error=%s", self.out_track_id, exc
            )
        finally:
            self.finalized = True

    async def _emit(self, text: str, *, finish: bool, notice: bool = True) -> None:
        content, _ = clamp_stream_bytes(text, with_notice=notice)
        body: dict[str, Any] = {
            "msgtype": "stream",
            "stream": {
                # 同一个 id 反复推送即为"原地更新"；首次推送隐式创建该消息。
                "id": self.out_track_id,
                "finish": finish,
                "content": content,
            },
        }
        await self._send_reply(self.req_id, body)
