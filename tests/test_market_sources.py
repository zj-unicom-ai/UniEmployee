import json
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app import auth, market_intake, market_research, market_sources
from app.routes.market_sources import router


@pytest.fixture(autouse=True)
def source_tables():
    market_intake.init_tables()
    market_sources.init_tables()


def test_manifest_dry_run_is_44_sources_and_import_is_idempotent():
    preview = market_sources.preview_import("tenant-a")
    assert preview["summary"] == {
        "new": 44, "reused": 0, "conflict": 0, "unsupported": 0,
        "desired_enabled": 37, "desired_disabled": 7,
    }
    assert preview["dry_run"] is True
    assert preview["activate_on_import"] is False

    imported = market_sources.import_sources("tenant-a", "admin-a", preview["manifest_hash"])
    assert imported["created"] == 44
    assert market_sources.source_summary("tenant-a")["enabled_source_count"] == 0

    first = market_sources.list_sources("tenant-a")[0]
    with market_sources._conn() as con:
        con.execute("UPDATE market_sources SET name='管理员自定义名' WHERE tenant_id=? AND id=?", ("tenant-a", first["id"]))
    repeated_preview = market_sources.preview_import("tenant-a")
    assert repeated_preview["summary"]["reused"] == 44
    repeated = market_sources.import_sources("tenant-a", "admin-a", repeated_preview["manifest_hash"])
    assert repeated["created"] == 0
    assert repeated["reused"] == 44
    assert market_sources.get_source("tenant-a", first["id"])["name"] == "管理员自定义名"


def test_feed_parser_supports_rss_atom_and_marks_excerpt_as_unverified():
    rss = b'''<rss version="2.0"><channel><item><title>First release</title>
      <link>https://publisher.example/story?id=2</link><guid>story-2</guid>
      <pubDate>Tue, 28 Oct 2026 10:00:00 GMT</pubDate><description>&lt;p&gt;Short summary&lt;/p&gt;</description>
    </item></channel></rss>'''
    parsed = market_sources.parse_feed(rss, "https://publisher.example/feed.xml")
    assert parsed[0]["title"] == "First release"
    assert parsed[0]["url"] == "https://publisher.example/story?id=2"
    assert parsed[0]["published_at"].startswith("2026-10-28T10:00:00")
    assert parsed[0]["has_fulltext"] is False

    atom = b'''<feed xmlns="http://www.w3.org/2005/Atom"><entry><title>Atom story</title>
      <id>tag:publisher.example,2026:7</id><link rel="alternate" href="/story/7"/>
      <updated>2026-10-28T10:00:00Z</updated><content type="html">''' + (b"body text " * 30) + b'''</content></entry></feed>'''
    parsed_atom = market_sources.parse_feed(atom, "https://publisher.example/feed.xml")
    assert parsed_atom[0]["url"] == "https://publisher.example/story/7"
    assert parsed_atom[0]["has_fulltext"] is True

    arxiv = b'''<feed xmlns="http://www.w3.org/2005/Atom"><entry><title>Arxiv paper</title>
      <id>https://arxiv.org/abs/2610.12345</id><link rel="alternate" href="https://arxiv.org/abs/2610.12345"/>
      <updated>2026-10-28T04:00:00Z</updated><summary>Paper abstract text.</summary></entry></feed>'''
    parsed_arxiv = market_sources.parse_feed(arxiv, "https://rss.arxiv.org/rss/cs.AI")
    assert parsed_arxiv[0]["published_at"] == ""
    assert parsed_arxiv[0]["publication_month"] == "2026-10"


def test_feed_connection_retries_only_public_cdn_addresses(monkeypatch):
    attempts = []

    class FakeSocket:
        timeout = None
        def settimeout(self, value):
            self.timeout = value

    def connect(address, timeout, source_address):
        attempts.append((address[0], timeout))
        if address[0] == "151.101.67.42":
            raise TimeoutError("unreachable CDN edge")
        return FakeSocket()

    monkeypatch.setattr(market_sources.socket, "create_connection", connect)
    monkeypatch.setattr(market_sources.socket, "getaddrinfo", lambda *args, **kwargs: [
        (market_sources.socket.AF_INET, market_sources.socket.SOCK_STREAM,
         market_sources.socket.IPPROTO_TCP, "", ("151.101.91.42", 443)),
    ])
    connected = market_intake._connect_public_ips(
        "rss.arxiv.org", 443, ["151.101.67.42"], timeout=20)
    assert attempts == [("151.101.67.42", 5.0), ("151.101.91.42", 5.0)]
    assert connected.timeout == 20


def test_feed_connection_rejects_private_refreshed_dns(monkeypatch):
    monkeypatch.setattr(market_sources.socket, "create_connection", lambda *args, **kwargs: (_ for _ in ()).throw(
        TimeoutError("unreachable CDN edge")))
    monkeypatch.setattr(market_sources.socket, "getaddrinfo", lambda *args, **kwargs: [
        (market_sources.socket.AF_INET, market_sources.socket.SOCK_STREAM,
         market_sources.socket.IPPROTO_TCP, "", ("127.0.0.1", 443)),
    ])
    with pytest.raises(ValueError, match="本机或内网地址"):
        market_intake._connect_public_ips("rss.arxiv.org", 443, ["151.101.67.42"], timeout=20)


def test_feed_rerediscovery_keeps_existing_article_version_current():
    market_research.init_tables()
    candidate = {
        "external_id": "paper-2610.12345", "title": "Research paper",
        "url": "https://arxiv.org/abs/2610.12345", "published_at": "",
        "publication_month": "2026-10", "summary": "RSS abstract excerpt",
        "body_text": "", "content_source": "summary", "has_fulltext": False,
    }
    with market_sources._conn() as con:
        document_id, created, is_new = market_sources._record_version(con, "tenant-a", "source-a", candidate)
        assert created and is_new
        market_sources._record_article_version(con, "tenant-a", document_id, candidate, {
            "text": "Full publisher article body. " * 30,
            "title": "Research paper", "fetched_at": "2026-10-28T10:00:00+00:00",
        })
        article_version = con.execute("SELECT current_version_id FROM market_documents WHERE tenant_id=? AND id=?",
                                      ("tenant-a", document_id)).fetchone()["current_version_id"]
        rediscovered_id, created_again, new_version_again = market_sources._record_version(
            con, "tenant-a", "source-a", {**candidate, "summary": "A revised RSS excerpt"})
        current = con.execute("""SELECT v.id,v.content_source,v.body_text FROM market_documents d
            JOIN market_document_versions v ON v.tenant_id=d.tenant_id AND v.id=d.current_version_id
            WHERE d.tenant_id=? AND d.id=?""", ("tenant-a", document_id)).fetchone()
    assert rediscovered_id == document_id
    assert not created_again and not new_version_again
    assert current["id"] == article_version
    assert current["content_source"] == "article_fetch"
    assert current["body_text"].startswith("Full publisher article body.")


def test_source_config_rejects_secret_queries_and_unimplemented_kinds():
    payload = {"name": "Private", "kind": "rss", "config": {"feed_url": "https://feed.example/rss?token=secret"},
               "candidate_topic_ids": ["ai-frontier"]}
    with pytest.raises(ValueError, match="不能包含 token"):
        market_sources.create_source("tenant-a", "admin-a", payload)
    payload["kind"] = "web"
    payload["config"] = {"feed_url": "https://feed.example/rss"}
    with pytest.raises(ValueError, match="当前仅支持 RSS/Atom"):
        market_sources.create_source("tenant-a", "admin-a", payload)


def test_source_config_supports_bounded_500_item_three_month_backfill():
    source = market_sources.create_source("tenant-a", "admin-a", {
        "name": "Quarterly feed", "kind": "rss",
        "config": {"feed_url": "https://quarterly.example/rss", "initial_backfill_limit": 500,
                   "initial_backfill_months": 3},
        "candidate_topic_ids": ["ai-frontier"],
    })
    assert source["config"]["initial_backfill_limit"] == 500
    assert source["config"]["initial_backfill_months"] == 3
    with pytest.raises(ValueError, match="1–500 条"):
        market_sources.create_source("tenant-a", "admin-a", {
            "name": "Oversized", "kind": "rss",
            "config": {"feed_url": "https://oversized.example/rss", "initial_backfill_limit": 501},
            "candidate_topic_ids": ["ai-frontier"],
        })


def test_config_change_requires_retrial_and_uses_version_compare():
    source = _enabled_source("Versioned")
    changed = market_sources.update_source("tenant-a", "admin-a", source["id"], {
        "name": source["name"], "kind": source["kind"],
        "config": {**source["config"], "feed_url": "https://changed.example/rss"},
        "candidate_topic_ids": source["candidate_topic_ids"], "tags": source["tags"],
        "tier": source["tier"], "first_party": source["first_party"],
        "participation_mode": source["participation_mode"], "desired_enabled": source["desired_enabled"],
        "interval_minutes": source["interval_minutes"],
    }, source["config_version"])
    assert changed["enabled"] is False
    assert changed["health"] == "unknown"
    with pytest.raises(RuntimeError, match="已被其他管理员修改"):
        market_sources.update_source("tenant-a", "admin-a", source["id"], {
            "name": changed["name"], "kind": changed["kind"], "config": changed["config"],
            "candidate_topic_ids": changed["candidate_topic_ids"], "tags": changed["tags"],
            "tier": changed["tier"], "first_party": changed["first_party"],
            "participation_mode": changed["participation_mode"], "desired_enabled": changed["desired_enabled"],
            "interval_minutes": changed["interval_minutes"],
        }, source["config_version"])


@pytest.fixture
def api_client(monkeypatch):
    app = FastAPI()
    app.include_router(router)
    context = SimpleNamespace(tenant_id="tenant-a", user_id="admin-a", allows=lambda _: True)
    app.dependency_overrides[auth.get_auth_context] = lambda: context
    with TestClient(app) as client:
        yield client, context


def test_source_admin_controls_and_tenant_scoping(api_client, monkeypatch):
    client, context = api_client
    response = client.post("/api/market-research/sources", json={
        "name": "OpenAI News", "kind": "rss", "config": {"feed_url": "https://openai.example/rss.xml"},
        "candidate_topic_ids": ["ai-frontier"], "interval_minutes": 120,
    })
    assert response.status_code == 200
    source_id = response.json()["id"]
    assert response.json()["enabled"] is False
    context.allows = lambda _: False
    from app import catalog
    monkeypatch.setattr(catalog, "assigned_employee_ids", lambda _: ["market-intel"])
    assert client.get("/api/market-research/sources").status_code == 403
    summary = client.get("/api/market-research/sources/summary")
    assert summary.status_code == 200
    assert "source_count" in summary.json()
    assert client.post("/api/market-research/sources/import/preview").status_code == 403
    context.tenant_id = "tenant-b"
    context.allows = lambda _: True
    assert client.get(f"/api/market-research/sources/{source_id}").status_code == 404


def test_source_documents_endpoint_is_admin_only(api_client, monkeypatch):
    client, context = api_client
    response = client.get("/api/market-research/source-documents")
    assert response.status_code == 200
    assert response.json()["summary"]["raw_documents"] == 0
    assert client.get("/api/market-research/source-documents?status=invalid").status_code == 422

    context.allows = lambda _: False
    from app import catalog
    monkeypatch.setattr(catalog, "assigned_employee_ids", lambda _: ["market-intel"])
    assert client.get("/api/market-research/source-documents").status_code == 403


def test_source_enabling_requires_successful_preview():
    source = market_sources.create_source("tenant-a", "admin-a", {
        "name": "Feed", "kind": "rss", "config": {"feed_url": "https://feed.example/rss"},
        "candidate_topic_ids": ["ai-frontier"],
    })
    with pytest.raises(ValueError, match="请先试抓"):
        market_sources.set_enabled("tenant-a", "admin-a", source["id"], True, source["config_version"])

    with market_sources._conn() as con:
        con.execute("UPDATE market_sources SET health='healthy' WHERE tenant_id=? AND id=?", ("tenant-a", source["id"]))
    enabled = market_sources.set_enabled("tenant-a", "admin-a", source["id"], True, source["config_version"])
    assert enabled["enabled"] is True


def test_rss_collection_persists_document_version_discovery_and_intake(monkeypatch):
    source = market_sources.create_source("tenant-a", "admin-a", {
        "name": "Feed", "kind": "rss", "config": {"feed_url": "https://feed.example/rss"},
        "candidate_topic_ids": ["ai-frontier"],
    })
    with market_sources._conn() as con:
        con.execute("UPDATE market_sources SET health='healthy' WHERE tenant_id=? AND id=?", ("tenant-a", source["id"]))
    source = market_sources.set_enabled("tenant-a", "admin-a", source["id"], True, source["config_version"])
    run = market_sources.queue_collect("tenant-a", "admin-a", source["id"])
    candidate = {"external_id": "feed-entry-1", "title": "Model release", "url": "https://publisher.example/news/1",
                 "published_at": "2026-10-28T10:00:00+00:00", "summary": "short release summary",
                 "body_text": "Long RSS excerpt that must not stand in for a fetched article page.",
                 "content_source": "content:encoded", "has_fulltext": True}
    monkeypatch.setattr(market_sources, "fetch_feed", lambda *args, **kwargs: {
        "status": 200, "url": "https://feed.example/rss", "body": b"<rss/>", "etag": "v1", "last_modified": ""})
    monkeypatch.setattr(market_sources, "parse_feed", lambda *args, **kwargs: [candidate])
    launched = []
    monkeypatch.setattr(market_intake, "launch", lambda job: launched.append(job["id"]))

    import asyncio
    asyncio.run(market_sources._process_run("tenant-a", run["id"]))
    saved_run = market_sources.get_run("tenant-a", run["id"])
    assert saved_run["status"] == "succeeded"
    assert saved_run["counts"]["found"] == 1
    assert saved_run["counts"]["new"] == 1
    assert saved_run["counts"]["intake_queued"] == 1
    assert len(launched) == 1
    assert market_intake.get_job("tenant-a", launched[0])["document_json"] == "{}"
    with market_sources._conn() as con:
        assert con.execute("SELECT COUNT(*) FROM market_documents WHERE tenant_id=?", ("tenant-a",)).fetchone()[0] == 1
        assert con.execute("SELECT COUNT(*) FROM market_document_versions WHERE tenant_id=?", ("tenant-a",)).fetchone()[0] == 1
        assert con.execute("SELECT COUNT(*) FROM market_source_discoveries WHERE tenant_id=?", ("tenant-a",)).fetchone()[0] == 1
        quality = con.execute("SELECT status FROM market_quality_reviews WHERE tenant_id=?", ("tenant-a",)).fetchone()
        assert quality["status"] == "unverified"
    with market_sources._conn() as con:
        document_id = con.execute("SELECT document_id FROM market_source_discoveries WHERE tenant_id=?", ("tenant-a",)).fetchone()["document_id"]
        con.execute("""INSERT INTO market_quality_reviews
            (id,tenant_id,source_id,document_id,observation_id,status,reason,evidence_json,created_at)
            VALUES(?,?,?,?,?,?,?,?,?)""",
            ("triaged-review-1", "tenant-a", source["id"], document_id,
             "", "triaged", "本地关键词初筛", "{}", market_research._now()))
    market_sources.mark_observation_attributed("tenant-a", candidate["url"], "obs-1")
    with market_sources._conn() as con:
        quality = con.execute("SELECT status,observation_id FROM market_quality_reviews WHERE tenant_id=? ORDER BY created_at DESC,id DESC LIMIT 1", ("tenant-a",)).fetchone()
        attributed_reviews = con.execute("SELECT COUNT(*) FROM market_quality_reviews WHERE tenant_id=? AND status='source_attributed'", ("tenant-a",)).fetchone()[0]
        discovery = con.execute("SELECT status FROM market_source_discoveries WHERE tenant_id=?", ("tenant-a",)).fetchone()
    assert quality["status"] == "source_attributed"
    assert quality["observation_id"] == "obs-1"
    assert attributed_reviews == 2
    assert discovery["status"] == "observation_saved"


def test_fetch_only_batch_persists_article_version_without_model_intake(monkeypatch):
    source = _enabled_source("Fetch only")
    batch = market_sources.create_batch("tenant-a", "admin-a", request_id="fetch-only-1",
        topic_id="ai-frontier", source_ids=[source["id"]], mode="fetch_only", max_items=10)
    run_id = market_sources.batch_tasks("tenant-a", batch["id"])[0]["run_id"]
    candidate = {"external_id": "feed-entry-fetch-only", "title": "Article from Feed", "url": "https://publisher.example/article/1",
                 "published_at": "2026-10-28T10:00:00+00:00", "summary": "short summary",
                 "body_text": "feed content", "content_source": "content:encoded", "has_fulltext": True}
    monkeypatch.setattr(market_sources, "fetch_feed", lambda *args, **kwargs: {
        "status": 200, "url": "https://feed-only.example/rss", "body": b"<rss/>", "etag": "v1", "last_modified": ""})
    monkeypatch.setattr(market_sources, "parse_feed", lambda *args, **kwargs: [candidate])
    monkeypatch.setattr(market_intake, "fetch_document", lambda url: {
        "url": url, "title": "Verified article page", "text": "Article body from the public page." * 20,
        "truncated": False, "fetched_at": "2026-10-28T10:00:00+00:00"})
    launched = []
    monkeypatch.setattr(market_intake, "launch", lambda job: launched.append(job["id"]))

    import asyncio
    asyncio.run(market_sources._process_run("tenant-a", run_id))
    completed = market_sources.get_batch("tenant-a", batch["id"])
    assert completed["status"] == "completed"
    assert completed["mode"] == "fetch_only"
    assert completed["counts"]["analysis_requested"] is False
    assert completed["counts"]["pipeline"]["not_requested"] == 1
    assert not launched
    with market_sources._conn() as con:
        discovery = con.execute("SELECT status,intake_job_id,document_id FROM market_source_discoveries WHERE tenant_id=? AND run_id=?",
                                ("tenant-a", run_id)).fetchone()
        version = con.execute("SELECT content_source,title,body_text,publication_month FROM market_document_versions WHERE tenant_id=? AND document_id=? ORDER BY created_at DESC LIMIT 1",
                              ("tenant-a", discovery["document_id"])).fetchone()
        review = con.execute("SELECT status,reason FROM market_quality_reviews WHERE tenant_id=? AND document_id=? ORDER BY created_at DESC LIMIT 1",
                             ("tenant-a", discovery["document_id"])).fetchone()
    assert discovery["status"] == "fetched"
    assert discovery["intake_job_id"] == ""
    assert version["content_source"] == "article_fetch"
    assert version["title"] == "Verified article page"
    assert version["publication_month"] == ""
    assert review["status"] == "unverified"
    assert "未启动模型分析" in review["reason"]


def test_fetch_only_arxiv_uses_official_abstract_without_redundant_abs_page(monkeypatch):
    source = _enabled_source("Arxiv")
    batch = market_sources.create_batch("tenant-a", "admin-a", request_id="arxiv-feed-only-1",
        topic_id="ai-frontier", source_ids=[source["id"]], mode="fetch_only", max_items=10)
    run_id = market_sources.batch_tasks("tenant-a", batch["id"])[0]["run_id"]
    abstract = "Official arXiv abstract with the complete publisher-provided abstract. " * 4
    candidate = {
        "external_id": "arxiv-entry-2610.12345", "title": "Arxiv research paper",
        "url": "https://arxiv.org/abs/2610.12345", "published_at": "",
        "publication_month": "2026-10", "summary": abstract, "body_text": "",
        "content_source": "summary", "has_fulltext": False,
    }
    monkeypatch.setattr(market_sources, "fetch_feed", lambda *args, **kwargs: {
        "status": 200, "url": "https://arxiv.example/rss", "body": b"<feed/>", "etag": "v1", "last_modified": ""})
    monkeypatch.setattr(market_sources, "parse_feed", lambda *args, **kwargs: [candidate])
    monkeypatch.setattr(market_intake, "fetch_document", lambda _url: (_ for _ in ()).throw(
        AssertionError("the abstract endpoint must not be fetched again")))
    launched = []
    monkeypatch.setattr(market_intake, "launch", lambda job: launched.append(job["id"]))

    import asyncio
    asyncio.run(market_sources._process_run("tenant-a", run_id))
    completed = market_sources.get_batch("tenant-a", batch["id"])
    assert completed["status"] == "completed"
    assert completed["counts"]["analysis_requested"] is False
    assert completed["counts"]["source"]["found"] == 1
    assert not launched
    with market_sources._conn() as con:
        discovery = con.execute("SELECT status,document_id FROM market_source_discoveries WHERE tenant_id=? AND run_id=?",
                                ("tenant-a", run_id)).fetchone()
        version = con.execute("SELECT content_source,body_text,publication_month FROM market_document_versions WHERE tenant_id=? AND document_id=?",
                              ("tenant-a", discovery["document_id"])).fetchone()
        review = con.execute("SELECT status,reason FROM market_quality_reviews WHERE tenant_id=? AND document_id=?",
                             ("tenant-a", discovery["document_id"])).fetchone()
    assert discovery["status"] == "fetched"
    assert version["content_source"] == "summary"
    assert version["body_text"] == abstract
    assert version["publication_month"] == "2026-10"
    assert review["status"] == "unverified"
    assert "原文页尚未读取" in review["reason"]


def test_fetch_only_keeps_feed_entry_when_article_page_is_blocked_and_retries_it(monkeypatch):
    source = _enabled_source("Blocked article")
    batch = market_sources.create_batch("tenant-a", "admin-a", request_id="fetch-only-blocked",
        topic_id="ai-frontier", source_ids=[source["id"]], mode="fetch_only", max_items=10)
    first_run_id = market_sources.batch_tasks("tenant-a", batch["id"])[0]["run_id"]
    candidate = {"external_id": "feed-entry-blocked", "title": "Blocked article", "url": "https://publisher.example/blocked",
                 "published_at": "2026-10-28T10:00:00+00:00", "summary": "Useful feed summary",
                 "body_text": "RSS excerpt that remains unverified.", "content_source": "content:encoded", "has_fulltext": True}
    monkeypatch.setattr(market_sources, "fetch_feed", lambda *args, **kwargs: {
        "status": 200, "url": "https://blocked-article.example/rss", "body": b"<rss/>", "etag": "v1", "last_modified": ""})
    monkeypatch.setattr(market_sources, "parse_feed", lambda *args, **kwargs: [candidate])

    def blocked_page(_url):
        raise ValueError("网页返回 HTTP 403；未入库")

    monkeypatch.setattr(market_intake, "fetch_document", blocked_page)
    import asyncio
    asyncio.run(market_sources._process_run("tenant-a", first_run_id))
    partial = market_sources.get_batch("tenant-a", batch["id"])
    assert partial["status"] == "completed_with_issues"
    with market_sources._conn() as con:
        discovery = con.execute("SELECT id,status,run_id,document_id FROM market_source_discoveries WHERE tenant_id=?",
                                ("tenant-a",)).fetchone()
        version = con.execute("SELECT content_source,body_text FROM market_document_versions WHERE tenant_id=? AND document_id=? ORDER BY created_at DESC LIMIT 1",
                              ("tenant-a", discovery["document_id"])).fetchone()
        review = con.execute("SELECT status,reason FROM market_quality_reviews WHERE tenant_id=? AND document_id=? ORDER BY created_at DESC LIMIT 1",
                             ("tenant-a", discovery["document_id"])).fetchone()
    assert discovery["status"] == "fetch_failed"
    assert discovery["run_id"] == first_run_id
    assert version["content_source"] == "content:encoded"
    assert version["body_text"] == "RSS excerpt that remains unverified."
    assert review["status"] == "unverified"
    assert "HTTP 403" in review["reason"]

    retried = market_sources.batch_action("tenant-a", "admin-a", batch["id"], "retry_failed")
    retry_run_id = market_sources.batch_tasks("tenant-a", batch["id"])[0]["run_id"]
    assert retry_run_id != first_run_id
    monkeypatch.setattr(market_intake, "fetch_document", lambda url: {
        "url": url, "title": "Readable article", "text": "Verified page body " * 30,
        "truncated": False, "fetched_at": "2026-10-28T10:05:00+00:00"})
    asyncio.run(market_sources._process_run("tenant-a", retry_run_id))
    completed = market_sources.get_batch("tenant-a", batch["id"])
    assert completed["status"] == "completed"
    with market_sources._conn() as con:
        discoveries = con.execute("SELECT status,run_id FROM market_source_discoveries WHERE tenant_id=?", ("tenant-a",)).fetchall()
        versions = con.execute("SELECT content_source FROM market_document_versions WHERE tenant_id=?", ("tenant-a",)).fetchall()
    assert len(discoveries) == 1
    assert discoveries[0]["status"] == "fetched"
    assert discoveries[0]["run_id"] == retry_run_id
    assert [row["content_source"] for row in versions].count("article_fetch") == 1


def test_initial_backfill_excludes_undated_and_out_of_window_items(monkeypatch):
    source = market_sources.create_source("tenant-a", "admin-a", {
        "name": "Three month feed", "kind": "rss",
        "config": {"feed_url": "https://three-month.example/rss", "initial_backfill_limit": 500,
                   "initial_backfill_months": 3},
        "candidate_topic_ids": ["ai-frontier"],
    })
    with market_sources._conn() as con:
        con.execute("UPDATE market_sources SET health='healthy' WHERE tenant_id=? AND id=?", ("tenant-a", source["id"]))
    source = market_sources.set_enabled("tenant-a", "admin-a", source["id"], True, source["config_version"])
    run = market_sources.queue_collect("tenant-a", "admin-a", source["id"])
    recent_date = market_research._now()
    candidates = [
        {"external_id": "recent", "title": "Recent", "url": "https://publisher.example/recent", "published_at": recent_date,
         "summary": "recent", "body_text": "", "content_source": "summary", "has_fulltext": False},
        {"external_id": "old", "title": "Old", "url": "https://publisher.example/old", "published_at": "2020-01-01T00:00:00+00:00",
         "summary": "old", "body_text": "", "content_source": "summary", "has_fulltext": False},
        {"external_id": "unknown", "title": "Unknown date", "url": "https://publisher.example/unknown", "published_at": "",
         "summary": "unknown", "body_text": "", "content_source": "summary", "has_fulltext": False},
        {"external_id": "recent-month", "title": "Recent month", "url": "https://arxiv.org/abs/2608.12345", "published_at": "",
         "publication_month": "2026-08", "summary": "recent month", "body_text": "", "content_source": "summary", "has_fulltext": False},
        {"external_id": "cutoff-month", "title": "Cutoff month", "url": "https://arxiv.org/abs/2607.12345", "published_at": "",
         "publication_month": "2026-07", "summary": "cutoff month", "body_text": "", "content_source": "summary", "has_fulltext": False},
        {"external_id": "old-month", "title": "Old month", "url": "https://arxiv.org/abs/2606.12345", "published_at": "",
         "publication_month": "2026-06", "summary": "old month", "body_text": "", "content_source": "summary", "has_fulltext": False},
    ]
    monkeypatch.setattr(market_sources, "fetch_feed", lambda *args, **kwargs: {
        "status": 200, "url": "https://three-month.example/rss", "body": b"<rss/>", "etag": "v1", "last_modified": ""})
    monkeypatch.setattr(market_sources, "parse_feed", lambda *args, **kwargs: candidates)
    launched = []
    monkeypatch.setattr(market_intake, "launch", lambda job: launched.append(job["id"]))
    import asyncio
    asyncio.run(market_sources._process_run("tenant-a", run["id"]))
    result = market_sources.get_run("tenant-a", run["id"])
    assert result["status"] == "succeeded"
    assert result["counts"]["found"] == 2
    assert result["counts"]["outside_window"] == 2
    assert result["counts"]["unknown_date_excluded"] == 2
    assert result["counts"]["intake_queued"] == 2
    assert len(launched) == 2


def _enabled_source(name="Feed"):
    source = market_sources.create_source("tenant-a", "admin-a", {
        "name": name, "kind": "rss", "config": {"feed_url": f"https://{name.lower()}.example/rss"},
        "candidate_topic_ids": ["ai-frontier"],
    })
    with market_sources._conn() as con:
        con.execute("UPDATE market_sources SET health='healthy' WHERE tenant_id=? AND id=?", ("tenant-a", source["id"]))
    return market_sources.set_enabled("tenant-a", "admin-a", source["id"], True, source["config_version"])


def test_source_document_list_exposes_unverified_material_deduplicated_and_tenant_scoped():
    first = _enabled_source("FirstRaw")
    second = _enabled_source("SecondRaw")
    now = market_research._now()
    with market_sources._conn() as con:
        con.execute("""INSERT INTO market_documents
            (id,tenant_id,canonical_identity,canonical_url,title,current_version_id,first_seen_at,last_seen_at)
            VALUES(?,?,?,?,?,?,?,?)""",
            ("doc-shared", "tenant-a", "url:https://publisher.example/story/1",
             "https://publisher.example/story/1", "Evidence-backed release", "ver-shared", now, now))
        con.execute("""INSERT INTO market_document_versions
            (id,tenant_id,document_id,content_hash,title,body_text,content_source,published_at,
             publication_month,fetched_at,created_at) VALUES(?,?,?,?,?,?,?,?,?,?,?)""",
            ("ver-shared", "tenant-a", "doc-shared", "hash-shared", "Evidence-backed release",
             "A short source summary with an evidence-backed release detail.", "summary",
             "2026-10-20T00:00:00+00:00", "", now, now))
        for source, external_id in ((first, "first-id"), (second, "second-id")):
            con.execute("""INSERT INTO market_source_discoveries
                (id,tenant_id,source_id,document_id,run_id,external_id,original_url,intake_job_id,
                 status,first_seen_at,last_seen_at) VALUES(?,?,?,?,?,?,?,?,?,?,?)""",
                (f"discovery-{external_id}", "tenant-a", source["id"], "doc-shared", "",
                 external_id, "https://publisher.example/story/1", "", "fetched", now, now))
        con.execute("""INSERT INTO market_quality_reviews
            (id,tenant_id,source_id,document_id,observation_id,status,reason,evidence_json,created_at)
            VALUES(?,?,?,?,?,?,?,?,?)""",
            ("review-shared", "tenant-a", first["id"], "doc-shared", "", "unverified",
             "Feed 摘要尚未与原文核对", "{}", now))

    result = market_sources.list_source_documents("tenant-a", status="unverified", query="evidence")
    assert result["total"] == 1
    assert result["summary"]["raw_documents"] == 1
    assert result["summary"]["unverified"] == 1
    assert len(result["items"]) == 1
    assert result["items"][0]["source_count"] == 2
    assert {item["source_id"] for item in result["items"][0]["sources"]} == {first["id"], second["id"]}
    assert result["items"][0]["quality_reason"] == "Feed 摘要尚未与原文核对"
    assert market_sources.list_source_documents("tenant-b")["total"] == 0
    topic_summary = market_sources.source_document_summary("tenant-a")["topics"]["ai-frontier"]
    assert topic_summary["raw_documents"] == 1
    assert topic_summary["unverified"] == 1

    with market_sources._conn() as con:
        con.execute("UPDATE market_quality_reviews SET status='source_attributed' WHERE tenant_id=? AND id=?",
                    ("tenant-a", "review-shared"))
    assert market_sources.list_source_documents("tenant-a", status="unverified")["total"] == 0
    all_material = market_sources.list_source_documents("tenant-a", status="all")
    assert all_material["total"] == 1
    assert all_material["items"][0]["quality_status"] == "source_attributed"
    topic_summary = market_sources.source_document_summary("tenant-a")["topics"]["ai-frontier"]
    assert topic_summary["raw_documents"] == 1
    assert topic_summary["source_attributed"] == 1

    # Review history and rediscovery through multiple feeds must not inflate
    # the current document status shown by the source overview.
    with market_sources._conn() as con:
        con.execute("""INSERT INTO market_quality_reviews
            (id,tenant_id,source_id,document_id,status,created_at)
            VALUES(?,?,?,?,?,?)""",
            ("review-shared-older", "tenant-a", second["id"], "doc-shared",
             "unverified", "2000-01-01T00:00:00+00:00"))
    quality = market_sources.source_summary("tenant-a")["quality"]
    assert quality.get("unverified", 0) == 0
    assert quality["source_attributed"] == 1
    assert sum(quality.values()) == 1


def test_local_triage_classifies_document_without_promoting_it_to_research_evidence():
    source = _enabled_source("LocalTriage")
    now = market_research._now()
    with market_sources._conn() as con:
        con.execute("UPDATE market_sources SET candidate_topics_json=? WHERE tenant_id=? AND id=?",
                    ('["ai-frontier","embodied-intelligence"]', "tenant-a", source["id"]))
        con.execute("""INSERT INTO market_documents
            (id,tenant_id,canonical_identity,canonical_url,title,current_version_id,first_seen_at,last_seen_at)
            VALUES(?,?,?,?,?,?,?,?)""",
            ("doc-triage", "tenant-a", "url:https://publisher.example/humanoid-vla",
             "https://publisher.example/humanoid-vla", "VLA model for humanoid robot manipulation",
             "ver-triage", now, now))
        con.execute("""INSERT INTO market_document_versions
            (id,tenant_id,document_id,content_hash,title,body_text,content_source,published_at,
             publication_month,fetched_at,created_at) VALUES(?,?,?,?,?,?,?,?,?,?,?)""",
            ("ver-triage", "tenant-a", "doc-triage", "hash-triage",
             "VLA model for humanoid robot manipulation",
             "The vision-language-action model controls a humanoid robot for dexterous manipulation in a factory.",
             "article_fetch", "2026-10-20T00:00:00+00:00", "", now, now))
        con.execute("""INSERT INTO market_source_discoveries
            (id,tenant_id,source_id,document_id,run_id,external_id,original_url,intake_job_id,
             status,first_seen_at,last_seen_at) VALUES(?,?,?,?,?,?,?,?,?,?,?)""",
            ("discovery-triage", "tenant-a", source["id"], "doc-triage", "", "triage-id",
             "https://publisher.example/humanoid-vla", "", "fetched", now, now))
        con.execute("""INSERT INTO market_quality_reviews
            (id,tenant_id,source_id,document_id,observation_id,status,reason,evidence_json,created_at)
            VALUES(?,?,?,?,?,?,?,?,?)""",
            ("review-triage", "tenant-a", source["id"], "doc-triage", "", "unverified",
             "原文已抓取，未作核验", "{}", now))

    result = market_sources.triage_unverified_documents_locally("tenant-a")
    assert result["processed"] == 1
    assert result["project_llm_called"] is False
    listed = market_sources.list_source_documents("tenant-a", status="triaged")
    assert listed["total"] == 1
    assert listed["summary"]["triaged"] == 1
    item = listed["items"][0]
    assert item["quality_status"] == "triaged"
    assert item["triage"]["evidence_scope"] == "article_body"
    assert {category["topic_id"] for category in item["triage"]["suggested_categories"]} == {
        "ai-frontier", "embodied-intelligence"}
    assert item["triage"]["counts_as_research_evidence"] is False
    assert "不计入有效研究依据" in item["quality_reason"]


def test_collection_batch_is_idempotent_tracks_progress_and_can_pause_resume():
    first = _enabled_source("First")
    second = _enabled_source("Second")
    batch = market_sources.create_batch("tenant-a", "admin-a", request_id="request-1",
                                        topic_id="ai-frontier", max_items=50)
    assert batch["source_total"] == 2
    assert batch["status"] == "running"
    assert batch["budget"]["max_items"] == 50
    same = market_sources.create_batch("tenant-a", "admin-a", request_id="request-1",
                                       topic_id="ai-frontier", max_items=50)
    assert same["id"] == batch["id"]
    same_scope = market_sources.create_batch("tenant-a", "admin-a", request_id="request-2",
                                             topic_id="ai-frontier", max_items=50)
    assert same_scope["id"] == batch["id"]
    with pytest.raises(RuntimeError, match="不同的采集范围"):
        market_sources.create_batch("tenant-a", "admin-a", request_id="request-1", topic_id="policy-analysis")

    paused = market_sources.batch_action("tenant-a", "admin-a", batch["id"], "pause")
    assert paused["status"] == "paused"
    assert market_sources.batch_tasks("tenant-a", batch["id"])[0]["status"] == "cancelled"
    resumed = market_sources.batch_action("tenant-a", "admin-a", batch["id"], "resume")
    assert resumed["status"] == "running"
    assert len(market_sources.batch_events("tenant-a", batch["id"])) >= 3

    with market_sources._conn() as con:
        members = con.execute("SELECT run_id FROM market_collection_members WHERE tenant_id=? AND batch_id=?",
                              ("tenant-a", batch["id"])).fetchall()
        for member in members:
            con.execute("UPDATE market_source_runs SET status='succeeded',stage='discover',counts_json=? WHERE tenant_id=? AND id=?",
                        (json.dumps({"found": 2, "new": 1, "duplicate": 1}), "tenant-a", member["run_id"]))
    completed = market_sources.get_batch("tenant-a", batch["id"])
    assert completed["status"] == "completed"
    assert completed["source_fetch_finished_at"]
    assert completed["pipeline_finished_at"]
    assert completed["counts"]["source"]["found"] == 4


def test_collection_batch_rejects_empty_scope_and_non_tenant_sources():
    source = _enabled_source("Scoped")
    with pytest.raises(ValueError, match="不存在、已停用或不属于"):
        market_sources.create_batch("tenant-b", "admin-b", request_id="empty", source_ids=[source["id"]])
    with pytest.raises(ValueError, match="没有已启用"):
        market_sources.create_batch("tenant-a", "admin-a", request_id="no-match", topic_id="policy-analysis")


def test_collection_batch_requires_topic_for_multi_topic_sources():
    source = market_sources.create_source("tenant-a", "admin-a", {
        "name": "Multi topic", "kind": "rss", "config": {"feed_url": "https://multi.example/rss"},
        "candidate_topic_ids": ["ai-frontier", "policy-analysis"],
    })
    with market_sources._conn() as con:
        con.execute("UPDATE market_sources SET health='healthy' WHERE tenant_id=? AND id=?", ("tenant-a", source["id"]))
    market_sources.set_enabled("tenant-a", "admin-a", source["id"], True, source["config_version"])
    with pytest.raises(ValueError, match="请选择研究主题"):
        market_sources.create_batch("tenant-a", "admin-a", request_id="ambiguous", max_items=10)
