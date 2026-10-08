"""审批落库、过期自动拒绝和 pending 数量上限测试。"""

import sqlite3

import pytest

from app import approvals


def test_approval_persisted_and_visible_across_connections():
    rec = approvals.create("conv_ap", "xiaosu", "create_ticket",
                           {"title": "工单"}, user_id="u_ap")
    got = approvals.get(rec["approval_id"])
    assert got["status"] == "pending"
    assert got["args"] == {"title": "工单"}
    assert got["expires_at"]

    decided = approvals.decide(rec["approval_id"], "approve", decided_by="u_reviewer")
    assert decided["status"] == "approve"
    assert decided["decided_by"] == "u_reviewer"
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


def test_legacy_approval_rows_migrate_decision_actor(tmp_path, monkeypatch):
    legacy_db = tmp_path / "legacy-approvals.db"
    con = sqlite3.connect(legacy_db)
    con.executescript("""
        CREATE TABLE approvals (
            approval_id TEXT PRIMARY KEY, conversation_id TEXT NOT NULL,
            employee_id TEXT NOT NULL, user_id TEXT DEFAULT 'default',
            tenant_id TEXT DEFAULT 'default', tool TEXT, args TEXT,
            inner_thread TEXT, status TEXT DEFAULT 'pending', created_at TEXT,
            expires_at TEXT
        );
        INSERT INTO approvals(approval_id, conversation_id, employee_id, status)
        VALUES ('ap_legacy', 'conv_legacy', 'xiaoshu', 'pending');
    """)
    con.close()
    monkeypatch.setattr(approvals, "DB", legacy_db)

    record = approvals.get("ap_legacy")

    assert record["status"] == "pending"
    assert record["decided_by"] == ""
