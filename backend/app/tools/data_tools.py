"""数据分析工具：run_python —— 在数据目录里直接跑 Python（pandas/matplotlib）。

为什么需要它：LocalShellBackend 的 `execute` 在 virtual_mode 下**不做** /data/ 虚拟
路径映射（命令里的 /data/ 是系统绝对路径），模型写 `pd.read_csv("/data/x.csv")`
或 `python3 /data/analysis.py` 会因路径找不到而失败。run_python 把工作目录直接
设为数据目录 workspace/data，代码里用文件名（如 sample_sales.csv）读取即可，
彻底绕开 execute 的路径坑。
"""
import os
import subprocess
import sys
import tempfile
import textwrap
from pathlib import Path

from langchain.tools import tool
from langgraph.config import get_config

from app.paths import WORKSPACE_DATA

DATA_DIR = WORKSPACE_DATA


@tool
def get_my_id() -> str:
    """【获取用户 ID】返回当前登录用户的 ID。

    用于生成按用户隔离的文件路径，如 write_file(f"/data/{get_my_id()}/dashboard.html")。"""
    try:
        return (get_config() or {}).get("configurable", {}).get("user_id", "default")
    except Exception:
        return "default"


@tool
def run_python(code: str) -> str:
    """【运行 Python 代码】在数据目录执行 Python 数据分析代码（支持 pandas/matplotlib）。

    数据分析师处理数据问题时调用此工具。工作目录是 workspace/data/，
    读取数据集直接用文件名（如 pd.read_csv("sample_sales.csv")），无需 /data/ 前缀。"""
    max_code_len = int(os.environ.get("RUN_PYTHON_MAX_CODE_LEN", "20000"))
    max_output_len = int(os.environ.get("RUN_PYTHON_MAX_OUTPUT_LEN", "6000"))
    if len(code) > max_code_len:
        return f"[错误] 代码长度超过 {max_code_len} 字符限制，请拆分为多步执行"
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    script = textwrap.dedent(code)
    fd, path = tempfile.mkstemp(suffix=".py", dir=str(DATA_DIR), prefix="_run_")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(script)
            f.flush()
            os.fsync(f.fileno())  # 关键：落盘后再跑，避免子进程读到空文件
        env = dict(os.environ)
        r = subprocess.run([sys.executable, path], cwd=str(DATA_DIR),
                           capture_output=True, text=True, timeout=120, env=env)
        out = r.stdout or ""
        if r.returncode != 0:
            out += f"\n[stderr]\n{r.stderr}\n[exit {r.returncode}]"
        return out[:max_output_len] or "(无输出)"
    except subprocess.TimeoutExpired:
        return "[错误] 代码执行超时（120s），请简化或拆分代码"
    finally:
        try:
            os.remove(path)
        except OSError:
            pass
