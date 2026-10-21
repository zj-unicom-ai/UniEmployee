"""安全实操工具：执行代码仅使用已有隔离沙箱，不新增宿主机执行通道。"""

import uuid
import logging
from pathlib import Path

from langchain.tools import tool
from langgraph.config import get_config

from app.paths import WORKSPACE_DATA
from .records import encode


def context():
    config = (get_config() or {}).get("configurable") or {}
    user, conv = config.get("user_id"), config.get("thread_id")
    if config.get("employee_id") != "net-ops" or not user or not conv:
        raise ValueError("安全实操工具需要小网会话和已验证用户上下文")
    if any(Path(value).name != value or value in {".", ".."} for value in (user, conv)):
        raise ValueError("无效的会话或用户标识")
    return user, conv


@tool
def run_security_python(code: str) -> str:
    """【安全实操 Python】在已启用的隔离沙箱中执行分析代码，120 秒超时。

    沙箱 /data 是当前用户目录，附件用 /data/uploads/<会话ID>/<文件名>。
    完整代码与执行结果保存到会话产物；返回结果预览及文件路径。
    仅执行本题所需操作，不安装依赖或访问未授权网络目标。
    """
    user, conv = context()
    from app import sandbox_mgr
    if not sandbox_mgr.enabled():
        raise ValueError("安全代码执行需要 OpenSandbox；不会回退宿主机")
    if len(code) > 50000:
        raise ValueError("单次代码超过 50000 字符，请拆分执行")
    backend = sandbox_mgr.manager.acquire(thread_id=conv, user_id=user)
    token = uuid.uuid4().hex
    directory = WORKSPACE_DATA / user / "security-tasks" / conv
    directory.mkdir(parents=True, exist_ok=True)
    if directory.resolve() != directory.absolute():
        raise ValueError("安全任务产物目录不能包含符号链接")
    (directory / f"{token}.py").write_text(code, encoding="utf-8")
    script = f"/tmp/ue-security-{token}.py"
    written = backend.write(script, code)
    if getattr(written, "error", None):
        raise RuntimeError("无法写入沙箱分析脚本")
    try:
        result = backend.execute(f"cd /data && python3 {script}", timeout=120)
    finally:
        try:
            backend.execute(f"rm -f {script}", timeout=5)
        except Exception:
            logging.getLogger(__name__).warning("沙箱临时脚本清理失败", exc_info=True)
    payload = encode(result)
    output = directory / f"{token}.result.json"
    output.write_text(payload, encoding="utf-8")
    return encode({"result_preview": payload[:6000], "truncated": len(payload) > 6000,
                   "full_result": "/data/" + output.relative_to(WORKSPACE_DATA).as_posix()})


@tool
def save_security_answer(question_id: str, answer: str, evidence: list[str]) -> str:
    """【保存实操答案】保存本题答案/Flag/提交文件说明及证据；不会替选手提交平台。

    question_id 为题号，answer 为最终结论，evidence 为文件行号、工具结果或产物路径。
    每次保存创建独立版本。需要修订时重新调用，保留旧版以供审计。
    """
    user, conv = context()
    if not question_id.strip() or len(question_id) > 100:
        raise ValueError("题号不能为空且须少于 100 字符")
    directory = WORKSPACE_DATA / user / "security-tasks" / conv
    directory.mkdir(parents=True, exist_ok=True)
    if directory.resolve() != directory.absolute():
        raise ValueError("安全任务产物目录不能包含符号链接")
    target = directory / f"answer-{uuid.uuid4().hex}.json"
    target.write_text(encode({"question_id": question_id, "answer": answer,
                              "evidence": evidence}) + "\n", encoding="utf-8")
    return "/data/" + target.relative_to(WORKSPACE_DATA).as_posix()


TOOLS = [run_security_python, save_security_answer]
