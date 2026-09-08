"""术语检索：从用户问题中匹配业务术语，返回 XML 块供 LLM 注入。

检索策略（P1 简单版）：
  1. 用 jieba 分词用户问题
  2. 对每个分词，与术语词 + 同义词做精确匹配（命中即匹配）
  3. 命中的术语去重后返回 XML 格式

输出 XML 格式（注入到 sql_db_smart_search / sql_db_query 工具返回文本）：
  <terminologies>
    <term word="客户" description="购买公司产品的企业或个人">
      <synonym>用户</synonym>
      <synonym>会员</synonym>
    </term>
  </terminologies>

P2 可升级：embedding 向量检索（基于 query 与术语+描述+同义词的语义相似度）。
"""

from __future__ import annotations

import logging
import re
from xml.sax.saxutils import escape as xml_escape
from typing import Iterable

import jieba

from app.agent.analyst.terminology import manager as term_manager

logger = logging.getLogger("app.agent.analyst.terminology.retriever")

# 单次注入的最大术语数，避免 prompt 过长
_MAX_TERMS_INJECT = 20


def _tokenize(text: str) -> set[str]:
    """jieba 分词，过滤标点和空白。"""
    if not text:
        return set()
    # 过滤标点
    cleaned = re.sub(r"[^一-龥a-zA-Z0-9]", " ", text)
    tokens = {t.strip() for t in jieba.lcut(cleaned, cut_all=False) if t.strip()}
    return tokens


def retrieve_terminologies(
    user_query: str,
    datasource_id: str | None = None,
    max_results: int = _MAX_TERMS_INJECT,
) -> list[dict]:
    """从用户问题中检索匹配的术语。

    命中策略（任一满足即命中）：
      1. 精确匹配：用户 query 的某个 jieba 分词与候选词（术语词/同义词）完全相等
      2. 子串匹配：候选词长度 >= 2 且作为子串出现在用户 query 中
         （弥补 jieba 把"用户数"切成整体 token 时漏掉"用户"的问题）

    Args:
        user_query: 用户问题
        datasource_id: 限定数据源（None=全部）
        max_results: 最大返回数

    Returns:
        命中的术语列表 [{id, word, description, synonyms, datasource_ids}]
    """
    if not user_query or not user_query.strip():
        return []

    query_text = user_query.strip()
    query_tokens = _tokenize(query_text)
    if not query_tokens:
        return []

    terms = term_manager.list_terminologies(
        datasource_id=datasource_id, include_disabled=False)

    matched: list[dict] = []
    for term in terms:
        # 候选词集合：术语词本身 + 所有同义词
        candidates = {term["word"]}
        candidates.update(term.get("synonyms", []))

        # 策略 1：精确匹配（jieba 分词与候选词相等）
        if query_tokens & candidates:
            matched.append(term)
            if len(matched) >= max_results:
                break
            continue

        # 策略 2：子串匹配（候选词长度 >= 2 且作为子串在 query 中出现）
        substring_hit = any(
            len(c) >= 2 and c in query_text for c in candidates
        )
        if substring_hit:
            matched.append(term)
            if len(matched) >= max_results:
                break

    logger.info("术语检索: query='%s' | 命中 %d 个", user_query[:50], len(matched))
    return matched


def format_terminologies_xml(terms: Iterable[dict]) -> str:
    """把术语列表格式化为 XML 文本块。

    返回空字符串表示无命中（注入时应判空避免空 XML 块）。
    """
    terms = list(terms)
    if not terms:
        return ""

    lines = ["<terminologies>"]
    for term in terms:
        attrs = f' word="{xml_escape(term["word"])}"'
        desc = term.get("description") or ""
        lines.append(f'  <term{attrs} description="{xml_escape(desc)}">')
        for syn in term.get("synonyms", []):
            lines.append(f"    <synonym>{xml_escape(syn)}</synonym>")
        lines.append("  </term>")
    lines.append("</terminologies>")
    return "\n".join(lines)


def build_terminology_injection(
    user_query: str,
    datasource_id: str | None = None,
) -> str:
    """一站式：检索 + 格式化，返回可拼接到 prompt 的 XML 文本块。

    无命中时返回空字符串。
    """
    matched = retrieve_terminologies(user_query, datasource_id=datasource_id)
    return format_terminologies_xml(matched)
