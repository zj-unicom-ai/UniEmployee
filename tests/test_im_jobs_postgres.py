import os
import uuid

import pytest
from dotenv import load_dotenv

from app import db as dblayer
from app.im import jobs
from app.im.contracts import NormalizedInbound


@pytest.mark.slow
def test_postgres_schema_and_inbox_idempotency(monkeypatch):
    if os.environ.get("RUN_POSTGRES_TESTS") != "1":
        pytest.skip("set RUN_POSTGRES_TESTS=1 to run against local PostgreSQL")
    load_dotenv(os.path.join(os.path.dirname(__file__), "..", ".env"), override=False)
    monkeypatch.setenv("DB_BACKEND", "postgres")
    monkeypatch.setenv("POSTGRES_HOST", "127.0.0.1")
    if not os.environ.get("POSTGRES_PASSWORD"):
        monkeypatch.setenv("POSTGRES_PASSWORD", "uniemployee_dev")
    marker = uuid.uuid4().hex
    channel_id = f"test_chan_{marker}"
    message = NormalizedInbound(
        provider="feishu", channel_id=channel_id, app_id="cli_test",
        tenant_key="tenant_test", event_id=f"evt_{marker}", message_id=f"om_{marker}",
        chat_id=f"oc_{marker}", chat_type="p2p", sender_open_id=f"ou_{marker}", text="test",
    )
    initialized = False
    try:
        jobs.init()
        initialized = True
        first = jobs.enqueue_inbound(message)
        second = jobs.enqueue_inbound(message)
        assert first[1] is True
        assert second == (first[0], False)
        claimed = jobs.claim_inbox("pg-worker")
        assert claimed["id"] == first[0]
        assert jobs.finish_inbox(first[0], "pg-worker") is True
    finally:
        if initialized:
            with dblayer.connect("conversations") as con:
                con.execute("DELETE FROM channel_outbox WHERE channel_id=?", (channel_id,))
                con.execute("DELETE FROM channel_inbox WHERE channel_id=?", (channel_id,))
                con.execute("DELETE FROM channel_threads WHERE channel_id=?", (channel_id,))
                con.execute("DELETE FROM channel_credentials WHERE channel_id=?", (channel_id,))
        dblayer.close_all_pools()
