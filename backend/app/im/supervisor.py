"""IM Provider 与 Inbox/Outbox Worker 的生命周期管理（协议无关）。"""

from __future__ import annotations

import asyncio
import logging
import os
from collections.abc import Callable
from typing import Any

from app.im import jobs
from app.im.credentials import ChannelCredential
from app.im.providers.feishu import FeishuProvider
from app.im.worker import deliver_outbox_once, process_inbox_once

logger = logging.getLogger("app.im.supervisor")


class ImSupervisor:
    def __init__(
        self,
        *,
        provider: Any,
        channel_id: str,
        employee_id: str,
        on_inbound: Callable[[], None] | None = None,
        on_outbound: Callable[[], None] | None = None,
    ):
        self.provider = provider
        self.channel_id = channel_id
        self.employee_id = employee_id
        self.on_inbound = on_inbound
        self.on_outbound = on_outbound
        self._stop = asyncio.Event()
        self._tasks: list[asyncio.Task] = []

    async def _on_message(self, message) -> None:
        jobs.enqueue_inbound(message)
        if self.on_inbound is not None:
            self.on_inbound()

    async def _inbox_loop(self) -> None:
        while not self._stop.is_set():
            await process_inbox_once(
                provider=self.provider, channel_id=self.channel_id,
                employee_id=self.employee_id,
            )
            await asyncio.sleep(0.05)

    async def _outbox_loop(self) -> None:
        while not self._stop.is_set():
            delivered = await deliver_outbox_once(provider=self.provider)
            if delivered and self.on_outbound is not None:
                self.on_outbound()
            await asyncio.sleep(0.05)

    async def start(self) -> None:
        await self.provider.connect()
        self._tasks = [asyncio.create_task(self._inbox_loop(), name="im-inbox"),
                       asyncio.create_task(self._outbox_loop(), name="im-outbox")]
        logger.info("IM supervisor started channel=%s employee=%s", self.channel_id, self.employee_id)

    async def stop(self) -> None:
        self._stop.set()
        for task in self._tasks:
            task.cancel()
        await asyncio.gather(*self._tasks, return_exceptions=True)
        await self.provider.disconnect()
        self._tasks.clear()
        logger.info("IM supervisor stopped channel=%s", self.channel_id)


def from_environment(*, on_message=None) -> ImSupervisor | None:
    """从环境变量构造 Supervisor；未显式启用时绝不连接飞书。"""
    if os.environ.get("FEISHU_ENABLED", "0").strip() != "1":
        return None
    required = ("FEISHU_APP_ID", "FEISHU_APP_SECRET", "FEISHU_CHANNEL_ID", "FEISHU_EMPLOYEE_ID")
    missing = [name for name in required if not os.environ.get(name, "").strip()]
    if missing:
        raise RuntimeError("FEISHU_ENABLED=1 但缺少配置: " + ", ".join(missing))
    channel_id = os.environ["FEISHU_CHANNEL_ID"]
    credential = ChannelCredential(
        channel_id=channel_id, app_id=os.environ["FEISHU_APP_ID"],
        tenant_key=os.environ.get("FEISHU_TENANT_KEY", ""),
        app_secret=os.environ["FEISHU_APP_SECRET"],
    )
    callback = on_message
    if callback is None:
        # 由 Supervisor 自己负责入队；这里使用占位，构造后替换。
        callback = lambda message: None
    supervisor = ImSupervisor(
        provider=FeishuProvider(credential, on_message=callback),
        channel_id=channel_id, employee_id=os.environ["FEISHU_EMPLOYEE_ID"],
    )
    if on_message is None:
        supervisor.provider.on_message = supervisor._on_message
    return supervisor
