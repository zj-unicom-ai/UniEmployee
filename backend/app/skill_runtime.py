"""业务技能快照、线程重载和按员工授权的技能工具绑定。"""
import hashlib
import json
import logging
import re
from pathlib import Path
from typing import Annotated, NotRequired

import yaml
from deepagents.middleware import SkillsMiddleware
from deepagents.middleware.skills import SkillsState
from langchain_core.messages import SystemMessage
from langchain.agents.middleware.types import PrivateStateAttr

from app import catalog
from app.paths import ROOT as BACKEND_ROOT


def skill_snapshot(employee_id, user_id=None):
    """以 catalog 当前有效配置为准；正文与元数据共同参与版本计算。"""
    result = []
    for skill_id, directory in catalog.get_skill_dirs_for_employee(employee_id, user_id).items():
        path = Path(directory)
        if not path.is_absolute():
            path = BACKEND_ROOT / path
        source = path / "SKILL.md"
        if not source.is_file():
            continue
        text = source.read_text(encoding="utf-8")
        frontmatter = {}
        if text.startswith("---\n"):
            parts = text.split("---", 2)
            if len(parts) == 3:
                try:
                    frontmatter = yaml.safe_load(parts[1]) or {}
                except yaml.YAMLError:
                    logging.getLogger(__name__).warning("跳过格式错误的技能: %s", skill_id)
                    continue
        if not isinstance(frontmatter, dict):
            frontmatter = {}
        if not isinstance(frontmatter.get("name"), str) or not frontmatter.get("name"):
            continue
        if not isinstance(frontmatter.get("description"), str) or not frontmatter.get("description"):
            continue
        metadata = frontmatter.get("metadata") or {}
        include = metadata.get("include_tools", []) if isinstance(metadata, dict) else []
        include = include.split() if isinstance(include, str) else []
        heading = re.search(r"^#\s+(.+)$", text, re.MULTILINE)
        result.append({"title": heading.group(1) if heading else skill_id,
                       "id": skill_id, "name": frontmatter["name"],
                       "description": str(frontmatter.get("description") or ""),
                       "text": text, "include_tools": [x for x in include if isinstance(x, str)]})
    return sorted(result, key=lambda s: s["id"])


def snapshot_revision(snapshot):
    return hashlib.sha256(json.dumps(snapshot, ensure_ascii=False, sort_keys=True).encode()).hexdigest()


def binding_signature(employee_id, user_id=None):
    return tuple((s["id"], s["name"], tuple(s["include_tools"]))
                 for s in skill_snapshot(employee_id, user_id))


def split_skill_tools(tools, snapshot, approval_tools=()):
    """只绑定已通过 _assemble_tools 授权的工具；全局工具始终可用。"""
    from app.compiler import GLOBAL_TOOL_NAMES
    names = {name for s in snapshot for name in s["include_tools"]} - set(GLOBAL_TOOL_NAMES)
    # 审批工具继续走现有静态 HITL 拦截路径，避免动态工具绕过审批。
    names -= {"create_ticket", "start_refund", "publish_briefing", *approval_tools}
    return ([t for t in tools if t.name not in names],
            [t for t in tools if t.name in names])


def validate_pinned_skills(employee_id, user_id, names):
    available = {s["name"] for s in skill_snapshot(employee_id, user_id)}
    unique = list(dict.fromkeys(names))
    if any(name not in available for name in unique):
        raise ValueError("所选技能未分配给当前员工或已不可用")
    return unique


class BusinessSkillsState(SkillsState):
    business_skills_revision: NotRequired[str]
    business_skill_routing: NotRequired[Annotated[str, PrivateStateAttr]]


class BusinessSkillsMiddleware(SkillsMiddleware):
    """原位替换官方技能中间件；版本变化时重载，路由使用当前正文。"""
    state_schema = BusinessSkillsState

    @property
    def name(self):
        return "SkillsMiddleware"

    def __init__(self, *, employee_id, user_id, backend, tools):
        super().__init__(backend=backend, sources=["/skills/"], tools=tools)
        self.employee_id = employee_id
        self.user_id = user_id

    def _reload_state(self, state):
        snapshot = skill_snapshot(self.employee_id, self.user_id)
        revision = snapshot_revision(snapshot)
        if state.get("business_skills_revision") != revision:
            state = {**state, "skills_metadata": None}
        return state, revision, snapshot

    def before_agent(self, state, runtime, config):
        current, revision, snapshot = self._reload_state(state)
        update = super().before_agent(current, runtime, config)
        return self._update_routing(current, update, revision, snapshot)

    async def abefore_agent(self, state, runtime, config):
        current, revision, snapshot = self._reload_state(state)
        update = await super().abefore_agent(current, runtime, config)
        return self._update_routing(current, update, revision, snapshot)

    def _update_routing(self, current, update, revision, snapshot):
        from app.compiler import _build_skill_routing, _extract_skill_triggers
        loaded = {s["name"] for s in (update or current).get("skills_metadata") or []}
        summaries = [{**s, "triggers": _extract_skill_triggers(s["text"])}
                     for s in snapshot if s["name"] in loaded]
        return {**(update or {}), "business_skills_revision": revision,
                "business_skill_routing": _build_skill_routing(summaries)}

    def modify_request(self, request):
        request = super().modify_request(request)
        # 路由在本次运行开始时快照化，避免模型循环内重复读盘或混入下一版规程。
        routing = request.state.get("business_skill_routing", "")
        if not routing:
            return request
        blocks = list(request.system_message.content_blocks) if request.system_message else []
        blocks.append({"type": "text", "text": routing})
        return request.override(system_message=SystemMessage(content=blocks))
