"""Inbox -> 员工执行 -> Outbox 的一次性 Worker 原语。"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import random
from datetime import datetime, timedelta, timezone
from typing import Any

from app import conversations
from app.im.cards import (
    WORKING_TEXT,
    card_enabled,
    card_factory,
    card_level,
    card_template_id,
    policy_for,
)
from app.im.context import ActorContext
from app.im.contracts import OutboundMessage
from app.im import jobs
from app.im.execution import collect_text, run_agent_events

logger = logging.getLogger("app.im.worker")


def retry_delay_seconds(
    attempt: int,
    *,
    base: float = 2.0,
    cap: float = 300.0,
    jitter_ratio: float = 0.2,
    random_value: float | None = None,
) -> float:
    """指数退避并加入有界抖动；attempt 从 1 开始。"""
    raw = min(cap, base * (2 ** max(0, attempt - 1)))
    sample = random.random() if random_value is None else random_value
    factor = 1 + jitter_ratio * (2 * sample - 1)
    return max(0.0, raw * factor)


def _status_code(exc: Exception) -> int | None:
    for value in (
        getattr(exc, "status_code", None),
        getattr(getattr(exc, "response", None), "status_code", None),
    ):
        if isinstance(value, int):
            return value
    return None


def _is_retryable_delivery_error(exc: Exception) -> bool:
    status = _status_code(exc)
    if status is None:
        return True
    return status in {408, 409, 425, 429} or status >= 500


def _context(row: dict[str, Any]) -> ActorContext:
    payload = row["payload"]
    return ActorContext.isolated(
        provider=payload.get("provider") or "feishu",
        app_id=payload["app_id"], tenant_key=payload["tenant_key"],
        sender_open_id=payload["sender_open_id"], chat_id=payload["chat_id"],
        chat_type=payload["chat_type"],
    )


def _delivery_message_id(result: Any) -> str:
    """不同 Provider 的回执形状不同，这里做统一的容错提取。"""
    for candidate in (
        getattr(result, "message_id", None),
        getattr(result, "provider_message_id", None),
    ):
        if isinstance(candidate, str) and candidate:
            return candidate
    payload = getattr(result, "data", None)
    if not isinstance(payload, dict):
        # 有的 Provider 直接返回 dict 回执。
        payload = result if isinstance(result, dict) else {}
    for key in ("message_id", "processQueryKey", "messageId", "id"):
        candidate = payload.get(key)
        if candidate:
            return str(candidate)
    return ""


# 员工执行通常要数十秒，期间用户端没有任何动静。这里在执行前先回一条提示。
# 注意：钉钉的 60 秒 ack 是连接层握手，用户看不见，替代不了这个反馈。
PROGRESS_NOTICE_TEXT = "已收到，正在处理，请稍候…"


def _progress_notice_enabled() -> bool:
    """执行前提示默认开启；显式设为 0/false/no/off 可关闭。"""
    raw = os.environ.get("IM_PROGRESS_NOTICE", "").strip().lower()
    return raw not in {"0", "false", "no", "off"}


async def _send_progress_notice(
    provider: Any, *, row: dict[str, Any], channel_id: str
) -> None:
    """尽力而为地告知用户"已收到"。

    提示发不出去不能影响正式回复，因此这里不写 Outbox、不向上抛异常。
    走 provider.send 而不是入队，是因为 Outbox 由投递协程异步消费，
    无法保证它排在员工执行之前发出。
    """
    payload = row["payload"]
    try:
        await provider.send(
            OutboundMessage(
                channel_id=channel_id,
                # 与正式回复同用入站携带的回复目标：飞书是 chat_id，钉钉是临时 sessionWebhook。
                receive_id=payload.get("reply_target") or payload["chat_id"],
                receive_id_type=payload.get("reply_target_type") or "chat_id",
                reply_to_message_id=row["provider_message_id"],
                text=PROGRESS_NOTICE_TEXT,
            )
        )
    except Exception as exc:
        logger.warning(
            "IM progress notice failed inbox=%s error=%s", row["id"], exc
        )


async def _open_card_session(provider: Any, *, row: dict[str, Any]) -> Any | None:
    """尝试投放一张 AI 卡片；不可用或投放失败返回 ``None``。

    返回 ``None`` 表示「这条消息走文本回复」，不是错误 —— 配置缺失、渠道不支持、
    连接未就绪、模板无权限都会走到这里，全部退化成改动前的行为。
    """
    if not card_enabled():
        return None
    factory = card_factory(provider)
    if factory is None:
        return None
    session = factory(
        payload=row["payload"],
        template_id=card_template_id(),
        policy=policy_for(card_level()),
        reply_to=row["provider_message_id"],
    )
    if session is None:
        return None
    try:
        await session.open(WORKING_TEXT)
    except Exception as exc:
        logger.warning("IM card open failed inbox=%s error=%s", row["id"], exc)
        return None
    jobs.create_card_session(
        inbox_id=row["id"],
        channel_id=row["channel_id"],
        out_track_id=session.out_track_id,
        template_id=card_template_id(),
        level=card_level(),
    )
    return session


# 等待态只对「刚到达」的消息有意义。给一条很旧的消息加表情回应，用户会看到
# 一个不知从哪冒出来的 Typing 挂在历史消息下面（OpenClaw 踩过的坑）。
TYPING_MAX_MESSAGE_AGE_SECONDS = 120.0


def _typing_is_worth_adding(row: dict[str, Any]) -> bool:
    raw = row.get("created_at")
    if not raw:
        return True
    try:
        created = datetime.fromisoformat(str(raw))
    except ValueError:
        return True
    if created.tzinfo is None:
        created = created.replace(tzinfo=timezone.utc)
    age = (datetime.now(timezone.utc) - created).total_seconds()
    return age <= TYPING_MAX_MESSAGE_AGE_SECONDS


async def _start_typing(provider: Any, *, row: dict[str, Any]) -> Any | None:
    """按能力请求等待态信号；渠道不支持或失败时返回 ``None``。

    用能力检测而不是 ``isinstance``，与卡片工厂同样的理由：Worker 不该反向
    依赖具体 Provider，新增支持等待态的渠道也不必改这里。
    """
    starter = getattr(provider, "start_typing", None)
    if not callable(starter) or not _typing_is_worth_adding(row):
        return None
    try:
        return await starter(message_id=row["provider_message_id"])
    except Exception as exc:
        logger.debug("IM typing indicator start failed inbox=%s error=%s", row["id"], exc)
        return None


async def _stop_typing(provider: Any, handle: Any | None) -> None:
    """移除等待态。必须无条件执行：表情回应是持久的，留着会一直挂在消息下面。"""
    if handle is None:
        return
    stopper = getattr(provider, "stop_typing", None)
    if not callable(stopper):
        return
    try:
        await stopper(handle)
    except Exception as exc:
        logger.warning("IM typing indicator stop failed error=%s", exc)


async def _abandon_card(session: Any | None, *, inbox_id: str, text: str) -> None:
    """执行失败时把卡片标成失败态，避免它一直停在「输入中」。"""
    if session is None:
        return
    await session.fail(text)
    jobs.finish_card_session(
        inbox_id, status="abandoned", update_count=session.update_count
    )


async def process_inbox_once(*, provider: Any, channel_id: str, employee_id: str,
                             worker_id: str = "im-worker", lease_seconds: int = 120) -> bool:
    """消费一条 Inbox；无任务返回 False，成功处理返回 True。"""
    row = jobs.claim_inbox(
        worker_id, lease_seconds=lease_seconds, channel_id=channel_id
    )
    if not row:
        return False
    inbox_id = row["id"]
    typing: Any | None = None
    try:
        # 等待态先于一切：它是最早可见的信号，也是对既有消息的操作，
        # 所以不像「发一条已收到」那样会留下一条永不消失的消息。
        typing = await _start_typing(provider, row=row)
        context = _context(row)
        thread, created = jobs.get_or_create_thread(
            context, channel_id=channel_id, employee_id=employee_id,
        )
        conv_id = thread["conv_id"]
        if created:
            conversations.create(
                conv_id, employee_id, user_id=context.subject_id,
                channel_id=channel_id, title=row["payload"].get("text", "")[:40],
            )
        payload = row["payload"]
        # 卡片优先：投放成功后，用户侧只会看到这一条消息在演进。
        session = await _open_card_session(provider, row=row)
        if session is None and _progress_notice_enabled():
            # 没有卡片时才发独立提示：钉钉的 60 秒 ack 是连接层握手，用户看不见。
            await _send_progress_notice(provider, row=row, channel_id=channel_id)

        async def on_delta(current: str) -> None:
            # 每个 token 都会被调用；是否真的推送由卡片会话的节流策略决定。
            if session is not None:
                await session.push(current)

        try:
            text, terminal = await collect_text(
                run_agent_events(
                    conv_id,
                    {"messages": [{"role": "user", "content": payload.get("text", "")}]},
                    context=context,
                ),
                on_delta=on_delta,
            )
        except Exception:
            await _abandon_card(session, inbox_id=inbox_id, text="处理失败，请稍后重试。")
            raise

        terminal_type = terminal.get("type") if terminal else None
        if terminal_type == "error":
            await _abandon_card(session, inbox_id=inbox_id, text="处理失败，请稍后重试。")
            raise RuntimeError(
                terminal.get("message") or terminal.get("error_code") or "employee execution failed"
            )
        if terminal_type == "approval_required":
            text = "该请求需要在 UniEmployee 平台完成审批。"
        if not text.strip():
            text = "员工未返回文本结果。"

        # 收尾：结果优先由卡片承载。但卡片只是体验优化，不是结果的唯一通道 ——
        # 收尾失败、内容超长时都要补一条文本消息，不能让用户什么都收不到。
        card_status = ""
        delivered_by_card = False
        if session is not None:
            # 截断与否由会话自己判断：各渠道的容量上限不一样（钉钉 3000 字符，
            # 飞书不截断），把这条判定留在 Worker 里就会变成「钉钉的限制泄漏给飞书」。
            try:
                truncated = await session.finalize(text)
            except Exception as exc:
                logger.warning("IM card finalize failed inbox=%s error=%s", inbox_id, exc)
                card_status = "finalize_failed"
            else:
                delivered_by_card = not truncated
                card_status = "truncated" if truncated else "completed"

        if not delivered_by_card:
            jobs.create_outbox(inbox_id, OutboundMessage(
                channel_id=channel_id,
                # 回复目标由入站消息携带：飞书是 chat_id，钉钉是临时 sessionWebhook。
                receive_id=payload.get("reply_target") or context.chat_id,
                receive_id_type=payload.get("reply_target_type") or "chat_id",
                reply_to_message_id=row["provider_message_id"],
                text=text,
            ))
        if session is not None:
            jobs.finish_card_session(
                inbox_id,
                status=card_status or "fallback",
                update_count=session.update_count,
            )
        jobs.finish_inbox(inbox_id, worker_id)
        return True
    except Exception as exc:
        logger.exception("IM inbox processing failed inbox=%s", inbox_id)
        jobs.finish_inbox(inbox_id, worker_id, error=f"{type(exc).__name__}: {exc}"[:500])
        return False
    finally:
        # 无论成功、失败还是提前返回，等待态都必须撤掉。
        await _stop_typing(provider, typing)


async def deliver_outbox_once(*, provider: Any, worker_id: str = "im-delivery",
                              lease_seconds: int = 120) -> bool:
    channel_id = getattr(provider, "credential", None)
    channel_id = getattr(channel_id, "channel_id", None)
    row = jobs.claim_outbox(
        worker_id, lease_seconds=lease_seconds, channel_id=channel_id
    )
    if not row:
        return False
    try:
        result = await provider.send(OutboundMessage(
            channel_id=row["channel_id"], receive_id=row["receive_id"],
            receive_id_type=row["receive_id_type"], text=row["content"],
            reply_to_message_id=row.get("reply_to_message_id"),
        ))
        message_id = _delivery_message_id(result)
        if not message_id:
            raise RuntimeError("投递通道未返回消息 ID")
        jobs.finish_outbox(row["id"], worker_id, provider_message_id=message_id)
        return True
    except Exception as exc:
        logger.exception("IM outbox delivery failed outbox=%s", row["id"])
        max_attempts = max(1, int(os.environ.get("IM_OUTBOX_MAX_ATTEMPTS", "5")))
        retryable = _is_retryable_delivery_error(exc)
        retry_at = None
        if retryable and row["attempts"] < max_attempts:
            base = max(0.1, float(os.environ.get("IM_OUTBOX_RETRY_BASE_SECONDS", "2")))
            cap = max(base, float(os.environ.get("IM_OUTBOX_RETRY_MAX_SECONDS", "300")))
            delay = retry_delay_seconds(row["attempts"], base=base, cap=cap)
            retry_at = datetime.now(timezone.utc) + timedelta(seconds=delay)
        jobs.retry_outbox(
            row["id"],
            worker_id,
            error=f"{type(exc).__name__}: {exc}"[:500],
            retry_at=retry_at,
        )
        return False
