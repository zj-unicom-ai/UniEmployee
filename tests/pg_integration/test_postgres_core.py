"""PostgreSQL-only integration coverage; requires an explicitly isolated CI database."""

import asyncio
import hashlib
import hmac
import os
import time
import uuid
from concurrent.futures import ThreadPoolExecutor

import pytest

pytestmark = pytest.mark.pg_integration

if os.environ.get("UE_RUN_POSTGRES_INTEGRATION") != "1":
    pytest.skip("需要显式启用隔离 PostgreSQL 集成套件", allow_module_level=True)

from fastapi import FastAPI
from fastapi.testclient import TestClient
from langgraph.checkpoint.base import empty_checkpoint

from app import approvals, automations, catalog, conversations, db, ontology, streaming
from app import auth
from app.routes.automations import router as automations_router


@pytest.fixture(scope="session", autouse=True)
def postgres_schema():
    """初始化真实 PG schema；连接仅由根 conftest 的显式安全门放行。"""
    assert db.is_pg()
    catalog.init()
    ontology.init()
    conversations._conn().close()
    approvals._conn().close()
    yield
    db.close_all_pools()


def _new_automation(*, tenant_id="tenant-pg", run_as="u_pg_runner", event_key=None):
    suffix = uuid.uuid4().hex
    return automations.create(
        f"PG integration {suffix}", "event", "emp_pg_integration",
        "处理 {{payload}}", event_key=event_key or f"pg.{suffix}",
        secret="s" * 32, run_as=run_as, enabled=True, tenant_id=tenant_id,
    )


def test_postgres_schema_initialization_and_legacy_automation_migration(monkeypatch):
    """应用初始化可重复；旧自动化表会被增量迁移且保留租户归属。"""
    monkeypatch.setenv("ENTERPRISE_TENANT_ID", "tenant-pg-migrated")
    auto = _new_automation(tenant_id="default", run_as="u_pg_legacy")
    execution, created = automations.create_execution(
        auto["id"], "event", f"legacy-{uuid.uuid4().hex}", tenant_id="default",
        trigger_actor="system:webhook", run_as_principal="u_pg_legacy",
    )
    assert created

    con = automations._conn()
    try:
        con.execute("DROP INDEX IF EXISTS idx_automations_tenant_created")
        con.execute("DROP INDEX IF EXISTS idx_auto_exec_tenant")
        con.execute("ALTER TABLE automations DROP COLUMN tenant_id")
        con.execute("ALTER TABLE automation_executions DROP COLUMN tenant_id")
        con.execute("ALTER TABLE automation_executions DROP COLUMN trigger_actor")
        con.execute("ALTER TABLE automation_executions DROP COLUMN run_as_principal")
        con.commit()
    finally:
        con.close()

    # Re-running the public startup seam performs the production migration path.
    con = automations._conn()
    try:
        auto_columns = db.table_columns(con, "automations")
        execution_columns = db.table_columns(con, "automation_executions")
        migrated_auto = con.execute(
            "SELECT tenant_id FROM automations WHERE id=?", (auto["id"],)
        ).fetchone()
        migrated_execution = con.execute(
            "SELECT tenant_id,trigger_actor,run_as_principal FROM automation_executions WHERE id=?",
            (execution["id"],),
        ).fetchone()
    finally:
        con.close()

    assert {"tenant_id"} <= set(auto_columns)
    assert {"tenant_id", "trigger_actor", "run_as_principal"} <= set(execution_columns)
    assert migrated_auto["tenant_id"] == "tenant-pg-migrated"
    assert migrated_execution["tenant_id"] == "tenant-pg-migrated"
    assert migrated_execution["trigger_actor"] == "system:legacy"
    assert migrated_execution["run_as_principal"] == "u_pg_legacy"


def test_postgres_automation_tenant_filtering_and_concurrent_idempotency():
    tenant_a = _new_automation(tenant_id="tenant-pg-a")
    tenant_b = _new_automation(tenant_id="tenant-pg-b")

    assert tenant_a["id"] in {row["id"] for row in automations.list_all("tenant-pg-a")}
    assert tenant_b["id"] not in {row["id"] for row in automations.list_all("tenant-pg-a")}
    assert automations.get(tenant_b["id"], tenant_id="tenant-pg-a") is None

    trigger_key = f"concurrent-{uuid.uuid4().hex}"
    args = (tenant_a["id"], "event", trigger_key)
    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(lambda _: automations.create_execution(
            *args, tenant_id="tenant-pg-a", trigger_actor="system:webhook",
            run_as_principal="u_pg_runner"), range(16)))

    rows, created = zip(*results)
    assert len({row["id"] for row in rows}) == 1
    assert sum(created) == 1
    assert automations.list_executions(tenant_a["id"], tenant_id="tenant-pg-b") == []


def test_postgres_transaction_rolls_back_on_exception():
    auto = _new_automation()
    with pytest.raises(RuntimeError, match="force rollback"):
        with automations._conn() as con:
            con.execute("UPDATE automations SET name=? WHERE id=?", ("uncommitted", auto["id"]))
            raise RuntimeError("force rollback")

    assert automations.get(auto["id"])["name"] == auto["name"]


def _signed_headers(body: bytes, secret: str, event_key: str,
                    timestamp: str, idempotency_key: str) -> dict[str, str]:
    path = f"/api/automations/events/{event_key}"
    body_digest = hashlib.sha256(body).hexdigest()
    message = "\n".join(("v2", "POST", path, "tenant-pg-webhook", timestamp,
                          idempotency_key, body_digest)).encode()
    signature = hmac.new(secret.encode(), message, hashlib.sha256).hexdigest()
    return {
        "Content-Type": "application/json",
        "Idempotency-Key": idempotency_key,
        "X-UniEmployee-Timestamp": timestamp,
        "X-UniEmployee-Signature": signature,
    }


def test_postgres_webhook_replay_does_not_start_a_second_agent(monkeypatch):
    monkeypatch.setenv("APP_ENV", "production")
    employee_id = f"emp_pg_{uuid.uuid4().hex}"
    user_id = f"u_pg_{uuid.uuid4().hex}"
    event_key = f"pg.webhook.{uuid.uuid4().hex}"
    secret = "w" * 32
    catalog.create_employee({"id": employee_id, "name": "PG integration employee"})
    catalog.create_user(user_id, "!test-only", tenant_id="tenant-pg-webhook", user_id=user_id)
    catalog.assign_employee(user_id, employee_id, granted_by="pg-integration")
    auto = automations.create(
        "PG webhook idempotency", "event", employee_id, "处理 {{payload}}",
        event_key=event_key, secret=secret, run_as=user_id,
        tenant_id="tenant-pg-webhook",
    )

    calls = 0

    async def fake_stream(*args, **kwargs):
        nonlocal calls
        calls += 1
        yield 'data: {"type":"token","content":"ok"}\n\n'

    monkeypatch.setattr(streaming, "_stream_run", fake_stream)
    app = FastAPI()
    app.include_router(automations_router)
    app.dependency_overrides[auth.get_current_user_or_fallback] = lambda: {
        "id": user_id, "username": user_id, "role": "user", "tenant_id": "tenant-pg-webhook",
    }
    body = b'{"payload":{"record":"pg-1"}}'
    key = f"webhook-{uuid.uuid4().hex}"
    headers = _signed_headers(body, secret, event_key, str(int(time.time())), key)

    with TestClient(app) as client:
        first = client.post(f"/api/automations/events/{event_key}", content=body, headers=headers)
        replay = client.post(f"/api/automations/events/{event_key}", content=body, headers=headers)

    assert first.status_code == replay.status_code == 200
    assert first.json()["results"][0]["execution_id"] == replay.json()["results"][0]["execution_id"]
    assert replay.json()["results"][0]["duplicate"] is True
    assert calls == 1
    assert len(automations.list_executions(auto["id"], tenant_id="tenant-pg-webhook")) == 1


def test_postgres_langgraph_checkpoint_and_store_roundtrip():
    from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
    from langgraph.store.postgres import AsyncPostgresStore

    async def roundtrip():
        thread_id = f"pg-integration-{uuid.uuid4().hex}"
        config = {"configurable": {"thread_id": thread_id, "checkpoint_ns": ""}}
        checkpoint = empty_checkpoint()
        checkpoint["channel_values"] = {"integration_probe": "checkpoint-ok"}
        async with AsyncPostgresSaver.from_conn_string(db.pg_dsn("checkpoints")) as saver:
            await saver.setup()
            saved_config = await saver.aput(
                config, checkpoint,
                {"source": "input", "step": -1, "parents": {}},
                {"integration_probe": 1},
            )
            loaded = await saver.aget_tuple(saved_config)
            assert loaded is not None
            assert loaded.checkpoint["channel_values"]["integration_probe"] == "checkpoint-ok"

        namespace = ("pg-integration", uuid.uuid4().hex)
        key = "memory-roundtrip"
        async with AsyncPostgresStore.from_conn_string(db.pg_dsn("store")) as store:
            await store.setup()
            await store.aput(namespace, key, {"probe": "store-ok"}, index=False)
            item = await store.aget(namespace, key)
            assert item is not None
            assert item.value == {"probe": "store-ok"}

    asyncio.run(roundtrip())
