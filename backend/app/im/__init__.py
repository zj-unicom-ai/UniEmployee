"""协议无关的即时消息接入内核。"""

from .context import ActorContext
from .contracts import DeliveryResult, NormalizedInbound, OutboundMessage
from .execution import collect_text, run_agent_events
from .worker import deliver_outbox_once, process_inbox_once

__all__ = [
    "ActorContext", "DeliveryResult", "NormalizedInbound", "OutboundMessage",
    "collect_text", "run_agent_events",
    "process_inbox_once", "deliver_outbox_once",
]
