"""术语管理：CRUD + 同义词管理。

术语（terminology）是数据分析员工的"业务词典"，用于：
  - LLM 写 SQL 时把业务名词映射到正确的表/字段
  - 检索时增加同义词扩展，避免用户问"客户"但表里只有"用户"导致的命中缺失

terminologies 表字段：
  - id: 主键
  - word: 术语词（业务名词，如"客户"）
  - description: 业务含义描述
  - synonyms: 同义词（JSON 数组，如 ["用户","会员","customer"]）
  - datasource_ids: 关联数据源 IDs（JSON 数组，空表示适用所有数据源）
  - enabled: 启用状态（1/0）
  - embedding: 预留向量字段（P1 阶段先用关键词匹配，P2 可升级向量检索）
  - created_at/updated_at: 时间戳

存储策略：
  - synonyms / datasource_ids 用 JSON 字符串存
  - 不在 _SOFT_DELETE_TABLES 中，硬删
"""

from __future__ import annotations

import json
import logging
import time
import uuid
from typing import Any

from app.catalog.db import _conn as _catalog_conn

logger = logging.getLogger("app.agent.analyst.terminology")


# ---------------------------------------------------------------------------
# 辅助
# ---------------------------------------------------------------------------

def _now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S")


def _gen_id() -> str:
    return f"term_{int(time.time()*1000)}_{uuid.uuid4().hex[:8]}"


def _normalize_synonyms(raw: Any) -> list[str]:
    """同义词归一化为字符串数组，去空白、去重、保序。"""
    if not raw:
        return []
    if isinstance(raw, str):
        # 逗号分隔的字符串
        items = [s.strip() for s in raw.split(",")]
    elif isinstance(raw, list):
        items = [str(s).strip() for s in raw]
    else:
        items = [str(raw).strip()]

    seen = set()
    result = []
    for s in items:
        if s and s not in seen:
            seen.add(s)
            result.append(s)
    return result


def _normalize_datasource_ids(raw: Any) -> list[str]:
    """数据源 IDs 归一化为字符串数组。"""
    if not raw:
        return []
    if isinstance(raw, str):
        items = [s.strip() for s in raw.split(",")]
    elif isinstance(raw, list):
        items = [str(s).strip() for s in raw]
    else:
        items = [str(raw).strip()]
    return [s for s in items if s]


# ---------------------------------------------------------------------------
# 行解析（从 DB 行到 dict）
# ---------------------------------------------------------------------------

def _row_to_term(r) -> dict:
    """DB 行转 dict，反序列化 JSON 字段。"""
    synonyms_raw = r["synonyms"] or "[]"
    ds_ids_raw = r["datasource_ids"] or "[]"
    try:
        synonyms = json.loads(synonyms_raw) if synonyms_raw else []
    except json.JSONDecodeError:
        # 兼容旧数据：逗号分隔字符串
        synonyms = _normalize_synonyms(synonyms_raw)
    try:
        datasource_ids = json.loads(ds_ids_raw) if ds_ids_raw else []
    except json.JSONDecodeError:
        datasource_ids = _normalize_datasource_ids(ds_ids_raw)

    return {
        "id": r["id"],
        "word": r["word"],
        "description": r["description"] or "",
        "synonyms": synonyms,
        "datasource_ids": datasource_ids,
        "enabled": r["enabled"],
        "created_at": r["created_at"],
        "updated_at": r["updated_at"],
    }


# ---------------------------------------------------------------------------
# CRUD
# ---------------------------------------------------------------------------

def list_terminologies(
    datasource_id: str | None = None,
    include_disabled: bool = False,
) -> list[dict]:
    """列出术语。

    Args:
        datasource_id: 过滤关联此数据源的术语（None=全部，空 datasource_ids 的术语始终命中）
        include_disabled: 是否包含已禁用的术语
    """
    sql = (
        "SELECT id, word, description, synonyms, datasource_ids, "
        "enabled, created_at, updated_at FROM terminologies"
    )
    clauses = []
    params: list = []
    if not include_disabled:
        clauses.append("enabled = 1")
    if clauses:
        sql += " WHERE " + " AND ".join(clauses)
    sql += " ORDER BY created_at DESC"

    con = _catalog_conn()
    try:
        rows = con.execute(sql, params).fetchall()
    finally:
        con.close()

    result = [_row_to_term(r) for r in rows]
    if datasource_id:
        # 客户端过滤：datasource_ids 为空（适用全部）或包含该数据源
        result = [t for t in result
                  if not t["datasource_ids"]
                  or datasource_id in t["datasource_ids"]]
    return result


def get_terminology(term_id: str) -> dict | None:
    """获取单个术语。"""
    con = _catalog_conn()
    try:
        r = con.execute(
            "SELECT id, word, description, synonyms, datasource_ids, "
            "enabled, created_at, updated_at FROM terminologies WHERE id=?",
            (term_id,)
        ).fetchone()
        if not r:
            return None
        return _row_to_term(r)
    finally:
        con.close()


def create_terminology(data: dict) -> dict:
    """创建术语。

    data: {id?, word, description?, synonyms?, datasource_ids?, enabled?}
    """
    if not data.get("word"):
        raise ValueError("word 不能为空")

    term_id = data.get("id") or _gen_id()
    synonyms = _normalize_synonyms(data.get("synonyms"))
    ds_ids = _normalize_datasource_ids(data.get("datasource_ids"))
    now = _now()

    con = _catalog_conn()
    try:
        con.execute(
            "INSERT INTO terminologies (id, word, description, synonyms, "
            "datasource_ids, enabled, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (term_id, data["word"], data.get("description", ""),
             json.dumps(synonyms, ensure_ascii=False),
             json.dumps(ds_ids, ensure_ascii=False),
             data.get("enabled", 1), now, now)
        )
        con.commit()
    finally:
        con.close()
    logger.info("创建术语: %s (%s)", data["word"], term_id)
    return get_terminology(term_id)


def update_terminology(term_id: str, data: dict) -> dict | None:
    """更新术语（部分更新）。"""
    existing = get_terminology(term_id)
    if not existing:
        return None

    word = data.get("word", existing["word"])
    description = data.get("description", existing["description"])
    enabled = data.get("enabled", existing["enabled"])

    if "synonyms" in data:
        synonyms = _normalize_synonyms(data["synonyms"])
    else:
        synonyms = existing["synonyms"]
    if "datasource_ids" in data:
        ds_ids = _normalize_datasource_ids(data["datasource_ids"])
    else:
        ds_ids = existing["datasource_ids"]

    now = _now()
    con = _catalog_conn()
    try:
        con.execute(
            "UPDATE terminologies SET word=?, description=?, synonyms=?, "
            "datasource_ids=?, enabled=?, updated_at=? WHERE id=?",
            (word, description,
             json.dumps(synonyms, ensure_ascii=False),
             json.dumps(ds_ids, ensure_ascii=False),
             enabled, now, term_id)
        )
        con.commit()
    finally:
        con.close()
    return get_terminology(term_id)


def delete_terminology(term_id: str) -> bool:
    """硬删术语（terminologies 不做软删）。"""
    con = _catalog_conn()
    try:
        con.execute("DELETE FROM terminologies WHERE id=?", (term_id,))
        con.commit()
        deleted = con.total_changes > 0
    finally:
        con.close()
    if deleted:
        logger.info("删除术语: %s", term_id)
    return deleted


def add_synonym(term_id: str, synonym: str) -> dict | None:
    """给术语追加单个同义词（去重）。"""
    existing = get_terminology(term_id)
    if not existing:
        return None
    syn = synonym.strip()
    if not syn:
        raise ValueError("synonym 不能为空")
    if syn in existing["synonyms"]:
        return existing  # 已存在，幂等返回
    existing["synonyms"].append(syn)
    return update_terminology(term_id, {"synonyms": existing["synonyms"]})


def remove_synonym(term_id: str, synonym: str) -> dict | None:
    """从术语中移除某个同义词。"""
    existing = get_terminology(term_id)
    if not existing:
        return None
    syn = synonym.strip()
    if syn not in existing["synonyms"]:
        return existing  # 不存在，幂等返回
    existing["synonyms"] = [s for s in existing["synonyms"] if s != syn]
    return update_terminology(term_id, {"synonyms": existing["synonyms"]})


def toggle_terminology(term_id: str, enabled: int) -> dict | None:
    """启用/禁用术语。"""
    return update_terminology(term_id, {"enabled": enabled})
