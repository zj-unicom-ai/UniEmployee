"""审批落库、过期自动拒绝和 pending 数量上限测试。"""

import pytest

from app import approvals


def test_approval_persisted_and_visible_across_connections():
    rec = approvals.create("conv_ap", "xiaosu", "create_ticket",
                           {"title": "工单"}, user_id="u_ap")
    got = approvals.get(rec["approval_id"])
    assert got["status"] == "pending"
    assert got["args"] == {"title": "工单"}
    assert got["expires_at"]

    decided = approvals.decide(rec["approval_id"], "approve")
    assert decided["status"] == "approve"
    assert approvals.decide(rec["approval_id"], "reject") is None


def test_expired_pending_is_auto_rejected(monkeypatch):
    monkeypatch.setenv("APPROVAL_TTL_SECONDS", "-1")
    rec = approvals.create("conv_exp", "xiaosu", "create_ticket", {}, user_id="u_exp")
    got = approvals.get(rec["approval_id"])
    assert got["status"] == "rejected"
    assert approvals.decide(rec["approval_id"], "approve") is None


def test_pending_limit_blocks_new_approval(monkeypatch):
    monkeypatch.setenv("APPROVAL_PENDING_LIMIT", "0")
    with pytest.raises(RuntimeError, match="审批队列已满"):
        approvals.create("conv_full", "xiaosu", "create_ticket", {}, user_id="u_full")
