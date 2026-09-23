"""AI 卡片会话：把「一次回复」表达为一张会原地演进的卡片。

卡片与普通消息的差别不只是好看：钉钉的文本消息发出后**不能原地修改**，
所以「已收到 → 结果」这种过程只能用两条消息硬凑。卡片可以更新，因此同一张
卡片能从「处理中」一路演进到最终结果，用户侧只看到一条消息。

代价是接口调用量：一次回复消耗 ``1 次投放 + N 次更新``，N 由这里的节流档位
决定。档位是可配的，配额紧张时降档即可，不需要改代码。
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from typing import Any

logger = logging.getLogger("app.im.cards")

LEVEL_STREAM = "stream"
LEVEL_STAGED = "staged"
LEVEL_TWO_STATE = "two_state"
DEFAULT_LEVEL = LEVEL_STAGED

LEVEL_LABELS: dict[str, str] = {
    LEVEL_STREAM: "真流式（调用量最高）",
    LEVEL_STAGED: "阶段式（默认）",
    LEVEL_TWO_STATE: "两态（最省调用量）",
}


@dataclass(frozen=True, slots=True)
class ThrottlePolicy:
    """流式推送的节流参数，直接决定一次回复的接口调用次数。

    - ``min_interval_seconds``：两次更新之间的最小间隔；
    - ``min_delta_chars``：相对上次推送至少新增多少字符才值得再推一次；
    - ``max_updates``：单次回复的中间更新次数上限。三档语义 ——
      ``None`` 表示**不限次数**（速率完全交给 ``min_interval_seconds`` 管），
      ``0`` 表示**不做任何中间更新**（只投放与收尾），正数表示硬上限。
    """

    min_interval_seconds: float
    min_delta_chars: int
    max_updates: int | None


POLICIES: dict[str, ThrottlePolicy] = {
    # 0.4s 一次（≈2.5 次/秒），**不限次数**：上限交给间隔去管，速率仍在飞书
    # 「单卡片 10 次/秒」之内。飞书默认用这一档，理由见 CHANNEL_DEFAULT_LEVELS。
    LEVEL_STREAM: ThrottlePolicy(0.4, 1, None),
    # 约 4~7 次/回复，与标准版入站额度同量级；为配额敏感的渠道（钉钉）保留。
    LEVEL_STAGED: ThrottlePolicy(2.0, 32, 6),
    # 只投放与收尾各一次，中间不更新。
    LEVEL_TWO_STATE: ThrottlePolicy(0.0, 0, 0),
}

# 渠道默认档位。没有条目就用 DEFAULT_LEVEL。
#
# 这个表存在的原因是「同一个档位在不同渠道的代价不同」：
#
# - 飞书：官方明示**流式更新模式下不触发接口 QPS 限制**（只需守单卡片 10 次/秒），
#   所以"省调用次数"在这里没有收益。而 `staged` 的 `max_updates=6` 会把回复的
#   后半段变成**长时间不更新**，收尾那次 PUT 再一口气把攒下的内容甩上屏 ——
#   用户看到的就是「打几个字 → 卡住 → 一大段突然蹦出来」。
# - 钉钉：入站额度是真的要省，所以仍用 `staged`。
# - 企业微信：流式刷新同样是「同 id 全量替换」，官方只在**会话级**限流
#   （30 条/分钟、1000 条/小时），不按帧计费。也就是说"省调用次数"在这里没有收益，
#   而 `staged` 的 `max_updates=6` 会重演飞书那个「打几个字 → 卡住 → 一大段突然
#   蹦出来」的观感问题，所以也用 `stream`。
CHANNEL_DEFAULT_LEVELS: dict[str, str] = {
    "feishu": LEVEL_STREAM,
    "wecom": LEVEL_STREAM,
}


def policy_for(level: str) -> ThrottlePolicy:
    return POLICIES.get(level, POLICIES[DEFAULT_LEVEL])


def level_label(level: str) -> str:
    return LEVEL_LABELS.get(level, level)


# 卡片正文长度上限（**钉钉专用**）。
#
# 飞书不适用：它的元素 content 文档上限是 100000 字符，真机实测 15000 字符
# （43.9KB）乃至 88KB 的卡 JSON 都能正常发送，所以飞书侧不做人工截断 ——
# 硬套这里的 3000 会把飞书的长回复误判成超长，重演钉钉那次「卡片截断 +
# 额外补发文本 → 用户看到两条重复消息」的问题。
#
# 官方文档《AI 卡片流式更新》只写「内容 size 单次不要超过 1 K，总大小建议不要
# 超过 3 K」，单位含糊（字符还是字节未说明）。2026-09-22 真机实测（纯中文内容、
# ``isFull=true``）显示这 1K 是**建议**而非硬边界：
#
# | content 长度 | 字节 | HTTP |
# |---|---|---|
# | 1000 字符 | 2820 B | 200 |
# | 3000 字符 | 8456 B | 200 |
# | 4500 字符 | 12684 B | 200 |
#
# 取 3K 作为上限：落在文档建议的总量之内，又远高于真实回复长度（实测观测到的
# 回复在 216~1248 字符之间）。早期设成 1000 会把正常的长回复误判为超长，
# 导致卡片被截断 + 额外补发一条文本 —— 用户侧看到两条重复消息。
#
# 另外注意：模板变量绑定 markdown 时 ``isFull`` 必须为 ``true``（文档明示，否则
# 报错），即每次全量覆盖 —— 所以「单次」就是「总量」，没法用增量拼接分多次把
# 超长文本塞进同一张卡片。
MAX_CARD_CONTENT_CHARS = 3000
TRUNCATED_SUFFIX = "\n\n……（内容较长，完整结果见下方消息）"


def merge_streaming_text(previous: str, current: str) -> str:
    """把上游给的增量安全地并入已有文本；返回合并后的**全量**内容。

    正常情况下 ``on_delta`` 传的就是累积全文，此函数退化为直接返回 ``current``。
    保留它是因为「上游一定是累积文本」这个假设不成立：钉钉那边靠实测确认过，
    飞书侧的上游（员工执行事件流）未来可能改成纯增量，届时不改这里就会丢字。

    合并规则与 OpenClaw 的 ``mergeStreamingText`` 对齐（互为前缀取长的、互为子串
    取包含的、尾部与头部重叠则去重拼接），最后兜底为直接追加 —— 宁可多几个字，
    也不要因为合并失败而把已经吐出来的内容丢掉。
    """
    if not current:
        return previous
    if not previous or current == previous:
        return current
    if current.startswith(previous) or previous in current:
        return current
    if previous.startswith(current) or current in previous:
        return previous

    overlap = min(len(previous), len(current))
    while overlap > 0:
        if previous[-overlap:] == current[:overlap]:
            return previous + current[overlap:]
        overlap -= 1
    return previous + current


def clamp_card_content(text: str, *, with_notice: bool = True) -> tuple[str, bool]:
    """把回复裁到卡片能承载的长度；返回 ``(正文, 是否被截断)``。

    被截断时调用方应把完整内容改用文本消息补发 —— 卡片塞不下，但结果不能丢。

    ``with_notice=False`` 供执行中的中间推送使用：那时还没有「补发」这回事，
    把补发提示提前显示在卡片上会让人以为已经被截断了，只有收尾那次可能真补发。
    """
    if len(text) <= MAX_CARD_CONTENT_CHARS:
        return text, False
    if not with_notice:
        return text[:MAX_CARD_CONTENT_CHARS], True
    keep = max(MAX_CARD_CONTENT_CHARS - len(TRUNCATED_SUFFIX), 0)
    return text[:keep] + TRUNCATED_SUFFIX, True


# 卡片投放时的初始文案；它替代了此前那条独立的「已收到，正在处理」文本提示。
WORKING_TEXT = "正在处理，请稍候…"


def card_factory(provider: Any) -> Any | None:
    """按能力发现卡片会话工厂；Provider 不支持卡片时返回 ``None``。

    用能力检测而不是 ``isinstance``，避免 Worker 反向依赖具体 Provider 实现，
    也让新增支持卡片的渠道不需要改 Worker。
    """
    factory = getattr(provider, "create_card_session", None)
    return factory if callable(factory) else None


ENV_CARD_ENABLED = "IM_CARD_ENABLED"
ENV_CARD_TEMPLATE_ID = "DINGTALK_CARD_TEMPLATE_ID"
ENV_CARD_LEVEL = "IM_CARD_LEVEL"
# 渠道级档位覆盖：IM_CARD_LEVEL_<渠道标识>，例如 IM_CARD_LEVEL_FEISHU=two_state。
ENV_CARD_LEVEL_PREFIX = "IM_CARD_LEVEL_"

# 「全局档位掩盖了渠道默认」的告警只报一次，避免每条消息刷日志。
_MASKED_LEVEL_WARNED: set[tuple[str, str]] = set()


def card_enabled() -> bool:
    """卡片能力总开关；默认开启，显式设为 0/false/no/off 可退回文本回复。"""
    raw = os.environ.get(ENV_CARD_ENABLED, "").strip().lower()
    return raw not in {"0", "false", "no", "off"}


def card_template_id() -> str:
    """卡片模板 ID（**钉钉专用**）。

    飞书不需要模板 —— 卡片 JSON 直接在代码里构造。这个取值保留是因为钉钉的
    模板必须先在卡片平台建好，模板名与文本变量名都得对上。
    """
    return os.environ.get(ENV_CARD_TEMPLATE_ID, "").strip()


def card_level(channel: str = "") -> str:
    """解析卡片档位，优先级：渠道专属 > 全局 > 渠道默认 > 全局默认。

    ``channel`` 传 provider 标识（``feishu`` / ``dingtalk``，见
    :func:`card_channel`）。不传则只按全局配置解析，行为与改动前一致。

    渠道级覆盖（如 ``IM_CARD_LEVEL_FEISHU=staged``）解决的是「同一份部署里两个
    渠道需要不同密度」—— 全局那一个值表达不了，而两边的代价结构本就不同。
    """
    if channel:
        scoped = os.environ.get(f"{ENV_CARD_LEVEL_PREFIX}{channel.strip().upper()}", "")
        scoped = scoped.strip().lower()
        if scoped in POLICIES:
            return scoped
    raw = os.environ.get(ENV_CARD_LEVEL, "").strip().lower()
    if raw in POLICIES:
        # 全局值会**覆盖渠道默认**。这正是个容易踩的坑：`CHANNEL_DEFAULT_LEVELS`
        # 是按渠道代价结构定的，一个历史遗留的全局值会让它整段失效，而表面上
        # 一切正常（卡片照发，只是观感没变）。所以这里留一条一次性告警。
        prefer = CHANNEL_DEFAULT_LEVELS.get(channel.strip().lower())
        key = (channel, raw)
        if prefer and prefer != raw and key not in _MASKED_LEVEL_WARNED:
            _MASKED_LEVEL_WARNED.add(key)
            logger.warning(
                "卡档位：全局 %s=%s 覆盖了渠道默认 %s=%s（channel=%s）；"
                "只想改单渠道请用 %s%s",
                ENV_CARD_LEVEL, raw, "CHANNEL_DEFAULT_LEVELS", prefer, channel,
                ENV_CARD_LEVEL_PREFIX, channel.strip().upper(),
            )
        return raw
    return CHANNEL_DEFAULT_LEVELS.get(channel.strip().lower(), DEFAULT_LEVEL)


def card_channel(provider: Any) -> str:
    """读 Provider 自报的渠道标识；没声明就返回空串。

    用它而不是 ``isinstance``，与 :func:`card_factory` 同样的理由：Worker 不该
    反向依赖具体 Provider。标识由各 Provider 的 ``PROVIDER_ID`` 类属性给出，
    取值与 ``providers.PROVIDERS`` 的键一致（有测试守着这条一致性）。
    """
    value = getattr(provider, "PROVIDER_ID", "")
    return value.strip().lower() if isinstance(value, str) else ""


# 注意：这里刻意**没有**「卡片是否可用」的统一判定。
#
# 各渠道的可用条件不一样 —— 钉钉必须先到卡片平台建模板拿到 template_id，
# 飞书则在代码里直接构造 card_json、不需要模板。把差异塞进一个共享判定函数，
# 只会让它变成「钉钉条件泄漏给所有渠道」。所以判定权下放给各 Provider 的
# ``create_card_session``：配置不齐就返回 ``None``，Worker 视为「这条消息走文本」。
# 共享的只有总开关 ``card_enabled()``。


__all__ = [
    "CHANNEL_DEFAULT_LEVELS",
    "DEFAULT_LEVEL",
    "ENV_CARD_ENABLED",
    "ENV_CARD_LEVEL",
    "ENV_CARD_LEVEL_PREFIX",
    "ENV_CARD_TEMPLATE_ID",
    "LEVEL_LABELS",
    "LEVEL_STAGED",
    "LEVEL_STREAM",
    "LEVEL_TWO_STATE",
    "MAX_CARD_CONTENT_CHARS",
    "POLICIES",
    "ThrottlePolicy",
    "TRUNCATED_SUFFIX",
    "WORKING_TEXT",
    "card_channel",
    "card_enabled",
    "card_factory",
    "card_level",
    "card_template_id",
    "clamp_card_content",
    "level_label",
    "merge_streaming_text",
    "policy_for",
]
