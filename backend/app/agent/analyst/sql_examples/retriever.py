"""SQL 示例检索：从用户问题匹配相似 SQL 示例，返回 XML 块供 LLM 注入。

检索策略（P1 简单版）：
  1. 用 jieba 分词用户问题
  2. 对每个示例的 question 分词后取并集
  3. 计算用户问题分词集合 ∩ 示例分词集合 / 示例分词数 = 命中比例
  4. 按命中比例倒序，取 Top-K

输出 XML 格式（注入到 sql_db_smart_search 工具返回文本）：
  <sql_examples>
    <example question="本月销售额 TOP10 客户" chart_type="bar">
      <sql>SELECT customer_name, SUM(amount) ...</sql>
    </example>
  </sql_examples>

P2 可升级：embedding 向量检索（语义相似度）。
"""

from __future__ import annotations

import logging
import re
from xml.sax.saxutils import escape as xml_escape
from typing import Iterable

import jieba

from app.agent.analyst.sql_examples import manager as ex_manager

logger = logging.getLogger("app.agent.analyst.sql_examples.retriever")

# 单次注入的最大示例数
_MAX_EXAMPLES_INJECT = 5
# 命中比例阈值：低于此值不返回（避免噪声）
_MIN_HIT_RATIO = 0.2


def _tokenize(text: str) -> set[str]:
    """jieba 分词，过滤标点和单字符空白。"""
    if not text:
        return set()
    cleaned = re.sub(r"[^一-龥a-zA-Z0-9]", " ", text)
    return {t.strip() for t in jieba.lcut(cleaned, cut_all=False) if t.strip()}


def _compute_hit_ratio(query_tokens: set[str], example_tokens: set[str]) -> float:
    """计算 query 在 example 上的命中比例。

    ratio = |query ∩ example| / max(|example|, 1)
    分母用 example 长度是为了让短问题能匹配长示例（短问题匹配多）。
    """
    if not example_tokens:
        return 0.0
    intersection = query_tokens & example_tokens
    return len(intersection) / max(len(example_tokens), 1)


def retrieve_sql_examples(
    user_query: str,
    datasource_id: str | None = None,
    max_results: int = _MAX_EXAMPLES_INJECT,
    min_ratio: float = _MIN_HIT_RATIO,
) -> list[dict]:
    """从用户问题检索相似的 SQL 示例。

    匹配策略（综合得分）：
      1. jieba 分词后的命中比例（query ∩ example / |example|）
      2. 子串加成：query 的 token 是否作为子串出现在 example 的 question 中
      最终分数 = hit_ratio + substring_bonus

    Args:
        user_query: 用户问题
        datasource_id: 限定数据源（None=全部）
        max_results: 最大返回数
        min_ratio: 最低命中比例（过滤噪声）

    Returns:
        命中的示例列表（按分数倒序）
    """
    if not user_query or not user_query.strip():
        return []

    query_text = user_query.strip()
    query_tokens = _tokenize(query_text)
    if not query_tokens:
        return []

    examples = ex_manager.list_sql_examples(
        datasource_id=datasource_id, include_disabled=False)

    scored: list[tuple[float, dict]] = []
    for ex in examples:
        ex_question = ex["question"] or ""
        ex_tokens = _tokenize(ex_question)
        ratio = _compute_hit_ratio(query_tokens, ex_tokens)

        # 子串加成：query 中长度>=2 的 token 作为子串出现在 example question 中
        substring_bonus = 0.0
        for tok in query_tokens:
            if len(tok) >= 2 and tok in ex_question:
                substring_bonus += 0.15

        score = ratio + substring_bonus
        if score >= min_ratio:
            scored.append((score, ex))

    # 按分数倒序，取 Top-K
    scored.sort(key=lambda x: x[0], reverse=True)
    result = [ex for _, ex in scored[:max_results]]

    logger.info(
        "SQL 示例检索: query='%s' | 命中 %d 个（共 %d 个候选）",
        user_query[:50], len(result), len(examples))
    return result


def format_sql_examples_xml(examples: Iterable[dict]) -> str:
    """把 SQL 示例列表格式化为 XML 文本块。

    返回空字符串表示无命中。
    """
    examples = list(examples)
    if not examples:
        return ""

    lines = ["<sql_examples>"]
    for ex in examples:
        chart = ex.get("chart_type") or ""
        attrs = f' question="{xml_escape(ex["question"])}"'
        if chart:
            attrs += f' chart_type="{xml_escape(chart)}"'
        lines.append(f"  <example{attrs}>")
        # SQL 文本可能含多行，CDATA 包裹避免转义问题
        lines.append("    <sql>")
        lines.append(f"      {xml_escape(ex['sql_text'])}")
        lines.append("    </sql>")
        if ex.get("description"):
            lines.append(
                f"    <description>{xml_escape(ex['description'])}</description>")
        lines.append("  </example>")
    lines.append("</sql_examples>")
    return "\n".join(lines)


def build_sql_example_injection(
    user_query: str,
    datasource_id: str | None = None,
) -> str:
    """一站式：检索 + 格式化，返回可拼接到 prompt 的 XML 文本块。

    无命中时返回空字符串。
    """
    matched = retrieve_sql_examples(user_query, datasource_id=datasource_id)
    return format_sql_examples_xml(matched)
