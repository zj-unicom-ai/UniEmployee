from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone

from cryptography.fernet import Fernet

from app.im import jobs
from app.im.context import ActorContext
from app.im.contracts import NormalizedInbound, OutboundMessage
from app.im.credentials import CredentialKeyError


def inbound(message_id: str = "om_1", channel_id: str = "chan_1") -> NormalizedInbound:
    return NormalizedInbound(
        provider="feishu", channel_id=channel_id, app_id="cli_test",
        tenant_key="tenant_a", event_id=f"evt_{message_id}", message_id=message_id,
        chat_id="oc_1", chat_type="group", sender_open_id="ou_1", text="hello",
    )


def test_concurrent_duplicate_message_creates_one_inbox():
    jobs.init()
    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(lambda _: jobs.enqueue_inbound(inbound()), range(16)))

    assert len({item[0] for item in results}) == 1
    assert sum(item[1] for item in results) == 1


def test_inbox_lease_can_only_be_reclaimed_after_expiry():
    inbox_id, _ = jobs.enqueue_inbound(inbound())
    start = datetime(2026, 9, 11, tzinfo=timezone.utc)

    first = jobs.claim_inbox("worker-a", lease_seconds=60, now=start)
    assert first["id"] == inbox_id
    assert first["attempts"] == 1
    assert jobs.claim_inbox("worker-b", now=start + timedelta(seconds=59)) is None

    recovered = jobs.claim_inbox("worker-b", now=start + timedelta(seconds=61))
    assert recovered["id"] == inbox_id
    assert recovered["lease_owner"] == "worker-b"
    assert recovered["attempts"] == 2
    assert jobs.finish_inbox(inbox_id, "worker-a") is False
    assert jobs.finish_inbox(inbox_id, "worker-b") is True


def test_workers_only_claim_jobs_for_their_channel():
    first_id, _ = jobs.enqueue_inbound(inbound("om_ch1", "chan_1"))
    second_id, _ = jobs.enqueue_inbound(inbound("om_ch2", "chan_2"))

    second = jobs.claim_inbox("worker-2", channel_id="chan_2")
    assert second["id"] == second_id
    first = jobs.claim_inbox("worker-1", channel_id="chan_1")
    assert first["id"] == first_id

    for row, worker in ((first, "worker-1"), (second, "worker-2")):
        jobs.create_outbox(
            row["id"],
            OutboundMessage(
                channel_id=row["channel_id"],
                receive_id="oc_1",
                receive_id_type="chat_id",
                text="answer",
            ),
        )
        assert jobs.finish_inbox(row["id"], worker)

    outbox_2 = jobs.claim_outbox("delivery-2", channel_id="chan_2")
    outbox_1 = jobs.claim_outbox("delivery-1", channel_id="chan_1")
    assert outbox_2["channel_id"] == "chan_2"
    assert outbox_1["channel_id"] == "chan_1"


def test_outbox_is_idempotent_and_preserves_uuid_across_retry():
    inbox_id, _ = jobs.enqueue_inbound(inbound())
    message = OutboundMessage(
        channel_id="chan_1", receive_id="oc_1", receive_id_type="chat_id",
        reply_to_message_id="om_1", text="answer",
    )
    first_id, first_created = jobs.create_outbox(inbox_id, message)
    second_id, second_created = jobs.create_outbox(inbox_id, message)
    assert first_id == second_id
    assert first_created is True
    assert second_created is False

    start = datetime(2026, 9, 11, tzinfo=timezone.utc)
    first = jobs.claim_outbox("worker-a", now=start)
    stable_uuid = first["provider_uuid"]
    assert jobs.retry_outbox(
        first_id, "worker-a", error="429", retry_at=start + timedelta(seconds=30)
    )
    assert jobs.claim_outbox("worker-b", now=start + timedelta(seconds=29)) is None
    retry = jobs.claim_outbox("worker-b", now=start + timedelta(seconds=31))
    assert retry["provider_uuid"] == stable_uuid
    assert retry["attempts"] == 2
    assert jobs.finish_outbox(first_id, "worker-b", provider_message_id="om_reply")


def test_dead_outbox_can_be_listed_and_replayed():
    inbox_id, _ = jobs.enqueue_inbound(inbound("om_dead"))
    outbox_id, _ = jobs.create_outbox(
        inbox_id,
        OutboundMessage(
            channel_id="chan_1",
            receive_id="oc_1",
            receive_id_type="chat_id",
            reply_to_message_id="om_dead",
            text="answer",
        ),
    )
    claimed = jobs.claim_outbox("worker-a")
    stable_uuid = claimed["provider_uuid"]
    assert jobs.retry_outbox(outbox_id, "worker-a", error="permanent", retry_at=None)

    dead = jobs.list_outbox(channel_id="chan_1", status="dead")
    assert dead[0]["id"] == outbox_id
    assert "content" not in dead[0]
    replayed = jobs.replay_outbox(outbox_id)
    assert replayed["status"] == "pending"
    assert replayed["attempts"] == 0

    retried = jobs.claim_outbox("worker-b")
    assert retried["provider_uuid"] == stable_uuid
    assert retried["attempts"] == 1


def test_credentials_are_encrypted_and_summary_never_exposes_secret(monkeypatch):
    monkeypatch.setenv("IM_CREDENTIAL_KEY", Fernet.generate_key().decode("ascii"))
    jobs.put_credential(
        channel_id="chan_1", app_id="cli_test", app_secret="secret-value",
        tenant_key="tenant_a",
    )

    summary = jobs.credential_summary("chan_1")
    assert summary["configured"] is True
    assert "secret-value" not in repr(summary)
    credential = jobs.get_credential("chan_1")
    assert credential.app_secret == "secret-value"
    assert "secret-value" not in repr(credential)

    with jobs._conn() as con:
        row = con.execute(
            "SELECT app_secret_ciphertext FROM channel_credentials WHERE channel_id=?",
            ("chan_1",),
        ).fetchone()
    assert row[0] != "secret-value"


def test_credentials_require_a_dedicated_key(monkeypatch):
    monkeypatch.delenv("IM_CREDENTIAL_KEY", raising=False)
    try:
        jobs.put_credential(
            channel_id="chan_1", app_id="cli_test", app_secret="secret-value",
            tenant_key="tenant_a",
        )
    except CredentialKeyError as exc:
        assert "IM_CREDENTIAL_KEY" in str(exc)
    else:
        raise AssertionError("缺少独立凭证密钥时不应允许写入")


def test_external_identity_and_group_thread_do_not_bind_platform_user():
    first = ActorContext.isolated_feishu(
        app_id="cli_test", tenant_key="tenant_a", sender_open_id="ou_first",
        chat_id="oc_group", chat_type="group",
    )
    second = ActorContext.isolated_feishu(
        app_id="cli_test", tenant_key="tenant_a", sender_open_id="ou_second",
        chat_id="oc_group", chat_type="group",
    )

    identity = jobs.ensure_external_identity(first)
    assert identity["internal_user_id"] is None
    assert identity["binding_status"] == "external"

    first_thread, created = jobs.get_or_create_thread(
        first, channel_id="chan_1", employee_id="employee_1"
    )
    second_thread, second_created = jobs.get_or_create_thread(
        second, channel_id="chan_1", employee_id="employee_1"
    )
    assert created is True
    assert second_created is False
    assert first_thread["conv_id"] == second_thread["conv_id"]
