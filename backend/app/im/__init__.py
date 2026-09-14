"""协议无关的即时消息接入内核。"""

from .context import ActorContext
from .contracts import DeliveryResult, NormalizedInbound, OutboundMessage
from .execution import collect_text, run_agent_events

__all__ = [
    "ActorContext", "DeliveryResult", "NormalizedInbound", "OutboundMessage",
    "collect_text", "run_agent_events",
]
