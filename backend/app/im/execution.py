"""IM 与 Web 共用的员工执行边界。

Transport/Provider 不应了解 LangGraph 或 SSE。该模块把现有 Web 执行器
适配为结构化事件流，供飞书 Worker 及其他 IM Provider 复用。
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from typing import Any

from app.im.context import ActorContext


def _event_from_sse(raw: str) -> dict[str, Any] | None:
    """将历史 SSE 行转换为内部事件；兼容 keep-alive/空行。"""
    if not isinstance(raw, str) or not raw.startswith("data:"):
        return None
    try:
        value = json.loads(raw[5:].strip())
    except (TypeError, ValueError):
        return None
    return value if isinstance(value, dict) else None


async def run_agent_events(
    conv_id: str,
    input_: dict[str, Any],
    *,
    context: ActorContext,
    datasource_id: str = "",
    data_source: str = "",
    model_override: str = "",
) -> AsyncIterator[dict[str, Any]]:
    """以统一身份上下文执行员工并输出结构化事件。

    ``subject_id`` 仅用于会话/记忆归属；首版外部身份没有平台授权用户，
    因此 ``authorization_user_id`` 不会被伪造为飞书 open_id。
    """
    # 延迟导入避免 streaming -> im 的循环依赖。
    from app.streaming import _stream_run

    # Web 用户沿用现有 user_id；外部 IM 使用稳定 subject_id，确保记忆隔离。
    execution_user = context.authorization_user_id or context.subject_id
    async for raw in _stream_run(
        conv_id,
        input_,
        user_id=execution_user,
        role="user",
        datasource_id=datasource_id,
        data_source=data_source,
        model_override=model_override,
    ):
        event = _event_from_sse(raw)
        if event is not None:
            yield event


async def collect_text(events: AsyncIterator[dict[str, Any]]) -> tuple[str, dict[str, Any] | None]:
    """收集文本回复，同时返回最后一个终态事件（便于非流式 IM 回复）。"""
    chunks: list[str] = []
    terminal: dict[str, Any] | None = None
    async for event in events:
        if event.get("type") == "token":
            chunks.append(str(event.get("content") or ""))
        if event.get("type") in {"message_end", "error", "approval_required"}:
            terminal = event
    return "".join(chunks), terminal

