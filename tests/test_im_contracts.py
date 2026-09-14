import pytest

from app.im.context import ActorContext
from app.im.contracts import NormalizedInbound


def test_group_context_is_shared_without_platform_authority():
    first = ActorContext.isolated_feishu(
        app_id="cli_test", tenant_key="tenant_a", sender_open_id="ou_first",
        chat_id="oc_group", chat_type="group",
    )
    second = ActorContext.isolated_feishu(
        app_id="cli_test", tenant_key="tenant_a", sender_open_id="ou_second",
        chat_id="oc_group", chat_type="group",
    )

    assert first.subject_id == second.subject_id
    assert first.authorization_user_id is None
    assert second.authorization_user_id is None
    assert first.sender_open_id != second.sender_open_id


def test_chat_and_tenant_boundaries_are_isolated():
    base = dict(app_id="cli_test", sender_open_id="ou_user", chat_type="group")
    a = ActorContext.isolated_feishu(tenant_key="tenant_a", chat_id="oc_1", **base)
    b = ActorContext.isolated_feishu(tenant_key="tenant_a", chat_id="oc_2", **base)
    c = ActorContext.isolated_feishu(tenant_key="tenant_b", chat_id="oc_1", **base)

    assert len({a.subject_id, b.subject_id, c.subject_id}) == 3


def test_normalized_inbound_persists_only_required_shape():
    message = NormalizedInbound(
        provider="feishu", channel_id="chan_1", app_id="cli_test",
        tenant_key="tenant_a", event_id="evt_1", message_id="om_1",
        chat_id="oc_1", chat_type="p2p", sender_open_id="ou_1", text="hello",
    )

    payload = message.persisted_payload()
    assert payload["text"] == "hello"
    assert "event_id" not in payload
    assert "message_id" not in payload
    assert "raw" not in payload


def test_invalid_chat_type_is_rejected():
    with pytest.raises(ValueError, match="chat_type"):
        ActorContext.isolated_feishu(
            app_id="cli_test", tenant_key="tenant_a", sender_open_id="ou_1",
            chat_id="oc_1", chat_type="topic",
        )
