"""可靠性修复回归测试。

覆盖：
1. doc_tools.generate_solution_doc：运行时上下文缺少 user_id 时显式报错
   （防止静默回退 "default" 把文档写进共享目录），有 user_id 时写入用户专属目录。
2. traces：写库/查询失败不再完全静默——记 warning 日志且不影响返回值
   （追踪失败绝不影响正常对话的原则不变）。
"""
import logging

import pytest

from app import traces
from app.tools import doc_tools


# ---------------------------------------------------------------------------
# doc_tools：用户隔离
# ---------------------------------------------------------------------------

def test_doc_tool_rejects_missing_user_id(tmp_path, monkeypatch):
    """无运行时上下文（user_id 缺失）→ 显式报错，不写共享 default 目录。"""
    monkeypatch.setattr(doc_tools, "DATA_DIR", tmp_path)
    with pytest.raises(RuntimeError, match="user_id"):
        doc_tools.generate_solution_doc.invoke({"customer_name": "张三"})
    assert not (tmp_path / "default").exists(), "不应写入共享 default 目录"


def test_doc_tool_writes_to_user_dir(tmp_path, monkeypatch):
    """有 user_id → 文档写入用户专属目录 workspace/data/<user_id>/。"""
    monkeypatch.setattr(doc_tools, "DATA_DIR", tmp_path)
    out = doc_tools.generate_solution_doc.invoke(
        {"customer_name": "张三"},
        config={"configurable": {"user_id": "u_test"}},
    )
    files = list((tmp_path / "u_test").glob("解决方案_张三_*.docx"))
    assert files, f"应在用户目录 u_test/ 生成文档: {out}"


# ---------------------------------------------------------------------------
# traces：失败可观测
# ---------------------------------------------------------------------------

def test_trace_db_failure_logs_and_survives(tmp_path, monkeypatch, caplog):
    """traces.db 不可写 → 记 warning 日志，函数不抛异常、返回兜底值。"""
    monkeypatch.setattr(traces, "DB", tmp_path / "no_such_dir" / "traces.db")
    with caplog.at_level(logging.WARNING, logger="app.traces"):
        rid = traces.start_run("c_x", "e1", "u1")     # 写库失败 → 不抛
        assert rid, "start_run 失败时仍应返回 run_id（对话不受影响）"
        assert traces.list_runs("c_x") == []          # 查询失败 → 空列表
    assert "start_run" in caplog.text, "写库失败应记 warning 日志"
    assert "list_runs" in caplog.text, "查询失败应记 warning 日志"
