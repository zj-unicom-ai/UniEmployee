"""单进程模型准入的并发、排队超时和统计验证。"""

import asyncio

import pytest

from app import model_admission


def test_admission_rejects_when_no_queue_slots(monkeypatch):
    monkeypatch.setenv("MODEL_MAX_CONCURRENT", "1")
    monkeypatch.setenv("MODEL_MAX_QUEUE", "0")
    monkeypatch.setenv("MODEL_QUEUE_TIMEOUT_SEC", "1")
    model_admission.reset_for_tests()

    async def scenario():
        lease = await model_admission.acquire("model-a")
        with pytest.raises(model_admission.AdmissionRejected):
            await model_admission.acquire("model-a")
        model_admission.release(lease)

    asyncio.run(scenario())
    item = model_admission.stats()["models"][0]
    assert item["admitted"] == 1
    assert item["rejected"] == 1
    assert item["active"] == 0


def test_admission_queues_and_releases_slot(monkeypatch):
    monkeypatch.setenv("MODEL_MAX_CONCURRENT", "1")
    monkeypatch.setenv("MODEL_MAX_QUEUE", "1")
    monkeypatch.setenv("MODEL_QUEUE_TIMEOUT_SEC", "1")
    model_admission.reset_for_tests()

    async def scenario():
        first = await model_admission.acquire("model-b")
        entered = asyncio.Event()

        async def waiter():
            lease = await model_admission.acquire("model-b")
            entered.set()
            model_admission.release(lease)

        task = asyncio.create_task(waiter())
        await asyncio.sleep(0.02)
        assert model_admission.stats()["models"][0]["waiting"] == 1
        model_admission.release(first)
        await asyncio.wait_for(entered.wait(), timeout=0.5)
        await task

    asyncio.run(scenario())
    stats = model_admission.stats()["models"][0]
    assert stats["admitted"] == 2
    assert stats["p95_wait_ms"] >= 0
    assert stats["active"] == stats["waiting"] == 0


def test_model_admission_is_disabled_by_default(monkeypatch):
    monkeypatch.delenv("MODEL_MAX_CONCURRENT", raising=False)
    model_admission.reset_for_tests()
    lease = asyncio.run(model_admission.acquire("model-c"))
    assert lease["state"] is None
    assert model_admission.stats()["enabled"] is False


def test_openai_compatible_model_gets_provider_request_timeout(monkeypatch):
    from app import compiler
    from app.catalog import ai_models

    seen = {}
    monkeypatch.setenv("MODEL_REQUEST_TIMEOUT_SEC", "37")
    monkeypatch.setattr(ai_models, "resolve_runtime_model", lambda model: {
        "base_model": "provider-model", "api_key": "test-key",
        "api_domain": "https://models.example/v1",
    })

    def fake_init(model, **kwargs):
        seen.update(model=model, **kwargs)
        return object()

    monkeypatch.setattr(compiler, "init_chat_model", fake_init)
    compiler._init_model("openai:provider-model")
    assert seen["timeout"] == 37
    assert seen["api_key"] == "test-key"
