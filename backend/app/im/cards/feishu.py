"""飞书卡片：投放与流式更新（CardKit）。

与钉钉最关键的两点差别，直接决定这里的实现方式：

1. **不需要模板**。钉钉得先去卡片平台建模板、拿 ``template_id``、还要猜对文本
   变量名；飞书的卡片 JSON 直接在代码里构造，所以本模块不读任何模板配置。
2. **打字机由服务端渲染**。钉钉是客户端不打字、靠 N 次接口调用"演"出打字效果；
   飞书只要把全量文本推上去，平台按卡片里的 ``streaming_config`` 逐字上屏。
   所以我们**不**用调用频率去控制观感 —— 那是卡片配置项的事。

协议依据（2026-09-22 真机实测，见 ``docs/飞书流式与等待回复调研.md``）：

- 四步流程：``POST /cardkit/v1/cards`` 建卡实体 → ``POST /im/v1/messages``
  （或 ``/messages/:id/reply``）发卡 → ``PUT /cardkit/v1/cards/:id/elements/
  :element_id/content`` 推全量 → ``PATCH /cardkit/v1/cards/:id/settings``
  关 ``streaming_mode``。
- ``sequence`` 在**同一张卡片的所有操作间共享**，必须严格递增 —— 这点与钉钉
  "每次新生成 guid、彼此独立"完全不同，所以这里用一个自增计数器统一管。
- **前缀规则**：新文本以旧文本为前缀才有打字机效果，否则整屏直出。我们的初始
  文案是「正在处理」，与最终回复无前缀关系，因此**第一次更新必然整屏直出**，
  之后的每次更新（累积全量、天然前缀）才是打字机。这是协议行为，不是缺陷。
- 元素 ``content`` 文档上限 100000 字符，卡片体积文档建议 30KB。实测（真发送）
  15000 字符（43.9KB）、88KB 卡 JSON 均正常通过，故**飞书侧不设人工截断**。
  真触发体积超限时收尾会抛错，Worker 会退回文本补发，用户仍拿得到结果。
- 卡片实体有效期 14 天；``uuid`` 是幂等键，这里由 ``(card_id, sequence)``
  确定性派生（``s_``/``c_`` 前缀），因为所有操作共享同一个自增 sequence、
  本就不会撞。
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import time
from collections.abc import Mapping
from typing import Any

from app.im.cards import ThrottlePolicy, merge_streaming_text
from app.im.credentials import ChannelCredential

logger = logging.getLogger("app.im.feishu.card")

API_BASE = "https://open.feishu.cn/open-apis"
TOKEN_API = f"{API_BASE}/auth/v3/tenant_access_token/internal"
CARD_CREATE_API = f"{API_BASE}/cardkit/v1/cards"

SCHEMA_VERSION = "2.0"
# 卡片的文本元素 ID；流式更新就打在它身上。由开发者自定义。
ELEMENT_ID_CONTENT = "content"

# 会话列表 / 消息预览里显示的文案。流式期间固定这个，收尾时换成正文摘要，
# 否则用户会在聊天列表里一直看到一个「生成中」。
SUMMARY_GENERATING = "[生成中...]"
SUMMARY_MAX_CHARS = 50

# 打字机密度是**卡片配置**，不是代码参数：我们只管发全量，逐字上屏由平台渲染。
#
# 上屏速率 = print_step / print_frequency_ms。**它必须 ≥ 模型产出速率**，
# 否则每次推送都要把积压的那一段"追赶"上屏（官方 `fast` 策略的行为），
# 观感就是「打几个字 → 蹦出一段」。
#
# 这里不取理论值，取真机实测值（data/db/traces.db 的 llm 事件）：
#
#   回复字数    LLM 耗时    产出速率
#     425 字     2.07s     206 字/秒
#     790 字     3.01s     262 字/秒
#     294 字     2.19s     134 字/秒
#
# 也就是 **模型 2 秒左右就把整条回复吐完**，而 OpenClaw 沿用的 1 字/50ms
# = 20 字/秒 只有它的十分之一 —— 425 字要让打字机打完得 21 秒，收尾关流式时
# 必然有 380 多字整块落地。所以默认取 **8 字/20ms = 400 字/秒**，留出约一倍余量：
# 上屏速率一旦快于模型，就不存在积压，观感等于"随模型产出逐字浮现"。
#
# 调这两个值不省也不费任何接口调用，纯观感；模型明显更快时可再调大
# （IM_FEISHU_PRINT_STEP 每 +1 约 +50 字/秒）。注意飞书要求**两个字段必须成对
# 出现**，只给一个会报 11311 printFrequencyMs or printStep is nil。
PRINT_FREQUENCY_MS = 20
PRINT_STEP = 8
# 关流式会终止打字机，收尾前最多留这么久让上屏追平（见 _let_typewriter_catch_up）。
CATCHUP_MAX_SECONDS = 2.0
# 显式写出 fast：客户端各版本的默认值可能不同，官方也建议"前置指定流式参数"。
PRINT_STRATEGY = "fast"
ENV_PRINT_FREQUENCY_MS = "IM_FEISHU_PRINT_FREQUENCY_MS"
ENV_PRINT_STEP = "IM_FEISHU_PRINT_STEP"

# tenant_access_token 有效期 7200 秒；提前刷新，避免边界上刚好过期。
TOKEN_REFRESH_MARGIN_SECONDS = 300.0
_MIN_TOKEN_LIFETIME_SECONDS = 60.0

# 进程内 token 缓存：app_id -> (token, monotonic 到期时间)。
_TOKEN_CACHE: dict[str, tuple[str, float]] = {}

# 飞书卡片的 markdown 表格数量限制。照 OpenClaw 的做法保留：他们的生产日志里
# 有 ``230099 / ErrCode: 11310 / card table number over limit`` 的实证。
# 注意我们自己的真机实测**没能复现**（10 张表格、真发送也正常），所以这是纯
# 防御性的 —— 代价只是超出部分的表格降级成代码块，仍然可读。
FEISHU_CARD_TABLE_LIMIT = 3

# markdown 表格：表头行 + 分隔行 + 后续以 ``|`` 开头的行。
_TABLE_RE = re.compile(r"\|.+\|[\r\n]+\|[-:| ]+\|[\s\S]*?(?=\n\n|\n(?!\|)|\Z)")
_CODE_BLOCK_RE = re.compile(r"```[\s\S]*?```")


def reset_token_cache() -> None:
    """清空进程内 token 缓存（测试、凭据轮换后使用）。"""
    _TOKEN_CACHE.clear()


class FeishuCardError(RuntimeError):
    """卡片链路错误；``code`` 是飞书的业务错误码，供排障与降级判定。"""

    def __init__(self, message: str, *, code: int | None = None, status_code: int | None = None):
        super().__init__(message)
        self.code = code
        self.status_code = status_code


def _json(response: Any) -> Mapping[str, Any]:
    try:
        payload = response.json()
    except Exception:
        return {}
    return payload if isinstance(payload, Mapping) else {}


def _succeeded(response: Any, payload: Mapping[str, Any]) -> bool:
    """飞书统一用 ``code`` 表达成败：0 成功，非 0 失败（HTTP 也可能是 200）。"""
    if getattr(response, "status_code", 0) >= 400:
        return False
    return int(payload.get("code") or 0) == 0


async def tenant_access_token(http: Any, credential: ChannelCredential) -> str:
    now = time.monotonic()
    cached = _TOKEN_CACHE.get(credential.app_id)
    if cached is not None and cached[1] > now:
        return cached[0]

    response = await http.post(
        TOKEN_API,
        json={"app_id": credential.app_id, "app_secret": credential.app_secret},
    )
    payload = _json(response)
    token = str(payload.get("tenant_access_token") or "").strip()
    if not _succeeded(response, payload) or not token:
        # 不回显响应体：它可能包含应用标识，排障看 debug 日志即可。
        logger.debug(
            "Feishu tenant_access_token failed channel=%s http=%s code=%s",
            credential.channel_id,
            getattr(response, "status_code", None),
            payload.get("code"),
        )
        raise FeishuCardError(
            "飞书 tenant_access_token 获取失败",
            code=payload.get("code"),
            status_code=getattr(response, "status_code", None),
        )

    expire = payload.get("expire")
    lifetime = float(expire) if isinstance(expire, (int, float)) else 7200.0
    ttl = max(lifetime - TOKEN_REFRESH_MARGIN_SECONDS, _MIN_TOKEN_LIFETIME_SECONDS)
    _TOKEN_CACHE[credential.app_id] = (token, now + ttl)
    return token


def find_markdown_tables_outside_code_blocks(text: str) -> list[tuple[int, int, str]]:
    """定位正文里**会被卡片渲染**的 markdown 表格，返回 ``(起点, 长度, 原文)``。

    代码块里的示例表格不会被飞书解析成卡片表格元素，所以要先排除 —— 预检与
    降级必须用同一份结果，否则会出现"预检说没超、降级却改了别处"。
    """
    ranges = [(m.start(), m.end()) for m in _CODE_BLOCK_RE.finditer(text)]

    def inside_code_block(index: int) -> bool:
        return any(start <= index < end for start, end in ranges)

    return [
        (m.start(), len(m.group(0)), m.group(0))
        for m in _TABLE_RE.finditer(text)
        if not inside_code_block(m.start())
    ]


def sanitize_markdown_for_card(text: str, limit: int = FEISHU_CARD_TABLE_LIMIT) -> str:
    """把超出 ``limit`` 的 markdown 表格用代码块包起来，阻止被解析成卡片表格。

    前 ``limit`` 张保持原样（仍以真表格渲染），超出的部分退化为代码块 —— 内容
    一个字不丢，只是不再是"表格样式"。这是为了绕开可能的
    ``230099 / 11310 card table number over limit``。
    """
    matches = find_markdown_tables_outside_code_blocks(text)
    if len(matches) <= limit:
        return text

    # 从后往前替换，避免前面的替换让后面的下标失效。
    result = text
    for index, length, raw in reversed(matches[limit:]):
        result = result[:index] + f"```\n{raw}\n```" + result[index + length:]
    return result


def truncate_summary(text: str, limit: int = SUMMARY_MAX_CHARS) -> str:
    """会话列表预览文案：压成单行并截断。"""
    if not text:
        return ""
    clean = " ".join(text.split())
    if len(clean) <= limit:
        return clean
    return clean[: max(limit - 3, 0)] + "..."


def _positive_int(name: str, fallback: int) -> int:
    """读一个正整数环境变量；缺失/非法/非正数都退回默认值并记日志。

    静默吞掉一个写错的值比报错更难查 —— 卡片照常发出去，只是观感没变。
    """
    raw = os.environ.get(name, "").strip()
    if not raw:
        return fallback
    try:
        value = int(raw)
    except ValueError:
        logger.warning("飞书打字机配置不是整数，已忽略 %s=%r", name, raw)
        return fallback
    if value < 1:
        logger.warning("飞书打字机配置需 ≥1，已忽略 %s=%r", name, raw)
        return fallback
    return value


def print_config() -> tuple[int, int]:
    """返回 ``(print_frequency_ms, print_step)``，可由环境变量覆盖。"""
    return (
        _positive_int(ENV_PRINT_FREQUENCY_MS, PRINT_FREQUENCY_MS),
        _positive_int(ENV_PRINT_STEP, PRINT_STEP),
    )


def print_rate_chars_per_second() -> float:
    """当前配置对应的上屏速率（字/秒），用于估算收尾该等多久。"""
    frequency_ms, step = print_config()
    return step / frequency_ms * 1000.0


def build_streaming_card_json(initial_text: str) -> dict[str, Any]:
    """构造开启流式模式的卡片 JSON（2.0 结构）。

    初始文案随建卡一次性写入，所以卡片一出现就带「正在处理」，不需要额外一条
    提示消息 —— 这与钉钉侧「投放时直接带初始文案」是同一个思路。
    """
    frequency_ms, step = print_config()
    return {
        "schema": SCHEMA_VERSION,
        "config": {
            "streaming_mode": True,
            "summary": {"content": SUMMARY_GENERATING},
            "streaming_config": {
                "print_frequency_ms": {"default": frequency_ms},
                "print_step": {"default": step},
                "print_strategy": PRINT_STRATEGY,
            },
        },
        "body": {
            "elements": [
                {"tag": "markdown", "content": initial_text, "element_id": ELEMENT_ID_CONTENT}
            ]
        },
    }


class FeishuCardSession:
    """一张卡片从投放到收尾的完整生命周期（与 ``DingtalkCardSession`` 同形）。

    ``push`` 是尽力而为的旁路（失败只记日志，收尾那次会把全量内容再推一遍），
    ``open`` / ``finalize`` 的失败必须让调用方知道 —— 用户拿不到结果时要能降级。
    """

    def __init__(
        self,
        *,
        http: Any,
        credential: ChannelCredential,
        receive_id: str,
        receive_id_type: str = "chat_id",
        reply_to: str | None = None,
        policy: ThrottlePolicy,
    ):
        self._http = http
        self._credential = credential
        self._receive_id = receive_id
        self._receive_id_type = receive_id_type or "chat_id"
        self._reply_to = reply_to
        self._policy = policy

        # 卡片会话的对外标识就是 card_id（钉钉那边是自生成的 outTrackId）。
        self.card_id = ""
        self.out_track_id = ""
        self.opened = False
        self.finalized = False
        # 已发出的中间更新次数（不含投放），用于观测与配额核账。
        self.update_count = 0

        # sequence 全链路共享、必须严格递增；建卡算第 1 次操作。
        self._sequence = 1
        # ``_text`` 是**合并基线**：只装真正推给卡片的答案文本，绝不包含初始文案。
        #
        # 这一点很容易写错：初始文案是「正在处理，请稍候…」，与答案没有任何前缀
        # 关系，若把它当基线去合并，merge 的兜底分支会把两者拼成
        # 「正在处理，请稍候…答案」。所以基线从空串起步 —— 与 OpenClaw 把
        # ``currentText`` 初始化成 ``""`` 是同一个理由。
        self._text = ""
        # ``_pushed`` 是卡片上当前**实际显示**的内容（初始文案或某次更新后的正文）。
        self._pushed = ""
        self._last_push_at = 0.0

    def _headers(self, token: str) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json; charset=utf-8",
        }

    async def open(self, initial_text: str) -> None:
        """建卡并投放。失败抛 ``FeishuCardError``，由调用方降级为文本回复。

        初始文案在**建卡时**就写进元素里，所以卡片出现即带「正在处理」。
        """
        display = sanitize_markdown_for_card(initial_text)
        token = await tenant_access_token(self._http, self._credential)

        created = await self._http.post(
            CARD_CREATE_API,
            headers=self._headers(token),
            json={
                "type": "card_json",
                "data": json.dumps(build_streaming_card_json(display), ensure_ascii=False),
            },
        )
        payload = _json(created)
        card_id = str((payload.get("data") or {}).get("card_id") or "")
        if not _succeeded(created, payload) or not card_id:
            raise FeishuCardError(
                f"飞书卡片实体创建失败：code={payload.get('code')}",
                code=payload.get("code"),
                status_code=getattr(created, "status_code", None),
            )
        self.card_id = card_id
        self.out_track_id = card_id

        card_ref = json.dumps({"type": "card", "data": {"card_id": card_id}}, ensure_ascii=False)
        if self._reply_to:
            # 优先回复用户那条消息：卡片落在原话题里，上下文不断。
            sent = await self._http.post(
                f"{API_BASE}/im/v1/messages/{self._reply_to}/reply",
                headers=self._headers(token),
                json={"msg_type": "interactive", "content": card_ref},
            )
        else:
            sent = await self._http.post(
                f"{API_BASE}/im/v1/messages",
                headers=self._headers(token),
                params={"receive_id_type": self._receive_id_type},
                json={
                    "receive_id": self._receive_id,
                    "msg_type": "interactive",
                    "content": card_ref,
                },
            )
        payload = _json(sent)
        if not _succeeded(sent, payload):
            raise FeishuCardError(
                f"飞书卡片发送失败：code={payload.get('code')}",
                code=payload.get("code"),
                status_code=getattr(sent, "status_code", None),
            )

        self.opened = True
        # 初始文案只记到 ``_pushed``（卡片上显示的就是它），不进合并基线。
        self._pushed = display

    def _should_push(self, text: str) -> bool:
        policy = self._policy
        limit = policy.max_updates
        if limit == 0:
            # 0 = 明确不做中间更新（两态档），只投放与收尾各一次。
            return False
        if limit is not None and self.update_count >= limit:
            # None = 不限次数；此时速率完全由 min_interval_seconds 兜住。
            return False
        if len(text) - len(self._text) < policy.min_delta_chars:
            return False
        return (time.monotonic() - self._last_push_at) >= policy.min_interval_seconds

    async def push(self, text: str) -> None:
        """按节流策略推送全量内容；异常只记日志，绝不打断员工执行。"""
        if not self.opened or self.finalized:
            return
        merged = merge_streaming_text(self._text, text)
        if not self._should_push(merged):
            return
        display = sanitize_markdown_for_card(merged)
        if display == self._pushed:
            # 内容没变就不发 —— 一次调用只为了推同样的文本是纯浪费。
            self._text = merged
            return
        try:
            await self._put_content(display)
        except Exception as exc:
            logger.warning("飞书卡片流式更新失败 card=%s error=%s", self.card_id, exc)
            return
        self.update_count += 1
        self._text = merged
        self._pushed = display
        self._last_push_at = time.monotonic()

    async def finalize(self, text: str) -> bool:
        """收尾：写入最终结果并关闭流式模式；返回**内容是否被截断**。

        飞书侧不截断（元素 content 文档上限 100000 字符，实测 15000 字符与 88KB
        卡 JSON 均通过），所以恒返回 ``False``。返回值存在的意义是与
        ``DingtalkCardSession`` 保持同一契约，让 Worker 不必关心渠道差异。

        失败必须抛出去 —— 调用方要据此改用文本消息补发，不能静默丢结果。
        """
        if not self.opened:
            raise FeishuCardError("卡片尚未投放，无法收尾")
        merged = merge_streaming_text(self._text, text)
        display = sanitize_markdown_for_card(merged)
        if display != self._pushed:
            # 收尾这次无论如何都要写，不受节流约束。
            previous_len = len(self._pushed)
            await self._put_content(display)
            self._text = merged
            self._pushed = display
            await self._let_typewriter_catch_up(previous_len)
        await self._close_streaming(merged)
        self.finalized = True
        return False

    async def _let_typewriter_catch_up(self, previous_len: int) -> None:
        """关流式前留一点时间让上屏追平，避免最后一段整块落地。

        收尾是「写全量 → 立刻关流式」，而关流式会终止打字机 —— 这次写入新增的
        字符若还没打完，就会在这一刻一次性出现。等待时间按
        ``新增字数 / 上屏速率`` 估算，上限 ``CATCHUP_MAX_SECONDS``：
        这是观感优化，不该拖着回复不交付。

        只对**已有过中间推送**的卡片有意义：首次写入与初始文案没有前缀关系，
        属协议规定的全屏直出，不存在"未上屏"的部分。
        """
        if self.update_count <= 0:
            return
        pending = len(self._pushed) - previous_len
        rate = print_rate_chars_per_second()
        if pending <= 0 or rate <= 0:
            return
        await asyncio.sleep(min(pending / rate, CATCHUP_MAX_SECONDS))

    async def fail(self, text: str) -> None:
        """把卡片标为失败态；失败本身不再向上抛。

        即使内容写不进去，也要尽力关掉流式模式 —— 否则卡片会一直停在「生成中」，
        比显示一句失败文案更让人困惑。
        """
        if not self.opened or self.finalized:
            return
        try:
            await self._put_content(sanitize_markdown_for_card(text))
        except Exception as exc:
            logger.warning("飞书卡片失败态内容更新失败 card=%s error=%s", self.card_id, exc)
        try:
            await self._close_streaming(text)
        except Exception as exc:
            logger.warning("飞书卡片失败态收尾失败 card=%s error=%s", self.card_id, exc)
        finally:
            self.finalized = True

    async def _put_content(self, content: str) -> None:
        """推全量内容；失败抛 ``FeishuCardError``。"""
        self._sequence += 1
        token = await tenant_access_token(self._http, self._credential)
        response = await self._http.put(
            f"{CARD_CREATE_API}/{self.card_id}/elements/{ELEMENT_ID_CONTENT}/content",
            headers=self._headers(token),
            json={
                "content": content,
                "sequence": self._sequence,
                "uuid": f"s_{self.card_id}_{self._sequence}",
            },
        )
        payload = _json(response)
        if not _succeeded(response, payload):
            raise FeishuCardError(
                f"飞书卡片更新失败：code={payload.get('code')}",
                code=payload.get("code"),
                status_code=getattr(response, "status_code", None),
            )

    async def _close_streaming(self, summary_text: str) -> None:
        """关闭流式模式，并把会话列表预览换成正文摘要。失败抛 ``FeishuCardError``。"""
        self._sequence += 1
        token = await tenant_access_token(self._http, self._credential)
        settings = json.dumps(
            {
                "config": {
                    "streaming_mode": False,
                    "summary": {"content": truncate_summary(summary_text)},
                }
            },
            ensure_ascii=False,
        )
        response = await self._http.patch(
            f"{CARD_CREATE_API}/{self.card_id}/settings",
            headers=self._headers(token),
            json={
                "settings": settings,
                "sequence": self._sequence,
                "uuid": f"c_{self.card_id}_{self._sequence}",
            },
        )
        payload = _json(response)
        if not _succeeded(response, payload):
            raise FeishuCardError(
                f"飞书卡片收尾失败：code={payload.get('code')}",
                code=payload.get("code"),
                status_code=getattr(response, "status_code", None),
            )
