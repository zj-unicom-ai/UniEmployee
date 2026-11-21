"""Native multi-platform IM gateway backed by Octop's MIT-licensed adapter package.

Octop's ``octop-gateway`` owns protocol-specific bot connections. This module
bridges its normalized messages to UniEmployee conversations and LangGraph runs.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import mimetypes
import os
import time
import uuid
from pathlib import Path
from typing import Any, AsyncIterator

from octop_gateway.channel import ChannelCredentialsError
from octop_gateway.manager import ChannelManager
from octop_gateway.media import FileSystemMediaBackend
from octop_gateway.models import (
    FileContent,
    InboundMessage,
    MessageEvent,
    MessageEventType,
)

from app import conversations, runtime
from app.attachments import (
    MAX_ATTACHMENT_SIZE,
    MAX_ATTACHMENTS_PER_MESSAGE,
    _sanitize_name,
    compose_user_content,
)
from app.paths import WORKSPACE_DATA
from app.streaming import _stream_run, conv_emp_map, conv_owner_map, conv_tenant_map

logger = logging.getLogger("app.im_gateway")

_NATIVE_KINDS = (
    "feishu", "dingtalk", "wecom", "qq", "weixin", "yuanbao",
    "telegram", "discord", "xiaoyi", "mqtt",
)

_PROVIDERS: list[dict[str, Any]] = [
    {
        "kind": "feishu", "name": "飞书 / Lark", "intro_url": "https://open.feishu.cn/app",
        "description": "飞书机器人私聊与群聊。请在开发者后台启用机器人和长连接事件接收。",
        "fields": [
            {"name": "app_id", "label": "App ID", "required": True, "placeholder": "cli_xxx"},
            {"name": "app_secret", "label": "App Secret", "type": "password", "required": True},
            {"name": "verification_token", "label": "Verification Token", "type": "password"},
            {"name": "encrypt_key", "label": "Encrypt Key", "type": "password"},
        ],
    },
    {
        "kind": "dingtalk", "name": "钉钉", "intro_url": "https://open-dev.dingtalk.com/",
        "description": "钉钉机器人 Stream 模式。",
        "fields": [
            {"name": "app_key", "label": "App Key / Client ID", "required": True},
            {"name": "app_secret", "label": "App Secret / Client Secret", "type": "password", "required": True},
            {"name": "robot_code", "label": "Robot Code"},
        ],
    },
    {
        "kind": "wecom", "name": "企业微信", "intro_url": "https://work.weixin.qq.com/wework_admin/frame#/aiHelper/create",
        "description": "企业微信智能机器人 WebSocket 长连接。",
        "fields": [
            {"name": "bot_id", "label": "Bot ID", "required": True},
            {"name": "secret", "label": "Bot Secret", "type": "password", "required": True},
            {"name": "ws_url", "label": "WebSocket URL"},
        ],
    },
    {
        "kind": "qq", "name": "QQ", "intro_url": "https://q.qq.com/qqbot/openclaw/",
        "description": "QQ 机器人私聊与群聊。",
        "fields": [
            {"name": "app_id", "label": "App ID", "required": True},
            {"name": "token", "label": "Bot Token", "type": "password", "required": True},
            {"name": "secret", "label": "App Secret", "type": "password", "required": True},
            {"name": "sandbox", "label": "使用沙箱环境", "type": "switch"},
        ],
    },
    {
        "kind": "weixin", "name": "微信", "intro_url": "https://ilinkai.weixin.qq.com/",
        "description": "微信 iLink 个人账号。填写账号配置 JSON；也可粘贴 Octop 微信扫码绑定得到的账号信息。",
        "fields": [
            {
                "name": "accounts", "label": "账号配置（JSON 数组）", "type": "json", "required": True,
                "placeholder": '[{"account_id":"账号ID","token":"令牌"}]',
            },
        ],
    },
    {
        "kind": "yuanbao", "name": "腾讯元宝", "intro_url": "https://yuanbao.tencent.com/bot",
        "description": "腾讯元宝机器人 WebSocket 通道。",
        "fields": [
            {"name": "app_key", "label": "App Key", "required": True},
            {"name": "app_secret", "label": "App Secret", "type": "password", "required": True},
            {"name": "api_domain", "label": "API Domain"},
            {"name": "ws_url", "label": "WebSocket URL"},
            {"name": "route_env", "label": "Route Environment"},
        ],
    },
    {
        "kind": "telegram", "name": "Telegram", "intro_url": "https://t.me/BotFather",
        "description": "Telegram Bot API 私聊与群聊。",
        "fields": [
            {"name": "bot_token", "label": "Bot Token", "type": "password", "required": True},
            {"name": "allowed_user_ids", "label": "允许的用户 ID（逗号分隔）", "type": "textarea"},
            {"name": "allowed_chat_ids", "label": "允许的会话 ID（逗号分隔）", "type": "textarea"},
            {"name": "http_proxy", "label": "HTTP Proxy", "type": "password", "placeholder": "http://127.0.0.1:7890"},
        ],
    },
    {
        "kind": "discord", "name": "Discord", "intro_url": "https://discord.com/developers/applications",
        "description": "Discord Bot 私聊与服务器频道。",
        "fields": [
            {"name": "bot_token", "label": "Bot Token", "type": "password", "required": True},
            {"name": "allow_all_channels", "label": "允许所有频道", "type": "switch"},
            {"name": "allowed_channel_ids", "label": "允许的频道 ID（逗号分隔）", "type": "textarea"},
            {"name": "allowed_user_ids", "label": "允许的用户 ID（逗号分隔）", "type": "textarea"},
            {"name": "http_proxy", "label": "HTTP Proxy", "type": "password"},
            {"name": "http_proxy_auth", "label": "Proxy Auth", "type": "password"},
        ],
    },
    {
        "kind": "xiaoyi", "name": "华为小艺", "intro_url": "",
        "description": "华为小艺 OpenClaw / A2A 通道。",
        "fields": [
            {"name": "ak", "label": "Access Key (AK)", "type": "password", "required": True},
            {"name": "sk", "label": "Secret Key (SK)", "type": "password", "required": True},
            {"name": "agent_id", "label": "Agent ID", "required": True},
            {"name": "ws_url", "label": "WebSocket URL"},
            {"name": "ws_url_backup", "label": "备用 WebSocket URL"},
        ],
    },
    {
        "kind": "mqtt", "name": "MQTT", "intro_url": "",
        "description": "MQTT 消息通道，可连接 IoT 设备或内部消息总线。",
        "fields": [
            {"name": "host", "label": "Broker Host", "required": True},
            {"name": "port", "label": "Port", "type": "number"},
            {"name": "transport", "label": "Transport", "placeholder": "tcp"},
            {"name": "username", "label": "Username", "type": "password"},
            {"name": "password", "label": "Password", "type": "password"},
            {"name": "subscribe_topic", "label": "Subscribe Topic", "placeholder": "devices/+/in"},
            {"name": "publish_topic", "label": "Publish Topic", "placeholder": "devices/{client_id}/out"},
            {"name": "tls_enabled", "label": "启用 TLS", "type": "switch"},
        ],
    },
    {
        "kind": "generic", "name": "通用 Webhook", "intro_url": "",
        "description": "兼容现有自建机器人：向入站 URL POST sender_id、message 和 secret。",
        "fields": [
            {"name": "secret", "label": "Webhook Secret", "type": "password"},
            {"name": "outbound_webhook", "label": "回复 Webhook URL", "type": "password"},
        ],
    },
]

_PROVIDER_BY_KIND = {item["kind"]: item for item in _PROVIDERS}
_CHANNEL_MODE_KEY = "__uniemployee_im_mode"
_SECRET_CONFIG_KEYS = frozenset({
    "access_token", "ak", "api_key", "app_secret", "authorization", "bot_token",
    "client_secret", "encrypt_key", "http_proxy", "http_proxy_auth", "outbound_webhook",
    "password", "refresh_token", "secret", "sk", "token", "username",
    "verification_token", "webhook_url",
})


def provider_catalog() -> list[dict[str, Any]]:
    """Return provider metadata for the IM channel configuration UI."""
    return [dict(item) | {"fields": [dict(field) for field in item["fields"]]} for item in _PROVIDERS]


def is_native_kind(kind: str) -> bool:
    return kind in _NATIVE_KINDS


def channel_mode(row: dict[str, Any]) -> str:
    """Resolve the transport while keeping pre-native provider rows as Webhooks."""
    kind = str(row.get("provider") or row.get("kind") or "")
    config = row.get("config") or {}
    if is_native_kind(kind) and isinstance(config, dict) and config.get(_CHANNEL_MODE_KEY) == "native":
        return "native"
    return "webhook"


def config_for_mode(config: dict[str, Any] | None, mode: str) -> dict[str, Any]:
    prepared = dict(config or {})
    if mode == "native":
        prepared[_CHANNEL_MODE_KEY] = "native"
    else:
        prepared.pop(_CHANNEL_MODE_KEY, None)
    return prepared


def is_native_channel(row: dict[str, Any]) -> bool:
    return channel_mode(row) == "native"


def redact_config(config: dict[str, Any] | None) -> tuple[dict[str, Any], list[str]]:
    """Mask credentials before returning channel configuration to the browser."""
    redacted = dict(config or {})
    redacted.pop(_CHANNEL_MODE_KEY, None)
    masked: list[str] = []
    for key in _SECRET_CONFIG_KEYS:
        if redacted.get(key):
            redacted[key] = ""
            masked.append(key)
    accounts = redacted.get("accounts")
    if isinstance(accounts, list):
        safe_accounts: list[dict[str, Any]] = []
        for index, account in enumerate(accounts):
            if not isinstance(account, dict):
                continue
            item = dict(account)
            if item.get("token"):
                item["token"] = ""
                masked.append(f"accounts.{index}.token")
            safe_accounts.append(item)
        redacted["accounts"] = safe_accounts
    return redacted, sorted(set(masked))


def merge_config_secrets(existing: dict[str, Any], incoming: dict[str, Any]) -> dict[str, Any]:
    """Keep stored secret values when an edit form submits their masked blanks."""
    merged = dict(incoming)
    for key in _SECRET_CONFIG_KEYS:
        if not merged.get(key) and existing.get(key):
            merged[key] = existing[key]
    old_accounts = existing.get("accounts")
    new_accounts = merged.get("accounts")
    if isinstance(old_accounts, list) and isinstance(new_accounts, list):
        old_by_id = {
            str(account.get("account_id") or ""): account
            for account in old_accounts
            if isinstance(account, dict)
        }
        preserved: list[Any] = []
        for account in new_accounts:
            if not isinstance(account, dict):
                preserved.append(account)
                continue
            item = dict(account)
            old = old_by_id.get(str(item.get("account_id") or "")) or {}
            if not item.get("token") and old.get("token"):
                item["token"] = old["token"]
            preserved.append(item)
        merged["accounts"] = preserved
    elif not new_accounts and old_accounts:
        merged["accounts"] = old_accounts
    return merged


def _external_identity(channel_id: str, subject_id: str, employee_id: str) -> tuple[str, str]:
    identity = hashlib.sha256(f"{channel_id}\0{subject_id}".encode("utf-8")).hexdigest()
    conversation = hashlib.sha256(
        f"{channel_id}\0{subject_id}\0{employee_id}".encode("utf-8")
    ).hexdigest()
    return f"im_{identity[:32]}", f"c_im_{conversation[:40]}"


def _parts_for_message(message: InboundMessage) -> list[Any]:
    return list(message.content or [])


class NativeImGateway:
    """Owns octop-gateway channel processes and bridges inbound turns."""

    def __init__(self) -> None:
        self._manager: ChannelManager | None = None
        self._media_backend: FileSystemMediaBackend | None = None
        self._started = False
        self._statuses: dict[str, dict[str, Any]] = {}
        self._sync_lock = asyncio.Lock()

    async def start(self) -> None:
        if self._started:
            return
        media_root = WORKSPACE_DATA / "im_media"
        media_root.mkdir(parents=True, exist_ok=True)
        self._media_backend = FileSystemMediaBackend(media_root)
        self._manager = ChannelManager(
            processor=self._process_inbound,
            workers_per_channel=2,
            queue_maxsize=100,
            media_backend=self._media_backend,
        )
        await self._manager.start()
        self._started = True
        try:
            rows = conversations.list_channels()
        except Exception:
            logger.exception("读取 IM 频道配置失败，原生通道暂未启动")
            return
        for row in rows:
            if is_native_channel(row):
                await self.sync_channel(row)

    async def stop(self) -> None:
        manager = self._manager
        self._manager = None
        self._started = False
        if manager is not None:
            await manager.stop()
        self._statuses.clear()

    async def sync_channel(self, row: dict[str, Any]) -> None:
        """Apply a channel row to the live protocol manager."""
        channel_id = str(row.get("id") or "")
        kind = str(row.get("provider") or row.get("kind") or "")
        if not channel_id:
            return
        async with self._sync_lock:
            manager = self._manager
            if manager is None:
                return
            if manager.get_channel(channel_id) is not None:
                await manager.remove_channel(channel_id)
            self._statuses.pop(channel_id, None)
            if not row.get("enabled", True) or not is_native_channel(row):
                return

            employees = conversations.list_employee_ids_for_channel(channel_id)
            if not employees:
                employees = [item["id"] for item in runtime.discover_employees()]
            employee_id = str((row.get("config") or {}).get("employee_id") or (employees[0] if employees else ""))
            if not employee_id:
                self._statuses[channel_id] = {
                    "connected": False,
                    "running": False,
                    "error": "请先为此通道绑定一个数字员工。",
                    "updated_at": int(time.time()),
                }
                return
            try:
                await manager.add_channel(
                    kind,
                    dict(row.get("config") or {}),
                    channel_id=channel_id,
                    tenant_id=employee_id,
                )
                live = manager.get_channel(channel_id)
                connected = self._connection_state(live)
                self._statuses[channel_id] = {
                    "connected": connected,
                    "running": live is not None,
                    "error": None,
                    "updated_at": int(time.time()),
                }
            except ChannelCredentialsError as exc:
                self._statuses[channel_id] = {
                    "connected": False,
                    "running": False,
                    "error": f"缺少必填配置：{', '.join(exc.missing)}",
                    "updated_at": int(time.time()),
                }
                logger.warning("原生 IM 通道凭据不完整 channel=%s kind=%s missing=%s", channel_id, kind, exc.missing)
            except Exception as exc:
                self._statuses[channel_id] = {
                    "connected": False,
                    "running": False,
                    "error": "连接失败，请检查平台凭据、网络和服务日志。",
                    "updated_at": int(time.time()),
                }
                logger.exception("启动原生 IM 通道失败 channel=%s kind=%s: %s", channel_id, kind, type(exc).__name__)

    async def remove_channel(self, channel_id: str) -> None:
        manager = self._manager
        if manager is not None and manager.get_channel(channel_id) is not None:
            async with self._sync_lock:
                if manager.get_channel(channel_id) is not None:
                    await manager.remove_channel(channel_id)
        self._statuses.pop(channel_id, None)

    def status(self, channel_id: str) -> dict[str, Any] | None:
        current = self._statuses.get(channel_id)
        if current is None:
            return None
        manager = self._manager
        channel = manager.get_channel(channel_id) if manager is not None else None
        running = channel is not None
        connected = self._connection_state(channel) if running else False
        if running != current.get("running") or connected != current.get("connected"):
            current = dict(current, running=running, connected=connected, updated_at=int(time.time()))
            self._statuses[channel_id] = current
        return dict(current)

    @staticmethod
    def _connection_state(channel: Any) -> bool | None:
        """Read an adapter's live state when it exposes one; otherwise unknown."""
        if channel is None:
            return False
        for name in ("is_connected", "_connected", "connected"):
            value = getattr(channel, name, None)
            if callable(value):
                try:
                    value = value()
                except Exception:
                    continue
            if isinstance(value, bool):
                return value
        return None

    async def probe(self, row: dict[str, Any]) -> dict[str, Any]:
        manager = self._manager
        kind = str(row.get("provider") or row.get("kind") or "")
        if manager is None or not self._started:
            return {"ok": False, "error": "IM 通道服务尚未启动。"}
        if not is_native_channel(row):
            return {"ok": False, "error": "通用 Webhook 通道不支持连接探测。"}
        employees = conversations.list_employee_ids_for_channel(str(row["id"]))
        employee_id = employees[0] if employees else ""
        try:
            await manager.probe_channel(
                kind,
                dict(row.get("config") or {}),
                channel_id=str(row["id"]),
                tenant_id=employee_id,
                processor=self._process_inbound,
            )
            return {"ok": True}
        except ChannelCredentialsError as exc:
            return {"ok": False, "error": f"缺少必填配置：{', '.join(exc.missing)}"}
        except Exception as exc:
            logger.info("IM 通道连通性探测失败 channel=%s kind=%s: %s", row.get("id"), kind, type(exc).__name__)
            return {"ok": False, "error": "连接失败，请检查平台凭据、机器人权限和服务日志。"}

    async def _copy_inbound_media(
        self,
        channel: Any,
        message: InboundMessage,
        *,
        user_id: str,
        conv_id: str,
    ) -> list[dict[str, Any]]:
        attachments: list[dict[str, Any]] = []
        index = 0
        for part in _parts_for_message(message):
            if getattr(part, "type", "") == "text":
                continue
            if index >= MAX_ATTACHMENTS_PER_MESSAGE:
                logger.info("IM 附件超过数量上限 channel=%s", message.channel_id)
                break
            try:
                data, mime_type = await channel.load_media_bytes(part)
            except Exception:
                logger.warning("读取 IM 媒体失败 channel=%s", message.channel_id, exc_info=True)
                continue
            if not data or len(data) > MAX_ATTACHMENT_SIZE:
                logger.info("跳过超限或空 IM 附件 channel=%s size=%d", message.channel_id, len(data or b""))
                continue
            index += 1
            source_name = str(
                getattr(part, "filename", "")
                or getattr(part, "alt_text", "")
                or f"im-media-{index}"
            )
            safe_name = _sanitize_name(source_name)
            if "." not in safe_name:
                extension = mimetypes.guess_extension(mime_type or getattr(part, "mime_type", "") or "") or ".bin"
                safe_name += extension
            stored_name = f"{index}_{uuid.uuid4().hex[:8]}_{safe_name}"
            target_dir = WORKSPACE_DATA / user_id / "uploads" / conv_id
            target = target_dir / stored_name
            await asyncio.to_thread(target_dir.mkdir, parents=True, exist_ok=True)
            await asyncio.to_thread(target.write_bytes, data)
            attachments.append({
                "name": source_name,
                "path": f"/data/{user_id}/uploads/{conv_id}/{stored_name}",
                "size": len(data),
                "content_type": mime_type or getattr(part, "mime_type", "") or "application/octet-stream",
            })
        return attachments

    async def _outbound_files(self, files: list[dict[str, Any]], channel_id: str) -> list[FileContent]:
        media = self._media_backend
        if media is None:
            return []
        result: list[FileContent] = []
        root = WORKSPACE_DATA.resolve()
        for item in files[:MAX_ATTACHMENTS_PER_MESSAGE]:
            try:
                source = (WORKSPACE_DATA / str(item.get("path") or "")).resolve()
                source.relative_to(root)
                if source.is_symlink() or not source.is_file() or source.stat().st_size > MAX_ATTACHMENT_SIZE:
                    continue
                name = _sanitize_name(str(item.get("name") or source.name))
                key = f"outbound/{channel_id}/{uuid.uuid4().hex}_{name}"
                data = await asyncio.to_thread(source.read_bytes)
                if not data:
                    continue
                await media.save(data, key)
                mime_type = mimetypes.guess_type(name)[0] or "application/octet-stream"
                result.append(FileContent(local_path=key, filename=name, mime_type=mime_type, size=len(data)))
            except (OSError, ValueError):
                logger.warning("无法转发 IM 会话产物 channel=%s", channel_id, exc_info=True)
        return result

    async def _process_inbound(self, message: InboundMessage) -> AsyncIterator[MessageEvent]:
        try:
            channel_id = str(message.channel_id or "")
            subject = message.channel_subject
            subject_id = str(getattr(subject, "subject_id", "") or message.metadata.get("sender_id") or "")
            employee_id = str(message.tenant_id or "")
            if not channel_id or not subject_id or not employee_id:
                yield MessageEvent.error_event("通道消息缺少频道、用户或员工标识。")
                return

            user_id, conv_id = _external_identity(channel_id, subject_id, employee_id)
            tenant_id = os.environ.get("ENTERPRISE_TENANT_ID", "default").strip() or "default"
            text = str(message.text or "").strip()
            if message.group_context and message.group_context.messages:
                context_lines = [
                    f"{item.sender_name or item.sender_id}: {item.text}"
                    for item in message.group_context.messages
                    if item.text.strip()
                ]
                if context_lines:
                    context = "\n".join(context_lines)
                    text = f"[群聊上下文]\n{context}\n[当前消息]\n{text}" if text else context

            channel = self._manager.get_channel(channel_id) if self._manager else None
            if channel is None:
                yield MessageEvent.error_event("该 IM 通道当前未连接。")
                return
            inbound_attachments = await self._copy_inbound_media(
                channel, message, user_id=user_id, conv_id=conv_id
            )
            if not text and not inbound_attachments:
                yield MessageEvent.text("目前无法读取这条消息的内容或附件，请发送文字或可读取的文件。")
                yield MessageEvent.completed()
                return

            title = text[:40] or f"附件：{inbound_attachments[0]['name']}"
            preview = text[:60] or f"[附件] {inbound_attachments[0]['name']}"
            meta = conversations.get(conv_id)
            if meta is None:
                conversations.create(
                    conv_id,
                    employee_id,
                    title=title,
                    preview=preview,
                    count=1,
                    user_id=user_id,
                    channel_id=channel_id,
                    tenant_id=tenant_id,
                )
            else:
                conversations.touch(conv_id, title=title, preview=preview, bump=1)
            conv_emp_map[conv_id] = employee_id
            conv_owner_map[conv_id] = user_id
            conv_tenant_map[conv_id] = tenant_id

            user_content = compose_user_content(text, inbound_attachments)
            raw_events = _stream_run(
                conv_id,
                {"messages": [{"role": "user", "content": user_content}]},
                user_id=user_id,
                role="user",
                tenant_id=tenant_id,
            )
            generated_files: list[dict[str, Any]] = []
            visible_output = False
            async for raw in raw_events:
                if not raw.startswith("data: "):
                    continue
                try:
                    event = json.loads(raw[6:])
                except (TypeError, json.JSONDecodeError):
                    continue
                event_type = event.get("type")
                if event_type == "token" and event.get("content"):
                    visible_output = True
                    yield MessageEvent.delta(str(event["content"]))
                elif event_type == "error":
                    visible_output = True
                    yield MessageEvent.text(f"⚠ {event.get('message') or '任务执行出错'}")
                elif event_type == "approval_required":
                    visible_output = True
                    yield MessageEvent.text("此操作需要人工审批，请登录 UniEmployee 管理台完成审批。")
                elif event_type == "file":
                    generated_files.append(event)

            if not visible_output:
                yield MessageEvent.text("本轮没有生成可发送的文字回复。")
            for file_part in await self._outbound_files(generated_files, channel_id):
                yield MessageEvent(type=MessageEventType.MESSAGE, content=[file_part])
            yield MessageEvent.completed()
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.exception("处理原生 IM 消息失败 channel=%s: %s", message.channel_id, type(exc).__name__)
            yield MessageEvent.error_event("处理消息失败，请检查 UniEmployee 服务日志后重试。")
            yield MessageEvent.completed()


gateway = NativeImGateway()
