"""#17/#19 recover_conversations 启动恢复：条数上限 + 员工归属不再靠 blob 猜。"""

import asyncio
import json
import sqlite3

from app import conversations, runtime, streaming, traces


def _demo(tmp_path) -> str:
    dbfile = tmp_path / "checkpoints.db"
    con = sqlite3.connect(str(dbfile))
    con.execute("CREATE TABLE checkpoints (thread_id TEXT, checkpoint BLOB, metadata BLOB)")
    con.close()
    return str(dbfile)


def _fake_agent():
    async def get_agent(*args, **kwargs):
        class FakeAgent:
            async def aget_state_history(self, *args, **kwargs):
                if False:
                    yield
        return FakeAgent(), []
    return get_agent


def test_recover_conversations_respects_limit(tmp_path, monkeypatch):
    dbfile = _demo(tmp_path)
    con = sqlite3.connect(dbfile)
    for i in range(3):
        con.execute(
            "INSERT INTO checkpoints (thread_id, checkpoint, metadata) VALUES (?, ?, ?)",
            (f"c_limit_{i}", None, None))
    con.commit()
    con.close()

    created = []
    monkeypatch.setattr(streaming, "db_path", lambda name: dbfile)
    monkeypatch.setattr(runtime, "discover_employees",
                        lambda: [{"id": "xiaosu", "skills": []}])
    monkeypatch.setattr(runtime, "get_agent", _fake_agent())
    monkeypatch.setattr(traces, "employee_of_conv", lambda cid: None)
    monkeypatch.setattr(conversations, "all_conv_ids", lambda: set())
    monkeypatch.setattr(conversations, "create",
                        lambda cid, emp, **kw: created.append((cid, emp)))

    asyncio.run(streaming.recover_conversations(limit=2))

    assert len(created) == 2
    assert all(cid.startswith("c_limit_") for cid, _ in created)
    assert all(emp == "xiaosu" for _, emp in created)


def test_recover_uses_metadata_employee_then_trace_fallback(tmp_path, monkeypatch):
    dbfile = _demo(tmp_path)
    con = sqlite3.connect(dbfile)
    con.execute(
        "INSERT INTO checkpoints (thread_id, checkpoint, metadata) VALUES (?, ?, ?)",
        ("c_meta", None, json.dumps({"employee_id": "hrbp"})))
    con.execute(
        "INSERT INTO checkpoints (thread_id, checkpoint, metadata) VALUES (?, ?, ?)",
        ("c_trace", None, None))
    con.commit()
    con.close()

    created = {}
    monkeypatch.setattr(streaming, "db_path", lambda name: dbfile)
    monkeypatch.setattr(runtime, "discover_employees",
                        lambda: [{"id": "xiaosu", "skills": []}, {"id": "hrbp", "skills": []}])
    monkeypatch.setattr(runtime, "get_agent", _fake_agent())
    monkeypatch.setattr(traces, "employee_of_conv",
                        lambda cid: "xiaoshu" if cid == "c_trace" else None)
    monkeypatch.setattr(conversations, "all_conv_ids", lambda: set())
    monkeypatch.setattr(conversations, "create",
                        lambda cid, emp, **kw: created.update({cid: emp}))

    asyncio.run(streaming.recover_conversations(limit=10))

    assert created == {"c_meta": "hrbp", "c_trace": "xiaoshu"}
