"""Inbox -> 员工执行 -> Outbox 的一次性 Worker 原语。"""

from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime, timezone
from typing import Any

from app import conversations
from app.im.context import ActorContext
from app.im.contracts import OutboundMessage
from app.im import jobs
from app.im.execution import collect_text, run_agent_events

logger = logging.getLogger("app.im.worker")


def _context(row: dict[str, Any]) -> ActorContext:
    payload = row["payload"]
    return ActorContext.isolated_feishu(
        app_id=payload["app_id"], tenant_key=payload["tenant_key"],
        sender_open_id=payload["sender_open_id"], chat_id=payload["chat_id"],
        chat_type=payload["chat_type"],
    )


async def process_inbox_once(*, provider: Any, channel_id: str, employee_id: str,
                             worker_id: str = "im-worker", lease_seconds: int = 120) -> bool:
    """消费一条 Inbox；无任务返回 False，成功处理返回 True。"""
    row = jobs.claim_inbox(worker_id, lease_seconds=lease_seconds)
    if not row:
        return False
    inbox_id = row["id"]
    try:
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
        text, terminal = await collect_text(run_agent_events(
            conv_id, {"messages": [{"role": "user", "content": row["payload"].get("text", "")}]},
            context=context,
        ))
        if terminal and terminal.get("type") == "error":
            raise RuntimeError(terminal.get("message") or terminal.get("error_code") or "employee execution failed")
        if terminal and terminal.get("type") == "approval_required":
            text = "该请求需要在 UniEmployee 平台完成审批。"
        if not text.strip():
            text = "员工未返回文本结果。"
        jobs.create_outbox(inbox_id, OutboundMessage(
            channel_id=channel_id, receive_id=context.chat_id,
            receive_id_type="chat_id", reply_to_message_id=row["provider_message_id"],
            text=text,
        ))
        jobs.finish_inbox(inbox_id, worker_id)
        return True
    except Exception as exc:
        logger.exception("IM inbox processing failed inbox=%s", inbox_id)
        jobs.finish_inbox(inbox_id, worker_id, error=f"{type(exc).__name__}: {exc}"[:500])
        return False


async def deliver_outbox_once(*, provider: Any, worker_id: str = "im-delivery",
                              lease_seconds: int = 120) -> bool:
    row = jobs.claim_outbox(worker_id, lease_seconds=lease_seconds)
    if not row:
        return False
    try:
        result = await provider.send(OutboundMessage(
            channel_id=row["channel_id"], receive_id=row["receive_id"],
            receive_id_type=row["receive_id_type"], text=row["content"],
            reply_to_message_id=row.get("reply_to_message_id"),
        ))
        message_id = getattr(result, "message_id", None) or getattr(result, "data", {}).get("message_id", "")
        if not message_id:
            raise RuntimeError("飞书未返回消息 ID")
        jobs.finish_outbox(row["id"], worker_id, provider_message_id=message_id)
        return True
    except Exception as exc:
        logger.exception("IM outbox delivery failed outbox=%s", row["id"])
        jobs.retry_outbox(row["id"], worker_id, error=f"{type(exc).__name__}: {exc}"[:500],
                          retry_at=datetime.now(timezone.utc))
        return False

