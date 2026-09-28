"""可重复运行的数字员工基准用例集。存储复用 traces 业务库。"""
from __future__ import annotations

import datetime
import json
import uuid

from app import db as dblayer


def _now() -> str:
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


def _conn():
    con = dblayer.connect("traces")
    con.execute("""CREATE TABLE IF NOT EXISTS evaluation_suites(
        id TEXT PRIMARY KEY, tenant_id TEXT NOT NULL, employee_id TEXT NOT NULL,
        name TEXT NOT NULL, description TEXT DEFAULT '', created_by TEXT NOT NULL,
        created_at TEXT NOT NULL, updated_at TEXT NOT NULL
    )""")
    con.execute("""CREATE TABLE IF NOT EXISTS evaluation_cases(
        id TEXT PRIMARY KEY, suite_id TEXT NOT NULL, tenant_id TEXT NOT NULL,
        prompt TEXT NOT NULL, criteria TEXT NOT NULL, tags TEXT DEFAULT '[]',
        enabled INTEGER DEFAULT 1, created_at TEXT NOT NULL, updated_at TEXT NOT NULL
    )""")
    con.execute("""CREATE TABLE IF NOT EXISTS evaluation_benchmark_runs(
        id TEXT PRIMARY KEY, suite_id TEXT NOT NULL, tenant_id TEXT NOT NULL,
        employee_id TEXT NOT NULL, config_hash TEXT NOT NULL, status TEXT NOT NULL,
        total_cases INTEGER DEFAULT 0, completed_cases INTEGER DEFAULT 0,
        passed_cases INTEGER DEFAULT 0, started_by TEXT NOT NULL,
        started_at TEXT NOT NULL, finished_at TEXT
    )""")
    con.execute("""CREATE TABLE IF NOT EXISTS evaluation_benchmark_results(
        id TEXT PRIMARY KEY, benchmark_run_id TEXT NOT NULL, case_id TEXT NOT NULL,
        trace_run_id TEXT DEFAULT '', conversation_id TEXT DEFAULT '', answer TEXT DEFAULT '',
        run_status TEXT NOT NULL, grade TEXT DEFAULT '', review_note TEXT DEFAULT '',
        duration_ms INTEGER, total_tokens INTEGER DEFAULT 0, created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL
    )""")
    con.execute("CREATE INDEX IF NOT EXISTS idx_eval_suites_tenant ON evaluation_suites(tenant_id, employee_id)")
    con.execute("CREATE INDEX IF NOT EXISTS idx_eval_cases_suite ON evaluation_cases(tenant_id, suite_id, enabled)")
    con.execute("CREATE INDEX IF NOT EXISTS idx_eval_bench_runs_suite ON evaluation_benchmark_runs(tenant_id, suite_id, started_at)")
    con.execute("CREATE INDEX IF NOT EXISTS idx_eval_bench_results_run ON evaluation_benchmark_results(benchmark_run_id)")
    con.commit()
    return con


def _case(row) -> dict:
    item = dict(row)
    try:
        item["tags"] = json.loads(item.get("tags") or "[]")
    except (TypeError, ValueError):
        item["tags"] = []
    item["enabled"] = bool(item.get("enabled"))
    return item


def list_suites(tenant_id: str, employee_id: str | None = None) -> list[dict]:
    con = _conn()
    sql = """SELECT s.*, COUNT(c.id) AS case_count FROM evaluation_suites s
             LEFT JOIN evaluation_cases c ON c.suite_id=s.id AND c.tenant_id=s.tenant_id
             WHERE s.tenant_id=?"""
    params = [tenant_id]
    if employee_id:
        sql += " AND s.employee_id=?"; params.append(employee_id)
    sql += " GROUP BY s.id ORDER BY s.updated_at DESC"
    rows = con.execute(sql, params).fetchall()
    con.close()
    return [dict(r) for r in rows]


def create_suite(tenant_id: str, employee_id: str, name: str, description: str, user_id: str) -> dict:
    suite_id, now = "es_" + uuid.uuid4().hex[:16], _now()
    con = _conn()
    con.execute("INSERT INTO evaluation_suites(id,tenant_id,employee_id,name,description,created_by,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?)",
                (suite_id, tenant_id, employee_id, name, description, user_id, now, now))
    con.commit()
    row = con.execute("SELECT * FROM evaluation_suites WHERE id=? AND tenant_id=?", (suite_id, tenant_id)).fetchone()
    con.close()
    return dict(row)


def get_suite(suite_id: str, tenant_id: str) -> dict | None:
    con = _conn()
    suite = con.execute("SELECT * FROM evaluation_suites WHERE id=? AND tenant_id=?", (suite_id, tenant_id)).fetchone()
    if not suite:
        con.close(); return None
    cases = con.execute("SELECT * FROM evaluation_cases WHERE suite_id=? AND tenant_id=? ORDER BY created_at,id",
                        (suite_id, tenant_id)).fetchall()
    con.close()
    item = dict(suite); item["cases"] = [_case(r) for r in cases]
    return item


def update_suite(suite_id: str, tenant_id: str, name: str, description: str) -> bool:
    con = _conn()
    cur = con.execute("UPDATE evaluation_suites SET name=?,description=?,updated_at=? WHERE id=? AND tenant_id=?",
                      (name, description, _now(), suite_id, tenant_id))
    con.commit(); con.close()
    return bool(cur.rowcount)


def delete_suite(suite_id: str, tenant_id: str) -> bool:
    con = _conn()
    if not con.execute("SELECT 1 FROM evaluation_suites WHERE id=? AND tenant_id=?", (suite_id, tenant_id)).fetchone():
        con.close(); return False
    con.execute("DELETE FROM evaluation_benchmark_results WHERE benchmark_run_id IN "
                "(SELECT id FROM evaluation_benchmark_runs WHERE suite_id=? AND tenant_id=?)", (suite_id, tenant_id))
    con.execute("DELETE FROM evaluation_benchmark_runs WHERE suite_id=? AND tenant_id=?", (suite_id, tenant_id))
    con.execute("DELETE FROM evaluation_cases WHERE suite_id=? AND tenant_id=?", (suite_id, tenant_id))
    con.execute("DELETE FROM evaluation_suites WHERE id=? AND tenant_id=?", (suite_id, tenant_id))
    con.commit(); con.close()
    return True


def save_case(suite_id: str, tenant_id: str, prompt: str, criteria: str,
              tags: list[str], enabled: bool, case_id: str | None = None) -> dict | None:
    con = _conn()
    if not con.execute("SELECT 1 FROM evaluation_suites WHERE id=? AND tenant_id=?", (suite_id, tenant_id)).fetchone():
        con.close(); return None
    now = _now()
    if case_id:
        cur = con.execute("UPDATE evaluation_cases SET prompt=?,criteria=?,tags=?,enabled=?,updated_at=? "
                          "WHERE id=? AND suite_id=? AND tenant_id=?",
                          (prompt, criteria, json.dumps(tags, ensure_ascii=False), int(enabled), now, case_id, suite_id, tenant_id))
        if not cur.rowcount:
            con.close(); return None
    else:
        case_id = "ec_" + uuid.uuid4().hex[:16]
        con.execute("INSERT INTO evaluation_cases(id,suite_id,tenant_id,prompt,criteria,tags,enabled,created_at,updated_at) "
                    "VALUES(?,?,?,?,?,?,?,?,?)",
                    (case_id, suite_id, tenant_id, prompt, criteria,
                     json.dumps(tags, ensure_ascii=False), int(enabled), now, now))
    con.commit()
    row = con.execute("SELECT * FROM evaluation_cases WHERE id=?", (case_id,)).fetchone()
    con.close()
    return _case(row)


def delete_case(case_id: str, tenant_id: str) -> bool:
    con = _conn()
    # Keep historical benchmark results intact; deleting the source case is soft.
    cur = con.execute("UPDATE evaluation_cases SET enabled=0,updated_at=? WHERE id=? AND tenant_id=?",
                      (_now(), case_id, tenant_id))
    con.commit(); con.close()
    return bool(cur.rowcount)


def create_benchmark_run(suite: dict, tenant_id: str, user_id: str,
                         config_hash: str, case_count: int) -> str:
    run_id = "ebr_" + uuid.uuid4().hex[:16]
    con = _conn()
    con.execute("INSERT INTO evaluation_benchmark_runs(id,suite_id,tenant_id,employee_id,config_hash,status,total_cases,started_by,started_at) "
                "VALUES(?,?,?,?,?,'queued',?,?,?)",
                (run_id, suite["id"], tenant_id, suite["employee_id"], config_hash,
                 case_count, user_id, _now()))
    con.commit(); con.close()
    return run_id


def mark_benchmark_running(run_id: str) -> None:
    con = _conn()
    con.execute("UPDATE evaluation_benchmark_runs SET status='running' WHERE id=? AND status='queued'", (run_id,))
    con.commit(); con.close()


def save_benchmark_result(benchmark_run_id: str, case_id: str, trace_run_id: str,
                          conversation_id: str, answer: str, run_status: str,
                          duration_ms: int | None, total_tokens: int = 0) -> None:
    now, result_id = _now(), "ebrres_" + uuid.uuid4().hex[:16]
    con = _conn()
    con.execute("INSERT INTO evaluation_benchmark_results(id,benchmark_run_id,case_id,trace_run_id,conversation_id,answer,run_status,duration_ms,total_tokens,created_at,updated_at) "
                "VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                (result_id, benchmark_run_id, case_id, trace_run_id, conversation_id,
                 answer[:12000], run_status, duration_ms, total_tokens, now, now))
    con.commit(); con.close()


def finish_benchmark_run(run_id: str, status: str) -> None:
    con = _conn()
    completed = con.execute("SELECT COUNT(*) AS n FROM evaluation_benchmark_results WHERE benchmark_run_id=?", (run_id,)).fetchone()["n"]
    passed = con.execute("SELECT COUNT(*) AS n FROM evaluation_benchmark_results WHERE benchmark_run_id=? AND grade='pass'", (run_id,)).fetchone()["n"]
    con.execute("UPDATE evaluation_benchmark_runs SET status=?,completed_cases=?,passed_cases=?,finished_at=? WHERE id=?",
                (status, completed, passed, _now(), run_id))
    con.commit(); con.close()


def list_benchmark_runs(suite_id: str, tenant_id: str) -> list[dict]:
    con = _conn()
    rows = con.execute("SELECT * FROM evaluation_benchmark_runs WHERE suite_id=? AND tenant_id=? ORDER BY started_at DESC LIMIT 20",
                       (suite_id, tenant_id)).fetchall()
    con.close()
    return [dict(r) for r in rows]


def get_benchmark_run(run_id: str, tenant_id: str) -> dict | None:
    con = _conn()
    run = con.execute("SELECT * FROM evaluation_benchmark_runs WHERE id=? AND tenant_id=?", (run_id, tenant_id)).fetchone()
    if not run:
        con.close(); return None
    rows = con.execute("SELECT r.*,c.prompt,c.criteria,c.tags FROM evaluation_benchmark_results r "
                       "JOIN evaluation_cases c ON c.id=r.case_id WHERE r.benchmark_run_id=? ORDER BY r.created_at,r.id",
                       (run_id,)).fetchall()
    con.close()
    result = dict(run); result["results"] = []
    for row in rows:
        item = dict(row)
        try: item["tags"] = json.loads(item.get("tags") or "[]")
        except (TypeError, ValueError): item["tags"] = []
        result["results"].append(item)
    return result


def grade_benchmark_result(result_id: str, run_id: str, tenant_id: str,
                           grade: str, note: str = "") -> bool:
    con = _conn()
    cur = con.execute("UPDATE evaluation_benchmark_results SET grade=?,review_note=?,updated_at=? "
                      "WHERE id=? AND benchmark_run_id=? AND benchmark_run_id IN "
                      "(SELECT id FROM evaluation_benchmark_runs WHERE tenant_id=?)",
                      (grade, note[:1000], _now(), result_id, run_id, tenant_id))
    con.commit(); con.close()
    if cur.rowcount:
        con = _conn()
        passed = con.execute("SELECT COUNT(*) AS n FROM evaluation_benchmark_results WHERE benchmark_run_id=? AND grade='pass'",
                             (run_id,)).fetchone()["n"]
        con.execute("UPDATE evaluation_benchmark_runs SET passed_cases=? WHERE id=?", (passed, run_id))
        con.commit(); con.close()
    return bool(cur.rowcount)


def suite_for_run(suite_id: str, tenant_id: str) -> dict | None:
    suite = get_suite(suite_id, tenant_id)
    if not suite:
        return None
    suite["cases"] = [c for c in suite["cases"] if c["enabled"]]
    return suite
