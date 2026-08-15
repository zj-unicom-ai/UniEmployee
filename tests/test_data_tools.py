"""run_python 工具资源限制测试。

锁定 #50 的一部分：代码长度上限、输出截断上限、超时友好提示。
"""
import os

from app.tools.data_tools import run_python


def test_run_python_rejects_oversized_code(monkeypatch):
    monkeypatch.setenv("RUN_PYTHON_MAX_CODE_LEN", "10")
    out = run_python.invoke({"code": "print('this-is-way-too-long')"})
    assert "代码长度超过" in out
    assert "10" in out


def test_run_python_truncates_output(monkeypatch):
    monkeypatch.setenv("RUN_PYTHON_MAX_OUTPUT_LEN", "20")
    out = run_python.invoke({"code": "print('a' * 1000)"})
    assert "\nrow" not in out or "a" in out
    assert len(out) <= 100


def test_run_python_valid_small_code(monkeypatch):
    monkeypatch.delenv("RUN_PYTHON_MAX_CODE_LEN", raising=False)
    monkeypatch.delenv("RUN_PYTHON_MAX_OUTPUT_LEN", raising=False)
    out = run_python.invoke({"code": "print(1 + 1)"})
    assert "2" in out
