#!/usr/bin/env python3
"""飞书长连接 G0 验证脚本。

该脚本只验证官方 Channel SDK、长连接、消息事件和回复 API，不连接
UniEmployee 数据库，也不会调用数字员工。凭证只从环境变量读取：

    FEISHU_APP_ID=cli_xxx
    FEISHU_APP_SECRET=xxx

示例（PowerShell）：

    $env:FEISHU_APP_ID='cli_xxx'
    $env:FEISHU_APP_SECRET='***'
    .venv\Scripts\python scripts\verify_feishu_connection.py --reply

收到第一条合规消息并完成可选回复后退出。输出为 JSON Lines，且不打印凭证
或消息正文，便于保存为验收记录。
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import socket
import ssl
import sys
import time
import uuid
from pathlib import Path
from typing import Any


SDK_CANDIDATE = "lark-channel-sdk==1.4.0"
ROOT = Path(__file__).resolve().parent.parent
SDK_TYPES: tuple[Any, Any, Any, Any, Any, Any] | None = None


def emit(event: str, **fields: Any) -> None:
    print(json.dumps({"event": event, **fields}, ensure_ascii=False), flush=True)


def masked(value: str | None) -> str:
    if not value:
        return ""
    if len(value) <= 8:
        return "***"
    return f"{value[:4]}...{value[-4:]}"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="验证飞书企业自建应用的长连接收发能力（G0 PoC）",
    )
    parser.add_argument(
        "--reply",
        action="store_true",
        help="收到文本消息后回复一条固定确认消息",
    )
    parser.add_argument(
        "--wait-timeout",
        type=float,
        default=180,
        help="等待首条消息的秒数，默认 180；设为 0 表示一直等待",
    )
    parser.add_argument(
        "--connect-timeout",
        type=float,
        default=30,
        help="等待长连接就绪的秒数，默认 30",
    )
    parser.add_argument(
        "--security-mode",
        choices=("audit", "strict"),
        default="audit",
        help="SDK 安全模式；首次验证用 audit，发布前必须再用 strict 验证",
    )
    parser.add_argument(
        "--verified-endpoint-dns",
        action="store_true",
        help=(
            "仅用于 G0：从系统 DNS 结果中选择通过标准 TLS 校验的 "
            "open.feishu.cn 节点；不降低 TLS 安全级别"
        ),
    )
    return parser.parse_args()


def select_verified_endpoint_ip(host: str = "open.feishu.cn", port: int = 443) -> str:
    """从系统 DNS 结果中选择一个可通过完整 TLS 校验的地址。"""
    candidates = sorted(
        {
            item[4][0]
            for item in socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
        }
    )
    failures: list[str] = []
    for ip in candidates:
        try:
            raw = socket.create_connection((ip, port), timeout=5)
            with ssl.create_default_context().wrap_socket(raw, server_hostname=host):
                return ip
        except (OSError, ssl.SSLError) as exc:
            failures.append(f"{ip}:{type(exc).__name__}")
    raise RuntimeError(f"没有可通过 TLS 校验的飞书端点（{', '.join(failures)}）")


def pin_host_resolutions(hosts: dict[str, str]) -> None:
    """在当前 PoC 进程内固定主机；TLS 仍按原始 host 校验。"""
    original = socket.getaddrinfo

    def getaddrinfo(name: str, port: int, *args: Any, **kwargs: Any) -> Any:
        if name in hosts:
            return original(hosts[name], port, *args, **kwargs)
        return original(name, port, *args, **kwargs)

    socket.getaddrinfo = getaddrinfo


async def run(args: argparse.Namespace) -> int:
    # 与主应用一致地支持项目根目录 .env；已由进程环境提供的值优先。
    try:
        from dotenv import load_dotenv

        load_dotenv(ROOT / ".env", override=False)
    except ImportError:
        pass
    app_id = os.environ.get("FEISHU_APP_ID", "").strip()
    app_secret = os.environ.get("FEISHU_APP_SECRET", "").strip()
    if not app_id or not app_secret:
        emit(
            "CONFIG_ERROR",
            reason="请设置 FEISHU_APP_ID 和 FEISHU_APP_SECRET；不要通过命令行参数传密钥",
        )
        return 2

    if args.verified_endpoint_dns:
        try:
            host = "open.feishu.cn"
            selected = {host: await asyncio.to_thread(select_verified_endpoint_ip, host)}
            emit("TLS_ENDPOINT_SELECTED", host=host, endpoint_ip=selected[host])
            pin_host_resolutions(selected)
            # 当前开发网络的飞书 API 直连证书正常，而 WebSocket 直连节点证书
            # 不被 OpenSSL 接受；只让 API 域名绕过环境代理，WSS 仍走代理。
            no_proxy = [item for item in os.environ.get("NO_PROXY", "").split(",") if item]
            if host not in no_proxy:
                no_proxy.append(host)
            os.environ["NO_PROXY"] = ",".join(no_proxy)
            emit(
                "NETWORK_ROUTE_READY",
                api_direct=True,
                websocket_proxy_configured=bool(os.environ.get("HTTPS_PROXY")),
            )
        except Exception as exc:
            emit("TLS_PREFLIGHT_ERROR", detail=str(exc)[:300])
            return 2

    if SDK_TYPES is None:
        emit("DEPENDENCY_ERROR", reason=f"缺少候选 SDK，请先安装 {SDK_CANDIDATE}")
        return 2
    Events, FeishuChannel, LogLevel, PolicyConfig, SecurityConfig, TransportConfig = (
        SDK_TYPES
    )

    queue: asyncio.Queue[Any] = asyncio.Queue(maxsize=10)
    completed = asyncio.Event()
    outcome = {"ok": False}
    main_loop = asyncio.get_running_loop()

    channel = FeishuChannel(
        app_id=app_id,
        app_secret=app_secret,
        # PoC 显式决定是否继承代理；生产实现将使用独立配置项而非宿主机隐式值。
        transport=TransportConfig(
            kind="ws", trust_env_proxy=True if args.verified_endpoint_dns else False
        ),
        # INFO 日志会包含带临时 access_key 的完整 WebSocket URL。
        log_level=LogLevel.WARNING,
        policy=PolicyConfig(
            dm_policy="open",
            group_policy="open",
            require_mention=True,
            respond_to_mention_all=False,
        ),
        security=SecurityConfig(
            mode=args.security_mode,
            strict_content_text=True,
            max_ws_fragment_parts=128,
            max_ws_fragment_bytes=8 * 1024 * 1024,
            max_concurrent_ws_handlers=32,
        ),
    )

    def enqueue_message(message: Any, started: float) -> None:
        try:
            queue.put_nowait(message)
        except asyncio.QueueFull:
            emit("MESSAGE_REJECTED", reason="本地 PoC 队列已满")
            return
        emit(
            "MESSAGE_ACCEPTED",
            message_id=message.message_id,
            chat_id=message.chat_id,
            chat_type=message.chat_type,
            sender_id=masked(message.sender_id),
            message_type=message.raw_content_type,
            mentioned_bot=bool(message.mentioned_bot),
            enqueue_ms=round((time.perf_counter() - started) * 1000, 2),
        )

    def on_message(message: Any) -> None:
        # SDK 在自己的后台事件循环中派发事件；跨线程写 asyncio.Queue
        # 并不安全，必须切回本脚本的主循环。
        main_loop.call_soon_threadsafe(enqueue_message, message, time.perf_counter())

    def on_error(error: Any) -> None:
        emit("SDK_ERROR", error_type=type(error).__name__, detail=str(error)[:300])

    def on_reconnecting() -> None:
        emit("RECONNECTING")

    def on_reconnected() -> None:
        emit("RECONNECTED")

    channel.on(Events.MESSAGE, on_message)
    channel.on(Events.ERROR, on_error)
    channel.on(Events.RECONNECTING, on_reconnecting)
    channel.on(Events.RECONNECTED, on_reconnected)

    async def consume_one() -> None:
        message = await queue.get()
        try:
            if message.raw_content_type != "text":
                emit("MESSAGE_SKIPPED", reason="首版仅验证 text")
                outcome["ok"] = True
                return
            if args.reply:
                result = await channel.reply(
                    message,
                    {"text": "UniEmployee 飞书长连接验证成功。"},
                    {"uuid": str(uuid.uuid5(uuid.NAMESPACE_URL, message.message_id))},
                )
                emit(
                    "REPLY_RESULT",
                    success=bool(result.success),
                    message_id=result.message_id or "",
                    error=str(result.error)[:300] if result.error else "",
                )
                outcome["ok"] = bool(result.success)
            else:
                outcome["ok"] = True
        finally:
            queue.task_done()
            completed.set()

    consumer = asyncio.create_task(consume_one())
    try:
        await channel.connect_until_ready(timeout=args.connect_timeout)
        identity = channel.bot_identity
        emit(
            "READY",
            sdk=SDK_CANDIDATE,
            security_mode=args.security_mode,
            app_id=masked(app_id),
            bot_open_id=masked(identity.open_id) if identity else "",
            bot_name=(identity.name or "") if identity else "",
            identity_resolved=identity is not None,
        )
        if args.wait_timeout > 0:
            await asyncio.wait_for(completed.wait(), timeout=args.wait_timeout)
        else:
            await completed.wait()
        return 0 if outcome["ok"] else 1
    except asyncio.TimeoutError:
        emit("TIMEOUT", phase="connect_or_message")
        return 3
    except KeyboardInterrupt:
        emit("INTERRUPTED")
        return 130
    except Exception as exc:
        emit("FAILED", error_type=type(exc).__name__, detail=str(exc)[:300])
        return 1
    finally:
        consumer.cancel()
        await asyncio.gather(consumer, return_exceptions=True)
        try:
            await channel.disconnect()
        except Exception as exc:
            emit("DISCONNECT_ERROR", error_type=type(exc).__name__)


def main() -> int:
    global SDK_TYPES
    args = parse_args()
    if args.wait_timeout < 0 or args.connect_timeout <= 0:
        emit("ARGUMENT_ERROR", reason="wait-timeout 不能小于 0，connect-timeout 必须大于 0")
        return 2
    # lark-channel-sdk 1.4.0 在导入时创建其 WebSocket 事件循环。必须在
    # asyncio.run() 启动本脚本的事件循环之前导入，否则 SDK 会尝试再次运行
    # 当前已运行的循环并报 "This event loop is already running"。
    try:
        from lark_channel import (
            Events,
            FeishuChannel,
            LogLevel,
            PolicyConfig,
            SecurityConfig,
            TransportConfig,
        )

        SDK_TYPES = (
            Events,
            FeishuChannel,
            LogLevel,
            PolicyConfig,
            SecurityConfig,
            TransportConfig,
        )
    except ImportError:
        emit("DEPENDENCY_ERROR", reason=f"缺少候选 SDK，请先安装 {SDK_CANDIDATE}")
        return 2
    try:
        return asyncio.run(run(args))
    except KeyboardInterrupt:
        emit("INTERRUPTED")
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
