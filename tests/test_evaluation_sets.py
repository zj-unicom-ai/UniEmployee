import sqlite3
import asyncio

from app import evaluation_sets


def test_evaluation_suite_cases_and_benchmark_history(tmp_path, monkeypatch):
    db_file = tmp_path / "eval-traces.db"

    def connect(_name):
        con = sqlite3.connect(str(db_file))
        con.row_factory = sqlite3.Row
        return con

    monkeypatch.setattr(evaluation_sets.dblayer, "connect", connect)

    suite = evaluation_sets.create_suite("tenant-a", "xiaoshu", "月报分析", "检查计算和结论", "admin")
    assert evaluation_sets.list_suites("tenant-a")[0]["case_count"] == 0
    assert evaluation_sets.get_suite(suite["id"], "tenant-b") is None

    case = evaluation_sets.save_case(suite["id"], "tenant-a", "分析一月销售变化", "数字正确并给出原因", ["数据分析"], True)
    assert case["enabled"] is True
    assert case["tags"] == ["数据分析"]

    run_id = evaluation_sets.create_benchmark_run(suite, "tenant-a", "admin", "abc123", 1)
    evaluation_sets.mark_benchmark_running(run_id)
    evaluation_sets.save_benchmark_result(run_id, case["id"], "r_123", "c_eval_123", "一月销售增长 10%", "completed", 1200, 45)
    evaluation_sets.finish_benchmark_run(run_id, "completed")
    result = evaluation_sets.get_benchmark_run(run_id, "tenant-a")
    assert result["status"] == "completed"
    assert result["results"][0]["prompt"] == "分析一月销售变化"
    assert result["results"][0]["answer"] == "一月销售增长 10%"

    result_id = result["results"][0]["id"]
    assert evaluation_sets.grade_benchmark_result(result_id, run_id, "tenant-a", "pass", "抽样核对通过")
    assert evaluation_sets.get_benchmark_run(run_id, "tenant-a")["passed_cases"] == 1
    assert evaluation_sets.get_benchmark_run(run_id, "tenant-b") is None

    assert evaluation_sets.delete_case(case["id"], "tenant-a")
    assert evaluation_sets.get_suite(suite["id"], "tenant-a")["cases"][0]["enabled"] is False


def test_benchmark_runner_records_streamed_answer_without_model_call(tmp_path, monkeypatch):
    from app import conversations, traces, streaming
    from app.routes import admin as admin_routes

    eval_db = tmp_path / "runner-eval.db"
    monkeypatch.setattr(evaluation_sets.dblayer, "connect", lambda _name: _sqlite_conn(eval_db))
    monkeypatch.setattr(conversations, "DB", tmp_path / "runner-conversations.db")
    monkeypatch.setattr(traces, "DB", tmp_path / "runner-traces.db")

    suite = evaluation_sets.create_suite("tenant-a", "xiaoshu", "冒烟", "验证评测结果归档", "admin")
    case = evaluation_sets.save_case(suite["id"], "tenant-a", "演示问题", "回答包含演示", [], True)
    suite["cases"] = [case]
    run_id = evaluation_sets.create_benchmark_run(suite, "tenant-a", "admin", "config-v1", 1)

    async def fake_stream(*args, **kwargs):
        yield 'data: {"type":"token","content":"演示回答"}\n\n'
        yield 'data: {"type":"message_end","run_id":"r_fake"}\n\n'

    monkeypatch.setattr(streaming, "_stream_run", fake_stream)
    asyncio.run(admin_routes._execute_evaluation_benchmark(
        run_id, suite, {"user_id": "admin", "tenant_id": "tenant-a", "role": "admin"}
    ))
    result = evaluation_sets.get_benchmark_run(run_id, "tenant-a")
    assert result["status"] == "completed"
    assert result["completed_cases"] == 1
    assert result["results"][0]["answer"] == "演示回答"
    assert result["results"][0]["trace_run_id"] == "r_fake"


def _sqlite_conn(path):
    con = sqlite3.connect(str(path))
    con.row_factory = sqlite3.Row
    return con
