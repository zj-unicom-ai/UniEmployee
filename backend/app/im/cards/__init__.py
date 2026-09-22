"""AI 卡片会话：把「一次回复」表达为一张会原地演进的卡片。

卡片与普通消息的差别不只是好看：钉钉的文本消息发出后**不能原地修改**，
所以「已收到 → 结果」这种过程只能用两条消息硬凑。卡片可以更新，因此同一张
卡片能从「处理中」一路演进到最终结果，用户侧只看到一条消息。

代价是接口调用量：一次回复消耗 ``1 次投放 + N 次更新``，N 由这里的节流档位
决定。档位是可配的，配额紧张时降档即可，不需要改代码。
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any

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
    - ``max_updates``：单次回复的更新次数硬上限（``0`` 表示不做中间更新）。
    """

    min_interval_seconds: float
    min_delta_chars: int
    max_updates: int


POLICIES: dict[str, ThrottlePolicy] = {
    # 约 20~40 次调用/回复，适合配额充裕（专业版）的场景。
    LEVEL_STREAM: ThrottlePolicy(0.4, 1, 40),
    # 约 4~7 次/回复，与标准版入站额度同量级，作为默认。
    LEVEL_STAGED: ThrottlePolicy(2.0, 32, 6),
    # 只投放与收尾各一次，中间不更新。
    LEVEL_TWO_STATE: ThrottlePolicy(0.0, 0, 0),
}


def policy_for(level: str) -> ThrottlePolicy:
    return POLICIES.get(level, POLICIES[DEFAULT_LEVEL])


def level_label(level: str) -> str:
    return LEVEL_LABELS.get(level, level)


# 卡片正文长度上限。
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


def card_enabled() -> bool:
    """卡片能力总开关；默认开启，显式设为 0/false/no/off 可退回文本回复。"""
    raw = os.environ.get(ENV_CARD_ENABLED, "").strip().lower()
    return raw not in {"0", "false", "no", "off"}


def card_template_id() -> str:
    """卡片模板 ID。为空表示卡片能力不可用 —— 宁可退回文本，也不要发一张空卡片。"""
    return os.environ.get(ENV_CARD_TEMPLATE_ID, "").strip()


def card_level() -> str:
    raw = os.environ.get(ENV_CARD_LEVEL, "").strip().lower()
    return raw if raw in POLICIES else DEFAULT_LEVEL


def card_available() -> bool:
    """卡片链路是否可用：开关打开且配置了模板。"""
    return card_enabled() and bool(card_template_id())


__all__ = [
    "DEFAULT_LEVEL",
    "ENV_CARD_ENABLED",
    "ENV_CARD_LEVEL",
    "ENV_CARD_TEMPLATE_ID",
    "LEVEL_LABELS",
    "LEVEL_STAGED",
    "LEVEL_STREAM",
    "LEVEL_TWO_STATE",
    "MAX_CARD_CONTENT_CHARS",
    "POLICIES",
    "ThrottlePolicy",
    "WORKING_TEXT",
    "card_available",
    "card_enabled",
    "card_factory",
    "card_level",
    "card_template_id",
    "clamp_card_content",
    "level_label",
    "policy_for",
]
