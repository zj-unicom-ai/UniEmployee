"""独立于 Trace 预览的完整事件记录；不把认证配置写入解题日志。"""

import hashlib
import json
import os
import threading
import time
from datetime import datetime, timezone

from langchain_core.callbacks import AsyncCallbackHandler

from app.paths import DATA_DIR


def encode(value):
    return json.dumps(value, ensure_ascii=False, default=lambda obj:
                      obj.model_dump(mode="json", serialize_as_any=True)
                      if hasattr(obj, "model_dump") else str(obj))


def record_dir(tenant_id, user_id, conv_id):
    keys = [hashlib.sha256(str(value).encode()).hexdigest() for value in (tenant_id, user_id, conv_id)]
    path = DATA_DIR / "security-records"
    for key in keys:
        path /= key
    if path.resolve() != path.absolute():
        raise ValueError("安全任务记录目录不能包含符号链接")
    return path


class SecurityRecorder(AsyncCallbackHandler):
    """保存模型公开输入输出和工具调用；写入失败时中止执行，避免无记录求解。"""

    raise_error = True
    run_inline = True

    def __init__(self, tenant_id, user_id, conv_id, run_id, input_):
        directory = record_dir(tenant_id, user_id, conv_id)
        directory.mkdir(parents=True, exist_ok=True)
        self.path = directory / f"{time.time_ns()}.jsonl"
        self.run_id = run_id
        self.lock = threading.Lock()
        self.seq = 0
        self.failed = False
        self.write("run_started", input=input_, conversation_id=conv_id)

    def write(self, event, **data):
        with self.lock:
            if self.failed:
                raise OSError("完整记录曾写入失败，本次运行不能继续")
            self.seq += 1
            entry = {"seq": self.seq, "run_id": self.run_id,
                     "time": datetime.now(timezone.utc).isoformat(), "event": event, **data}
            # 一次追加一条完整 JSON；不裁剪消息、参数或工具结果。
            try:
                with self.path.open("a", encoding="utf-8") as output:
                    output.write(encode(entry) + "\n")
                    output.flush()
                    os.fsync(output.fileno())
            except Exception:
                self.failed = True
                raise

    async def on_chat_model_start(self, serialized, messages, *, run_id, parent_run_id=None, **kwargs):
        self.write("model_started", call_id=str(run_id), parent_id=str(parent_run_id or ""),
                   model=(kwargs.get("metadata") or {}).get("ls_model_name", ""), messages=messages)

    async def on_llm_end(self, response, *, run_id, **kwargs):
        self.write("model_finished", call_id=str(run_id), generations=response.generations,
                   usage=response.llm_output)

    async def on_llm_error(self, error, *, run_id, **kwargs):
        self.write("model_error", call_id=str(run_id), error=str(error))

    async def on_tool_start(self, serialized, input_str, *, run_id, parent_run_id=None, inputs=None, **kwargs):
        self.write("tool_started", call_id=str(run_id), parent_id=str(parent_run_id or ""),
                   tool=(serialized or {}).get("name", ""),
                   tool_call_id=kwargs.get("tool_call_id", ""),
                   arguments=inputs if inputs is not None else input_str)

    async def on_tool_end(self, output, *, run_id, **kwargs):
        self.write("tool_finished", call_id=str(run_id), result=output)

    async def on_tool_error(self, error, *, run_id, **kwargs):
        self.write("tool_error", call_id=str(run_id), error=str(error))
