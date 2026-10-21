"""同一小网员工的可选赛事运行配置，默认不改变日常运营能力。"""

import os
from urllib.parse import urlsplit

from langchain.chat_models import init_chat_model

TOOL_NAMES = ["run_security_python", "save_security_answer"]
SKILL_NAME = "security-practical"


def enabled(employee_id):
    return employee_id == "net-ops" and os.environ.get("NETOPS_COMPETITION_MODE") == "1"


def official_model():
    model = os.environ.get("COMPETITION_MODEL", "").strip()
    url = os.environ.get("COMPETITION_BASE_URL", "").strip()
    key = os.environ.get("COMPETITION_API_KEY", "").strip()
    parsed = urlsplit(url)
    if not model or not key or parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise ValueError("请完整配置 COMPETITION_MODEL / BASE_URL / API_KEY；禁止回退其他模型")
    if parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise ValueError("赛事接口地址不能包含认证信息、查询参数或片段")
    return init_chat_model(model, model_provider="openai", base_url=url, api_key=key,
                           use_responses_api=False, timeout=120, max_retries=1)


def apply(spec):
    if not enabled(spec.id):
        return spec
    from app.sandbox_mgr import enabled as sandbox_enabled
    if not sandbox_enabled():
        raise ValueError("小网赛事运行需要启用并验证 OpenSandbox，禁止回退宿主机")
    return spec.model_copy(update={
        "tools": TOOL_NAMES + ["get_current_time"], "skills": [SKILL_NAME],
        "kbs": [], "sops": [], "sop_text": "", "mcp_servers": {}, "connectors": [],
        "subagents": [], "subagent_policy": "不委派任务；只分析本题附件及明确授权的目标。",
        "backend": "sandbox", "interrupt_on": {},
    })


def sandbox_options(thread_id):
    from app import conversations
    meta = conversations.get(thread_id) or {}
    if not enabled(meta.get("employee_id")):
        return {}
    from opensandbox.models.sandboxes import NetworkPolicy
    # 首版只支持离线附件分析；目标交互需单独配置并验证授权范围。
    return {"network_policy": NetworkPolicy(default_action="deny", egress=[])}
