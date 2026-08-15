"""EmployeeSpec：员工的"岗位说明书"，yaml 加载后编译成 deepagents 实例。"""
import os
import re
import yaml
from pydantic import BaseModel


class EmployeeSpec(BaseModel):
    id: str
    name: str
    role: str = ""
    model: str
    persona: str
    skills: list[str] = []
    tools: list[str] = []
    mcp_servers: dict = {}
    interrupt_on: dict = {}
    backend: str = "state"  # 默认 StateBackend；分析师类员工用 "local_shell" 拿到 execute/read_file/ls/write_file
    sop: str = ""  # SOP 说明：追加到 system_prompt，并用于"加载 SOP"阶段展示
    # ---- 目录库（catalog.db）驱动的新字段 ----
    kbs: list[str] = []          # 选中的知识库 id
    sops: list[str] = []         # 选中的 SOP id（SOP 内容经 /sops/ Store 运行时读取）
    sop_text: str = ""           # 拼接后的 SOP 文档（拼进 system_prompt）
    connectors: list[str] = []   # 选中的 MCP 连接器 id
    skill_dirs: dict = {}        # skill_id -> 目录路径（相对 ROOT 或绝对路径，支持外部技能）
    subagents: list[dict] = []   # 子代理配置（name/description/system_prompt/tools/model/permissions）
    subagent_policy: str = ""    # 委派策略：追加到 system_prompt 的硬性规则，可经 catalog 配置


_ENV_RE = re.compile(r"\$\{(\w+)\}")


def _substitute(value):
    if isinstance(value, str):
        return _ENV_RE.sub(lambda m: os.environ.get(m.group(1), m.group(0)), value)
    if isinstance(value, dict):
        return {k: _substitute(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_substitute(v) for v in value]
    return value


def load_spec(path: str) -> EmployeeSpec:
    with open(path, encoding="utf-8") as f:
        data = _substitute(yaml.safe_load(f))
    return EmployeeSpec(**data)
