"""小察信源配置、试抓与逐源采集 API。"""
from __future__ import annotations

import asyncio

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from app import auth, market_sources
from .market_research import _ensure_market_intel_access

router = APIRouter(prefix="/api/market-research", tags=["market-sources"])


class SourceWrite(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    kind: str = "rss"
    config: dict = Field(default_factory=dict)
    candidate_topic_ids: list[str] = Field(min_length=1, max_length=5)
    tags: list[str] = Field(default_factory=list, max_length=30)
    tier: str = "T3"
    first_party: bool = False
    participation_mode: str = "editorial"
    desired_enabled: bool = False
    interval_minutes: int = Field(default=1440, ge=5, le=10080)


class SourceUpdate(SourceWrite):
    config_version: int = Field(ge=1)


class EnabledUpdate(BaseModel):
    enabled: bool
    config_version: int | None = Field(default=None, ge=1)


class ImportRequest(BaseModel):
    manifest_hash: str = Field(min_length=64, max_length=64)


class CollectRequest(BaseModel):
    topic_id: str = ""


class CollectionBatchCreate(BaseModel):
    request_id: str = Field(min_length=1, max_length=100)
    topic_id: str = ""
    source_ids: list[str] = Field(default_factory=list, max_length=100)
    mode: str = "incremental"
    max_items: int = Field(default=500, ge=1, le=2000)


def _admin(context) -> None:
    if not context.allows("*"):
        raise HTTPException(403, "需要管理员权限")


def _validation_error(exc: ValueError) -> HTTPException:
    return HTTPException(422, str(exc))


@router.get("/sources")
async def get_sources(topic_id: str = "", kind: str = "", health: str = "",
                      enabled: bool | None = None,
                      context=Depends(auth.get_auth_context)):
    _ensure_market_intel_access(context)
    _admin(context)
    return {"items": market_sources.list_sources(context.tenant_id, topic_id=topic_id,
            kind=kind, health=health, enabled=enabled), "summary": market_sources.source_summary(context.tenant_id)}


@router.get("/sources/summary")
async def get_sources_summary(context=Depends(auth.get_auth_context)):
    _ensure_market_intel_access(context)
    return market_sources.source_summary(context.tenant_id)


@router.get("/sources/runs")
async def get_recent_source_runs(limit: int = Query(default=100, ge=1, le=500),
                                 context=Depends(auth.get_auth_context)):
    _ensure_market_intel_access(context)
    return {"items": market_sources.list_recent_runs(context.tenant_id, limit)}


@router.get("/source-documents")
async def get_source_documents(status: str = Query(default="unverified", max_length=32),
                               source_id: str = Query(default="", max_length=200),
                               topic_id: str = Query(default="", max_length=100),
                               q: str = Query(default="", max_length=100),
                               limit: int = Query(default=50, ge=1, le=100),
                               offset: int = Query(default=0, ge=0),
                               context=Depends(auth.get_auth_context)):
    _ensure_market_intel_access(context)
    _admin(context)
    try:
        return market_sources.list_source_documents(context.tenant_id, status=status,
            source_id=source_id, topic_id=topic_id, query=q, limit=limit, offset=offset)
    except ValueError as exc:
        raise _validation_error(exc) from exc


@router.get("/source-documents/summary")
async def get_source_document_summary(context=Depends(auth.get_auth_context)):
    _ensure_market_intel_access(context)
    _admin(context)
    return market_sources.source_document_summary(context.tenant_id)


@router.post("/source-documents/local-triage")
async def locally_triage_source_documents(context=Depends(auth.get_auth_context)):
    """Classify pending material scope locally; this endpoint does not call the employee LLM."""
    _ensure_market_intel_access(context); _admin(context)
    return market_sources.triage_unverified_documents_locally(context.tenant_id)


@router.post("/collection-batches", status_code=202)
async def create_collection_batch(body: CollectionBatchCreate,
                                  context=Depends(auth.get_auth_context)):
    _ensure_market_intel_access(context); _admin(context)
    try:
        batch = market_sources.create_batch(context.tenant_id, context.user_id,
            request_id=body.request_id, topic_id=body.topic_id,
            source_ids=body.source_ids, mode=body.mode, max_items=body.max_items)
    except RuntimeError as exc:
        raise HTTPException(409, str(exc)) from exc
    except ValueError as exc:
        raise _validation_error(exc) from exc
    market_sources.start()
    return batch


@router.get("/collection-batches")
async def get_collection_batches(limit: int = Query(default=30, ge=1, le=100),
                                 offset: int = Query(default=0, ge=0),
                                 context=Depends(auth.get_auth_context)):
    _ensure_market_intel_access(context)
    return {"items": market_sources.list_batches(context.tenant_id, limit, offset)}


@router.get("/collection-batches/{batch_id}")
async def get_collection_batch(batch_id: str, context=Depends(auth.get_auth_context)):
    _ensure_market_intel_access(context)
    batch = market_sources.get_batch(context.tenant_id, batch_id)
    if not batch: raise HTTPException(404, "没有找到该采集批次")
    return batch


@router.get("/collection-batches/{batch_id}/tasks")
async def get_collection_batch_tasks(batch_id: str, context=Depends(auth.get_auth_context)):
    _ensure_market_intel_access(context)
    tasks = market_sources.batch_tasks(context.tenant_id, batch_id)
    if tasks is None: raise HTTPException(404, "没有找到该采集批次")
    return {"items": tasks}


@router.get("/collection-batches/{batch_id}/events")
async def get_collection_batch_events(batch_id: str, after_sequence: int = Query(default=0, ge=0),
                                      limit: int = Query(default=100, ge=1, le=500),
                                      context=Depends(auth.get_auth_context)):
    _ensure_market_intel_access(context)
    events = market_sources.batch_events(context.tenant_id, batch_id, after_sequence, limit)
    if events is None: raise HTTPException(404, "没有找到该采集批次")
    return {"items": events}


async def _batch_action(batch_id: str, action: str, context):
    _ensure_market_intel_access(context); _admin(context)
    try:
        batch = market_sources.batch_action(context.tenant_id, context.user_id, batch_id, action)
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc
    if not batch: raise HTTPException(404, "没有找到该采集批次")
    market_sources.start()
    return batch


@router.post("/collection-batches/{batch_id}/pause")
async def pause_collection_batch(batch_id: str, context=Depends(auth.get_auth_context)):
    return await _batch_action(batch_id, "pause", context)


@router.post("/collection-batches/{batch_id}/resume")
async def resume_collection_batch(batch_id: str, context=Depends(auth.get_auth_context)):
    return await _batch_action(batch_id, "resume", context)


@router.post("/collection-batches/{batch_id}/stop")
async def stop_collection_batch(batch_id: str, context=Depends(auth.get_auth_context)):
    return await _batch_action(batch_id, "stop", context)


@router.post("/collection-batches/{batch_id}/retry-failed")
async def retry_failed_collection_batch(batch_id: str, context=Depends(auth.get_auth_context)):
    return await _batch_action(batch_id, "retry_failed", context)


@router.post("/sources/import/preview")
async def preview_source_import(context=Depends(auth.get_auth_context)):
    _ensure_market_intel_access(context); _admin(context)
    try:
        return market_sources.preview_import(context.tenant_id)
    except ValueError as exc:
        raise _validation_error(exc) from exc


@router.post("/sources/import")
async def import_sources(body: ImportRequest, context=Depends(auth.get_auth_context)):
    _ensure_market_intel_access(context); _admin(context)
    try:
        return market_sources.import_sources(context.tenant_id, context.user_id, body.manifest_hash)
    except ValueError as exc:
        raise _validation_error(exc) from exc


@router.post("/sources")
async def create_source(body: SourceWrite, context=Depends(auth.get_auth_context)):
    _ensure_market_intel_access(context); _admin(context)
    try:
        return market_sources.create_source(context.tenant_id, context.user_id, body.model_dump())
    except ValueError as exc:
        raise _validation_error(exc) from exc


@router.get("/sources/{source_id}")
async def get_source(source_id: str, context=Depends(auth.get_auth_context)):
    _ensure_market_intel_access(context)
    _admin(context)
    source = market_sources.get_source(context.tenant_id, source_id)
    if not source: raise HTTPException(404, "没有找到该信源")
    return source


@router.patch("/sources/{source_id}")
async def update_source(source_id: str, body: SourceUpdate, context=Depends(auth.get_auth_context)):
    _ensure_market_intel_access(context); _admin(context)
    data = body.model_dump()
    expected = data.pop("config_version")
    try:
        result = market_sources.update_source(context.tenant_id, context.user_id, source_id, data, expected)
    except RuntimeError as exc:
        raise HTTPException(409, str(exc)) from exc
    except ValueError as exc:
        raise _validation_error(exc) from exc
    if not result: raise HTTPException(404, "没有找到该信源")
    return result


@router.patch("/sources/{source_id}/enabled")
async def update_source_enabled(source_id: str, body: EnabledUpdate, context=Depends(auth.get_auth_context)):
    _ensure_market_intel_access(context); _admin(context)
    try:
        result = market_sources.set_enabled(context.tenant_id, context.user_id, source_id,
                                            body.enabled, body.config_version)
    except RuntimeError as exc:
        raise HTTPException(409, str(exc)) from exc
    except ValueError as exc:
        raise _validation_error(exc) from exc
    if not result: raise HTTPException(404, "没有找到该信源")
    return result


@router.post("/sources/{source_id}/preview")
async def preview_source(source_id: str, limit: int = Query(default=5, ge=1, le=20),
                         context=Depends(auth.get_auth_context)):
    _ensure_market_intel_access(context); _admin(context)
    try:
        result = await asyncio.to_thread(market_sources.preview_source, context.tenant_id, source_id, limit=limit)
    except ValueError as exc:
        raise _validation_error(exc) from exc
    if not result: raise HTTPException(404, "没有找到该信源")
    return result


@router.post("/sources/{source_id}/collect", status_code=202)
async def collect_source(source_id: str, body: CollectRequest,
                         context=Depends(auth.get_auth_context)):
    _ensure_market_intel_access(context); _admin(context)
    try:
        run = market_sources.queue_collect(context.tenant_id, context.user_id, source_id, body.topic_id)
    except ValueError as exc:
        raise _validation_error(exc) from exc
    if not run: raise HTTPException(404, "没有找到该信源")
    market_sources.start()
    return market_sources.get_run(context.tenant_id, run["id"])


@router.get("/sources/{source_id}/runs")
async def get_source_runs(source_id: str, limit: int = Query(default=30, ge=1, le=100),
                          context=Depends(auth.get_auth_context)):
    _ensure_market_intel_access(context)
    if not market_sources.get_source(context.tenant_id, source_id):
        raise HTTPException(404, "没有找到该信源")
    return {"items": market_sources.list_runs(context.tenant_id, source_id, limit)}


@router.get("/source-runs/{run_id}")
async def get_source_run(run_id: str, context=Depends(auth.get_auth_context)):
    _ensure_market_intel_access(context)
    run = market_sources.get_run(context.tenant_id, run_id)
    if not run: raise HTTPException(404, "没有找到该采集运行")
    return run


@router.post("/source-runs/{run_id}/retry", status_code=202)
async def retry_source_run(run_id: str, context=Depends(auth.get_auth_context)):
    _ensure_market_intel_access(context); _admin(context)
    run = market_sources.get_run(context.tenant_id, run_id)
    if not run: raise HTTPException(404, "没有找到该采集运行")
    if run["status"] not in {"failed", "completed_with_issues"}:
        raise HTTPException(409, "只有失败或部分失败的运行可以重试")
    source = market_sources.get_source(context.tenant_id, run["source_id"])
    if not source: raise HTTPException(404, "没有找到该信源")
    try:
        queued = market_sources.queue_collect(context.tenant_id, context.user_id, source["id"], run["topic_id"], force_refresh=True)
    except ValueError as exc:
        raise _validation_error(exc) from exc
    market_sources.start()
    return market_sources.get_run(context.tenant_id, queued["id"])
