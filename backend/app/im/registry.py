"""数据库驱动的 IM Supervisor 注册表与运行状态。"""

from __future__ import annotations

import asyncio
import logging
import os
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from app import conversations
from app.im import jobs
from app.im.credentials import ChannelCredential
from app.im.providers import (
    create_provider,
    credential_label,
    provider_label,
    supported_providers,
)
from app.im.supervisor import ImSupervisor

logger = logging.getLogger("app.im.registry")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


def _safe_error(exc: BaseException | str) -> str:
    text = str(exc).replace("\r", " ").replace("\n", " ")
    text = re.sub(r"(?:wss?|https?)://\S+", "<redacted-url>", text)
    return text[:500]


@dataclass(frozen=True, slots=True)
class ChannelSpec:
    channel_id: str
    provider: str
    employee_id: str
    credential: ChannelCredential
    fingerprint: tuple[str, ...]


@dataclass(slots=True)
class RuntimeEntry:
    spec: ChannelSpec
    stop_event: asyncio.Event = field(default_factory=asyncio.Event)
    task: asyncio.Task | None = None
    supervisor: ImSupervisor | None = None


class SupervisorRegistry:
    """按频道独立启停长连接；单频道失败不影响应用和其他频道。"""

    def __init__(self) -> None:
        self._entries: dict[str, RuntimeEntry] = {}
        self._states: dict[str, dict[str, Any]] = {}
        self._lock = asyncio.Lock()
        self._running = False

    def _set_state(self, channel_id: str, status: str, **changes: Any) -> None:
        state = self._states.setdefault(
            channel_id,
            {
                "channel_id": channel_id,
                "status": "disabled",
                "last_error": None,
                "last_connected_at": None,
                "last_inbound_at": None,
                "last_outbound_at": None,
                "reconnect_count": 0,
            },
        )
        state["status"] = status
        state.update(changes)
        state["updated_at"] = _now()

    def status(self, channel_id: str) -> dict[str, Any]:
        state = self._states.get(channel_id)
        if state is None:
            return {
                "channel_id": channel_id,
                "status": "disabled",
                "last_error": None,
                "last_connected_at": None,
                "last_inbound_at": None,
                "last_outbound_at": None,
                "reconnect_count": 0,
                "updated_at": None,
            }
        return dict(state)

    def _legacy_credential(self, channel_id: str) -> ChannelCredential | None:
        if os.environ.get("FEISHU_ENABLED", "0").strip() != "1":
            return None
        if os.environ.get("FEISHU_CHANNEL_ID", "").strip() != channel_id:
            return None
        app_id = os.environ.get("FEISHU_APP_ID", "").strip()
        app_secret = os.environ.get("FEISHU_APP_SECRET", "").strip()
        if not app_id or not app_secret:
            return None
        return ChannelCredential(
            channel_id=channel_id,
            app_id=app_id,
            app_secret=app_secret,
            tenant_key=os.environ.get("FEISHU_TENANT_KEY", "").strip(),
        )

    def _spec_for(self, channel: dict[str, Any]) -> ChannelSpec | None:
        channel_id = channel["id"]
        provider = str(channel.get("provider") or "").strip() or "web"
        label = provider_label(provider)
        if not channel.get("enabled", True):
            self._set_state(channel_id, "disabled", last_error=None)
            return None

        employee_ids = conversations.list_employee_ids_for_channel(channel_id)
        legacy_employee = ""
        # 只有飞书保留了环境变量过渡配置；新渠道一律以数据库为唯一事实来源。
        if provider == "feishu" and os.environ.get("FEISHU_CHANNEL_ID", "").strip() == channel_id:
            legacy_employee = os.environ.get("FEISHU_EMPLOYEE_ID", "").strip()
        if not employee_ids and legacy_employee:
            employee_ids = [legacy_employee]
        if len(employee_ids) != 1:
            self._set_state(
                channel_id,
                "unconfigured",
                last_error=f"{label}频道必须且只能绑定一个默认数字员工",
            )
            return None

        try:
            credential = jobs.get_credential(channel_id)
        except Exception as exc:
            self._set_state(
                channel_id,
                "failed",
                last_error=f"凭证读取失败：{_safe_error(exc)}",
            )
            return None
        if credential is None and provider == "feishu":
            credential = self._legacy_credential(channel_id)
        if credential is None:
            self._set_state(
                channel_id,
                "unconfigured",
                last_error=f"尚未配置{label} {credential_label(provider)}",
            )
            return None

        summary = jobs.credential_summary(channel_id) or {}
        fingerprint = (
            str(channel.get("updated_at") or ""),
            employee_ids[0],
            credential.app_id,
            credential.tenant_key,
            str(summary.get("updated_at") or "legacy"),
        )
        return ChannelSpec(
            channel_id=channel_id,
            provider=provider,
            employee_id=employee_ids[0],
            credential=credential,
            fingerprint=fingerprint,
        )

    def _desired_specs(self) -> dict[str, ChannelSpec]:
        # 只有已登记 provider 的频道才建立长连接；web 与未实现渠道不进 Registry。
        runners = supported_providers()
        channels = {
            row["id"]: row
            for row in conversations.list_channels()
            if row.get("provider") in runners
        }
        legacy_id = os.environ.get("FEISHU_CHANNEL_ID", "").strip()
        if (
            legacy_id
            and os.environ.get("FEISHU_ENABLED", "0").strip() == "1"
            # 页面配置一旦存在，数据库就是唯一事实来源。不能再把旧环境变量
            # 追加成第二个频道，否则同一 App 会建立重复长连接并重复消费消息。
            and not channels
        ):
            channels[legacy_id] = {
                "id": legacy_id,
                "provider": "feishu",
                "enabled": True,
                "updated_at": "legacy",
            }

        desired: dict[str, ChannelSpec] = {}
        for channel in channels.values():
            spec = self._spec_for(channel)
            if spec is not None:
                desired[spec.channel_id] = spec
        return desired

    async def start(self) -> None:
        self._running = True
        try:
            await self.reconcile()
        except Exception:
            logger.exception("IM registry initial reconciliation failed")

    async def stop(self) -> None:
        self._running = False
        async with self._lock:
            entries = list(self._entries.values())
            self._entries.clear()
        for entry in entries:
            await self._stop_entry(entry)

    async def _stop_entry(self, entry: RuntimeEntry) -> None:
        entry.stop_event.set()
        if entry.task is not None and not entry.task.done():
            entry.task.cancel()
        if entry.task is not None:
            await asyncio.gather(entry.task, return_exceptions=True)

    async def reconcile(self, *, force_channel_id: str | None = None) -> None:
        if not self._running:
            return
        desired = self._desired_specs()
        async with self._lock:
            for channel_id, entry in list(self._entries.items()):
                target = desired.get(channel_id)
                should_restart = (
                    target is None
                    or target.fingerprint != entry.spec.fingerprint
                    or force_channel_id == channel_id
                )
                if should_restart:
                    self._entries.pop(channel_id, None)
                    await self._stop_entry(entry)
            for channel_id, spec in desired.items():
                if channel_id in self._entries:
                    continue
                entry = RuntimeEntry(spec=spec)
                self._entries[channel_id] = entry
                entry.task = asyncio.create_task(
                    self._run_channel(entry),
                    name=f"im-channel-{channel_id}",
                )

    async def reconnect(self, channel_id: str) -> dict[str, Any]:
        await self.reconcile(force_channel_id=channel_id)
        return self.status(channel_id)

    async def _run_channel(self, entry: RuntimeEntry) -> None:
        delay = 2.0
        while self._running and not entry.stop_event.is_set():
            spec = entry.spec
            current = self.status(spec.channel_id)
            status = "reconnecting" if current["reconnect_count"] else "connecting"
            self._set_state(spec.channel_id, status)

            def provider_status(value: str, error: str | None) -> None:
                changes: dict[str, Any] = {}
                if error:
                    changes["last_error"] = _safe_error(error)
                if value == "connected":
                    changes.update(last_connected_at=_now(), last_error=None)
                self._set_state(spec.channel_id, value, **changes)

            async def placeholder(message) -> None:
                return None

            provider = None
            supervisor = None
            started = False
            try:
                provider = create_provider(
                    spec.provider,
                    spec.credential,
                    on_message=placeholder,
                    on_status=provider_status,
                )
                supervisor = ImSupervisor(
                    provider=provider,
                    channel_id=spec.channel_id,
                    employee_id=spec.employee_id,
                    on_inbound=lambda: self._set_state(
                        spec.channel_id, "connected", last_inbound_at=_now()
                    ),
                    on_outbound=lambda: self._set_state(
                        spec.channel_id, "connected", last_outbound_at=_now()
                    ),
                )
                provider.on_message = supervisor._on_message
                entry.supervisor = supervisor
                await supervisor.start()
                started = True
                self._set_state(
                    spec.channel_id,
                    "connected",
                    last_connected_at=_now(),
                    last_error=None,
                )
                await entry.stop_event.wait()
                return
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                state = self.status(spec.channel_id)
                self._set_state(
                    spec.channel_id,
                    "failed",
                    last_error=_safe_error(exc),
                    reconnect_count=state["reconnect_count"] + 1,
                )
                logger.warning(
                    "IM channel failed channel=%s provider=%s error=%s",
                    spec.channel_id,
                    spec.provider,
                    _safe_error(exc),
                )
            finally:
                if supervisor is not None and (started or provider.channel is not None):
                    try:
                        await supervisor.stop()
                    except Exception:
                        logger.exception(
                            "IM channel shutdown failed channel=%s", spec.channel_id
                        )
                entry.supervisor = None

            if entry.stop_event.is_set() or not self._running:
                return
            try:
                await asyncio.wait_for(entry.stop_event.wait(), timeout=delay)
            except TimeoutError:
                pass
            delay = min(delay * 2, 60.0)


registry = SupervisorRegistry()
