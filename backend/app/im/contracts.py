"""Transport、Provider、Worker 之间共享的协议无关数据类型。"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Literal


ChatType = Literal["p2p", "group"]


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


@dataclass(frozen=True, slots=True)
class NormalizedInbound:
    provider: str
    channel_id: str
    app_id: str
    tenant_key: str
    event_id: str
    message_id: str
    chat_id: str
    chat_type: ChatType
    sender_open_id: str
    text: str
    root_id: str | None = None
    parent_id: str | None = None
    received_at: str = field(default_factory=utc_now)

    def __post_init__(self) -> None:
        required = (
            self.provider,
            self.channel_id,
            self.app_id,
            self.tenant_key,
            self.event_id,
            self.message_id,
            self.chat_id,
            self.sender_open_id,
        )
        if not all(required):
            raise ValueError("标准入站消息的标识字段不能为空")
        if self.chat_type not in {"p2p", "group"}:
            raise ValueError(f"不支持的 chat_type: {self.chat_type!r}")

    def persisted_payload(self) -> dict[str, Any]:
        """仅返回处理必需字段，不包含原始飞书事件。"""
        return {
            "provider": self.provider,
            "app_id": self.app_id,
            "tenant_key": self.tenant_key,
            "chat_id": self.chat_id,
            "chat_type": self.chat_type,
            "sender_open_id": self.sender_open_id,
            "text": self.text,
            "root_id": self.root_id,
            "parent_id": self.parent_id,
            "received_at": self.received_at,
        }


@dataclass(frozen=True, slots=True)
class OutboundMessage:
    channel_id: str
    receive_id: str
    receive_id_type: str
    text: str
    reply_to_message_id: str | None = None


@dataclass(frozen=True, slots=True)
class DeliveryResult:
    success: bool
    provider_message_id: str | None = None
    error_code: str | None = None
    error_detail: str | None = None
    retryable: bool = False
