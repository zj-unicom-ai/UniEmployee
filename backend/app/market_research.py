"""小察行业研究工作台的结构化观察记录。"""

from __future__ import annotations

import json
import hashlib
import uuid
from datetime import datetime, timezone
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from app import conversations
from app import db as dblayer

TOPICS = [
    {
        "id": "embodied-intelligence",
        "name": "具身智能",
        "eyebrow": "ROBOTICS & EMBODIED AI",
        "description": "机器人本体、具身模型、核心零部件与落地场景",
        "accent": "copper",
        "categories": [
            {"id": "vla-embodied-reasoning", "name": "VLA 与具身推理", "description": "视觉-语言-动作模型、物理推理与机器人任务执行"},
            {"id": "world-model-spatial-intelligence", "name": "世界模型与空间智能", "description": "环境表征、空间理解、状态预测与行动规划"},
            {"id": "robot-learning-data", "name": "机器人学习与数据", "description": "机器人数据采集、示教学习、训练规模与跨本体迁移"},
            {"id": "dexterous-manipulation-whole-body", "name": "灵巧操作与全身控制", "description": "灵巧手、触觉反馈、精细操作、运动与全身协调"},
            {"id": "simulation-training-toolchain", "name": "仿真训练与工具链", "description": "机器人仿真环境、训练框架、合成数据与 Sim-to-Real"},
            {"id": "evaluation-safety-agent-integration", "name": "评测、安全与 Agent 融合", "description": "能力评测、安全验证、可靠运行与 Agent 系统集成"},
            {"id": "home-service-robots", "name": "家庭服务机器人", "description": "家务、陪伴与家庭场景的机器人产品和落地"},
            {"id": "industrial-robots", "name": "工业机器人", "description": "制造、仓储与工业现场的机器人应用"},
            {"id": "commercial-service-robots", "name": "商业服务机器人", "description": "商用服务、公共空间与专业服务场景"},
            {"id": "robot-platforms", "name": "机器人本体与核心部件", "description": "整机平台、灵巧手、执行器、传感器与控制系统"},
            {"id": "embodied-models", "name": "具身模型与训练", "description": "具身基础模型、数据、仿真与训练方法"},
            {"id": "robot-commercialization", "name": "量产与商业化", "description": "成本、交付、供应链、融资与规模化进程"},
        ],
    },
    {
        "id": "ai-frontier",
        "name": "AI 前沿观察",
        "eyebrow": "MODELS, AGENTS & COMPUTE",
        "description": "模型与智能体进展、算力基础设施和应用边界",
        "accent": "blue",
        "categories": [
            {"id": "foundation-models", "name": "基础模型", "description": "大语言模型、推理模型与模型能力进展"},
            {"id": "multimodal-ai", "name": "多模态 AI", "description": "图像、音频、视频与跨模态理解生成"},
            {"id": "ai-agents", "name": "智能体与工具链", "description": "Agent、工作流、开发框架与工具生态"},
            {"id": "compute-infrastructure", "name": "算力与基础设施", "description": "芯片、云平台、推理成本与数据基础设施"},
            {"id": "ai-applications", "name": "产品与行业应用", "description": "AI 产品发布、商业模式与行业落地"},
            {"id": "ai-ecosystem", "name": "企业与开源生态", "description": "企业竞争、开源项目与产业合作"},
        ],
    },
    {
        "id": "policy-analysis",
        "name": "政策分析",
        "eyebrow": "POLICY & REGULATION",
        "description": "产业政策、监管规则、标准与政策传导影响",
        "accent": "green",
        "categories": [
            {"id": "national-strategy", "name": "国家战略与规划", "description": "国家级规划、战略部署与专项行动"},
            {"id": "industry-support", "name": "产业扶持政策", "description": "补贴、税收、基金与产业扶持措施"},
            {"id": "regulation-compliance", "name": "监管与合规", "description": "监管规则、数据治理、安全与合规要求"},
            {"id": "standards-certification", "name": "标准与认证", "description": "国家/行业标准、认证和检测规则"},
            {"id": "local-pilots", "name": "地方试点与项目", "description": "地方试点、示范项目与政府采购"},
            {"id": "policy-impact", "name": "政策落地与产业影响", "description": "政策执行进度及其对产业链的传导"},
        ],
    },
]
TOPIC_BY_ID = {topic["id"]: topic for topic in TOPICS}
CATEGORY_BY_TOPIC_ID = {
    (topic["id"], category["id"]): category
    for topic in TOPICS for category in topic["categories"]
}

_DDL = """
CREATE TABLE IF NOT EXISTS market_research_observations (
    id TEXT PRIMARY KEY,
    tenant_id TEXT NOT NULL,
    topic_id TEXT NOT NULL,
    category_id TEXT NOT NULL DEFAULT '',
    title TEXT NOT NULL,
    summary TEXT NOT NULL DEFAULT '',
    content_markdown TEXT NOT NULL DEFAULT '',
    sources_json TEXT NOT NULL DEFAULT '[]',
    ingest_method TEXT NOT NULL DEFAULT 'agent',
    source_name TEXT NOT NULL DEFAULT '',
    published_at TEXT NOT NULL DEFAULT '',
    captured_at TEXT NOT NULL,
    created_by TEXT NOT NULL DEFAULT '',
    created_by_name TEXT NOT NULL DEFAULT '',
    employee_id TEXT NOT NULL DEFAULT 'market-intel',
    conv_id TEXT NOT NULL DEFAULT '',
    source_key TEXT NOT NULL DEFAULT '',
    deleted_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_market_research_tenant_topic_time
    ON market_research_observations(tenant_id, topic_id, captured_at DESC);
CREATE TABLE IF NOT EXISTS market_research_analyses (
    id TEXT PRIMARY KEY,
    tenant_id TEXT NOT NULL,
    observation_id TEXT NOT NULL,
    user_id TEXT NOT NULL,
    conversation_id TEXT NOT NULL,
    run_id TEXT NOT NULL,
    focus_question TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_market_research_analyses_observation
    ON market_research_analyses(tenant_id, observation_id, user_id, created_at DESC);
CREATE TABLE IF NOT EXISTS market_research_judgements (
    id TEXT PRIMARY KEY,
    tenant_id TEXT NOT NULL,
    topic_id TEXT NOT NULL,
    category_id TEXT NOT NULL DEFAULT '',
    version INTEGER NOT NULL,
    title TEXT NOT NULL,
    conclusion TEXT NOT NULL DEFAULT '',
    content_markdown TEXT NOT NULL DEFAULT '',
    confidence TEXT NOT NULL DEFAULT 'medium',
    report_status TEXT NOT NULL DEFAULT 'draft',
    data_cutoff TEXT NOT NULL DEFAULT '',
    evidence_ids_json TEXT NOT NULL DEFAULT '[]',
    sources_json TEXT NOT NULL DEFAULT '[]',
    created_at TEXT NOT NULL,
    created_by TEXT NOT NULL DEFAULT '',
    created_by_name TEXT NOT NULL DEFAULT '',
    UNIQUE(tenant_id,topic_id,category_id,version)
);
CREATE INDEX IF NOT EXISTS idx_market_research_judgements_scope
    ON market_research_judgements(tenant_id,topic_id,category_id,version DESC);
"""


def _conn():
    con = conversations._conn()
    con.executescript(_DDL)
    if "source_key" not in dblayer.table_columns(con, "market_research_observations"):
        con.execute(
            "ALTER TABLE market_research_observations ADD COLUMN source_key TEXT NOT NULL DEFAULT ''"
        )
    if "deleted_at" not in dblayer.table_columns(con, "market_research_observations"):
        con.execute("ALTER TABLE market_research_observations ADD COLUMN deleted_at TEXT")
    if "category_id" not in dblayer.table_columns(con, "market_research_observations"):
        con.execute(
            "ALTER TABLE market_research_observations "
            "ADD COLUMN category_id TEXT NOT NULL DEFAULT ''")
    if "updated_at" not in dblayer.table_columns(con, "market_research_observations"):
        con.execute("ALTER TABLE market_research_observations ADD COLUMN updated_at TEXT NOT NULL DEFAULT ''")
    if "research_metadata_json" not in dblayer.table_columns(con, "market_research_observations"):
        con.execute("ALTER TABLE market_research_observations ADD COLUMN research_metadata_json TEXT NOT NULL DEFAULT '{}'")
    if "generation_key" not in dblayer.table_columns(con, "market_research_judgements"):
        con.execute("ALTER TABLE market_research_judgements ADD COLUMN generation_key TEXT NOT NULL DEFAULT ''")
    con.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_market_judgement_generation ON market_research_judgements(tenant_id,generation_key) WHERE generation_key<>''")
    con.execute(
        "CREATE INDEX IF NOT EXISTS idx_market_research_tenant_topic_category "
        "ON market_research_observations(tenant_id,topic_id,category_id)"
    )
    con.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS idx_market_research_source_key "
        "ON market_research_observations(tenant_id,topic_id,source_key) "
        "WHERE source_key<>''"
    )
    return con


def init_tables() -> None:
    con = _conn()
    con.commit()
    con.close()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="microseconds")


def _validate_sources(sources: list[dict] | None) -> list[dict]:
    if not isinstance(sources or [], list):
        raise ValueError("sources 必须是列表")
    normalized = []
    for source in (sources or [])[:30]:
        if not isinstance(source, dict):
            continue
        url = str(source.get("url") or "").strip()[:2000]
        if url and not url.startswith(("https://", "http://")):
            continue
        normalized.append({
            "title": str(source.get("title") or "").strip()[:300],
            "url": url,
            "published_at": str(source.get("published_at") or "").strip()[:100],
            "organization": str(source.get("organization") or "").strip()[:200],
        })
    return normalized


def _validate_category(topic_id: str, category_id: str | None) -> str:
    if topic_id not in TOPIC_BY_ID:
        raise ValueError("不支持的研究主题")
    category_id = str(category_id or "").strip()
    if not category_id:
        return ""
    allowed = {item["id"] for item in TOPIC_BY_ID[topic_id]["categories"]}
    if category_id not in allowed:
        raise ValueError("细分领域不属于所选研究主题")
    return category_id


def create_observation(*, tenant_id: str, topic_id: str, title: str,
                       category_id: str = "",
                       summary: str = "", content_markdown: str = "",
                       sources: list[dict] | None = None,
                       ingest_method: str = "agent", source_name: str = "",
                       published_at: str = "", created_by: str = "",
                       created_by_name: str = "", employee_id: str = "market-intel",
                       conv_id: str = "", source_key: str = "", research_metadata: dict | None = None) -> dict:
    if topic_id not in TOPIC_BY_ID:
        raise ValueError("不支持的研究主题")
    clean_category_id = _validate_category(topic_id, category_id)
    clean_title = str(title or "").strip()[:300]
    if not clean_title:
        raise ValueError("标题不能为空")
    if ingest_method not in {"agent", "manual", "source_task", "file_import"}:
        raise ValueError("不支持的采集方式")
    clean_sources = _validate_sources(sources)
    if not isinstance(research_metadata or {}, dict):
        raise ValueError("research_metadata 必须是对象")
    item = {
        "id": "mro_" + uuid.uuid4().hex,
        "tenant_id": tenant_id,
        "topic_id": topic_id,
        "category_id": clean_category_id,
        "title": clean_title,
        "summary": str(summary or "").strip()[:2000],
        "content_markdown": str(content_markdown or "").strip()[:100_000],
        "sources_json": json.dumps(clean_sources, ensure_ascii=False),
        "research_metadata_json": json.dumps(research_metadata or {}, ensure_ascii=False),
        "ingest_method": ingest_method,
        "source_name": str(source_name or "").strip()[:200],
        "published_at": str(published_at or "").strip()[:100],
        "captured_at": _now(),
        "created_by": str(created_by or "")[:200],
        "created_by_name": str(created_by_name or "")[:200],
        "employee_id": employee_id or "market-intel",
        "conv_id": conv_id or "",
        "source_key": str(source_key or "")[:128],
    }
    with _conn() as con:
        con.execute(
            "INSERT INTO market_research_observations "
            "(id,tenant_id,topic_id,category_id,title,summary,content_markdown,sources_json,"
            "ingest_method,source_name,published_at,captured_at,created_by,"
            "created_by_name,employee_id,conv_id,source_key,research_metadata_json) "
            "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            tuple(item[key] for key in (
                "id", "tenant_id", "topic_id", "category_id", "title", "summary", "content_markdown",
                "sources_json", "ingest_method", "source_name", "published_at", "captured_at",
                "created_by", "created_by_name", "employee_id", "conv_id", "source_key", "research_metadata_json")),
        )
    return _deserialize(item)


def _source_identity(external_id: str, sources: list[dict] | None) -> str:
    """Normalize a stable feed identity; prefer a publisher's immutable item ID."""
    external_id = str(external_id or "").strip()
    normalized = _validate_sources(sources)
    source_url = next((source["url"] for source in normalized if source.get("url")), "")
    if not source_url:
        raise ValueError("定时采集记录必须提供至少一个来源 URL")
    if external_id:
        namespace = urlsplit(source_url).netloc.strip().casefold()
        identity = f"id:{namespace}:{external_id}"
    else:
        parts = urlsplit(source_url)
        query = [(key, value) for key, value in parse_qsl(parts.query, keep_blank_values=True)
                 if not key.lower().startswith("utm_")
                 and key.lower() not in {"gclid", "fbclid", "mc_cid", "mc_eid"}]
        path = parts.path.rstrip("/") or "/"
        identity = "url:" + urlunsplit((parts.scheme.lower(), parts.netloc.lower(), path,
                                        urlencode(sorted(query)), ""))
    return hashlib.sha256(identity.encode("utf-8")).hexdigest()


def save_source_observation(*, tenant_id: str, topic_id: str, title: str,
                            category_id: str = "",
                            summary: str = "", content_markdown: str = "",
                            sources: list[dict] | None = None,
                            source_name: str = "", published_at: str = "",
                            external_id: str = "", created_by: str = "",
                            created_by_name: str = "外部研究智能体", research_metadata: dict | None = None,
                            conv_id: str = "", ingest_method: str = "source_task") -> dict:
    """Save a source-ingested observation once per publisher ID or canonical URL.

    Returns ``{"created": bool, "item": observation}``, allowing scheduled agents
    to run repeatedly without duplicating the same source item for a tenant/topic.
    """
    source_key = _source_identity(external_id, sources)
    existing = find_source_observation(tenant_id=tenant_id, topic_id=topic_id, sources=sources) if not external_id else None
    if existing:
        return {"created": False, "item": existing}
    with _conn() as con:
        row = con.execute(
            "SELECT * FROM market_research_observations "
            "WHERE tenant_id=? AND topic_id=? AND source_key=?",
            (tenant_id, topic_id, source_key),
        ).fetchone()
    if row:
        return {"created": False, "item": _deserialize(dict(row))}

    try:
        item = create_observation(
            tenant_id=tenant_id, topic_id=topic_id, category_id=category_id, title=title,
            summary=summary, content_markdown=content_markdown, sources=sources,
            ingest_method=ingest_method, source_name=source_name, conv_id=conv_id,
            published_at=published_at, created_by=created_by,
            created_by_name=created_by_name, employee_id="market-intel",
            source_key=source_key, research_metadata=research_metadata,
        )
    except Exception:
        # Concurrent scheduled runs may race after the initial lookup; the unique
        # index chooses a single winner and the loser returns that same record.
        with _conn() as con:
            row = con.execute(
                "SELECT * FROM market_research_observations "
                "WHERE tenant_id=? AND topic_id=? AND source_key=?",
                (tenant_id, topic_id, source_key),
            ).fetchone()
        if row:
            return {"created": False, "item": _deserialize(dict(row))}
        raise
    from app import market_intake
    market_intake.enqueue_source(tenant_id, item)
    return {"created": True, "item": item}


def find_source_observation(*, tenant_id: str, topic_id: str, sources: list[dict] | None) -> dict | None:
    wanted = {_source_identity("", [s]) for s in _validate_sources(sources) if s.get("url")}
    if not wanted:
        return None
    with _conn() as con:
        placeholders = ','.join('?' for _ in wanted)
        indexed = con.execute("SELECT * FROM market_research_observations WHERE tenant_id=? AND topic_id=? AND source_key IN (" + placeholders + ") ORDER BY captured_at,id LIMIT 1", [tenant_id, topic_id, *wanted]).fetchone()
        if indexed:
            return _deserialize(dict(indexed))
        rows = con.execute("SELECT * FROM market_research_observations WHERE tenant_id=? AND topic_id=? ORDER BY captured_at,id", (tenant_id, topic_id)).fetchall()
    for row in rows:
        item = _deserialize(dict(row))
        if any(_source_identity("", [s]) in wanted for s in item["sources"] if s.get("url")):
            return item
    return None


def _deserialize(row: dict) -> dict:
    item = dict(row)
    item.pop("tenant_id", None)
    item.pop("source_key", None)
    category = CATEGORY_BY_TOPIC_ID.get((item.get("topic_id"), item.get("category_id")))
    item["category_name"] = category["name"] if category else ""
    raw = item.pop("sources_json", "[]")
    try:
        item["sources"] = json.loads(raw or "[]")
    except (TypeError, json.JSONDecodeError):
        item["sources"] = []
    try:
        item["research_metadata"] = json.loads(item.pop("research_metadata_json", "{}") or "{}")
    except (TypeError, json.JSONDecodeError):
        item["research_metadata"] = {}
    return item


def get_observation(*, tenant_id: str, observation_id: str,
                   include_deleted: bool = False) -> dict | None:
    """按租户读取一条小察研究观察；回收站操作可显式包含已删除记录。"""
    deleted_clause = "" if include_deleted else " AND deleted_at IS NULL"
    with _conn() as con:
        row = con.execute(
            "SELECT * FROM market_research_observations "
            "WHERE id=? AND tenant_id=? AND employee_id=?" + deleted_clause,
            (observation_id, tenant_id, "market-intel"),
        ).fetchone()
    return _deserialize(dict(row)) if row else None


def soft_delete_observation(*, tenant_id: str, observation_id: str) -> bool:
    """把观察移入回收站；正文、来源和研判关联均保留，可恢复。"""
    with _conn() as con:
        cur = con.execute(
            "UPDATE market_research_observations SET deleted_at=? "
            "WHERE id=? AND tenant_id=? AND employee_id=? AND deleted_at IS NULL",
            (_now(), observation_id, tenant_id, "market-intel"),
        )
    return cur.rowcount > 0


def restore_observation(*, tenant_id: str, observation_id: str) -> bool:
    """从回收站恢复观察，关联研判记录同时重新可用。"""
    with _conn() as con:
        cur = con.execute(
            "UPDATE market_research_observations SET deleted_at=NULL,updated_at=? "
            "WHERE id=? AND tenant_id=? AND employee_id=? AND deleted_at IS NOT NULL",
            (_now(), observation_id, tenant_id, "market-intel"),
        )
    return cur.rowcount > 0


def set_observation_category(*, tenant_id: str, observation_id: str,
                             category_id: str = "") -> dict | None:
    item = get_observation(tenant_id=tenant_id, observation_id=observation_id)
    if item is None:
        return None
    clean_category_id = _validate_category(item["topic_id"], category_id)
    with _conn() as con:
        con.execute(
            "UPDATE market_research_observations SET category_id=?,updated_at=? "
            "WHERE id=? AND tenant_id=? AND employee_id=? AND deleted_at IS NULL",
            (clean_category_id, _now(), observation_id, tenant_id, "market-intel"),
        )
    return get_observation(tenant_id=tenant_id, observation_id=observation_id)


def create_analysis(*, tenant_id: str, observation_id: str, user_id: str,
                    conversation_id: str, run_id: str,
                    focus_question: str = "") -> dict:
    item = {
        "id": "mra_" + uuid.uuid4().hex,
        "tenant_id": tenant_id,
        "observation_id": observation_id,
        "user_id": user_id,
        "conversation_id": conversation_id,
        "run_id": run_id,
        "focus_question": str(focus_question or "").strip()[:2000],
        "created_at": _now(),
    }
    with _conn() as con:
        con.execute(
            "INSERT INTO market_research_analyses "
            "(id,tenant_id,observation_id,user_id,conversation_id,run_id,focus_question,created_at) "
            "VALUES(?,?,?,?,?,?,?,?)",
            tuple(item[key] for key in (
                "id", "tenant_id", "observation_id", "user_id", "conversation_id",
                "run_id", "focus_question", "created_at")),
        )
    item.pop("tenant_id", None)
    item.pop("user_id", None)
    return item


def list_analyses(*, tenant_id: str, observation_id: str, user_id: str,
                  limit: int = 20) -> list[dict]:
    limit = min(50, max(1, int(limit)))
    with _conn() as con:
        rows = con.execute(
            "SELECT id,observation_id,conversation_id,run_id,focus_question,created_at "
            "FROM market_research_analyses WHERE tenant_id=? AND observation_id=? AND user_id=? "
            "ORDER BY created_at DESC,id DESC LIMIT ?",
            (tenant_id, observation_id, user_id, limit),
        ).fetchall()
    return [dict(row) for row in rows]


def _judgement_dict(row: dict | None) -> dict | None:
    if not row:
        return None
    item = dict(row)
    item.pop("tenant_id", None)
    for source_key, target_key in (("evidence_ids_json", "evidence_ids"),
                                   ("sources_json", "sources")):
        raw = item.pop(source_key, "[]")
        try:
            item[target_key] = json.loads(raw or "[]")
        except (TypeError, json.JSONDecodeError):
            item[target_key] = []
    return item


def get_judgement(*, tenant_id: str, topic_id: str, category_id: str = "",
                  include_evidence: bool = False, evidence_limit: int = 100) -> dict:
    """读取主题或细分领域最新一版研判，并计算新增证据状态。"""
    if topic_id not in TOPIC_BY_ID:
        raise ValueError("不支持的研究主题")
    clean_category_id = _validate_category(topic_id, category_id)
    with _conn() as con:
        row = con.execute(
            "SELECT * FROM market_research_judgements "
            "WHERE tenant_id=? AND topic_id=? AND category_id=? "
            "ORDER BY version DESC LIMIT 1",
            (tenant_id, topic_id, clean_category_id),
        ).fetchone()
        scope_where = "tenant_id=? AND topic_id=? AND employee_id=? AND deleted_at IS NULL"
        scope_params: list = [tenant_id, topic_id, "market-intel"]
        if clean_category_id:
            scope_where += " AND category_id=?"
            scope_params.append(clean_category_id)
        stats = con.execute(
            "SELECT COUNT(*) AS evidence_count,MAX(captured_at) AS latest_evidence_at "
            "FROM market_research_observations WHERE " + scope_where,
            scope_params,
        ).fetchone()
        report = _judgement_dict(dict(row)) if row else None
        evidence_count = int(stats["evidence_count"] or 0)
        latest_evidence_at = stats["latest_evidence_at"]
        new_evidence_count = 0
        if report and report.get("data_cutoff"):
            new_evidence_count = int(con.execute(
                "SELECT COUNT(*) FROM market_research_observations WHERE "
                + scope_where + " AND (captured_at>? OR updated_at>? OR captured_at>?)",
                [*scope_params, report["data_cutoff"], report["created_at"], report["created_at"]],
            ).fetchone()[0])
        invalid_reference_count = 0
        if report and report["evidence_ids"]:
            placeholders = ','.join('?' for _ in report["evidence_ids"])
            valid_references = con.execute("SELECT COUNT(*) FROM market_research_observations WHERE " + scope_where + f" AND id IN ({placeholders})", [*scope_params, *report["evidence_ids"]]).fetchone()[0]
            invalid_reference_count = len(report["evidence_ids"]) - int(valid_references)
        items = []
        if include_evidence:
            evidence_rows = con.execute(
                "SELECT * FROM market_research_observations WHERE " + scope_where
                + " ORDER BY captured_at DESC,id DESC LIMIT ?",
                [*scope_params, min(100, max(1, int(evidence_limit)))],
            ).fetchall()
            items = [_deserialize(dict(entry)) for entry in evidence_rows]

    return {
        "topic_id": topic_id,
        "category_id": clean_category_id,
        "report": report,
        "evidence_count": evidence_count,
        "latest_evidence_at": latest_evidence_at,
        "new_evidence_count": new_evidence_count,
        "invalid_reference_count": invalid_reference_count,
        "freshness": "missing" if not report else ("stale" if new_evidence_count or invalid_reference_count else "current"),
        "evidence": items,
    }


def list_judgement_history(*, tenant_id: str, topic_id: str, category_id: str = "",
                           limit: int = 20) -> list[dict]:
    """Return compact, newest-first snapshots so users can follow report changes."""
    if topic_id not in TOPIC_BY_ID:
        raise ValueError("不支持的研究主题")
    clean_category_id = _validate_category(topic_id, category_id)
    limit = min(50, max(1, int(limit)))
    with _conn() as con:
        rows = con.execute(
            "SELECT id,version,title,conclusion,confidence,report_status,data_cutoff,"
            "evidence_ids_json,sources_json,created_at,created_by_name "
            "FROM market_research_judgements WHERE tenant_id=? AND topic_id=? "
            "AND category_id=? ORDER BY version DESC LIMIT ?",
            (tenant_id, topic_id, clean_category_id, limit),
        ).fetchall()
    history = []
    for row in rows:
        item = dict(row)
        try:
            item["evidence_count"] = len(json.loads(item.pop("evidence_ids_json") or "[]"))
        except (TypeError, json.JSONDecodeError):
            item["evidence_count"] = 0
        try:
            item["source_count"] = len(json.loads(item.pop("sources_json") or "[]"))
        except (TypeError, json.JSONDecodeError):
            item["source_count"] = 0
        history.append(item)
    return history


def get_topic_judgement_overview(*, tenant_id: str, topic_id: str) -> dict:
    """主题总览：返回主题级研判及各细分研判，供主题判断汇总使用。"""
    if topic_id not in TOPIC_BY_ID:
        raise ValueError("不支持的研究主题")
    topic_report = get_judgement(tenant_id=tenant_id, topic_id=topic_id)
    categories = [
        {**category, **get_judgement(
            tenant_id=tenant_id, topic_id=topic_id, category_id=category["id"])}
        for category in TOPIC_BY_ID[topic_id]["categories"]
    ]
    topic_report = topic_report.copy()
    report = topic_report.get("report")
    if report:
        newer_category_reports = [
            item for item in categories
            if item.get("report") and item["report"].get("created_at", "") > report.get("created_at", "")
        ]
        topic_report["updated_category_count"] = len(newer_category_reports)
        pending_children = any(item["evidence_count"] and item["freshness"] == "stale" for item in categories)
        topic_report["freshness"] = (
            "stale" if newer_category_reports or pending_children
            or topic_report["new_evidence_count"] else "current")
    else:
        topic_report["updated_category_count"] = 0
        topic_report["freshness"] = "missing"
    return {
        "topic_id": topic_id,
        "topic": {key: TOPIC_BY_ID[topic_id][key]
                  for key in ("id", "name", "description", "accent", "eyebrow")},
        "topic_report": topic_report,
        "categories": categories,
        "reported_category_count": sum(1 for item in categories if item.get("report") and item["evidence_count"]),
        "category_count": len(categories),
    }


def save_judgement(*, tenant_id: str, topic_id: str, category_id: str = "",
                   title: str, conclusion: str, content_markdown: str,
                   confidence: str = "medium", data_cutoff: str = "",
                   evidence_ids: list[str] | None = None,
                   sources: list[dict] | None = None, created_by: str = "",
                   created_by_name: str = "", generation_key: str = "") -> dict:
    """追加保存一版主题/细分领域研判，保留版本与引用证据。"""
    if topic_id not in TOPIC_BY_ID:
        raise ValueError("不支持的研究主题")
    clean_category_id = _validate_category(topic_id, category_id)
    confidence = str(confidence or "medium").strip().lower()
    if confidence not in {"high", "medium", "low"}:
        raise ValueError("confidence 只能是 high、medium 或 low")
    clean_title = str(title or "").strip()[:300]
    clean_conclusion = str(conclusion or "").strip()[:4000]
    clean_content = str(content_markdown or "").strip()[:100_000]
    if not clean_title or not clean_conclusion or not clean_content:
        raise ValueError("研判标题、结论和正文不能为空")
    clean_sources = _validate_sources(sources)
    if not any(s.get("url") for s in clean_sources):
        raise ValueError("研判至少需要一个可追溯来源")
    if not isinstance(evidence_ids or [], list):
        raise ValueError("evidence_ids 必须是列表")
    clean_evidence_ids = list(dict.fromkeys(
        str(value).strip()[:100] for value in (evidence_ids or []) if str(value).strip()))[:100]
    now = _now()
    clean_cutoff = str(data_cutoff or "").strip()[:100]
    if clean_cutoff:
        try:
            parsed_cutoff = datetime.fromisoformat(clean_cutoff.replace('Z', '+00:00'))
            if parsed_cutoff.tzinfo is None:
                parsed_cutoff = parsed_cutoff.replace(tzinfo=timezone.utc)
            if parsed_cutoff > datetime.now(timezone.utc):
                raise ValueError("研判资料截止时间不能晚于当前时间")
        except (TypeError, ValueError) as exc:
            raise ValueError("研判资料截止时间须是有效且不晚于当前时间的 ISO 日期") from exc
    with _conn() as con:
        if generation_key:
            existing = con.execute("SELECT * FROM market_research_judgements WHERE tenant_id=? AND generation_key=?", (tenant_id, generation_key)).fetchone()
            if existing:
                return {"report": _judgement_dict(dict(existing))}
        if not clean_category_id:
            child_reports = con.execute(
                "SELECT COUNT(DISTINCT category_id) FROM market_research_judgements "
                "WHERE tenant_id=? AND topic_id=? AND category_id<>''",
                (tenant_id, topic_id),
            ).fetchone()[0]
            if not child_reports:
                raise ValueError("至少形成一个细分领域研判后，才能生成主题综合研判")
        scope_where = (
            "tenant_id=? AND topic_id=? AND employee_id=? AND deleted_at IS NULL")
        scope_params: list = [tenant_id, topic_id, "market-intel"]
        if clean_category_id:
            scope_where += " AND category_id=?"
            scope_params.append(clean_category_id)
        if clean_evidence_ids:
            placeholders = ",".join("?" for _ in clean_evidence_ids)
            valid_ids = {row["id"] for row in con.execute(
                "SELECT id FROM market_research_observations WHERE " + scope_where
                + f" AND id IN ({placeholders})",
                [*scope_params, *clean_evidence_ids],
            ).fetchall()}
            if set(clean_evidence_ids) - valid_ids:
                raise ValueError("研判引用包含不属于当前范围或已删除的观察")
        if clean_category_id and not clean_evidence_ids:
            raise ValueError("细分领域研判必须关联至少一条已入库的研究观察")
        if not clean_cutoff:
            latest_row = con.execute(
                "SELECT MAX(captured_at) AS latest FROM market_research_observations WHERE "
                + scope_where,
                scope_params,
            ).fetchone()
            clean_cutoff = latest_row["latest"] or now
        version = int(con.execute(
            "SELECT COALESCE(MAX(version),0)+1 FROM market_research_judgements "
            "WHERE tenant_id=? AND topic_id=? AND category_id=?",
            (tenant_id, topic_id, clean_category_id),
        ).fetchone()[0])
        item = {
            "id": "mrj_" + uuid.uuid4().hex,
            "tenant_id": tenant_id,
            "topic_id": topic_id,
            "category_id": clean_category_id,
            "version": version,
            "title": clean_title,
            "conclusion": clean_conclusion,
            "content_markdown": clean_content,
            "confidence": confidence,
            "report_status": "draft",
            "generation_key": generation_key,
            "data_cutoff": clean_cutoff,
            "evidence_ids_json": json.dumps(clean_evidence_ids, ensure_ascii=False),
            "sources_json": json.dumps(clean_sources, ensure_ascii=False),
            "created_at": now,
            "created_by": str(created_by or "")[:200],
            "created_by_name": str(created_by_name or "")[:200],
        }
        con.execute(
            "INSERT INTO market_research_judgements "
            "(id,tenant_id,topic_id,category_id,version,title,conclusion,content_markdown,"
            "confidence,report_status,data_cutoff,evidence_ids_json,sources_json,created_at,"
            "created_by,created_by_name,generation_key) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            tuple(item[key] for key in (
                "id", "tenant_id", "topic_id", "category_id", "version", "title",
                "conclusion", "content_markdown", "confidence", "report_status",
                "data_cutoff", "evidence_ids_json", "sources_json", "created_at",
                "created_by", "created_by_name", "generation_key")),
        )
    return get_judgement(
        tenant_id=tenant_id, topic_id=topic_id, category_id=clean_category_id)


def list_workbench(*, tenant_id: str, topic_id: str | None = None,
                   category_id: str | None = None,
                   limit: int = 30, offset: int = 0, include_deleted: bool = False,
                   deleted_owner: str | None = None) -> dict:
    limit = min(100, max(1, int(limit)))
    offset = max(0, int(offset))
    if topic_id and topic_id not in TOPIC_BY_ID:
        raise ValueError("不支持的研究主题")
    if category_id is not None:
        if topic_id:
            _validate_category(topic_id, category_id)
        elif category_id and not any(
                category_id == category["id"]
                for topic in TOPICS for category in topic["categories"]):
            raise ValueError("不支持的细分领域")
    with _conn() as con:
        counts = con.execute(
            "SELECT topic_id,COUNT(*) AS observation_count,MAX(captured_at) AS latest_at "
            "FROM market_research_observations WHERE tenant_id=? AND deleted_at IS NULL GROUP BY topic_id",
            (tenant_id,),
        ).fetchall()
        summary = {row["topic_id"]: dict(row) for row in counts}
        category_rows = con.execute(
            "SELECT topic_id,category_id,COUNT(*) AS observation_count, "
            "MAX(captured_at) AS latest_at FROM market_research_observations "
            "WHERE tenant_id=? AND deleted_at IS NULL "
            "GROUP BY topic_id,category_id",
            (tenant_id,),
        ).fetchall()
        category_summary = {
            (row["topic_id"], row["category_id"]): dict(row)
            for row in category_rows
        }
        params: list = [tenant_id]
        where = "tenant_id=? AND deleted_at IS " + ("NOT " if include_deleted else "") + "NULL"
        if include_deleted and deleted_owner:
            where += " AND created_by=?"
            params.append(deleted_owner)
        if topic_id:
            where += " AND topic_id=?"
            params.append(topic_id)
        if category_id is not None:
            where += " AND category_id=?"
            params.append(category_id)
        rows = con.execute(
            "SELECT * FROM market_research_observations WHERE " + where +
            " ORDER BY captured_at DESC,id DESC LIMIT ? OFFSET ?", [*params, limit, offset],
        ).fetchall()
        deleted_sql = ("SELECT COUNT(*) FROM market_research_observations "
                       "WHERE tenant_id=? AND deleted_at IS NOT NULL")
        deleted_params: list = [tenant_id]
        if deleted_owner:
            deleted_sql += " AND created_by=?"
            deleted_params.append(deleted_owner)
        deleted_count = con.execute(deleted_sql, deleted_params).fetchone()[0]
    topics = []
    for topic in TOPICS:
        metrics = summary.get(topic["id"], {})
        categories = []
        for category in topic["categories"]:
            category_metrics = category_summary.get((topic["id"], category["id"]), {})
            categories.append({
                **category,
                "observation_count": category_metrics.get("observation_count", 0),
                "latest_at": category_metrics.get("latest_at"),
            })
        unclassified = category_summary.get((topic["id"], ""), {})
        topics.append({**topic,
                       "categories": categories,
                       "observation_count": metrics.get("observation_count", 0),
                       "latest_at": metrics.get("latest_at"),
                       "unclassified_count": unclassified.get("observation_count", 0)})
    from app import automations
    tasks = []
    for auto in automations.list_all(tenant_id):
        if auto.get("employee_id") != "market-intel":
            continue
        tasks.append({key: auto.get(key) for key in (
            "id", "name", "trigger_type", "cron_expr", "enabled",
            "last_status", "last_run_at", "next_fire_at")})
    return {"topics": topics, "items": [_deserialize(dict(row)) for row in rows],
            "tasks": tasks, "deleted_count": deleted_count}


def save_from_agent(*, topic_id: str, title: str, summary: str,
                    category_id: str = "",
                    content_markdown: str, sources_json: str = "[]",
                    source_name: str = "", published_at: str = "") -> str:
    """从 market-intel agent 的工具调用上下文写入租户级研究观察。"""
    try:
        from langgraph.config import get_config
        cfg = get_config() or {}
        configurable = cfg.get("configurable") or {}
        auth_context = configurable.get("auth_context") or {}
        if configurable.get("employee_id") != "market-intel":
            raise RuntimeError("仅小察可以写入行业研究观察")
        user_id = configurable.get("user_id") or auth_context.get("user_id")
        tenant_id = auth_context.get("tenant_id")
        if not user_id or not tenant_id:
            raise RuntimeError("运行上下文缺少用户或租户信息，未保存观察记录")
    except RuntimeError:
        raise
    except Exception as exc:
        raise RuntimeError("无法读取运行上下文，未保存观察记录") from exc
    try:
        sources = json.loads(sources_json or "[]")
    except json.JSONDecodeError as exc:
        raise ValueError("sources_json 必须是 JSON 列表") from exc
    if not isinstance(sources, list):
        raise ValueError("sources_json 必须是 JSON 列表")
    user = None
    try:
        from app.catalog import get_user
        user = get_user(user_id)
    except Exception:
        pass
    result = save_source_observation(
        tenant_id=tenant_id, topic_id=topic_id, category_id=category_id,
        title=title, summary=summary,
        content_markdown=content_markdown, sources=sources,
        conv_id=configurable.get("thread_id", ""), ingest_method="agent",
        source_name=source_name, published_at=published_at, created_by=user_id,
        created_by_name=(user or {}).get("display_name") or (user or {}).get("username") or "",
    )
    return f"研究观察已保存（或复用已有记录），observation_id={result['item']['id']}。请确认引用来源与日期准确，再用于后续趋势判断。"
