"""数据分析工具：run_python —— 在数据目录里直接跑 Python（pandas/matplotlib）。

为什么需要它：LocalShellBackend 的 `execute` 在 virtual_mode 下**不做** /data/ 虚拟
路径映射（命令里的 /data/ 是系统绝对路径），模型写 `pd.read_csv("/data/x.csv")`
或 `python3 /data/analysis.py` 会因路径找不到而失败。run_python 把工作目录直接
设为数据目录 workspace/data，代码里用文件名（如 sample_sales.csv）读取即可，
彻底绕开 execute 的路径坑。

v0.13.0 起双路径：
- SANDBOX_ENABLED=1：代码写入沙箱 /tmp/_run_<rand>.py，沙箱内
  `cd /data && python3 /tmp/_run_<rand>.py` 执行。/data 是按用户 subPath
  挂载的本用户目录；共享数据集在 /datasets/（只读）。
- SANDBOX_ENABLED 未置 1：保持原宿主机 subprocess 路径（开发/测试环境）。
三道护栏（代码长度/输出长度/超时）始终生效；沙箱不可用时明确报错，不回退宿主机。
"""
import os
import secrets
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


def _run_python_in_sandbox(code: str, max_output_len: int) -> str:
    """沙箱内执行 Python：代码写到 /tmp/_run_<rand>.py → cd /data && python3 ..."""
    from app import sandbox_mgr
    from langgraph.config import get_config as _get_cfg
    cfg = _get_cfg() or {}
    conf = cfg.get("configurable") or {}
    thread_id = conf.get("thread_id")
    user_id = conf.get("user_id")
    if not thread_id:
        return "[错误] 沙箱模式需要会话上下文（thread_id），当前缺失"
    rand = secrets.token_hex(6)
    script_path = f"/tmp/_run_{rand}.py"
    try:
        backend = sandbox_mgr.manager.acquire(thread_id=thread_id, user_id=user_id)
    except Exception as e:
        return f"[错误] 沙箱不可用：{type(e).__name__}: {e}（不回退宿主机执行，请联系管理员）"
    try:
        backend.write(script_path, code)
        result = backend.execute(
            f"cd /data && python3 {script_path}",
            timeout=120,
        )
    except Exception as e:
        return f"[错误] 沙箱执行失败：{type(e).__name__}: {e}"
    finally:
        try:
            backend.execute(f"rm -f {script_path}", timeout=5)
        except Exception:
            pass
    # execute 返回结构：stdout/stderr/exit_code 字段或字符串，按 deepagents 协议适配
    if isinstance(result, dict):
        out = result.get("stdout") or result.get("output") or ""
        stderr = result.get("stderr") or ""
        exit_code = result.get("exit_code") or result.get("returncode") or 0
        if exit_code and int(exit_code) != 0:
            out += f"\n[stderr]\n{stderr}\n[exit {exit_code}]"
    elif isinstance(result, str):
        out = result
    else:
        out = str(result)
    return out[:max_output_len] or "(无输出)"


def _run_python_on_host(code: str, max_output_len: int) -> str:
    """宿主机 subprocess 执行（开发/测试环境兜底路径）。"""
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    script = textwrap.dedent(code)
    fd, path = tempfile.mkstemp(suffix=".py", dir=str(DATA_DIR), prefix="_run_")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(script)
            f.flush()
            os.fsync(f.fileno())
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


@tool
def run_python(code: str) -> str:
    """【运行 Python 代码】执行 Python 数据分析代码（支持 pandas/matplotlib）。

    工作目录：沙箱模式下为 /data（按用户隔离的本用户目录，可读写）；
    非沙箱模式下为 workspace/data/。共享数据集在 /datasets/（只读，
    如 pd.read_csv("/datasets/netops_alerts.csv")）。
    """
    max_code_len = int(os.environ.get("RUN_PYTHON_MAX_CODE_LEN", "20000"))
    max_output_len = int(os.environ.get("RUN_PYTHON_MAX_OUTPUT_LEN", "6000"))
    if len(code) > max_code_len:
        return f"[错误] 代码长度超过 {max_code_len} 字符限制，请拆分为多步执行"
    from app import sandbox_mgr
    if sandbox_mgr.enabled():
        return _run_python_in_sandbox(code, max_output_len)
    return _run_python_on_host(code, max_output_len)
