import pytest

from app import market_research


def test_workbench_sorts_and_scopes_observations_by_tenant_and_topic():
    first = market_research.create_observation(
        tenant_id="tenant-a", topic_id="ai-frontier", title="模型更新",
        summary="首条观察", content_markdown="正文 A",
        sources=[{"title": "机构公告", "url": "https://example.com/a",
                  "published_at": "2026-10-20"}],
        ingest_method="agent", created_by="u1", conv_id="c1",
    )
    second = market_research.create_observation(
        tenant_id="tenant-a", topic_id="policy-analysis", title="新规发布",
        summary="政策观察", ingest_method="source_task", source_name="政策网站",
    )
    market_research.create_observation(
        tenant_id="tenant-b", topic_id="ai-frontier", title="其他租户记录",
    )

    all_topics = market_research.list_workbench(tenant_id="tenant-a")
    assert [item["id"] for item in all_topics["items"]] == [second["id"], first["id"]]
    assert {topic["id"]: topic["observation_count"] for topic in all_topics["topics"]}[
        "ai-frontier"] == 1
    assert "tenant_id" not in all_topics["items"][0]

    focused = market_research.list_workbench(
        tenant_id="tenant-a", topic_id="ai-frontier")
    assert [item["title"] for item in focused["items"]] == ["模型更新"]
    assert focused["items"][0]["sources"][0]["url"] == "https://example.com/a"


def test_workbench_rejects_unknown_topics_and_unsafe_source_urls():
    with pytest.raises(ValueError, match="研究主题"):
        market_research.create_observation(
            tenant_id="tenant-a", topic_id="unknown", title="不支持的主题")

    observation = market_research.create_observation(
        tenant_id="tenant-a", topic_id="embodied-intelligence", title="观察",
        sources=[{"title": "不安全链接", "url": "javascript:alert(1)"},
                 {"title": "有效链接", "url": "https://example.com"}],
    )
    assert [source["title"] for source in observation["sources"]] == ["有效链接"]


def test_workbench_pagination_covers_more_than_one_hundred_active_topic_records():
    expected = set()
    for i in range(105):
        item = market_research.create_observation(
            tenant_id="radar-a", topic_id="embodied-intelligence", title=f"进展 {i}")
        expected.add(item["id"])
    deleted = market_research.create_observation(
        tenant_id="radar-a", topic_id="embodied-intelligence", title="已删除")
    market_research.soft_delete_observation(tenant_id="radar-a", observation_id=deleted["id"])
    market_research.create_observation(tenant_id="radar-b", topic_id="embodied-intelligence", title="其他租户")
    market_research.create_observation(tenant_id="radar-a", topic_id="ai-frontier", title="其他主题")
    first = market_research.list_workbench(tenant_id="radar-a", topic_id="embodied-intelligence", limit=100)
    second = market_research.list_workbench(tenant_id="radar-a", topic_id="embodied-intelligence", limit=100, offset=100)
    assert len(first["items"]) == 100
    assert len(second["items"]) == 5
    ids = [item["id"] for item in first["items"] + second["items"]]
    assert len(ids) == len(set(ids)) == 105
    assert set(ids) == expected


def test_topic_judgement_stays_stale_until_new_evidence_is_absorbed():
    topic_id = "embodied-intelligence"
    category_id = "vla-embodied-reasoning"
    source = {"title": "研究原文", "url": "https://example.com/research"}
    first = market_research.create_observation(
        tenant_id="assessment-a", topic_id=topic_id, category_id=category_id, title="初始研究")
    child = market_research.save_judgement(
        tenant_id="assessment-a", topic_id=topic_id, category_id=category_id,
        title="技术研判", conclusion="判断", content_markdown="正文",
        evidence_ids=[first["id"]], sources=[source])["report"]
    market_research.save_judgement(
        tenant_id="assessment-a", topic_id=topic_id, title="综合研判",
        conclusion="主题判断", content_markdown="主题正文", sources=[source],
        evidence_ids=[first["id"]], data_cutoff=child["created_at"])
    assert market_research.get_topic_judgement_overview(
        tenant_id="assessment-a", topic_id=topic_id)["topic_report"]["freshness"] == "current"
    market_research.create_observation(
        tenant_id="assessment-a", topic_id=topic_id, category_id=category_id, title="新研究")
    overview = market_research.get_topic_judgement_overview(
        tenant_id="assessment-a", topic_id=topic_id)
    assert overview["topic_report"]["freshness"] == "stale"
    assert overview["topic_report"]["new_evidence_count"] == 1
    assert overview["topic_report"]["updated_category_count"] == 0


def test_deleted_and_reclassified_evidence_invalidates_prior_report():
    topic = 'embodied-intelligence'
    category = 'vla-embodied-reasoning'
    item = market_research.create_observation(tenant_id='scope-a', topic_id=topic, category_id=category, title='原始证据')
    market_research.save_judgement(tenant_id='scope-a', topic_id=topic, category_id=category,
        title='原判断', conclusion='结论', content_markdown='正文', evidence_ids=[item['id']], sources=[{'url':'https://example.com/source'}])
    market_research.set_observation_category(tenant_id='scope-a', observation_id=item['id'], category_id='robot-learning-data')
    old = market_research.get_judgement(tenant_id='scope-a', topic_id=topic, category_id=category)
    assert old['freshness'] == 'stale' and old['invalid_reference_count'] == 1
    with pytest.raises(ValueError, match='不属于当前范围'):
        market_research.save_judgement(tenant_id='scope-a', topic_id=topic, category_id=category,
            title='错误引用', conclusion='结论', content_markdown='正文', evidence_ids=[item['id']], sources=[{'url':'https://example.com/source'}])


def test_future_cutoff_cannot_hide_new_evidence():
    with pytest.raises(ValueError,match='截止时间'):
        market_research.save_judgement(tenant_id='clock-a',topic_id='embodied-intelligence',category_id='robot-learning-data',
            title='未来时间',conclusion='不能假装未来资料已吸收',content_markdown='正文',data_cutoff='2999-01-01',sources=[{'url':'https://example.com/source'}])
