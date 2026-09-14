"""协议无关的即时消息接入内核。"""

from .context import ActorContext
from .contracts import DeliveryResult, NormalizedInbound, OutboundMessage

__all__ = ["ActorContext", "DeliveryResult", "NormalizedInbound", "OutboundMessage"]
