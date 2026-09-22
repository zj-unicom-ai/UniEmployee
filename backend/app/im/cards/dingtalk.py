"""钉钉 AI 卡片：投放与流式更新（OpenAPI）。

协议依据（2026-09-21 / 09-22 真机实测，见 ``docs/钉钉接入开发计划.md`` §0.2）：
``POST /v1.0/card/instances/createAndDeliver`` 投放，``PUT /v1.0/card/streaming``
更新。三条硬约束直接决定实现方式：

1. 每次更新必须发**全量**内容（``isFull=true``），服务端据此重做 markdown 转换；
2. ``guid`` 每次必须新生成（服务端幂等键），复用会导致后续更新被静默吞掉；
3. ``key`` 必须与卡片模板里的文本变量名逐字一致 —— 不存在的 key 会让流式更新
   返回 500，而投放阶段对多余的 ``cardParamMap`` 键是静默忽略的，所以变量名
   只能从流式阶段的表现反推。

鉴权与 Stream 出站是两套：出站回复走入站消息携带的 sessionWebhook，无需 token；
卡片走 OpenAPI，需要 accessToken。token 按 appId 在进程内缓存，提前刷新。
"""

from __future__ import annotations

import logging
import time
import uuid
from collections.abc import Mapping
from typing import Any

from app.im.cards import ThrottlePolicy, clamp_card_content
from app.im.credentials import ChannelCredential

logger = logging.getLogger("app.im.dingtalk.card")

OPENAPI_BASE = "https://api.dingtalk.com"
TOKEN_API = f"{OPENAPI_BASE}/v1.0/oauth2/accessToken"
CREATE_API = f"{OPENAPI_BASE}/v1.0/card/instances/createAndDeliver"
STREAM_API = f"{OPENAPI_BASE}/v1.0/card/streaming"

SPACE_TYPE_ROBOT = "IM_ROBOT"
SPACE_TYPE_GROUP = "IM_GROUP"

# 卡片模板里的文本变量名。必须与模板严格一致，否则流式更新 500。
TEMPLATE_CONTENT_KEY = "content"

# accessToken 有效期 7200 秒；提前刷新，避免边界上刚好过期。
TOKEN_REFRESH_MARGIN_SECONDS = 300.0
_MIN_TOKEN_LIFETIME_SECONDS = 60.0

# 进程内 token 缓存：appId -> (token, monotonic 到期时间)。
# 不用锁：并发未命中时最坏重复取一次 token，代价远小于跨事件循环持锁的风险。
_TOKEN_CACHE: dict[str, tuple[str, float]] = {}


def reset_token_cache() -> None:
    """清空进程内 token 缓存（测试、凭据轮换后使用）。"""
    _TOKEN_CACHE.clear()


class DingtalkCardError(RuntimeError):
    """卡片链路错误；``status_code`` 供调用方判断是否值得重试或降级。"""

    def __init__(self, message: str, *, status_code: int | None = None):
        super().__init__(message)
        self.status_code = status_code


def _json(response: Any) -> Any:
    try:
        return response.json()
    except Exception:
        return {}


def _as_mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _succeeded(response: Any, payload: Any) -> bool:
    """钉钉成功时可能回 ``{"success": true}``，也可能只回业务体。"""
    if getattr(response, "status_code", 0) >= 400:
        return False
    return _as_mapping(payload).get("success") is not False


async def _access_token(http: Any, credential: ChannelCredential) -> str:
    now = time.monotonic()
    cached = _TOKEN_CACHE.get(credential.app_id)
    if cached is not None and cached[1] > now:
        return cached[0]

    response = await http.post(
        TOKEN_API,
        json={"appKey": credential.app_id, "appSecret": credential.app_secret},
    )
    payload = _as_mapping(_json(response))
    token = str(payload.get("accessToken") or "").strip()
    if getattr(response, "status_code", 0) >= 400 or not token:
        # 不回显响应体：它可能包含应用标识，排障看 debug 日志即可。
        logger.debug(
            "DingTalk accessToken failed channel=%s http=%s",
            credential.channel_id,
            getattr(response, "status_code", None),
        )
        raise DingtalkCardError(
            "钉钉 accessToken 获取失败",
            status_code=getattr(response, "status_code", None),
        )

    expire = payload.get("expireIn")
    lifetime = float(expire) if isinstance(expire, (int, float)) else 7200.0
    ttl = max(lifetime - TOKEN_REFRESH_MARGIN_SECONDS, _MIN_TOKEN_LIFETIME_SECONDS)
    _TOKEN_CACHE[credential.app_id] = (token, now + ttl)
    return token


class DingtalkCardSession:
    """一张卡片从投放到收尾的完整生命周期。

    ``push`` 是尽力而为的旁路（失败只记日志，收尾那次会把全量内容再推一遍），
    ``open`` / ``finalize`` 的失败必须让调用方知道 —— 用户拿不到结果时要能降级。
    """

    def __init__(
        self,
        *,
        http: Any,
        credential: ChannelCredential,
        template_id: str,
        space_type: str,
        space_id: str,
        policy: ThrottlePolicy,
        robot_code: str = "",
    ):
        self._http = http
        self._credential = credential
        self._template_id = template_id
        self._space_type = space_type
        self._space_id = space_id
        self._policy = policy
        # 群聊场域需要 robotCode，取值与应用 clientId 相同。
        self._robot_code = robot_code or credential.app_id

        self.out_track_id = "uniemployee-" + uuid.uuid4().hex[:24]
        self.opened = False
        self.finalized = False
        # 已发出的中间更新次数（不含投放），用于观测与配额核账。
        self.update_count = 0
        self._last_text = ""
        self._last_push_at = 0.0

    @property
    def open_space_id(self) -> str:
        return f"dtv1.card//{self._space_type}.{self._space_id}"

    def _headers(self, token: str) -> dict[str, str]:
        return {
            "x-acs-dingtalk-access-token": token,
            "Content-Type": "application/json",
        }

    async def open(self, initial_text: str) -> None:
        """投放卡片。失败抛 ``DingtalkCardError``，由调用方降级为文本回复。

        初始文案随 ``cardParamMap`` 一起投出：卡片一出现就带「正在处理」，
        不需要额外一条提示消息。
        """
        token = await _access_token(self._http, self._credential)
        content, _ = clamp_card_content(initial_text)
        body: dict[str, Any] = {
            "cardTemplateId": self._template_id,
            "outTrackId": self.out_track_id,
            "cardData": {"cardParamMap": {TEMPLATE_CONTENT_KEY: content}},
            "openSpaceId": self.open_space_id,
        }
        if self._space_type == SPACE_TYPE_GROUP:
            body["imGroupOpenDeliverModel"] = {"robotCode": self._robot_code}
            body["imGroupOpenSpaceModel"] = {"supportForward": False}
        else:
            body["imRobotOpenDeliverModel"] = {"spaceType": SPACE_TYPE_ROBOT}
            body["imRobotOpenSpaceModel"] = {"supportForward": False}

        response = await self._http.post(CREATE_API, headers=self._headers(token), json=body)
        payload = _json(response)
        if not _succeeded(response, payload):
            raise DingtalkCardError(
                f"钉钉卡片投放失败：http={getattr(response, 'status_code', None)}",
                status_code=getattr(response, "status_code", None),
            )
        self.opened = True
        self._last_text = initial_text

    def _should_push(self, text: str) -> bool:
        policy = self._policy
        if policy.max_updates <= 0 or self.update_count >= policy.max_updates:
            return False
        if len(text) - len(self._last_text) < policy.min_delta_chars:
            return False
        return (time.monotonic() - self._last_push_at) >= policy.min_interval_seconds

    async def push(self, text: str) -> None:
        """按节流策略推送全量内容；异常只记日志，绝不打断员工执行。"""
        if not self.opened or self.finalized or not self._should_push(text):
            return
        try:
            # 中间推送不带「结果另发」提示：执行中还没有补发这回事。
            await self._stream(text, finalize=False, is_error=False, notice=False)
        except Exception as exc:
            logger.warning(
                "钉钉卡片流式更新失败 track=%s error=%s", self.out_track_id, exc
            )
            return
        self.update_count += 1
        self._last_text = text
        self._last_push_at = time.monotonic()

    async def finalize(self, text: str) -> bool:
        """收尾：写入最终结果并让卡片转入「完成」态；返回**内容是否被截断**。

        返回值决定 Worker 要不要再补一条文本消息，所以它必须如实反映卡片里
        到底有没有被裁。失败则抛出去 —— 调用方要据此改用文本补发，不能静默丢结果。
        """
        if not self.opened:
            raise DingtalkCardError("卡片尚未投放，无法收尾")
        _, truncated = clamp_card_content(text)
        await self._stream(text, finalize=True, is_error=False)
        self.finalized = True
        return truncated

    async def fail(self, text: str) -> None:
        """把卡片标记为失败态；失败本身不再向上抛。"""
        if not self.opened or self.finalized:
            return
        try:
            await self._stream(text, finalize=True, is_error=True)
        except Exception as exc:
            logger.warning(
                "钉钉卡片失败态更新失败 track=%s error=%s", self.out_track_id, exc
            )
        finally:
            self.finalized = True

    async def _stream(
        self, text: str, *, finalize: bool, is_error: bool, notice: bool = True
    ) -> None:
        token = await _access_token(self._http, self._credential)
        content, _ = clamp_card_content(text, with_notice=notice)
        body = {
            "outTrackId": self.out_track_id,
            # 每次必须新生成：服务端用它做幂等，复用会让后续更新被吞掉。
            "guid": uuid.uuid4().hex,
            "key": TEMPLATE_CONTENT_KEY,
            "content": content,
            "isFull": True,
            "isFinalize": finalize,
            "isError": is_error,
        }
        response = await self._http.put(STREAM_API, headers=self._headers(token), json=body)
        payload = _json(response)
        if not _succeeded(response, payload):
            raise DingtalkCardError(
                f"钉钉卡片更新失败：http={getattr(response, 'status_code', None)}",
                status_code=getattr(response, "status_code", None),
            )
