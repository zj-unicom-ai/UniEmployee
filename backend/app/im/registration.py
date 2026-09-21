"""飞书「扫码一键创建应用」（路径 B）的协议实现与会话管理。

对应文档：`docs/飞书扫码一键接入方案.md`
  - §2.1  两条接入路径的差异（本模块只服务路径 B）
  - §3    协议链路（init / begin / poll 三个动作、轮询状态机）
  - §7.2  后端改动（3 个接口不能阻塞 HTTP 请求，轮询必须放进后台任务）
  - 附录 C OpenClaw 参考实现（轮询状态机用「返回值」而非「异常」）

协议是 OAuth 2.0 Device Authorization Grant（RFC 8628），端点
`{accounts}/oauth/v1/app/registration`，只有三个 POST，无需 SDK。

为什么自实现而不用 `lark-oapi`（结论同文档 §7.1）：
1. SDK 的异步版 `aregister_app()` 没有 `cancel_event`，做不出「取消」接口；
2. SDK 内部 HTTP 客户端的代理策略不可控，而本机实测必须显式 `trust_env=False`
   才能绕开代理引入的弱证书（否则轮询会随机 TLS 失败）；
3. 服务端只接受 `archetype=PersonalAgent`，SDK 在能力上不比自实现多任何可能。
"""

from __future__ import annotations

import asyncio
import logging
import re
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Awaitable, Callable
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

import httpx

logger = logging.getLogger("app.im.registration")

FEISHU_ACCOUNTS_URL = "https://accounts.feishu.cn"
LARK_ACCOUNTS_URL = "https://accounts.larksuite.com"
REGISTRATION_PATH = "/oauth/v1/app/registration"

# 实测（2026-09-21）：服务端只接受这一个取值，其余候选值与不传值一律
# 400 / invalid_request（code 20099）。不要"顺手改成企业形态"——没有这个选项。
ARCHETYPE = "PersonalAgent"

REQUEST_TIMEOUT_SECONDS = 10.0
DEFAULT_POLL_INTERVAL_SECONDS = 5.0
# 兜底值：实测服务端返回 expires_in=3600，取不到时才用 600。
DEFAULT_EXPIRE_SECONDS = 600.0
MAX_POLL_INTERVAL_SECONDS = 60.0
SLOW_DOWN_INCREMENT_SECONDS = 5.0
# 终态会话在内存中的保留时长（前端刷新页面后仍能读到结果）。
SESSION_TTL_SECONDS = 600.0

# 二维码渠道标识：只是给飞书侧统计来源用，换成自己的标识不影响扫码。
QR_FROM = "uniemployee"
QR_TP = "ue_web_scan"

STATUS_PENDING = "pending"
STATUS_SUCCESS = "success"
STATUS_DENIED = "denied"
STATUS_EXPIRED = "expired"
STATUS_TIMEOUT = "timeout"
STATUS_ERROR = "error"
STATUS_CANCELLED = "cancelled"

_TERMINAL_STATUSES = frozenset(
    {STATUS_SUCCESS, STATUS_DENIED, STATUS_EXPIRED, STATUS_TIMEOUT, STATUS_ERROR, STATUS_CANCELLED}
)

_URL_PATTERN = re.compile(r"(?:wss?|https?)://\S+")

SuccessCallback = Callable[[str, str, str, "str | None"], Awaitable[None]]


class RegistrationUnavailable(RuntimeError):
    """环境自检或 begin 失败：页面应降级回手工填写凭据（路径 A）。"""


def _safe_error(exc: BaseException | str) -> str:
    text = str(exc).replace("\r", " ").replace("\n", " ")
    return _URL_PATTERN.sub("<redacted-url>", text)[:300]


def _iso(epoch: float) -> str:
    return datetime.fromtimestamp(epoch, timezone.utc).isoformat(timespec="seconds")


def _number(data: dict[str, Any], *keys: str, default: float) -> float:
    """取正数配置项，同时兼容 `interval` 与 `expires_in` / `expire_in` 的命名差异。"""
    for key in keys:
        value = data.get(key)
        if value is None:
            continue
        try:
            number = float(value)
        except (TypeError, ValueError):
            continue
        if number > 0:
            return number
    return default


def _decorate_qr_url(url: str) -> str:
    parts = urlsplit(url)
    query = dict(parse_qsl(parts.query, keep_blank_values=True))
    query["from"] = QR_FROM
    query["tp"] = QR_TP
    return urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(query), parts.fragment))


@dataclass(slots=True)
class RegistrationSession:
    session_id: str
    channel_id: str
    created_by: str
    status: str
    qr_url: str
    user_code: str
    interval: float
    expire_in: float
    created_at: float
    updated_at: float
    expires_at: float
    device_code: str = ""
    app_id: str | None = None
    open_id: str | None = None
    error: str | None = None
    cancel_event: asyncio.Event = field(default_factory=asyncio.Event)
    task: asyncio.Task | None = None

    def snapshot(self) -> dict[str, Any]:
        """对外的状态快照。**不含 `device_code`，也不含 App Secret。**"""
        pending = self.status == STATUS_PENDING
        return {
            "session_id": self.session_id,
            "channel_id": self.channel_id,
            "status": self.status,
            "qr_url": self.qr_url if pending else None,
            "user_code": self.user_code if pending else None,
            "interval": self.interval,
            "expire_in": self.expire_in,
            "remaining_seconds": max(0, int(self.expires_at - time.time())) if pending else 0,
            "app_id": self.app_id,
            "open_id": self.open_id,
            "error": self.error,
            "created_at": _iso(self.created_at),
            "updated_at": _iso(self.updated_at),
        }


class AppRegistrationService:
    """内存态的扫码会话管理：单进程部署够用，多 worker 不共享（同文档 §7.2 的限制）。"""

    def __init__(self, *, transport: httpx.AsyncBaseTransport | None = None) -> None:
        self._sessions: dict[str, RegistrationSession] = {}
        self._lock = asyncio.Lock()
        self._transport = transport
        self._client: httpx.AsyncClient | None = None

    # ---------- HTTP ----------

    def _http(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            # trust_env=False：本机环境注入了 HTTP(S)_PROXY，经代理请求飞书会命中
            # 弱证书并 TLS 失败（实测见文档附录 A）。这里显式忽略代理设置。
            self._client = httpx.AsyncClient(
                timeout=REQUEST_TIMEOUT_SECONDS,
                trust_env=False,
                transport=self._transport,
            )
        return self._client

    async def _post(self, base_url: str, payload: dict[str, Any]) -> dict[str, Any]:
        # 实测：该接口只接受 form-urlencoded，用 JSON body 会被判 invalid_request。
        # （S0 脚本一直用 data=payload，SDK 内部同样如此。）
        response = await self._http().post(
            base_url + REGISTRATION_PATH,
            data=payload,
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        try:
            data = response.json()
        except ValueError:
            data = {}
        if not isinstance(data, dict):
            data = {}
        if response.status_code >= 400 and not data.get("error"):
            raise RegistrationUnavailable(f"飞书注册接口返回 HTTP {response.status_code}")
        return data

    # ---------- 三个协议动作 ----------

    async def _check_environment(self) -> None:
        data = await self._post(FEISHU_ACCOUNTS_URL, {"action": "init"})
        error = data.get("error")
        if error:
            raise RegistrationUnavailable(f"注册环境自检失败：{error}")
        methods = data.get("supported_auth_methods")
        if isinstance(methods, list):
            if "client_secret" not in methods:
                raise RegistrationUnavailable("当前环境不支持 client_secret 接入方式")
        else:
            logger.warning("飞书注册 init 未返回 supported_auth_methods，跳过校验")

    async def _begin(self) -> dict[str, Any]:
        data = await self._post(
            FEISHU_ACCOUNTS_URL,
            {
                "action": "begin",
                "archetype": ARCHETYPE,
                "auth_method": "client_secret",
                "request_user_info": "open_id",
            },
        )
        device_code = str(data.get("device_code") or "")
        qr_url = str(data.get("verification_uri_complete") or data.get("verification_uri") or "")
        if not device_code or not qr_url:
            raise RegistrationUnavailable(
                f"飞书未返回二维码信息：{data.get('error') or data.get('error_description') or '缺少 device_code'}"
            )
        return {
            "device_code": device_code,
            "qr_url": _decorate_qr_url(qr_url),
            "user_code": str(data.get("user_code") or ""),
            "interval": _number(data, "interval", default=DEFAULT_POLL_INTERVAL_SECONDS),
            "expire_in": _number(
                data, "expires_in", "expire_in", default=DEFAULT_EXPIRE_SECONDS
            ),
        }

    # ---------- 会话生命周期 ----------

    async def start(
        self,
        *,
        channel_id: str,
        created_by: str,
        on_success: SuccessCallback,
    ) -> dict[str, Any]:
        """发起一次扫码流程。同频道已在进行的会话会先被取消，避免重复创建应用。"""
        await self._check_environment()
        begin = await self._begin()
        now = time.time()
        session = RegistrationSession(
            session_id="reg_" + uuid.uuid4().hex[:16],
            channel_id=channel_id,
            created_by=created_by,
            status=STATUS_PENDING,
            qr_url=begin["qr_url"],
            user_code=begin["user_code"],
            interval=begin["interval"],
            expire_in=begin["expire_in"],
            created_at=now,
            updated_at=now,
            expires_at=now + begin["expire_in"],
            device_code=begin["device_code"],
        )
        async with self._lock:
            await self._cancel_channel_sessions(channel_id)
            self._sessions[session.session_id] = session
            session.task = asyncio.create_task(
                self._poll_loop(session, on_success),
                name=f"im-app-registration-{session.session_id}",
            )
            self._sweep()
        return session.snapshot()

    def get(self, session_id: str) -> dict[str, Any] | None:
        session = self._sessions.get(session_id)
        if session is None:
            return None
        self._sweep()
        return session.snapshot()

    async def cancel(self, session_id: str) -> dict[str, Any] | None:
        session = self._sessions.get(session_id)
        if session is None:
            return None
        async with self._lock:
            await self._cancel_session(session)
        return session.snapshot()

    async def shutdown(self) -> None:
        async with self._lock:
            for session in list(self._sessions.values()):
                await self._cancel_session(session)
            self._sessions.clear()
        if self._client is not None and not self._client.is_closed:
            await self._client.aclose()
        self._client = None

    # ---------- 内部：取消与清理 ----------

    async def _cancel_session(self, session: RegistrationSession) -> None:
        if session.status in _TERMINAL_STATUSES:
            return
        self._finish(session, STATUS_CANCELLED)
        session.cancel_event.set()
        task = session.task
        if task is not None and not task.done():
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
        session.task = None

    async def _cancel_channel_sessions(self, channel_id: str) -> None:
        for session in list(self._sessions.values()):
            if session.channel_id == channel_id and session.status not in _TERMINAL_STATUSES:
                await self._cancel_session(session)

    def _sweep(self) -> None:
        now = time.time()
        for session_id, session in list(self._sessions.items()):
            if session.status in _TERMINAL_STATUSES and now - session.updated_at > SESSION_TTL_SECONDS:
                self._sessions.pop(session_id, None)

    @staticmethod
    def _finish(session: RegistrationSession, status: str, *, error: str | None = None) -> None:
        session.status = status
        session.error = error
        session.updated_at = time.time()

    @staticmethod
    async def _pause(session: RegistrationSession, seconds: float) -> None:
        try:
            await asyncio.wait_for(session.cancel_event.wait(), timeout=max(0.0, seconds))
        except TimeoutError:
            pass

    # ---------- 内部：轮询状态机 ----------

    async def _poll_loop(
        self,
        session: RegistrationSession,
        on_success: SuccessCallback,
    ) -> None:
        domain = FEISHU_ACCOUNTS_URL
        domain_switched = False
        interval = session.interval

        while True:
            if session.cancel_event.is_set():
                if session.status not in _TERMINAL_STATUSES:
                    self._finish(session, STATUS_CANCELLED)
                return
            remaining = session.expires_at - time.time()
            if remaining <= 0:
                self._finish(session, STATUS_TIMEOUT)
                return

            try:
                data = await self._post(
                    domain,
                    {"action": "poll", "device_code": session.device_code, "tp": QR_TP},
                )
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                # 网络抖动不终止流程：继续轮询（与 OpenClaw 的容错策略一致）。
                logger.warning(
                    "飞书注册轮询请求失败 session=%s error=%s",
                    session.session_id,
                    _safe_error(exc),
                )
                await self._pause(session, min(interval, session.expires_at - time.time()))
                continue

            user_info = data.get("user_info")
            if not isinstance(user_info, dict):
                user_info = {}

            # 检测到 Lark 租户：切域名后立即重试一次。
            if user_info.get("tenant_brand") == "lark" and not domain_switched:
                domain = LARK_ACCOUNTS_URL
                domain_switched = True
                continue

            client_id = data.get("client_id")
            client_secret = data.get("client_secret")
            if client_id and client_secret:
                session.app_id = str(client_id)
                session.open_id = user_info.get("open_id") or None
                session.updated_at = time.time()
                session.status = STATUS_SUCCESS
                try:
                    await on_success(
                        session.channel_id, str(client_id), str(client_secret), session.open_id
                    )
                except asyncio.CancelledError:
                    raise
                except Exception as exc:
                    logger.exception("飞书注册凭据落库失败 channel=%s", session.channel_id)
                    self._finish(session, STATUS_ERROR, error=f"凭据写入失败：{_safe_error(exc)}")
                return

            error = str(data.get("error") or "")
            if error == "slow_down":
                interval = min(interval + SLOW_DOWN_INCREMENT_SECONDS, MAX_POLL_INTERVAL_SECONDS)
            elif error == "access_denied":
                self._finish(session, STATUS_DENIED)
                return
            elif error == "expired_token":
                self._finish(session, STATUS_EXPIRED)
                return
            elif error and error != "authorization_pending":
                description = str(data.get("error_description") or "")
                self._finish(session, STATUS_ERROR, error=f"{error}: {description}".strip(": "))
                return

            session.updated_at = time.time()
            await self._pause(session, min(interval, session.expires_at - time.time()))


registration_service = AppRegistrationService()
