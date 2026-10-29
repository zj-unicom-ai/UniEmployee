"""租户隔离的市场研究信源、RSS 发现与持久采集运行。"""
from __future__ import annotations

import asyncio
import hashlib
import html
import http.client
import ipaddress
import json
import logging
import re
import socket
import threading
import uuid
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urljoin, urlsplit, urlunsplit

from app import market_intake, market_research

log = logging.getLogger(__name__)
_dispatcher: asyncio.Task | None = None
_workers: set[asyncio.Task] = set()
_scheduled_runs: set[tuple[str, str]] = set()
_DISPATCH_INTERVAL_SEC = 1.0
_SOURCE_CAPACITY = asyncio.Semaphore(8)
_MAX_ITEMS_PER_SOURCE_RUN = 500
_DOMAIN_SEMAPHORES: dict[str, threading.BoundedSemaphore] = {}
_DOMAIN_LOCK = threading.Lock()
_RUNS_DDL = """
CREATE TABLE IF NOT EXISTS market_sources (
 id TEXT PRIMARY KEY, tenant_id TEXT NOT NULL, name TEXT NOT NULL,
 kind TEXT NOT NULL, config_json TEXT NOT NULL DEFAULT '{}',
 candidate_topics_json TEXT NOT NULL DEFAULT '[]', tags_json TEXT NOT NULL DEFAULT '[]',
 tier TEXT NOT NULL DEFAULT 'T3', first_party INTEGER NOT NULL DEFAULT 0,
 participation_mode TEXT NOT NULL DEFAULT 'editorial', desired_enabled INTEGER NOT NULL DEFAULT 0,
 enabled INTEGER NOT NULL DEFAULT 0, status TEXT NOT NULL DEFAULT 'draft',
 interval_minutes INTEGER NOT NULL DEFAULT 1440, cursor_json TEXT NOT NULL DEFAULT '{}',
 health TEXT NOT NULL DEFAULT 'unknown', config_version INTEGER NOT NULL DEFAULT 1,
 import_namespace TEXT NOT NULL DEFAULT '', legacy_source_id TEXT NOT NULL DEFAULT '',
 import_hash TEXT NOT NULL DEFAULT '', origin_json TEXT NOT NULL DEFAULT '{}',
 created_by TEXT NOT NULL DEFAULT '', updated_by TEXT NOT NULL DEFAULT '',
 created_at TEXT NOT NULL, updated_at TEXT NOT NULL
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_market_source_legacy_import
 ON market_sources(tenant_id,import_namespace,legacy_source_id) WHERE legacy_source_id<>'';
CREATE INDEX IF NOT EXISTS idx_market_sources_tenant_enabled
 ON market_sources(tenant_id, enabled, kind);
CREATE TABLE IF NOT EXISTS market_source_runs (
 id TEXT PRIMARY KEY, tenant_id TEXT NOT NULL, source_id TEXT NOT NULL,
 user_id TEXT NOT NULL DEFAULT '', trigger_type TEXT NOT NULL,
 topic_id TEXT NOT NULL DEFAULT '', status TEXT NOT NULL, stage TEXT NOT NULL DEFAULT 'queued',
 counts_json TEXT NOT NULL DEFAULT '{}', candidates_json TEXT NOT NULL DEFAULT '[]',
 error TEXT NOT NULL DEFAULT '', cursor_before_json TEXT NOT NULL DEFAULT '{}',
 cursor_after_json TEXT NOT NULL DEFAULT '{}', etag TEXT NOT NULL DEFAULT '',
 config_snapshot_json TEXT NOT NULL DEFAULT '{}',
 last_modified TEXT NOT NULL DEFAULT '', started_at TEXT NOT NULL DEFAULT '',
 finished_at TEXT NOT NULL DEFAULT '', created_at TEXT NOT NULL, updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_market_source_runs_tenant_source
 ON market_source_runs(tenant_id, source_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_market_source_runs_queue
 ON market_source_runs(status, created_at);
CREATE UNIQUE INDEX IF NOT EXISTS idx_market_source_one_active_run
 ON market_source_runs(tenant_id, source_id) WHERE status IN ('queued','running');
CREATE TABLE IF NOT EXISTS market_documents (
 id TEXT PRIMARY KEY, tenant_id TEXT NOT NULL, canonical_identity TEXT NOT NULL,
 canonical_url TEXT NOT NULL, title TEXT NOT NULL DEFAULT '', current_version_id TEXT NOT NULL DEFAULT '',
 first_seen_at TEXT NOT NULL, last_seen_at TEXT NOT NULL,
 UNIQUE(tenant_id, canonical_identity)
);
CREATE TABLE IF NOT EXISTS market_document_versions (
 id TEXT PRIMARY KEY, tenant_id TEXT NOT NULL, document_id TEXT NOT NULL,
 content_hash TEXT NOT NULL, title TEXT NOT NULL DEFAULT '', body_text TEXT NOT NULL DEFAULT '',
 content_source TEXT NOT NULL DEFAULT 'rss', published_at TEXT NOT NULL DEFAULT '',
 publication_month TEXT NOT NULL DEFAULT '',
 fetched_at TEXT NOT NULL, created_at TEXT NOT NULL,
 UNIQUE(tenant_id, document_id, content_hash)
);
CREATE INDEX IF NOT EXISTS idx_market_document_versions_doc
 ON market_document_versions(tenant_id, document_id, created_at DESC);
CREATE TABLE IF NOT EXISTS market_source_discoveries (
 id TEXT PRIMARY KEY, tenant_id TEXT NOT NULL, source_id TEXT NOT NULL,
 document_id TEXT NOT NULL, run_id TEXT NOT NULL DEFAULT '', external_id TEXT NOT NULL, original_url TEXT NOT NULL,
 intake_job_id TEXT NOT NULL DEFAULT '', status TEXT NOT NULL DEFAULT 'discovered',
 first_seen_at TEXT NOT NULL, last_seen_at TEXT NOT NULL,
 UNIQUE(tenant_id, source_id, external_id)
);
CREATE INDEX IF NOT EXISTS idx_market_discoveries_doc
 ON market_source_discoveries(tenant_id, document_id);
CREATE TABLE IF NOT EXISTS market_quality_reviews (
 id TEXT PRIMARY KEY, tenant_id TEXT NOT NULL, source_id TEXT NOT NULL DEFAULT '',
 document_id TEXT NOT NULL DEFAULT '', observation_id TEXT NOT NULL DEFAULT '',
 status TEXT NOT NULL, reason TEXT NOT NULL DEFAULT '', evidence_json TEXT NOT NULL DEFAULT '{}',
 reviewer_id TEXT NOT NULL DEFAULT '', rule_version TEXT NOT NULL DEFAULT 'q0-q1-v1',
 created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS market_collection_batches (
 id TEXT PRIMARY KEY, tenant_id TEXT NOT NULL, user_id TEXT NOT NULL,
 request_id TEXT NOT NULL, scope_hash TEXT NOT NULL, topic_id TEXT NOT NULL DEFAULT '',
 mode TEXT NOT NULL DEFAULT 'incremental', status TEXT NOT NULL,
 source_ids_json TEXT NOT NULL DEFAULT '[]', config_snapshot_json TEXT NOT NULL DEFAULT '{}',
 counts_json TEXT NOT NULL DEFAULT '{}', budget_json TEXT NOT NULL DEFAULT '{}', event_sequence INTEGER NOT NULL DEFAULT 0,
 source_total INTEGER NOT NULL DEFAULT 0, source_fetch_finished_at TEXT NOT NULL DEFAULT '',
 pipeline_finished_at TEXT NOT NULL DEFAULT '', error TEXT NOT NULL DEFAULT '',
 created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
 UNIQUE(tenant_id, request_id)
);
CREATE INDEX IF NOT EXISTS idx_market_collection_batches_tenant
 ON market_collection_batches(tenant_id, created_at DESC);
CREATE UNIQUE INDEX IF NOT EXISTS idx_market_collection_active_scope
 ON market_collection_batches(tenant_id,scope_hash) WHERE status IN ('queued','running','waiting','paused');
CREATE TABLE IF NOT EXISTS market_collection_requests (
 tenant_id TEXT NOT NULL, request_id TEXT NOT NULL, scope_hash TEXT NOT NULL,
 batch_id TEXT NOT NULL, created_at TEXT NOT NULL,
 PRIMARY KEY(tenant_id, request_id)
);
CREATE TABLE IF NOT EXISTS market_collection_members (
 id TEXT PRIMARY KEY, tenant_id TEXT NOT NULL, batch_id TEXT NOT NULL,
 source_id TEXT NOT NULL, run_id TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'queued',
 counts_json TEXT NOT NULL DEFAULT '{}', config_snapshot_json TEXT NOT NULL DEFAULT '{}',
 created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
 UNIQUE(tenant_id, batch_id, source_id)
);
CREATE INDEX IF NOT EXISTS idx_market_collection_members_batch
 ON market_collection_members(tenant_id, batch_id, status);
CREATE TABLE IF NOT EXISTS market_pipeline_events (
 id TEXT PRIMARY KEY, tenant_id TEXT NOT NULL, batch_id TEXT NOT NULL,
 sequence INTEGER NOT NULL, event_type TEXT NOT NULL, payload_json TEXT NOT NULL DEFAULT '{}',
 created_at TEXT NOT NULL, UNIQUE(tenant_id, batch_id, sequence)
);
CREATE INDEX IF NOT EXISTS idx_market_pipeline_events_batch
 ON market_pipeline_events(tenant_id, batch_id, sequence);
"""
_CONFIG_KEYS = {"feed_url", "sort_by_published_at", "initial_backfill_limit", "initial_backfill_months"}
_SENSITIVE_QUERY_NAMES = {"access_token", "api_key", "apikey", "auth", "authorization", "client_secret", "key", "password", "secret", "signature", "sig", "token"}
_SUPPORTED_IMPORT_SCHEMA = "market-source-import-proposal-v1"
_IMPORT_NAMESPACE = "aihot-market-sources-v1"
_MANIFEST_PATH = Path(__file__).resolve().parents[2] / "docs/guide/market-intel-initial-sources-2026-10-28.json"


def _conn():
    return market_research._conn()


def init_tables() -> None:
    with _conn() as con:
        con.executescript(_RUNS_DDL)
        if "config_snapshot_json" not in market_research.dblayer.table_columns(con, "market_source_runs"):
            con.execute("ALTER TABLE market_source_runs ADD COLUMN config_snapshot_json TEXT NOT NULL DEFAULT '{}' ")
        if "run_id" not in market_research.dblayer.table_columns(con, "market_source_discoveries"):
            con.execute("ALTER TABLE market_source_discoveries ADD COLUMN run_id TEXT NOT NULL DEFAULT ''")
        if "budget_json" not in market_research.dblayer.table_columns(con, "market_collection_batches"):
            con.execute("ALTER TABLE market_collection_batches ADD COLUMN budget_json TEXT NOT NULL DEFAULT '{}' ")
        if "publication_month" not in market_research.dblayer.table_columns(con, "market_document_versions"):
            con.execute("ALTER TABLE market_document_versions ADD COLUMN publication_month TEXT NOT NULL DEFAULT ''")


def _json(value, default):
    try:
        return json.loads(value or "")
    except (TypeError, json.JSONDecodeError):
        return default


def _canonical_url(url: str) -> str:
    clean = market_intake.public_url(url)
    parts = urlsplit(clean)
    query = [(key, value) for key, value in parse_qsl(parts.query, keep_blank_values=True)
             if not (key.lower().startswith("utm_") or key.lower() in {"fbclid", "gclid", "mc_cid", "mc_eid"})]
    return urlunsplit((parts.scheme.lower(), parts.netloc.lower(), parts.path or "/",
                       urlencode(query, doseq=True), ""))


def _validate_url(url: str) -> str:
    normalized = market_intake.public_url(url)
    parts = urlsplit(normalized)
    if any(key.lower() in _SENSITIVE_QUERY_NAMES for key, _ in parse_qsl(parts.query, keep_blank_values=True)):
        raise ValueError("来源 URL 不能包含 token、密钥或登录凭据；请使用后端凭据引用")
    return normalized


def _validate_source_payload(payload: dict) -> dict:
    kind = str(payload.get("kind") or "rss").strip().lower()
    if kind != "rss":
        raise ValueError("当前仅支持 RSS/Atom 来源；其他类型暂不能保存为可运行配置")
    name = str(payload.get("name") or "").strip()
    if not name or len(name) > 200:
        raise ValueError("来源名称不能为空，且最多 200 个字符")
    config = payload.get("config") or {}
    if not isinstance(config, dict):
        raise ValueError("config 必须是 JSON 对象")
    unknown = set(config) - _CONFIG_KEYS
    if unknown:
        raise ValueError("不支持的 RSS 配置字段：" + ", ".join(sorted(unknown)))
    feed_url = _validate_url(str(config.get("feed_url") or ""))
    topics = list(dict.fromkeys(str(item) for item in (payload.get("candidate_topic_ids") or [])))
    if not topics or any(topic not in market_research.TOPIC_BY_ID for topic in topics):
        raise ValueError("候选主题必须是一个或多个小察已配置的研究主题")
    try:
        interval = int(payload.get("interval_minutes", 1440))
        backfill_limit = int(config.get("initial_backfill_limit", 5))
        backfill_months = int(config.get("initial_backfill_months", 6))
    except (TypeError, ValueError) as exc:
        raise ValueError("采集间隔和首次回采限制必须是整数") from exc
    if not 5 <= interval <= 10080:
        raise ValueError("采集间隔须在 5–10080 分钟之间")
    if not 1 <= backfill_limit <= _MAX_ITEMS_PER_SOURCE_RUN or not 1 <= backfill_months <= 60:
        raise ValueError(f"首次回采限制须为 1–{_MAX_ITEMS_PER_SOURCE_RUN} 条、1–60 个月")
    tier = str(payload.get("tier") or "T3").upper()
    if tier not in {"T1", "T2", "T3"}:
        raise ValueError("来源等级只支持 T1、T2、T3")
    return {
        "name": name, "kind": kind,
        "config": {"feed_url": feed_url,
                   "sort_by_published_at": bool(config.get("sort_by_published_at", True)),
                   "initial_backfill_limit": backfill_limit,
                   "initial_backfill_months": backfill_months},
        "candidate_topic_ids": topics,
        "tags": [str(tag)[:80] for tag in (payload.get("tags") or [])[:30]],
        "tier": tier, "first_party": bool(payload.get("first_party", False)),
        "participation_mode": str(payload.get("participation_mode") or "editorial")[:40],
        "desired_enabled": bool(payload.get("desired_enabled", False)),
        "interval_minutes": interval,
    }


def _row(row) -> dict:
    item = dict(row)
    item["config"] = _json(item.pop("config_json", "{}"), {})
    # Sensitive query parameters are rejected on writes; sanitize legacy rows on reads too.
    if item["config"].get("feed_url"):
        item["config"]["feed_url"] = _redact_url(item["config"]["feed_url"])
    item["candidate_topic_ids"] = _json(item.pop("candidate_topics_json", "[]"), [])
    item["tags"] = _json(item.pop("tags_json", "[]"), [])
    item["cursor"] = _json(item.pop("cursor_json", "{}"), {})
    item["origin"] = _sanitize_origin(_json(item.pop("origin_json", "{}"), {}))
    item["enabled"] = bool(item.get("enabled"))
    item["desired_enabled"] = bool(item.get("desired_enabled"))
    item["first_party"] = bool(item.get("first_party"))
    return item


def _redact_url(url: str) -> str:
    parts = urlsplit(url)
    netloc = parts.hostname or ""
    try: port = parts.port
    except ValueError: port = None
    if port:
        netloc += f":{port}"
    query = [(k, "[redacted]" if k.lower() in _SENSITIVE_QUERY_NAMES else v)
             for k, v in parse_qsl(parts.query, keep_blank_values=True)]
    return urlunsplit((parts.scheme, netloc, parts.path, urlencode(query, doseq=True), ""))


def _sanitize_origin(value):
    if isinstance(value, dict):
        clean = {}
        for key, child in value.items():
            key_name = str(key).lower()
            if any(secret in key_name for secret in ("token", "secret", "password", "credential", "authorization", "api_key", "apikey")):
                clean[key] = "[redacted]"
            elif isinstance(child, str) and child.startswith(("http://", "https://")):
                clean[key] = _redact_url(child)
            else:
                clean[key] = _sanitize_origin(child)
        return clean
    if isinstance(value, list):
        return [_sanitize_origin(item) for item in value]
    return value


def get_source(tenant_id: str, source_id: str) -> dict | None:
    with _conn() as con:
        row = con.execute("SELECT * FROM market_sources WHERE tenant_id=? AND id=?", (tenant_id, source_id)).fetchone()
    return _row(row) if row else None


def list_sources(tenant_id: str, *, topic_id: str = "", kind: str = "", health: str = "", enabled: bool | None = None) -> list[dict]:
    where, params = ["tenant_id=?"], [tenant_id]
    if kind:
        where.append("kind=?"); params.append(kind)
    if health:
        where.append("health=?"); params.append(health)
    if enabled is not None:
        where.append("enabled=?"); params.append(int(enabled))
    with _conn() as con:
        rows = con.execute("SELECT * FROM market_sources WHERE " + " AND ".join(where) + " ORDER BY name", params).fetchall()
    items = [_row(row) for row in rows]
    return [item for item in items if not topic_id or topic_id in item["candidate_topic_ids"]]


def create_source(tenant_id: str, user_id: str, payload: dict) -> dict:
    source = _validate_source_payload(payload)
    feed_identity = _canonical_url(source["config"]["feed_url"])
    if any(_canonical_url(item["config"].get("feed_url", "")) == feed_identity
           for item in list_sources(tenant_id)):
        raise ValueError("该租户已配置相同的 RSS 地址")
    source_id = "ms_" + uuid.uuid4().hex
    now = market_research._now()
    with _conn() as con:
        con.execute("""INSERT INTO market_sources(
            id,tenant_id,name,kind,config_json,candidate_topics_json,tags_json,tier,first_party,
            participation_mode,desired_enabled,enabled,status,interval_minutes,created_by,updated_by,created_at,updated_at)
            VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""", (
            source_id, tenant_id, source["name"], source["kind"], json.dumps(source["config"], ensure_ascii=False),
            json.dumps(source["candidate_topic_ids"], ensure_ascii=False), json.dumps(source["tags"], ensure_ascii=False),
            source["tier"], int(source["first_party"]), source["participation_mode"], int(source["desired_enabled"]),
            0, "draft", source["interval_minutes"], user_id, user_id, now, now))
    return get_source(tenant_id, source_id)


def update_source(tenant_id: str, user_id: str, source_id: str, payload: dict, expected_version: int) -> dict | None:
    existing = get_source(tenant_id, source_id)
    if not existing:
        return None
    if expected_version != existing["config_version"]:
        raise RuntimeError("来源配置已被其他管理员修改，请刷新后重试")
    merged = {**existing, **payload,
              "candidate_topic_ids": payload.get("candidate_topic_ids", existing["candidate_topic_ids"]),
              "config": payload.get("config", existing["config"])}
    source = _validate_source_payload(merged)
    feed_identity = _canonical_url(source["config"]["feed_url"])
    if any(item["id"] != source_id and _canonical_url(item["config"].get("feed_url", "")) == feed_identity
           for item in list_sources(tenant_id)):
        raise ValueError("该租户已配置相同的 RSS 地址")
    config_changed = source["config"] != existing["config"]
    now = market_research._now()
    with _conn() as con:
        updated = con.execute("""UPDATE market_sources SET name=?,kind=?,config_json=?,candidate_topics_json=?,tags_json=?,
            tier=?,first_party=?,participation_mode=?,desired_enabled=?,interval_minutes=?,
            enabled=CASE WHEN ? THEN 0 ELSE enabled END,
            status=CASE WHEN ? THEN 'draft' ELSE status END,
            health=CASE WHEN ? THEN 'unknown' ELSE health END,
            config_version=config_version+1,
            updated_by=?,updated_at=? WHERE tenant_id=? AND id=? AND config_version=?""", (
            source["name"], source["kind"], json.dumps(source["config"], ensure_ascii=False),
            json.dumps(source["candidate_topic_ids"], ensure_ascii=False), json.dumps(source["tags"], ensure_ascii=False),
            source["tier"], int(source["first_party"]), source["participation_mode"], int(source["desired_enabled"]),
            source["interval_minutes"], config_changed, config_changed, config_changed,
            user_id, now, tenant_id, source_id, expected_version))
        if updated.rowcount == 0:
            raise RuntimeError("来源配置已被其他管理员修改，请刷新后重试")
    return get_source(tenant_id, source_id)


def set_enabled(tenant_id: str, user_id: str, source_id: str, enabled: bool, expected_version: int | None = None) -> dict | None:
    source = get_source(tenant_id, source_id)
    if not source:
        return None
    if enabled and source["health"] != "healthy":
        raise ValueError("请先试抓来源；只有解析成功的 RSS/Atom 来源可以启用")
    now = market_research._now()
    with _conn() as con:
        sql = "UPDATE market_sources SET enabled=?,status=?,config_version=config_version+1,updated_by=?,updated_at=? WHERE tenant_id=? AND id=?"
        params = [int(enabled), "active" if enabled else "draft", user_id, now, tenant_id, source_id]
        if expected_version is not None:
            sql += " AND config_version=?"; params.append(expected_version)
        updated = con.execute(sql, params)
        if updated.rowcount == 0:
            raise RuntimeError("来源配置已被其他管理员修改，请刷新后重试")
    return get_source(tenant_id, source_id)


def _load_manifest() -> dict:
    try:
        manifest = json.loads(_MANIFEST_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError("首批信源清单不可用，请检查 docs/guide 中的导入设计文件") from exc
    if manifest.get("schema_version") != _SUPPORTED_IMPORT_SCHEMA:
        raise ValueError("不支持的信源导入清单版本")
    return manifest


def preview_import(tenant_id: str, manifest: dict | None = None) -> dict:
    manifest = manifest or _load_manifest()
    if manifest.get("schema_version") != _SUPPORTED_IMPORT_SCHEMA:
        raise ValueError("不支持的信源导入清单版本")
    sources = manifest.get("sources")
    if not isinstance(sources, list) or len(sources) > 1000:
        raise ValueError("信源清单格式错误或数量超过上限")
    raw = json.dumps(manifest, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    manifest_hash = hashlib.sha256(raw.encode()).hexdigest()
    current = list_sources(tenant_id)
    by_legacy = {(s["import_namespace"], s["legacy_source_id"]): s for s in current if s["legacy_source_id"]}
    by_feed = {_canonical_url(s["config"].get("feed_url", "")): s for s in current}
    items, counts = [], {"new": 0, "reused": 0, "conflict": 0, "unsupported": 0, "desired_enabled": 0, "desired_disabled": 0}
    for entry in sources:
        legacy_id = str(entry.get("id") or entry.get("origin", {}).get("source_id") or "")
        try:
            normalized = _validate_source_payload({
                "name": entry.get("name"), "kind": entry.get("kind"), "config": entry.get("config"),
                "candidate_topic_ids": (entry.get("routing") or {}).get("candidate_topic_ids"),
                "tags": entry.get("tags"), "tier": entry.get("tier"), "first_party": entry.get("first_party"),
                "participation_mode": entry.get("participation_mode"), "desired_enabled": entry.get("desired_enabled"),
                "interval_minutes": entry.get("interval_minutes"),
            })
        except ValueError as exc:
            counts["unsupported"] += 1
            items.append({"legacy_source_id": legacy_id, "name": str(entry.get("name") or ""), "action": "unsupported", "reason": str(exc)})
            continue
        identity = ( _IMPORT_NAMESPACE, legacy_id)
        feed = _canonical_url(normalized["config"]["feed_url"])
        existing = by_legacy.get(identity)
        if existing:
            action = "reused"
            reason = "已导入；重复预览不会覆盖管理员修改"
        elif feed in by_feed:
            action = "conflict"
            reason = "该 RSS 地址已被当前租户的另一来源使用"
        else:
            action, reason = "new", "导入为草稿，需试抓并由管理员启用"
        counts[action] += 1
        counts["desired_enabled" if normalized["desired_enabled"] else "desired_disabled"] += 1
        items.append({"legacy_source_id": legacy_id, "name": normalized["name"], "kind": normalized["kind"],
                      "feed_url": _redact_url(normalized["config"]["feed_url"]),
                      "candidate_topic_ids": normalized["candidate_topic_ids"], "tier": normalized["tier"],
                      "desired_enabled": normalized["desired_enabled"], "action": action, "reason": reason})
    return {"schema_version": manifest["schema_version"], "manifest_hash": manifest_hash,
            "summary": counts, "items": items, "dry_run": True, "activate_on_import": False}


def import_sources(tenant_id: str, user_id: str, manifest_hash: str, manifest: dict | None = None) -> dict:
    manifest = manifest or _load_manifest()
    preview = preview_import(tenant_id, manifest)
    if not manifest_hash or manifest_hash != preview["manifest_hash"]:
        raise ValueError("导入预览已过期，请重新预览后提交")
    outcome = {"created": 0, "reused": 0, "conflict": 0, "unsupported": 0, "items": []}
    for entry, preview_item in zip(manifest.get("sources", []), preview["items"]):
        action = preview_item["action"]
        if action == "unsupported":
            outcome["unsupported"] += 1; continue
        if action == "conflict":
            outcome["conflict"] += 1; continue
        if action == "reused":
            outcome["reused"] += 1; continue
        normalized = _validate_source_payload({
            "name": entry.get("name"), "kind": entry.get("kind"), "config": entry.get("config"),
            "candidate_topic_ids": (entry.get("routing") or {}).get("candidate_topic_ids"),
            "tags": entry.get("tags"), "tier": entry.get("tier"), "first_party": entry.get("first_party"),
            "participation_mode": entry.get("participation_mode"), "desired_enabled": entry.get("desired_enabled"),
            "interval_minutes": entry.get("interval_minutes"),
        })
        legacy_id = str(entry.get("id") or entry.get("origin", {}).get("source_id") or "")
        source_id, now = "ms_" + uuid.uuid4().hex, market_research._now()
        origin = entry.get("origin") or {}
        with _conn() as con:
            con.execute("""INSERT INTO market_sources(
                id,tenant_id,name,kind,config_json,candidate_topics_json,tags_json,tier,first_party,
                participation_mode,desired_enabled,enabled,status,interval_minutes,import_namespace,
                legacy_source_id,import_hash,origin_json,created_by,updated_by,created_at,updated_at)
                VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""", (
                source_id, tenant_id, normalized["name"], normalized["kind"], json.dumps(normalized["config"], ensure_ascii=False),
                json.dumps(normalized["candidate_topic_ids"], ensure_ascii=False), json.dumps(normalized["tags"], ensure_ascii=False),
                normalized["tier"], int(normalized["first_party"]), normalized["participation_mode"],
                int(normalized["desired_enabled"]), 0, "draft", normalized["interval_minutes"],
                _IMPORT_NAMESPACE, legacy_id, preview["manifest_hash"], json.dumps(origin, ensure_ascii=False),
                user_id, user_id, now, now))
        outcome["created"] += 1
        outcome["items"].append({"id": source_id, "name": normalized["name"], "status": "draft"})
    return outcome


class _Text(HTMLParser):
    def __init__(self):
        super().__init__(); self.parts = []
    def handle_data(self, data):
        if data.strip(): self.parts.append(data.strip())


def _clean_markup(value: str) -> str:
    parser = _Text()
    try: parser.feed(value)
    except Exception: return html.unescape(re.sub(r"<[^>]+>", " ", value))
    return " ".join(parser.parts)


def _tag(element, name: str) -> str:
    for child in element.iter():
        if child.tag.rsplit("}", 1)[-1].lower() == name.lower():
            return " ".join(child.itertext()).strip()
    return ""


def _atom_link(item) -> str:
    candidates = []
    for child in item:
        if child.tag.rsplit("}", 1)[-1].lower() == "link":
            href = child.attrib.get("href")
            if href:
                candidates.append((child.attrib.get("rel", "alternate"), href))
            elif child.text:
                candidates.append(("alternate", child.text.strip()))
    return next((url for rel, url in candidates if rel == "alternate"), candidates[0][1] if candidates else "")


def _published(value: str) -> str:
    if not value: return ""
    try:
        date = parsedate_to_datetime(value)
    except (TypeError, ValueError, OverflowError):
        try:
            date = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return ""
    if date.tzinfo is None: date = date.replace(tzinfo=timezone.utc)
    return date.astimezone(timezone.utc).isoformat(timespec="seconds")


def _domain_slot(host: str) -> threading.BoundedSemaphore:
    with _DOMAIN_LOCK:
        return _DOMAIN_SEMAPHORES.setdefault(host.lower(), threading.BoundedSemaphore(1))


def _fetch_article(url: str) -> dict:
    """Fetch one article page with the same per-host concurrency bound as its feed."""
    normalized = market_intake.public_url(url)
    host = (urlsplit(normalized).hostname or "").lower()
    with _domain_slot(host):
        return market_intake.fetch_document(normalized)


def parse_feed(payload: bytes, feed_url: str, limit: int = 100) -> list[dict]:
    try:
        root = ET.fromstring(payload)
    except ET.ParseError as exc:
        raise ValueError("RSS/Atom XML 解析失败") from exc
    entries = [node for node in root.iter() if node.tag.rsplit("}", 1)[-1].lower() in {"item", "entry"}]
    result = []
    for node in entries[:limit]:
        title = _clean_markup(_tag(node, "title"))[:300]
        link = _atom_link(node) or _tag(node, "link")
        if not link:
            link = _tag(node, "guid")
        if not link or not title:
            continue
        try: link = _validate_url(urljoin(feed_url, html.unescape(link)))
        except ValueError: continue
        content = _tag(node, "encoded") or _tag(node, "content")
        summary = _tag(node, "description") or _tag(node, "summary")
        content_source = "fulltext" if content and len(_clean_markup(content)) >= 180 else "summary"
        body = _clean_markup(content or summary)[:60000]
        published = _published(_tag(node, "published") or _tag(node, "pubDate") or _tag(node, "updated"))
        publication_month = ""
        arxiv_id = re.search(r"/abs/(\d{2})(\d{2})\.\d+", urlsplit(link).path, re.I)
        if (urlsplit(link).hostname or "").lower().endswith("arxiv.org") and arxiv_id:
            publication_month = f"20{arxiv_id.group(1)}-{arxiv_id.group(2)}"
            # arXiv's Atom updated timestamp can be shared across every entry in a feed.
            # Keep the day unknown and use the paper ID's month for conservative backfill filtering.
            published = ""
        external_id = _tag(node, "guid") or _tag(node, "id") or link
        digest = hashlib.sha256(external_id.encode("utf-8")).hexdigest()
        result.append({"external_id": digest, "title": title, "url": link, "published_at": published,
                       "publication_month": publication_month,
                       "summary": _clean_markup(summary)[:1000], "body_text": body if content_source == "fulltext" else "",
                       "content_source": content_source, "has_fulltext": content_source == "fulltext"})
    return result


def _fetch_feed_hop(url: str, headers: dict, etag: str, last_modified: str) -> dict:
    parts = urlsplit(url)
    port = parts.port or (443 if parts.scheme == "https" else 80)
    host = (parts.hostname or "").lower()
    domain_slot = _domain_slot(host)
    with domain_slot:
        addresses = socket.getaddrinfo(parts.hostname, port, type=socket.SOCK_STREAM)
        ips = {entry[4][0] for entry in addresses}
        if not ips or any(not ipaddress.ip_address(ip).is_global or ipaddress.ip_address(ip).is_multicast for ip in ips):
            raise ValueError("RSS 地址解析到了本机或内网地址，已停止抓取")
        cls = http.client.HTTPSConnection if parts.scheme == "https" else http.client.HTTPConnection
        conn = cls(parts.hostname, port, timeout=20)
        conn._create_connection = lambda address, timeout=None, source_address=None: market_intake._connect_public_ips(
            parts.hostname, port, sorted(ips), timeout, source_address)
        try:
            conn.request("GET", (parts.path or "/") + ("?" + parts.query if parts.query else ""), headers=headers)
            response = conn.getresponse()
            if response.status in (301, 302, 303, 307, 308):
                location = response.getheader("Location")
                if not location: raise ValueError("RSS 重定向缺少目标地址")
                return {"status": response.status, "location": location}
            if response.status == 304:
                return {"status": 304, "body": b"", "etag": response.getheader("ETag", etag),
                        "last_modified": response.getheader("Last-Modified", last_modified)}
            if response.status != 200:
                raise ValueError(f"RSS 返回 HTTP {response.status}")
            raw = response.read(2_000_001)
            if len(raw) > 2_000_000: raise ValueError("RSS 响应超过 2 MB")
            content_type = (response.getheader("Content-Type") or "").lower()
            if content_type and not any(part in content_type for part in ("xml", "rss", "atom", "text/plain", "octet-stream")):
                raise ValueError("来源响应不是 RSS/Atom XML")
            return {"status": 200, "body": raw, "etag": response.getheader("ETag", ""),
                    "last_modified": response.getheader("Last-Modified", "")}
        finally:
            conn.close()


def fetch_feed(url: str, *, etag: str = "", last_modified: str = "") -> dict:
    """逐跳校验并固定公网 IP，执行条件请求、2 MB 限额和单域名并发限流。"""
    headers = {"User-Agent": "UniEmployee-MarketSources/1.0", "Accept": "application/rss+xml, application/atom+xml, application/xml, text/xml;q=0.9, */*;q=0.5", "Accept-Encoding": "identity"}
    if etag: headers["If-None-Match"] = etag[:500]
    if last_modified: headers["If-Modified-Since"] = last_modified[:200]
    for _ in range(6):
        url = market_intake.public_url(url)
        response = _fetch_feed_hop(url, headers, etag, last_modified)
        if response["status"] in (301, 302, 303, 307, 308):
            url = urljoin(url, response["location"])
            continue
        return {**response, "url": url}
    raise ValueError("RSS 重定向次数过多")


def _record_version(con, tenant_id: str, source_id: str, candidate: dict) -> tuple[str, bool, bool]:
    now = market_research._now()
    # Canonical URL is the document identity; the feed's external ID remains a source alias.
    identity = market_research._source_identity("", [{"url": candidate["url"]}])
    doc = con.execute("SELECT * FROM market_documents WHERE tenant_id=? AND canonical_identity=?", (tenant_id, identity)).fetchone()
    created = False
    if not doc:
        doc_id = "md_" + uuid.uuid4().hex
        con.execute("INSERT INTO market_documents(id,tenant_id,canonical_identity,canonical_url,title,first_seen_at,last_seen_at) VALUES(?,?,?,?,?,?,?)",
                    (doc_id, tenant_id, identity, candidate["url"], candidate["title"], now, now))
        created = True
    else:
        doc_id = doc["id"]
        con.execute("UPDATE market_documents SET last_seen_at=?,title=CASE WHEN title='' THEN ? ELSE title END WHERE tenant_id=? AND id=?",
                    (now, candidate["title"], tenant_id, doc_id))
        current = con.execute("SELECT content_source FROM market_document_versions WHERE tenant_id=? AND id=?",
                              (tenant_id, doc["current_version_id"])).fetchone()
        if current and current["content_source"] == "article_fetch":
            # A feed excerpt is weaker evidence than a previously fetched publisher page.
            # Re-discovery must not replace the current full article with its RSS summary.
            return doc_id, False, False
    text = candidate.get("body_text") or candidate.get("summary") or ""
    fingerprint = hashlib.sha256((candidate["title"].strip() + "\n" + re.sub(r"\s+", " ", text).strip()).encode()).hexdigest()
    existing = con.execute("SELECT id FROM market_document_versions WHERE tenant_id=? AND document_id=? AND content_hash=?",
                           (tenant_id, doc_id, fingerprint)).fetchone()
    version_id = existing["id"] if existing else "mdv_" + uuid.uuid4().hex
    is_new_version = not bool(existing)
    if is_new_version:
        con.execute("""INSERT INTO market_document_versions(
            id,tenant_id,document_id,content_hash,title,body_text,content_source,published_at,publication_month,fetched_at,created_at)
            VALUES(?,?,?,?,?,?,?,?,?,?,?)""",
                    (version_id, tenant_id, doc_id, fingerprint, candidate["title"], text[:100000], candidate.get("content_source", "rss"),
                     candidate.get("published_at", ""), candidate.get("publication_month", ""), now, now))
        con.execute("UPDATE market_documents SET current_version_id=? WHERE tenant_id=? AND id=?", (version_id, tenant_id, doc_id))
    return doc_id, created, is_new_version


def _record_article_version(con, tenant_id: str, document_id: str, candidate: dict,
                            article: dict) -> str:
    """Persist a fetched article page as an immutable version without invoking an LLM."""
    now = market_research._now()
    title = str(article.get("title") or candidate.get("title") or "").strip()
    body = str(article.get("text") or "")[:100000]
    fingerprint = hashlib.sha256((title + "\n" + re.sub(r"\s+", " ", body).strip()).encode()).hexdigest()
    existing = con.execute("SELECT id FROM market_document_versions WHERE tenant_id=? AND document_id=? AND content_hash=?",
                           (tenant_id, document_id, fingerprint)).fetchone()
    if existing:
        version_id = existing["id"]
    else:
        version_id = "mdv_" + uuid.uuid4().hex
        con.execute("""INSERT INTO market_document_versions(
            id,tenant_id,document_id,content_hash,title,body_text,content_source,published_at,publication_month,fetched_at,created_at)
            VALUES(?,?,?,?,?,?,?,?,?,?,?)""", (
            version_id, tenant_id, document_id, fingerprint, title, body, "article_fetch",
            candidate.get("published_at", ""), candidate.get("publication_month", ""), article.get("fetched_at") or now, now))
    con.execute("UPDATE market_documents SET current_version_id=?,title=CASE WHEN ?<>'' THEN ? ELSE title END,last_seen_at=? WHERE tenant_id=? AND id=?",
                (version_id, title, title, now, tenant_id, document_id))
    return version_id


def preview_source(tenant_id: str, source_id: str, *, limit: int = 5) -> dict:
    source = get_source(tenant_id, source_id)
    if not source: return None
    config, cursor = source["config"], source["cursor"]
    try:
        fetched = fetch_feed(config["feed_url"], etag=cursor.get("etag", ""), last_modified=cursor.get("last_modified", ""))
    except Exception as exc:
        now, run_id = market_research._now(), "msr_" + uuid.uuid4().hex
        message = (str(exc) if isinstance(exc, ValueError) else "RSS 网络请求失败，请检查地址或稍后重试")[:1000]
        with _conn() as con:
            con.execute("""INSERT INTO market_source_runs(id,tenant_id,source_id,user_id,trigger_type,topic_id,status,stage,error,started_at,finished_at,created_at,updated_at)
                VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)""", (run_id, tenant_id, source_id, "", "preview", "", "failed", "preview", message, now, now, now, now))
            con.execute("UPDATE market_sources SET health='degraded',updated_at=? WHERE tenant_id=? AND id=?", (now, tenant_id, source_id))
        if isinstance(exc, ValueError):
            raise
        raise ValueError("RSS 网络请求失败，请检查地址或稍后重试") from exc
    try:
        candidates = parse_feed(fetched["body"], fetched["url"], limit=max(limit, 1)) if fetched["status"] == 200 else []
    except Exception as exc:
        now, run_id = market_research._now(), "msr_" + uuid.uuid4().hex
        message = (str(exc) if isinstance(exc, ValueError) else "RSS/Atom 解析失败")[:1000]
        with _conn() as con:
            con.execute("""INSERT INTO market_source_runs(id,tenant_id,source_id,user_id,trigger_type,topic_id,status,stage,error,started_at,finished_at,created_at,updated_at)
                VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)""", (run_id, tenant_id, source_id, "", "preview", "", "failed", "preview", message, now, now, now, now))
            con.execute("UPDATE market_sources SET health='degraded',updated_at=? WHERE tenant_id=? AND id=?", (now, tenant_id, source_id))
        if isinstance(exc, ValueError): raise
        raise ValueError("RSS/Atom 解析失败") from exc
    now = market_research._now()
    with _conn() as con:
        run_id = "msr_" + uuid.uuid4().hex
        counts = {"found": len(candidates), "new": 0, "duplicate": 0, "failed": 0}
        con.execute("""INSERT INTO market_source_runs(id,tenant_id,source_id,user_id,trigger_type,topic_id,status,stage,
            counts_json,candidates_json,etag,last_modified,started_at,finished_at,created_at,updated_at)
            VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""", (
            run_id, tenant_id, source_id, "", "preview", "", "succeeded", "preview",
            json.dumps({**counts, "http_status": fetched["status"]}), json.dumps(candidates, ensure_ascii=False),
            fetched["etag"], fetched["last_modified"], now, now, now, now))
        con.execute("UPDATE market_sources SET health='healthy',updated_at=? WHERE tenant_id=? AND id=?",
                    (now, tenant_id, source_id))
    return {"run_id": run_id, "status": "succeeded", "http_status": fetched["status"], "counts": counts,
            "items": [{k: item.get(k) for k in ("title", "url", "published_at", "summary", "has_fulltext", "content_source")} for item in candidates],
            "diagnostic": "RSS/Atom 解析完成；试抓不会触发模型或写入研究观察。" if fetched["status"] == 200 else "Feed 未变化（HTTP 304）。"}


def _new_run(tenant_id: str, user_id: str, source: dict, topic_id: str, *, force_refresh: bool = False,
             max_items: int = _MAX_ITEMS_PER_SOURCE_RUN, analysis_enabled: bool = True) -> dict:
    if not source["enabled"]:
        raise ValueError("来源已停用，不能开始采集")
    if topic_id not in source["candidate_topic_ids"]:
        raise ValueError("所选主题不在该来源的候选主题范围内")
    try:
        with _conn() as con:
            active = con.execute("SELECT id FROM market_source_runs WHERE tenant_id=? AND source_id=? AND status IN ('queued','running') ORDER BY created_at LIMIT 1",
                                 (tenant_id, source["id"])).fetchone()
            if active: return get_run(tenant_id, active["id"])
            now, run_id = market_research._now(), "msr_" + uuid.uuid4().hex
            run_cursor = dict(source["cursor"])
            if force_refresh:
                run_cursor.pop("etag", None); run_cursor.pop("last_modified", None)
            snapshot = {"config": source["config"], "config_version": source["config_version"],
                        "candidate_topic_ids": source["candidate_topic_ids"], "cursor": run_cursor,
                        "max_items": max(1, min(_MAX_ITEMS_PER_SOURCE_RUN, int(max_items))),
                        "analysis_enabled": bool(analysis_enabled)}
            con.execute("""INSERT INTO market_source_runs(id,tenant_id,source_id,user_id,trigger_type,topic_id,status,stage,
                cursor_before_json,config_snapshot_json,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)""",
                (run_id, tenant_id, source["id"], user_id, "retry" if force_refresh else "manual", topic_id, "queued", "queued",
                 json.dumps(run_cursor, ensure_ascii=False), json.dumps(snapshot, ensure_ascii=False), now, now))
        return get_run(tenant_id, run_id)
    except Exception:
        # The partial unique index is the cross-process arbiter for concurrent requests.
        with _conn() as con:
            active = con.execute("SELECT id FROM market_source_runs WHERE tenant_id=? AND source_id=? AND status IN ('queued','running') ORDER BY created_at LIMIT 1",
                                 (tenant_id, source["id"])).fetchone()
        if active: return get_run(tenant_id, active["id"])
        raise


def get_run(tenant_id: str, run_id: str, *, include_config: bool = False) -> dict | None:
    with _conn() as con:
        row = con.execute("SELECT * FROM market_source_runs WHERE tenant_id=? AND id=?", (tenant_id, run_id)).fetchone()
    if not row: return None
    item = dict(row)
    for col, key, default in (("counts_json", "counts", {}), ("candidates_json", "candidates", []), ("cursor_before_json", "cursor_before", {}), ("cursor_after_json", "cursor_after", {})):
        item[key] = _json(item.pop(col), default)
    config_snapshot = _json(item.pop("config_snapshot_json", "{}"), {})
    if include_config:
        item["config_snapshot"] = config_snapshot
    item.pop("tenant_id", None)
    item["candidates"] = [{key: candidate.get(key) for key in ("title", "url", "published_at", "summary", "has_fulltext", "content_source")}
                           for candidate in item["candidates"]]
    return item


def list_runs(tenant_id: str, source_id: str, limit: int = 30) -> list[dict]:
    with _conn() as con:
        rows = con.execute("SELECT id,source_id,trigger_type,topic_id,status,stage,counts_json,error,started_at,finished_at,created_at,updated_at FROM market_source_runs WHERE tenant_id=? AND source_id=? ORDER BY created_at DESC LIMIT ?",
                            (tenant_id, source_id, limit)).fetchall()
    return [{**dict(row), "counts": _json(row["counts_json"], {})} for row in rows]


def list_recent_runs(tenant_id: str, limit: int = 100) -> list[dict]:
    with _conn() as con:
        rows = con.execute("""SELECT r.id,r.source_id,s.name AS source_name,r.trigger_type,r.topic_id,r.status,r.stage,
            r.counts_json,r.error,r.started_at,r.finished_at,r.created_at,r.updated_at
            FROM market_source_runs r LEFT JOIN market_sources s ON s.tenant_id=r.tenant_id AND s.id=r.source_id
            WHERE r.tenant_id=? ORDER BY r.created_at DESC LIMIT ?""", (tenant_id, limit)).fetchall()
    return [{**dict(row), "counts": _json(row["counts_json"], {})} for row in rows]


async def _execute_run(tenant_id: str, run_id: str) -> None:
    with _conn() as con:
        row = con.execute("SELECT * FROM market_source_runs WHERE tenant_id=? AND id=?", (tenant_id, run_id)).fetchone()
        if not row or row["status"] != "queued": return
        changed = con.execute("UPDATE market_source_runs SET status='running',stage='fetch',started_at=?,updated_at=? WHERE tenant_id=? AND id=? AND status='queued'",
                              (market_research._now(), market_research._now(), tenant_id, run_id)).rowcount
        if not changed: return
    run = get_run(tenant_id, run_id, include_config=True)
    source = get_source(tenant_id, run["source_id"])
    try:
        if not source or not source["enabled"]:
            raise ValueError("来源已停用，未认领本轮采集")
        snapshot = run.get("config_snapshot") or {}
        config = snapshot.get("config") or source["config"]
        cursor = snapshot.get("cursor") or source["cursor"]
        analysis_enabled = bool(snapshot.get("analysis_enabled", True))
        fetched = await asyncio.to_thread(fetch_feed, config["feed_url"], etag=cursor.get("etag", ""), last_modified=cursor.get("last_modified", ""))
        if fetched["status"] == 304:
            counts = {"found": 0, "new": 0, "revised": 0, "duplicate": 0, "failed": 0,
                      "intake_queued": 0, "article_fetched": 0, "article_reused": 0, "article_fetch_failed": 0,
                      "unknown_date_excluded": 0, "outside_window": 0}
            candidates = []
        else:
            candidates = parse_feed(fetched["body"], fetched["url"], limit=500)
            per_source_limit = max(1, min(_MAX_ITEMS_PER_SOURCE_RUN, int(snapshot.get("max_items", _MAX_ITEMS_PER_SOURCE_RUN))))
            if config.get("sort_by_published_at"):
                candidates.sort(key=lambda item: item.get("published_at") or "", reverse=True)
            unknown_date_excluded = 0
            outside_window = 0
            if not cursor.get("initial_backfill_done"):
                max_items = min(per_source_limit, config.get("initial_backfill_limit", 5))
                cutoff = datetime.now(timezone.utc) - timedelta(days=30 * config.get("initial_backfill_months", 6))
                in_window = []
                for item in candidates:
                    publication_month = str(item.get("publication_month") or "")
                    if publication_month:
                        try:
                            month_start = datetime.strptime(publication_month, "%Y-%m").replace(tzinfo=timezone.utc)
                        except ValueError:
                            unknown_date_excluded += 1
                            continue
                        next_month = (month_start.replace(day=28) + timedelta(days=4)).replace(day=1)
                        if month_start >= cutoff:
                            in_window.append(item)
                        elif next_month <= cutoff:
                            outside_window += 1
                        else:
                            # Month-level dates that cross the cutoff cannot prove inclusion.
                            unknown_date_excluded += 1
                        continue
                    published_at = item.get("published_at") or ""
                    if not published_at:
                        unknown_date_excluded += 1
                        continue
                    try:
                        published = datetime.fromisoformat(published_at.replace("Z", "+00:00"))
                        if published.tzinfo is None:
                            published = published.replace(tzinfo=timezone.utc)
                    except ValueError:
                        unknown_date_excluded += 1
                        continue
                    if published >= cutoff:
                        in_window.append(item)
                    else:
                        outside_window += 1
                candidates = in_window[:max_items]
            else:
                candidates = candidates[:per_source_limit]
            counts = {"found": len(candidates), "new": 0, "revised": 0, "duplicate": 0,
                      "failed": 0, "intake_queued": 0, "article_fetched": 0, "article_reused": 0,
                      "article_fetch_failed": 0,
                      "unknown_date_excluded": unknown_date_excluded, "outside_window": outside_window}
            for candidate in candidates:
                try:
                    identity = market_research._source_identity(candidate["external_id"], [{"url": candidate["url"]}])
                    now = market_research._now()
                    article_cached = False
                    retry_discovery_id = ""
                    with _conn() as con:
                        prior = con.execute("SELECT * FROM market_source_discoveries WHERE tenant_id=? AND source_id=? AND external_id=?",
                                            (tenant_id, source["id"], candidate["external_id"])).fetchone()
                        doc_id, is_new_doc, is_new_version = _record_version(con, tenant_id, source["id"], candidate)
                        retry_failed_article = False
                        if prior and not analysis_enabled and prior["status"] == "fetch_failed":
                            current_version = con.execute("""SELECT v.content_source FROM market_documents d
                                JOIN market_document_versions v ON v.tenant_id=d.tenant_id AND v.id=d.current_version_id
                                WHERE d.tenant_id=? AND d.id=?""", (tenant_id, doc_id)).fetchone()
                            retry_failed_article = not current_version or current_version["content_source"] != "article_fetch"
                            if retry_failed_article:
                                retry_discovery_id = prior["id"]
                        if prior and not is_new_version and not retry_failed_article:
                            con.execute("UPDATE market_source_discoveries SET last_seen_at=? WHERE tenant_id=? AND id=?", (now, tenant_id, prior["id"]))
                            counts["duplicate"] += 1
                            continue
                        if prior and is_new_version and not retry_failed_article:
                            con.execute("UPDATE market_source_discoveries SET last_seen_at=?,status='revised' WHERE tenant_id=? AND id=?", (now, tenant_id, prior["id"]))
                            con.execute("INSERT INTO market_quality_reviews(id,tenant_id,source_id,document_id,status,reason,evidence_json,created_at) VALUES(?,?,?,?,?,?,?,?)",
                                ("mqr_" + uuid.uuid4().hex, tenant_id, source["id"], doc_id, "needs_review",
                                 "检测到正文版本变化；等待后续版本研判流程处理",
                                 json.dumps({"content_hash_changed": True, "published_at": candidate.get("published_at", "")}, ensure_ascii=False), now))
                            counts["revised"] += 1
                            continue
                        if not analysis_enabled:
                            current_version = con.execute("""SELECT v.content_source FROM market_documents d
                                JOIN market_document_versions v ON v.tenant_id=d.tenant_id AND v.id=d.current_version_id
                                WHERE d.tenant_id=? AND d.id=?""", (tenant_id, doc_id)).fetchone()
                            article_cached = bool(current_version and current_version["content_source"] == "article_fetch")
                    job, article = None, None
                    article_error = ""
                    if analysis_enabled:
                        job = market_intake.create_job(tenant_id=tenant_id, user_id=run["user_id"] or "system:market-source",
                            url=candidate["url"], topic_id=run["topic_id"], internal=True,
                            source_id=source["id"], source_name=source["name"])
                    elif article_cached:
                        article = {"cached": True}
                    elif candidate.get("publication_month") and (urlsplit(candidate["url"]).hostname or "").lower().endswith("arxiv.org"):
                        # The official arXiv Atom summary is the paper abstract; /abs repeats it,
                        # while PDF full text is outside this HTML/text adapter's scope.
                        # Persist the abstract and keep the quality review explicitly unverified.
                        article = None
                    else:
                        try:
                            article = await asyncio.to_thread(_fetch_article, candidate["url"])
                        except Exception as exc:
                            article_error = str(exc)[:300] if isinstance(exc, ValueError) else "文章页请求失败；保留 Feed 元数据和摘要"
                    with _conn() as con:
                        if article and article.get("text"):
                            _record_article_version(con, tenant_id, doc_id, candidate, article)
                        discovery_status = "queued" if job else ("fetch_failed" if article_error else "fetched")
                        intake_job_id = job["id"] if job else ""
                        if retry_discovery_id:
                            con.execute("""UPDATE market_source_discoveries SET document_id=?,run_id=?,original_url=?,
                                intake_job_id=?,status=?,last_seen_at=? WHERE tenant_id=? AND id=?""",
                                (doc_id, run_id, candidate["url"], intake_job_id, discovery_status, now, tenant_id, retry_discovery_id))
                        else:
                            discovery_id = "msd_" + uuid.uuid4().hex
                            con.execute("""INSERT INTO market_source_discoveries(id,tenant_id,source_id,document_id,run_id,external_id,original_url,intake_job_id,status,first_seen_at,last_seen_at)
                                VALUES(?,?,?,?,?,?,?,?,?,?,?)""", (discovery_id, tenant_id, source["id"], doc_id, run_id, candidate["external_id"], candidate["url"], intake_job_id, discovery_status, now, now))
                        page_available = bool(article and (article.get("text") or article_cached))
                        quality_reason = ("文章页原文已版本化；本批未启动模型分析" if page_available else
                                          f"文章页抓取失败（{article_error}）；已保留 RSS 元数据/摘要，原文未验证" if article_error else
                                          "Feed 含正文片段；仍需读取文章页并逐字校验引述" if candidate.get("has_fulltext") else
                                          "Feed 仅提供摘要；原文页尚未读取与校验引述")
                        con.execute("INSERT INTO market_quality_reviews(id,tenant_id,source_id,document_id,status,reason,evidence_json,created_at) VALUES(?,?,?,?,?,?,?,?)",
                            ("mqr_" + uuid.uuid4().hex, tenant_id, source["id"], doc_id,
                             "unverified",
                             quality_reason,
                             json.dumps({"feed_url": _redact_url(source["config"]["feed_url"]),
                                         "published_at": candidate.get("published_at", ""),
                                         "publication_month": candidate.get("publication_month", ""),
                                         "article_fetched": bool(article and article.get("text")),
                                         "article_reused": article_cached, "analysis_enabled": analysis_enabled}, ensure_ascii=False), now))
                    if job:
                        market_intake.launch(job)
                    counts["new"] += int(is_new_doc)
                    counts["duplicate"] += int(not is_new_doc)
                    if job:
                        counts["intake_queued"] += 1
                    elif article_error:
                        counts["failed"] += 1
                        counts["article_fetch_failed"] += 1
                    else:
                        counts["article_fetched"] += int(bool(article and article.get("text")) or article_cached)
                        counts["article_reused"] += int(article_cached)
                except Exception as exc:
                    log.warning("RSS 条目入队失败 source=%s: %s", source["id"], exc)
                    counts["failed"] += 1
            cursor_after = dict(cursor)
            if counts["failed"] == 0:
                cursor_after = {"etag": fetched["etag"], "last_modified": fetched["last_modified"],
                                "last_success_at": market_research._now(), "initial_backfill_done": True,
                                "initial_backfill_at": cursor.get("initial_backfill_at") or market_research._now()}
                with _conn() as con:
                    con.execute("UPDATE market_sources SET cursor_json=?,health='healthy',updated_at=? WHERE tenant_id=? AND id=?",
                                (json.dumps(cursor_after, ensure_ascii=False), market_research._now(), tenant_id, source["id"]))
            else:
                with _conn() as con:
                    con.execute("UPDATE market_sources SET health='degraded',updated_at=? WHERE tenant_id=? AND id=?",
                                (market_research._now(), tenant_id, source["id"]))
        with _conn() as con:
            con.execute("UPDATE market_source_runs SET status=?,stage='discover',counts_json=?,cursor_after_json=?,etag=?,last_modified=?,finished_at=?,updated_at=? WHERE tenant_id=? AND id=?",
                        ("completed_with_issues" if counts["failed"] else "succeeded", json.dumps(counts), json.dumps(source["cursor"] if fetched["status"] == 304 else cursor_after),
                         fetched["etag"], fetched["last_modified"], market_research._now(), market_research._now(), tenant_id, run_id))
    except Exception as exc:
        message = (str(exc) if isinstance(exc, ValueError) else "RSS 网络请求失败，请检查来源配置或稍后重试")[:1000]
        with _conn() as con:
            con.execute("UPDATE market_sources SET health='degraded',updated_at=? WHERE tenant_id=? AND id=?", (market_research._now(), tenant_id, run["source_id"]))
            con.execute("UPDATE market_source_runs SET status='failed',stage='fetch',error=?,finished_at=?,updated_at=? WHERE tenant_id=? AND id=?",
                        (message, market_research._now(), market_research._now(), tenant_id, run_id))


async def _process_run(tenant_id: str, run_id: str) -> None:
    # Claim only after a capacity slot is available; paused batches can still cancel queued runs.
    key = (tenant_id, run_id)
    try:
        async with _SOURCE_CAPACITY:
            await _execute_run(tenant_id, run_id)
    finally:
        _scheduled_runs.discard(key)


async def _dispatch_loop() -> None:
    while True:
        try:
            with _conn() as con:
                rows = con.execute("SELECT id,tenant_id FROM market_source_runs WHERE status='queued' ORDER BY created_at LIMIT 20").fetchall()
            for row in rows:
                key = (row["tenant_id"], row["id"])
                if key in _scheduled_runs:
                    continue
                _scheduled_runs.add(key)
                task = asyncio.create_task(_process_run(row["tenant_id"], row["id"]))
                _workers.add(task); task.add_done_callback(_workers.discard)
            with _conn() as con:
                batches = con.execute("SELECT tenant_id,id FROM market_collection_batches WHERE status IN ('running','waiting') ORDER BY created_at LIMIT 200").fetchall()
            for batch in batches:
                refresh_batch(batch["tenant_id"], batch["id"])
            await asyncio.sleep(_DISPATCH_INTERVAL_SEC)
        except asyncio.CancelledError:
            raise
        except Exception:
            log.exception("市场信源运行派发失败")
            await asyncio.sleep(2)


def start() -> None:
    global _dispatcher
    if _dispatcher is None or _dispatcher.done():
        _dispatcher = asyncio.create_task(_dispatch_loop())


async def shutdown() -> None:
    global _dispatcher
    if _dispatcher:
        _dispatcher.cancel()
        try: await _dispatcher
        except asyncio.CancelledError: pass
        _dispatcher = None
    for task in list(_workers): task.cancel()
    if _workers: await asyncio.gather(*_workers, return_exceptions=True)
    _workers.clear()
    _scheduled_runs.clear()


def recover() -> int:
    """重启后把中断的运行恢复到队列；来源和发现身份保证重试幂等。"""
    with _conn() as con:
        return con.execute("UPDATE market_source_runs SET status='queued',stage='queued',updated_at=? WHERE status='running'",
                           (market_research._now(),)).rowcount


def queue_collect(tenant_id: str, user_id: str, source_id: str, topic_id: str = "", *, force_refresh: bool = False) -> dict | None:
    source = get_source(tenant_id, source_id)
    if not source: return None
    topics = source["candidate_topic_ids"]
    if not topic_id:
        if len(topics) != 1: raise ValueError("该来源关联多个主题，请选择本轮要采集的主题")
        topic_id = topics[0]
    return _new_run(tenant_id, user_id, source, topic_id, force_refresh=force_refresh)


def _append_event(con, tenant_id: str, batch_id: str, event_type: str, payload: dict) -> int:
    con.execute("UPDATE market_collection_batches SET event_sequence=event_sequence+1,updated_at=? WHERE tenant_id=? AND id=?",
                (market_research._now(), tenant_id, batch_id))
    row = con.execute("SELECT event_sequence FROM market_collection_batches WHERE tenant_id=? AND id=?", (tenant_id, batch_id)).fetchone()
    if not row: return 0
    sequence = row["event_sequence"]
    con.execute("INSERT INTO market_pipeline_events(id,tenant_id,batch_id,sequence,event_type,payload_json,created_at) VALUES(?,?,?,?,?,?,?)",
                ("mpe_" + uuid.uuid4().hex, tenant_id, batch_id, sequence, event_type,
                 json.dumps(payload, ensure_ascii=False), market_research._now()))
    return sequence


def create_batch(tenant_id: str, user_id: str, *, request_id: str, topic_id: str = "",
                 source_ids: list[str] | None = None, mode: str = "incremental", max_items: int = 500) -> dict:
    request_id = str(request_id or "").strip()
    if not request_id or len(request_id) > 100:
        raise ValueError("request_id 必须为 1–100 个字符")
    if topic_id and topic_id not in market_research.TOPIC_BY_ID:
        raise ValueError("不支持的研究主题")
    if mode == "historical":
        raise ValueError("当前只开放 RSS 可见范围内的增量/首次回采；不支持来源站点的完整历史归档")
    if mode not in {"incremental", "fetch_only"}:
        raise ValueError("mode 只支持 incremental 或 fetch_only")
    analysis_enabled = mode == "incremental"
    try: max_items = int(max_items)
    except (TypeError, ValueError) as exc: raise ValueError("max_items 必须是整数") from exc
    if not 1 <= max_items <= 2000:
        raise ValueError("单批候选条数预算须在 1–2000 之间")
    requested_ids = list(dict.fromkeys(str(source_id) for source_id in (source_ids or [])))
    scope = {"topic_id": topic_id, "mode": mode, "source_ids": requested_ids, "max_items": max_items}
    scope_hash = hashlib.sha256(json.dumps(scope, sort_keys=True).encode()).hexdigest()
    with _conn() as con:
        existing = con.execute("SELECT batch_id,scope_hash FROM market_collection_requests WHERE tenant_id=? AND request_id=?",
                               (tenant_id, request_id)).fetchone()
    if existing:
        if existing["scope_hash"] != scope_hash:
            raise RuntimeError("request_id 已用于不同的采集范围，请生成新的 request_id")
        return get_batch(tenant_id, existing["batch_id"])
    active_batch_id = ""
    with _conn() as con:
        active_scope = con.execute("SELECT id FROM market_collection_batches WHERE tenant_id=? AND scope_hash=? AND status IN ('queued','running','waiting','paused') ORDER BY created_at LIMIT 1",
                                   (tenant_id, scope_hash)).fetchone()
        if active_scope:
            con.execute("INSERT INTO market_collection_requests(tenant_id,request_id,scope_hash,batch_id,created_at) VALUES(?,?,?,?,?)",
                        (tenant_id, request_id, scope_hash, active_scope["id"], market_research._now()))
            active_batch_id = active_scope["id"]
    if active_batch_id:
        return get_batch(tenant_id, active_batch_id)

    sources = list_sources(tenant_id, enabled=True)
    if requested_ids:
        by_id = {item["id"]: item for item in sources}
        missing = [source_id for source_id in requested_ids if source_id not in by_id]
        if missing:
            raise ValueError("部分来源不存在、已停用或不属于当前租户")
        sources = [by_id[source_id] for source_id in requested_ids]
    if topic_id:
        sources = [item for item in sources if topic_id in item["candidate_topic_ids"]]
    elif any(len(item["candidate_topic_ids"]) > 1 for item in sources):
        raise ValueError("请选择研究主题后启动批次；多主题来源不能自动归入某个主题")
    if len(sources) > 100:
        raise ValueError("单批最多采集 100 个来源")
    if not sources:
        raise ValueError("当前范围没有已启用且匹配主题的来源；未创建空批次")
    if max_items < len(sources):
        raise ValueError("候选条数预算低于来源数；请提高预算或缩小来源范围")
    per_source_limit = max(1, min(_MAX_ITEMS_PER_SOURCE_RUN, max_items // len(sources)))
    batch_id, now = "mcb_" + uuid.uuid4().hex, market_research._now()
    snapshots = {item["id"]: {"name": item["name"], "kind": item["kind"], "config_version": item["config_version"],
                             "config": item["config"], "candidate_topic_ids": item["candidate_topic_ids"],
                             "tier": item["tier"], "first_party": item["first_party"], "interval_minutes": item["interval_minutes"],
                             "max_items": per_source_limit, "analysis_enabled": analysis_enabled}
                 for item in sources}
    try:
        with _conn() as con:
            con.execute("""INSERT INTO market_collection_batches(id,tenant_id,user_id,request_id,scope_hash,topic_id,mode,status,
                source_ids_json,config_snapshot_json,budget_json,source_total,created_at,updated_at)
                VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)""", (
                batch_id, tenant_id, user_id, request_id, scope_hash, topic_id, mode, "running",
            json.dumps([item["id"] for item in sources]), json.dumps(snapshots, ensure_ascii=False),
            json.dumps({"max_items": max_items, "per_source_limit": per_source_limit}), len(sources), now, now))
            con.execute("INSERT INTO market_collection_requests(tenant_id,request_id,scope_hash,batch_id,created_at) VALUES(?,?,?,?,?)",
                        (tenant_id, request_id, scope_hash, batch_id, now))
            _append_event(con, tenant_id, batch_id, "batch_created", {"source_total": len(sources), "topic_id": topic_id, "mode": mode})
    except Exception:
        recovered_batch_id = ""
        with _conn() as con:
            existing = con.execute("SELECT batch_id,scope_hash FROM market_collection_requests WHERE tenant_id=? AND request_id=?",
                                   (tenant_id, request_id)).fetchone()
            active_scope = con.execute("SELECT id FROM market_collection_batches WHERE tenant_id=? AND scope_hash=? AND status IN ('queued','running','waiting','paused') ORDER BY created_at LIMIT 1",
                                       (tenant_id, scope_hash)).fetchone()
            if existing:
                if existing["scope_hash"] != scope_hash:
                    raise RuntimeError("request_id 已用于不同的采集范围，请生成新的 request_id")
                recovered_batch_id = existing["batch_id"]
            elif active_scope:
                con.execute("INSERT OR IGNORE INTO market_collection_requests(tenant_id,request_id,scope_hash,batch_id,created_at) VALUES(?,?,?,?,?)",
                            (tenant_id, request_id, scope_hash, active_scope["id"], market_research._now()))
                recovered_batch_id = active_scope["id"]
        if recovered_batch_id:
            return get_batch(tenant_id, recovered_batch_id)
        raise
    excluded = []
    for source in sources:
        selected_topic = topic_id or source["candidate_topic_ids"][0]
        try:
            run = _new_run(tenant_id, user_id, source, selected_topic, max_items=per_source_limit,
                           analysis_enabled=analysis_enabled)
            with _conn() as con:
                con.execute("""INSERT INTO market_collection_members(id,tenant_id,batch_id,source_id,run_id,status,config_snapshot_json,created_at,updated_at)
                    VALUES(?,?,?,?,?,?,?,?,?)""", ("mcm_" + uuid.uuid4().hex, tenant_id, batch_id, source["id"], run["id"],
                    run["status"], json.dumps(snapshots[source["id"]], ensure_ascii=False), market_research._now(), market_research._now()))
        except Exception as exc:
            excluded.append({"source_id": source["id"], "reason": str(exc)[:300]})
            with _conn() as con:
                con.execute("INSERT INTO market_collection_members(id,tenant_id,batch_id,source_id,run_id,status,config_snapshot_json,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?)",
                    ("mcm_" + uuid.uuid4().hex, tenant_id, batch_id, source["id"], "", "failed", json.dumps(snapshots[source["id"]], ensure_ascii=False), market_research._now(), market_research._now()))
        else:
            # A source may already belong to an active run. Its run ID is shared, not re-fetched.
            pass
    if excluded:
        with _conn() as con:
            _append_event(con, tenant_id, batch_id, "sources_excluded", {"items": excluded})
    refresh_batch(tenant_id, batch_id)
    result = get_batch(tenant_id, batch_id)
    result["excluded"] = excluded
    return result


def _batch_payload(row) -> dict:
    item = dict(row)
    item["source_ids"] = _json(item.pop("source_ids_json", "[]"), [])
    item["counts"] = _json(item.pop("counts_json", "{}"), {})
    item["budget"] = _json(item.pop("budget_json", "{}"), {})
    item.pop("config_snapshot_json", None); item.pop("scope_hash", None)
    return item


def refresh_batch(tenant_id: str, batch_id: str) -> dict | None:
    with _conn() as con:
        batch = con.execute("SELECT * FROM market_collection_batches WHERE tenant_id=? AND id=?", (tenant_id, batch_id)).fetchone()
        if not batch: return None
        if batch["status"] in {"paused", "cancelled", "failed", "completed"}:
            return _batch_payload(batch)
        members = con.execute("SELECT * FROM market_collection_members WHERE tenant_id=? AND batch_id=? ORDER BY created_at",
                              (tenant_id, batch_id)).fetchall()
        source_counts = {"queued": 0, "running": 0, "succeeded": 0, "skipped": 0, "failed": 0, "cancelled": 0,
                         "found": 0, "new": 0, "revised": 0, "duplicate": 0, "fetch_failed": 0}
        run_ids = []
        source_terminal = 0
        analysis_requested = any(
            bool(_json(member["config_snapshot_json"], {}).get("analysis_enabled", batch["mode"] != "fetch_only"))
            for member in members)
        for member in members:
            if not member["run_id"]:
                run_status, counts = member["status"], {}
            else:
                run = con.execute("SELECT status,counts_json FROM market_source_runs WHERE tenant_id=? AND id=?",
                                  (tenant_id, member["run_id"])).fetchone()
                run_status = run["status"] if run else "failed"
                counts = _json(run["counts_json"], {}) if run else {}
                run_ids.append(member["run_id"])
            member_status = {"completed_with_issues": "failed", "interrupted": "queued"}.get(run_status, run_status)
            con.execute("UPDATE market_collection_members SET status=?,counts_json=?,updated_at=? WHERE tenant_id=? AND id=?",
                        (member_status, json.dumps(counts), market_research._now(), tenant_id, member["id"]))
            if member_status in source_counts: source_counts[member_status] += 1
            if member_status in {"succeeded", "failed", "cancelled", "skipped"}: source_terminal += 1
            for key in ("found", "new", "revised", "duplicate"):
                source_counts[key] += int(counts.get(key, 0) or 0)
            source_counts["fetch_failed"] += int(counts.get("failed", 0) or 0)

        placeholders = ",".join("?" for _ in run_ids)
        intake_statuses = []
        if run_ids:
            intake_rows = con.execute(f"""SELECT j.status FROM market_intake_jobs j JOIN market_source_discoveries d
                ON d.tenant_id=j.tenant_id AND d.intake_job_id=j.id WHERE d.tenant_id=? AND d.run_id IN ({placeholders})""",
                [tenant_id, *run_ids]).fetchall()
            intake_statuses = [row["status"] for row in intake_rows]
        pipeline = {"queued": 0, "running": 0, "waiting_retry": 0, "succeeded": 0, "failed": 0}
        for status in intake_statuses:
            mapped = {"queued": "queued", "running": "running", "interrupted": "waiting_retry", "done": "succeeded", "failed": "failed"}.get(status)
            if mapped: pipeline[mapped] += 1
        if not analysis_requested:
            pipeline["not_requested"] = len(members)
        unique_documents = 0
        observations = 0
        if run_ids:
            unique_documents = con.execute(f"SELECT COUNT(DISTINCT document_id) FROM market_source_discoveries WHERE tenant_id=? AND run_id IN ({placeholders})",
                                           [tenant_id, *run_ids]).fetchone()[0]
            observations = con.execute(f"SELECT COUNT(DISTINCT observation_id) FROM market_quality_reviews WHERE tenant_id=? AND observation_id<>'' AND document_id IN (SELECT DISTINCT document_id FROM market_source_discoveries WHERE tenant_id=? AND run_id IN ({placeholders}))",
                                       [tenant_id, tenant_id, *run_ids]).fetchone()[0]
        source_done = source_terminal >= len(members)
        pipeline_pending = pipeline["queued"] + pipeline["running"] + pipeline["waiting_retry"]
        now = market_research._now()
        if not source_done:
            status = "running"
        elif pipeline_pending:
            status = "waiting"
        else:
            status = "completed_with_issues" if source_counts["failed"] or pipeline["failed"] else "completed"
        new_fetch_finished = batch["source_fetch_finished_at"] or (now if source_done else "")
        pipeline_finished = batch["pipeline_finished_at"] or (now if source_done and not pipeline_pending else "")
        counts = {"source": source_counts, "source_terminal": source_terminal, "source_total": len(members),
                  "source_fetch_finished": source_done, "pipeline": pipeline,
                  "analysis_requested": analysis_requested,
                  "pipeline_finished": bool(source_done and not pipeline_pending),
                  "unique_documents": unique_documents, "observations": observations,
                  "as_of": now, "version": batch["event_sequence"]}
        previous_status = batch["status"]
        con.execute("UPDATE market_collection_batches SET status=?,counts_json=?,source_fetch_finished_at=?,pipeline_finished_at=?,updated_at=? WHERE tenant_id=? AND id=?",
                    (status, json.dumps(counts), new_fetch_finished, pipeline_finished, now, tenant_id, batch_id))
        if status != previous_status:
            _append_event(con, tenant_id, batch_id, "batch_status_changed", {"from": previous_status, "to": status, "counts": counts})
        refreshed = con.execute("SELECT * FROM market_collection_batches WHERE tenant_id=? AND id=?", (tenant_id, batch_id)).fetchone()
    return _batch_payload(refreshed)


def get_batch(tenant_id: str, batch_id: str) -> dict | None:
    batch = refresh_batch(tenant_id, batch_id)
    if batch is None: return None
    return {**batch, "as_of": market_research._now()}


def list_batches(tenant_id: str, limit: int = 30, offset: int = 0) -> list[dict]:
    with _conn() as con:
        rows = con.execute("SELECT id FROM market_collection_batches WHERE tenant_id=? ORDER BY created_at DESC LIMIT ? OFFSET ?",
                            (tenant_id, limit, offset)).fetchall()
    return [item for row in rows if (item := get_batch(tenant_id, row["id"]))]


def batch_tasks(tenant_id: str, batch_id: str) -> list[dict] | None:
    if not get_batch(tenant_id, batch_id): return None
    with _conn() as con:
        members = con.execute("SELECT * FROM market_collection_members WHERE tenant_id=? AND batch_id=? ORDER BY created_at",
                              (tenant_id, batch_id)).fetchall()
    result = []
    for member in members:
        source = get_source(tenant_id, member["source_id"])
        run = get_run(tenant_id, member["run_id"]) if member["run_id"] else None
        result.append({"source_id": member["source_id"], "source_name": source["name"] if source else "来源已删除",
                       "run_id": member["run_id"], "status": member["status"],
                       "counts": _json(member["counts_json"], {}), "error": run.get("error", "") if run else ""})
    return result


def batch_events(tenant_id: str, batch_id: str, after_sequence: int = 0, limit: int = 100) -> list[dict] | None:
    if not get_batch(tenant_id, batch_id): return None
    with _conn() as con:
        rows = con.execute("SELECT sequence,event_type,payload_json,created_at FROM market_pipeline_events WHERE tenant_id=? AND batch_id=? AND sequence>? ORDER BY sequence LIMIT ?",
                            (tenant_id, batch_id, after_sequence, limit)).fetchall()
    return [{**dict(row), "payload": _json(row["payload_json"], {})} for row in rows]


def batch_action(tenant_id: str, user_id: str, batch_id: str, action: str) -> dict | None:
    batch = get_batch(tenant_id, batch_id)
    if not batch: return None
    if action not in {"pause", "resume", "stop", "retry_failed"}:
        raise ValueError("不支持的批次操作")
    if action == "pause" and batch["status"] not in {"running", "waiting", "queued"}:
        raise ValueError("只有活动批次可以暂停")
    if action == "stop" and batch["status"] in {"completed", "completed_with_issues", "failed", "cancelled"}:
        raise ValueError("批次已结束")
    if action == "resume" and batch["status"] != "paused":
        raise ValueError("只有已暂停批次可以继续")
    if action == "retry_failed" and batch["status"] not in {"completed_with_issues", "failed", "cancelled"}:
        raise ValueError("仅可重试已结束批次中的失败来源")
    with _conn() as con:
        members = con.execute("SELECT * FROM market_collection_members WHERE tenant_id=? AND batch_id=? ORDER BY created_at",
                              (tenant_id, batch_id)).fetchall()
    affected = 0
    if action in {"pause", "stop"}:
        for member in members:
            if member["status"] != "queued" or not member["run_id"]: continue
            with _conn() as con:
                shared = con.execute("SELECT COUNT(*) FROM market_collection_members m JOIN market_collection_batches b ON b.id=m.batch_id AND b.tenant_id=m.tenant_id WHERE m.tenant_id=? AND m.run_id=? AND m.batch_id<>? AND b.status IN ('running','waiting','queued')",
                                     (tenant_id, member["run_id"], batch_id)).fetchone()[0]
                if not shared:
                    con.execute("UPDATE market_source_runs SET status='cancelled',stage='cancelled',updated_at=? WHERE tenant_id=? AND id=? AND status='queued'",
                                (market_research._now(), tenant_id, member["run_id"]))
                    con.execute("UPDATE market_collection_members SET status='cancelled',updated_at=? WHERE tenant_id=? AND id=?",
                                (market_research._now(), tenant_id, member["id"]))
                    affected += 1
    if action in {"resume", "retry_failed"}:
        for member in members:
            should_retry = member["status"] == "cancelled" if action == "resume" else member["status"] in {"failed", "queued"}
            if not should_retry: continue
            source = get_source(tenant_id, member["source_id"])
            if not source or not source["enabled"]: continue
            old = get_run(tenant_id, member["run_id"]) if member["run_id"] else None
            topic_id = (old or {}).get("topic_id") or (batch.get("topic_id") or source["candidate_topic_ids"][0])
            member_snapshot = _json(member["config_snapshot_json"], {})
            member_budget = member_snapshot.get("max_items", _MAX_ITEMS_PER_SOURCE_RUN)
            analysis_enabled = bool(member_snapshot.get("analysis_enabled", batch["mode"] != "fetch_only"))
            try: run = _new_run(tenant_id, user_id, source, topic_id, force_refresh=True,
                                max_items=member_budget, analysis_enabled=analysis_enabled)
            except ValueError: continue
            with _conn() as con:
                con.execute("UPDATE market_collection_members SET run_id=?,status=?,counts_json='{}',updated_at=? WHERE tenant_id=? AND id=?",
                            (run["id"], run["status"], market_research._now(), tenant_id, member["id"]))
            affected += 1
    new_status = {"pause": "paused", "resume": "running", "stop": "cancelled", "retry_failed": "running"}[action]
    with _conn() as con:
        con.execute("UPDATE market_collection_batches SET status=?,source_fetch_finished_at='',pipeline_finished_at='',updated_at=? WHERE tenant_id=? AND id=?",
                    (new_status, market_research._now(), tenant_id, batch_id))
        _append_event(con, tenant_id, batch_id, "batch_" + action, {"user_id": user_id, "affected_members": affected})
    return get_batch(tenant_id, batch_id)


def source_summary(tenant_id: str) -> dict:
    with _conn() as con:
        sources = con.execute("SELECT COUNT(*) AS total, SUM(CASE WHEN enabled=1 THEN 1 ELSE 0 END) AS enabled FROM market_sources WHERE tenant_id=?", (tenant_id,)).fetchone()
        runs = con.execute("SELECT status,COUNT(*) AS count FROM market_source_runs WHERE tenant_id=? GROUP BY status", (tenant_id,)).fetchall()
        queued = con.execute("SELECT COUNT(*) FROM market_intake_jobs WHERE tenant_id=? AND status IN ('queued','running')", (tenant_id,)).fetchone()[0]
    # Reviews are append-only history; report each discovered document's
    # latest disposition, using the same scope as the document workbench.
    document_counts = source_document_summary(tenant_id)["overall"]
    return {"source_count": sources["total"] or 0, "enabled_source_count": sources["enabled"] or 0,
            "runs": {r["status"]: r["count"] for r in runs}, "intake_pending": queued,
            "quality": {status: count for status, count in document_counts.items()
                        if status != "raw_documents"},
            "as_of": market_research._now()}


def source_document_summary(tenant_id: str) -> dict:
    """Return de-duplicated raw-document counts by each source's configured topic."""
    with _conn() as con:
        rows = con.execute("""SELECT sd.document_id,s.candidate_topics_json,
                COALESCE(q.status,'unverified') AS quality_status,COALESCE(q.evidence_json,'{}') AS review_json
            FROM market_source_discoveries sd
            JOIN market_documents d ON d.tenant_id=sd.tenant_id AND d.id=sd.document_id
            JOIN market_sources s ON s.tenant_id=sd.tenant_id AND s.id=sd.source_id
            LEFT JOIN market_quality_reviews q ON q.tenant_id=sd.tenant_id AND q.document_id=sd.document_id
                AND q.id=(SELECT q2.id FROM market_quality_reviews q2
                    WHERE q2.tenant_id=sd.tenant_id AND q2.document_id=sd.document_id
                    ORDER BY q2.created_at DESC,q2.id DESC LIMIT 1)
            WHERE sd.tenant_id=?""", (tenant_id,)).fetchall()

    document_topics: dict[str, set[str]] = {}
    document_status: dict[str, str] = {}
    for row in rows:
        document_id = row["document_id"]
        document_status[document_id] = row["quality_status"]
        review = _json(row["review_json"], {})
        reviewed_topic = review.get("topic_id") or review.get("review_topic_id")
        if reviewed_topic in market_research.TOPIC_BY_ID:
            document_topics.setdefault(document_id, set()).add(reviewed_topic)
        else:
            document_topics.setdefault(document_id, set()).update(
                topic_id for topic_id in _json(row["candidate_topics_json"], [])
                if topic_id in market_research.TOPIC_BY_ID)
    topics = {topic_id: {"raw_documents": 0, "unverified": 0, "needs_review": 0,
                         "triaged": 0, "source_attributed": 0}
              for topic_id in market_research.TOPIC_BY_ID}
    overall = {"raw_documents": len(document_topics), "unverified": 0, "needs_review": 0,
               "triaged": 0, "source_attributed": 0}
    for document_id, topic_ids in document_topics.items():
        status = document_status[document_id]
        overall[status] = overall.get(status, 0) + 1
        for topic_id in topic_ids:
            counts = topics[topic_id]
            counts["raw_documents"] += 1
            counts[status] = counts.get(status, 0) + 1
    return {"topics": topics, "overall": overall, "raw_documents": len(document_topics),
            "as_of": market_research._now()}


_LOCAL_TRIAGE_RULE_VERSION = "codex-local-triage-v1"

_LOCAL_TRIAGE_CATEGORY_RULES = {
    "ai-frontier": {
        "foundation-models": ("基础模型", (
            "large language model", "foundation model", "reasoning model", "pretraining", "fine-tuning",
            "transformer", "llm", "gpt", "claude", "gemini", "deepseek", "qwen", "llama",
            "大语言模型", "基础模型", "推理模型", "预训练", "微调", "模型训练", "语言模型")),
        "multimodal-ai": ("多模态 AI", (
            "multimodal", "vision-language", "text-to-image", "image generation", "video generation",
            "speech recognition", "audio generation", "视觉语言", "多模态", "文生图", "图像生成", "视频生成", "语音识别")),
        "ai-agents": ("智能体与工具链", (
            "agent", "agentic", "tool use", "browser use", "coding agent", "multi-agent", "workflow",
            "智能体", "工具调用", "多智能体", "工作流", "代理")),
        "compute-infrastructure": ("算力与基础设施", (
            "gpu", "accelerator", "nvidia", "inference serving", "data center", "data centre", "semiconductor",
            "inference cost", "compute cluster", "算力", "推理成本", "数据中心", "芯片", "集群")),
        "ai-applications": ("产品与行业应用", (
            "product launch", "customer", "deployment", "deployed", "clinical", "healthcare", "enterprise adoption",
            "application", "api launch", "产品发布", "客户", "部署", "临床", "医疗", "企业应用", "行业落地")),
        "ai-ecosystem": ("企业与开源生态", (
            "open source", "open-source", "github", "startup", "partnership", "funding", "fundraise", "release",
            "开源", "创业", "融资", "合作", "发布", "社区")),
    },
    "embodied-intelligence": {
        "vla-embodied-reasoning": ("VLA 与具身推理", (
            "vision-language-action", "vision language action", "vla", "embodied reasoning", "具身推理", "视觉语言动作")),
        "world-model-spatial-intelligence": ("世界模型与空间智能", (
            "world model", "spatial intelligence", "spatial reasoning", "world modeling", "世界模型", "空间智能", "空间推理")),
        "robot-learning-data": ("机器人学习与数据", (
            "robot learning", "robot dataset", "robot data", "imitation learning", "demonstration data", "机器人学习", "机器人数据", "示教学习")),
        "dexterous-manipulation-whole-body": ("灵巧操作与全身控制", (
            "manipulation", "dexterous", "whole-body control", "whole body control", "tactile", "灵巧操作", "灵巧手", "全身控制", "触觉")),
        "simulation-training-toolchain": ("仿真训练与工具链", (
            "sim-to-real", "sim2real", "simulator", "simulation", "synthetic data", "仿真", "合成数据", "虚实迁移")),
        "evaluation-safety-agent-integration": ("评测、安全与 Agent 融合", (
            "robot benchmark", "robot safety", "safety evaluation", "human-robot", "human robot", "机器人评测", "机器人安全", "人机协作")),
        "home-service-robots": ("家庭服务机器人", (
            "home robot", "household robot", "domestic robot", "home service", "家务机器人", "家庭机器人", "家庭服务")),
        "industrial-robots": ("工业机器人", (
            "industrial robot", "factory robot", "manufacturing robot", "warehouse robot", "工业机器人", "工厂机器人", "仓储机器人")),
        "commercial-service-robots": ("商业服务机器人", (
            "service robot", "commercial robot", "delivery robot", "商用服务机器人", "配送机器人", "服务机器人")),
        "robot-platforms": ("机器人本体与核心部件", (
            "humanoid", "actuator", "end-effector", "robot arm", "robot platform", "人形机器人", "执行器", "末端执行器", "机械臂", "机器人本体")),
        "embodied-models": ("具身模型与训练", (
            "embodied model", "embodied ai", "physical ai", "robot foundation model", "具身模型", "具身智能", "物理 ai")),
        "robot-commercialization": ("量产与商业化", (
            "robot deployment", "robot production", "robot orders", "robot commercialization", "机器人部署", "机器人量产", "机器人订单", "商业化")),
    },
}


def _local_document_triage(*, title: str, body_text: str, content_source: str,
                           canonical_url: str, source_rows: list[dict]) -> dict:
    """Classify material scope and suggest topics locally; this does not verify claims."""
    title_text = str(title or "").strip()
    body = re.sub(r"\s+", " ", str(body_text or "")).strip()
    title_lower, text_lower = title_text.lower(), (title_text + " " + body).lower()
    source_topics = {topic for source in source_rows
                     for topic in _json(source.get("candidate_topics_json", "[]"), [])}
    failure_count = sum(source.get("status") == "fetch_failed" for source in source_rows)
    category_matches: list[tuple[str, str, int, str]] = []
    keyword_matches: list[str] = []
    suggested_topics = set(source_topics)
    for topic_id, categories in _LOCAL_TRIAGE_CATEGORY_RULES.items():
        for category_id, (category_name, keywords) in categories.items():
            score = 0
            matched = []
            for keyword in keywords:
                phrase = keyword.lower()
                occurrences = title_lower.count(phrase) * 3 + text_lower.count(phrase)
                if occurrences:
                    score += min(occurrences, 6)
                    matched.append(keyword)
            if score:
                category_matches.append((topic_id, category_id, score, category_name))
                keyword_matches.extend(matched[:4])
                suggested_topics.add(topic_id)
    category_matches.sort(key=lambda item: (-item[2], item[0], item[1]))
    selected_categories = []
    used_topics = set()
    for topic_id, category_id, score, category_name in category_matches:
        if topic_id in source_topics or topic_id in suggested_topics:
            if topic_id not in used_topics and len(selected_categories) < 3:
                selected_categories.append({"topic_id": topic_id, "category_id": category_id,
                                           "name": category_name, "keyword_score": score})
                used_topics.add(topic_id)

    body_chars = len(body)
    hostname = (urlsplit(str(canonical_url or "")).hostname or "").lower()
    if content_source == "article_fetch" and body_chars >= 80:
        evidence_scope = "article_body"
        evidence_label = "文章正文已抓取"
    elif content_source == "fulltext" and body_chars >= 80:
        evidence_scope = "feed_body_excerpt"
        evidence_label = "Feed 含正文片段"
    elif content_source == "summary" and body_chars >= 80 and hostname.endswith("arxiv.org"):
        evidence_scope = "official_abstract"
        evidence_label = "arXiv 摘要"
    elif content_source == "summary" and body_chars >= 80:
        evidence_scope = "feed_summary"
        evidence_label = "Feed 摘要"
    else:
        evidence_scope = "metadata_or_short_text"
        evidence_label = "标题/短文本"

    if failure_count:
        next_action = "文章页抓取失败；需更换原文链接或重试，摘要不能替代全文核验。"
    elif evidence_scope == "article_body":
        next_action = "检查正文事实、数字和发布方口径，再决定是否整理成研究观察。"
    elif evidence_scope == "feed_body_excerpt":
        next_action = "Feed 正文可能是节选；关键事实回到原文确认后再整理观察。"
    elif evidence_scope == "official_abstract":
        next_action = "按论文摘要范围复核；结论、方法与数据仍需全文核对。"
    elif evidence_scope == "feed_summary":
        next_action = "先回到发布页核验摘要中的事实和数字，再决定是否整理观察。"
    else:
        next_action = "可读证据不足；先补抓原文，不从标题推导事实。"

    if category_matches:
        relevance = "来源主题内有关键词匹配；分类仅为候选提示"
    else:
        relevance = "未匹配到细分主题关键词；需人工判断相关性"
    if not suggested_topics:
        suggested_topics = {"ai-frontier"}
    return {
        "triage_method": "local_rules",
        "triage_rule_version": _LOCAL_TRIAGE_RULE_VERSION,
        "triage_generated_at": market_research._now(),
        "evidence_scope": evidence_scope,
        "evidence_scope_label": evidence_label,
        "body_chars": body_chars,
        "candidate_topics": sorted(suggested_topics),
        "suggested_categories": selected_categories,
        "matched_keywords": list(dict.fromkeys(keyword_matches))[:12],
        "relevance_hint": relevance,
        "source_count": len({source.get("source_id") for source in source_rows}),
        "failed_source_count": failure_count,
        "discovery_statuses": sorted({str(source.get("status") or "") for source in source_rows if source.get("status")}),
        "next_action": next_action,
        "human_review_required": True,
        "counts_as_research_evidence": False,
        "project_llm_called": False,
    }


def triage_unverified_documents_locally(tenant_id: str, *, limit: int = 5000) -> dict:
    """Persist a no-LLM disposition for each pending document without verifying its claims."""
    limit = min(5000, max(1, int(limit)))
    with _conn() as con:
        rows = con.execute("""SELECT DISTINCT x.id AS document_id,x.canonical_url,v.title,v.body_text,v.content_source,
                COALESCE(q.status,'unverified') AS quality_status
            FROM market_documents x
            JOIN market_document_versions v ON v.tenant_id=x.tenant_id AND v.id=x.current_version_id
            JOIN market_source_discoveries d ON d.tenant_id=x.tenant_id AND d.document_id=x.id
            LEFT JOIN market_quality_reviews q ON q.tenant_id=x.tenant_id AND q.document_id=x.id
                AND q.id=(SELECT q2.id FROM market_quality_reviews q2
                    WHERE q2.tenant_id=x.tenant_id AND q2.document_id=x.id
                    ORDER BY q2.created_at DESC,q2.id DESC LIMIT 1)
            WHERE x.tenant_id=? AND COALESCE(q.status,'unverified')='unverified'
            ORDER BY x.last_seen_at,x.id LIMIT ?""", (tenant_id, limit)).fetchall()
        if not rows:
            return {"processed": 0, "by_evidence_scope": {}, "by_candidate_topic": {},
                    "project_llm_called": False, "as_of": market_research._now()}
        doc_ids = [row["document_id"] for row in rows]
        placeholders = ",".join("?" for _ in doc_ids)
        alias_rows = con.execute(f"""SELECT d.document_id,d.source_id,d.status,s.name AS source_name,
                s.candidate_topics_json
            FROM market_source_discoveries d
            JOIN market_sources s ON s.tenant_id=d.tenant_id AND s.id=d.source_id
            WHERE d.tenant_id=? AND d.document_id IN ({placeholders})
            ORDER BY s.name,d.original_url""", [tenant_id, *doc_ids]).fetchall()
        aliases: dict[str, list[dict]] = {doc_id: [] for doc_id in doc_ids}
        for alias in alias_rows:
            aliases[alias["document_id"]].append(dict(alias))
        by_scope: dict[str, int] = {}
        by_topic: dict[str, int] = {}
        now = market_research._now()
        for row in rows:
            triage = _local_document_triage(title=row["title"], body_text=row["body_text"],
                content_source=row["content_source"], canonical_url=row["canonical_url"],
                source_rows=aliases.get(row["document_id"], []))
            triage["triage_generated_at"] = now
            triage["source_names"] = list(dict.fromkeys(source["source_name"] for source in aliases[row["document_id"]]))
            category_text = "、".join(item["name"] for item in triage["suggested_categories"][:2]) or "细分主题待人工判断"
            reason = (f"本地预审（未调用平台大模型）：{triage['evidence_scope_label']}；候选领域：{category_text}。"
                      f"{triage['next_action']}此预审不代表事实核验，暂不计入有效研究依据。")
            source_id = aliases[row["document_id"]][0]["source_id"] if aliases[row["document_id"]] else ""
            con.execute("""INSERT INTO market_quality_reviews
                (id,tenant_id,source_id,document_id,status,reason,evidence_json,reviewer_id,rule_version,created_at)
                VALUES(?,?,?,?,?,?,?,?,?,?)""",
                ("mqr_" + uuid.uuid4().hex, tenant_id, source_id, row["document_id"], "triaged",
                 reason, json.dumps(triage, ensure_ascii=False), "system:local-triage",
                 _LOCAL_TRIAGE_RULE_VERSION, now))
            by_scope[triage["evidence_scope"]] = by_scope.get(triage["evidence_scope"], 0) + 1
            for topic in triage["candidate_topics"]:
                by_topic[topic] = by_topic.get(topic, 0) + 1
        con.commit()
    return {"processed": len(rows), "by_evidence_scope": by_scope, "by_candidate_topic": by_topic,
            "project_llm_called": False, "as_of": now}


def list_source_documents(tenant_id: str, *, status: str = "unverified", source_id: str = "",
                          topic_id: str = "", query: str = "", limit: int = 50,
                          offset: int = 0) -> dict:
    """List deduplicated source documents for the raw/unverified material workbench."""
    allowed_statuses = {"unverified", "needs_review", "triaged", "source_attributed", "all"}
    if status not in allowed_statuses:
        raise ValueError("资料状态只支持 unverified、needs_review、triaged、source_attributed 或 all")
    if topic_id and topic_id not in market_research.TOPIC_BY_ID:
        raise ValueError("不支持的研究主题")
    limit = min(100, max(1, int(limit)))
    offset = max(0, int(offset))
    query = str(query or "").strip()[:100]

    sources = list_sources(tenant_id)
    if source_id and not any(item["id"] == source_id for item in sources):
        raise ValueError("没有找到该信源")
    source_ids = [item["id"] for item in sources
                  if (not source_id or item["id"] == source_id)
                  and (not topic_id or topic_id in item["candidate_topic_ids"])]
    if not source_ids:
        return {"items": [], "total": 0, "limit": limit, "offset": offset,
                "summary": {"raw_documents": 0, "unverified": 0, "needs_review": 0, "triaged": 0,
                            "source_attributed": 0, "as_of": market_research._now()}}

    source_placeholders = ",".join("?" for _ in source_ids)
    latest_review_join = """LEFT JOIN market_quality_reviews qr
        ON qr.tenant_id=x.tenant_id AND qr.document_id=x.id AND qr.id=(
            SELECT q2.id FROM market_quality_reviews q2
            WHERE q2.tenant_id=x.tenant_id AND q2.document_id=x.id
            ORDER BY q2.created_at DESC,q2.id DESC LIMIT 1
        )"""
    base_from = f"""FROM market_documents x
        JOIN market_document_versions v ON v.tenant_id=x.tenant_id AND v.id=x.current_version_id
        JOIN market_source_discoveries d ON d.tenant_id=x.tenant_id AND d.document_id=x.id
        {latest_review_join}
        WHERE x.tenant_id=? AND d.source_id IN ({source_placeholders})"""
    base_params: list = [tenant_id, *source_ids]
    search_sql = ""
    search_params: list = []
    if query:
        escaped = query.lower().replace("!", "!!").replace("%", "!%").replace("_", "!_")
        pattern = f"%{escaped}%"
        search_sql = " AND (LOWER(v.title) LIKE ? ESCAPE '!' OR LOWER(v.body_text) LIKE ? ESCAPE '!')"
        search_params = [pattern, pattern]
    status_sql = ""
    if status != "all":
        status_sql = " AND COALESCE(qr.status,'unverified')=?"
    with _conn() as con:
        status_rows = con.execute(f"""SELECT COALESCE(qr.status,'unverified') AS status,
                COUNT(DISTINCT x.id) AS count {base_from} GROUP BY COALESCE(qr.status,'unverified')""",
            base_params).fetchall()
        summary = {"raw_documents": sum(int(row["count"] or 0) for row in status_rows),
                   "unverified": 0, "needs_review": 0, "triaged": 0, "source_attributed": 0,
                   "as_of": market_research._now()}
        for row in status_rows:
            summary[row["status"]] = int(row["count"] or 0)
        total = con.execute(f"SELECT COUNT(DISTINCT x.id) {base_from}{status_sql}{search_sql}",
                             [*base_params, *([status] if status != "all" else []), *search_params]).fetchone()[0]
        rows = con.execute(f"""SELECT DISTINCT x.id AS document_id,x.canonical_url,x.title AS document_title,
                v.title,v.body_text,v.content_source,v.published_at,v.publication_month,v.fetched_at,
                COALESCE(qr.status,'unverified') AS quality_status,
                COALESCE(qr.reason,'尚未生成质量核验记录') AS quality_reason,
                COALESCE(qr.evidence_json,'{{}}') AS evidence_json,
                COALESCE(qr.observation_id,'') AS observation_id,x.first_seen_at,x.last_seen_at
            {base_from}{status_sql}{search_sql}
            ORDER BY x.last_seen_at DESC,x.id LIMIT ? OFFSET ?""",
            [*base_params, *([status] if status != "all" else []), *search_params, limit, offset]).fetchall()
        document_ids = [row["document_id"] for row in rows]
        aliases: dict[str, list[dict]] = {document_id: [] for document_id in document_ids}
        if document_ids:
            doc_placeholders = ",".join("?" for _ in document_ids)
            alias_rows = con.execute(f"""SELECT DISTINCT d.document_id,s.id AS source_id,s.name AS source_name,
                    d.original_url,d.status AS discovery_status,d.intake_job_id
                FROM market_source_discoveries d
                JOIN market_sources s ON s.tenant_id=d.tenant_id AND s.id=d.source_id
                WHERE d.tenant_id=? AND d.document_id IN ({doc_placeholders})
                ORDER BY s.name,d.original_url""", [tenant_id, *document_ids]).fetchall()
            for alias in alias_rows:
                aliases[alias["document_id"]].append({
                    "source_id": alias["source_id"], "source_name": alias["source_name"],
                    "url": alias["original_url"], "discovery_status": alias["discovery_status"],
                    "intake_job_id": alias["intake_job_id"],
                })

    items = []
    for row in rows:
        item = dict(row)
        item["triage"] = _json(item.pop("evidence_json", "{}"), {})
        body = " ".join(str(item.pop("body_text") or "").split())
        item["excerpt"] = body[:1200]
        item["sources"] = aliases.get(item["document_id"], [])
        item["source_count"] = len({source["source_id"] for source in item["sources"]})
        item["discovery_statuses"] = sorted({source["discovery_status"] for source in item["sources"]})
        items.append(item)
    return {"items": items, "total": int(total), "limit": limit, "offset": offset,
            "summary": summary}


def mark_observation_attributed(tenant_id: str, url: str, observation_id: str, *,
                                source_name: str = "", published_at: str = "",
                                document_snapshot: dict | None = None) -> None:
    """Only called after intake's exact-quote check and observation save succeed."""
    identity = market_research._source_identity("", [{"url": url}])
    with _conn() as con:
        document = con.execute("SELECT id,current_version_id FROM market_documents WHERE tenant_id=? AND canonical_identity=?",
                               (tenant_id, identity)).fetchone()
        if not document:
            return
        now = market_research._now()
        version_id = document["current_version_id"]
        snapshot_text = str((document_snapshot or {}).get("text") or "")
        if snapshot_text:
            snapshot_title = str((document_snapshot or {}).get("title") or "").strip()
            fingerprint = hashlib.sha256((snapshot_title + "\n" + re.sub(r"\s+", " ", snapshot_text).strip()).encode()).hexdigest()
            version = con.execute("SELECT id FROM market_document_versions WHERE tenant_id=? AND document_id=? AND content_hash=?",
                                  (tenant_id, document["id"], fingerprint)).fetchone()
            if version:
                version_id = version["id"]
            else:
                version_id = "mdv_" + uuid.uuid4().hex
                con.execute("INSERT INTO market_document_versions(id,tenant_id,document_id,content_hash,title,body_text,content_source,published_at,fetched_at,created_at) VALUES(?,?,?,?,?,?,?,?,?,?)",
                    (version_id, tenant_id, document["id"], fingerprint, snapshot_title, snapshot_text[:100000],
                     "article_fetch", published_at, (document_snapshot or {}).get("fetched_at") or now, now))
                con.execute("UPDATE market_documents SET current_version_id=? WHERE tenant_id=? AND id=?",
                            (version_id, tenant_id, document["id"]))
        observation = con.execute("SELECT sources_json,research_metadata_json,source_name FROM market_research_observations WHERE tenant_id=? AND id=?",
                                  (tenant_id, observation_id)).fetchone()
        if observation:
            sources = _json(observation["sources_json"], [])
            source_records = con.execute("""SELECT d.original_url,s.name FROM market_source_discoveries d
                JOIN market_sources s ON s.tenant_id=d.tenant_id AND s.id=d.source_id
                WHERE d.tenant_id=? AND d.document_id=?""", (tenant_id, document["id"])).fetchall()
            if source_name:
                source_records = list(source_records) + [{"original_url": url, "name": source_name}]
            for source_record in source_records:
                attributed_url = source_record["original_url"] or url
                attributed_name = source_record["name"] or source_name
                if attributed_name and not any(item.get("url") == attributed_url and item.get("organization") == attributed_name for item in sources):
                    sources.append({"title": attributed_name, "url": attributed_url,
                                    "published_at": published_at if attributed_url == url else "",
                                    "organization": attributed_name})
            metadata = _json(observation["research_metadata_json"], {})
            metadata["source_provenance"] = {
                "document_id": document["id"], "document_version_id": version_id,
                "quality_status": "source_attributed",
                "quality_note": "原文已读取且抽取引述通过原文匹配校验；尚未独立交叉验证",
            }
            con.execute("UPDATE market_research_observations SET sources_json=?,research_metadata_json=?,source_name=CASE WHEN source_name IN ('','链接采集') AND ?<>'' THEN ? ELSE source_name END,updated_at=? WHERE tenant_id=? AND id=?",
                        (json.dumps(sources[:30], ensure_ascii=False), json.dumps(metadata, ensure_ascii=False),
                         source_name, source_name, now, tenant_id, observation_id))
        con.execute("UPDATE market_quality_reviews SET status='source_attributed',observation_id=?,reason='原文已读取且抽取引述通过原文匹配校验；不代表独立交叉验证' WHERE tenant_id=? AND document_id=? AND status IN ('unverified','needs_review','triaged')",
                    (observation_id, tenant_id, document["id"]))
        con.execute("UPDATE market_source_discoveries SET status='observation_saved',last_seen_at=? WHERE tenant_id=? AND document_id=?",
                    (now, tenant_id, document["id"]))
