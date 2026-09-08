"""编译层内置工具护栏回归测试。

覆盖 guard 模块之下的 compiler 层行为：
  1. _make_denied_tool() —— 「拒绝执行」替身的 name/desc/schema/raise
  2. _assemble_tools()   —— 按角色 + 白名单装配工具：
       - admin 角色一律不裁剪
       - 非 admin 命中 admin_only_tools → 替身
       - 非 admin 命中普通工具 → 真实工具
       - 空白名单 = 不限制
  3. 通用工具无条件注入（GLOBAL_TOOL_NAMES）
  4. 声明未注册工具静默跳过
  5. 闭包工具（kb_search / ontology_*）声明即注入

与 test_guard.py 互补：后者测 guard 模块层（settings/sensitive/logs），
本文件测 compiler 装配层（替身构造 + 角色 + 工具集组合）。

注：AGENTS.md 提及的 FilesystemMiddleware / FS_TOOLS / fs_tools 字段 /
GP 子代理继承 / read_file 强制必选，截至 v0.11.0 尚未实现，故本文件
不覆盖这些规划特性，仅测已落地行为。
"""
import asyncio
import inspect

import pytest
from pydantic import BaseModel
from langchain_core.tools import tool as langchain_tool

from app import guard
from app.compiler import _assemble_tools, _make_denied_tool, ALL_LOCAL_TOOLS, GLOBAL_TOOL_NAMES
from app.spec import EmployeeSpec


# ---------- 测试用替身工具 ----------

class _FakeSchema(BaseModel):
    """替身测试用的合法 args_schema。"""
    x: int = 0


def _fake_tool(name="fake_tool", desc="测试用工具", schema=None):
    """构造一个最小可用的 LangChain 工具，供替身测试使用。"""
    @langchain_tool(name, description=desc, args_schema=schema)
    def _t(**kwargs):
        return "ok"
    return _t


# ---------- _make_denied_tool 替身构造 ----------

def test_denied_tool_preserves_name_and_schema():
    """替身必须保留原工具名和 args_schema，否则模型 schema 对不上。"""
    orig = _fake_tool("preserve_me", desc="原描述", schema=_FakeSchema)
    denied = _make_denied_tool(orig)
    assert denied.name == "preserve_me"
    # args_schema 原样继承
    assert getattr(denied, "args_schema", None) is _FakeSchema


def test_denied_tool_description_marks_no_permission():
    """description 必须含「无权限」标识，让模型可读到权限提示。"""
    orig = _fake_tool("some_tool", desc="这是一个工具")
    denied = _make_denied_tool(orig)
    assert "无权限" in (getattr(denied, "description", "") or "")


def test_denied_tool_raises_permission_error():
    """执行替身必须抛 PermissionError，真实逻辑不执行。"""
    orig = _fake_tool("do_not_run")
    denied = _make_denied_tool(orig)
    with pytest.raises(PermissionError):
        denied.invoke({})


# ---------- _assemble_tools 角色与白名单 ----------

def _spec(tools, **kw):
    """构造最小 EmployeeSpec（mcp_servers 留空避免拉起 MCP）。"""
    return EmployeeSpec(
        id=kw.get("id", "t_emp"),
        name=kw.get("name", "测试员工"),
        model=kw.get("model", "gpt-4o-mini"),
        persona=kw.get("persona", ""),
        tools=tools,
        mcp_servers={},
    )


def _mock_role(monkeypatch, role):
    """让 _assemble_tools 内部 _users.get_user 返回指定角色。"""
    from app.catalog import users as _users
    monkeypatch.setattr(_users, "get_user",
                        lambda uid: {"id": uid, "role": role} if uid else None)


def test_assemble_admin_gets_real_tools(monkeypatch):
    """admin 角色拿到的都是真实工具，不含替身。"""
    guard.set_setting("admin_only_tools", "create_ticket")
    _mock_role(monkeypatch, "admin")
    spec = _spec(["create_ticket"])
    tools, _ = asyncio.run(_assemble_tools(spec, user_id="u_admin"))
    t = next(x for x in tools if x.name == "create_ticket")
    # 不是替身：替身 description 含「无权限」
    assert "无权限" not in (getattr(t, "description", "") or "")


def test_assemble_non_admin_admin_only_tool_wrapped(monkeypatch):
    """非 admin 命中 admin_only 工具 → 替身（描述含「无权限」标识）。

    注：不在此处直接 invoke 真实工具替身，因为 create_ticket 自带必填
    参数（category/urgency/summary），invoke({}) 会先触发 pydantic 校验
    失败而非 PermissionError。raise 行为由 test_denied_tool_raises_permission_error
    用无参 fake_tool 单独覆盖。
    """
    guard.set_setting("admin_only_tools", "create_ticket")
    _mock_role(monkeypatch, "user")
    spec = _spec(["create_ticket"])
    tools, _ = asyncio.run(_assemble_tools(spec, user_id="u_user"))
    t = next(x for x in tools if x.name == "create_ticket")
    assert "无权限" in (getattr(t, "description", "") or "")


def test_assemble_non_admin_normal_tool_real(monkeypatch):
    """非 admin 拿普通工具 → 真实工具（不被白名单拦）。"""
    guard.set_setting("admin_only_tools", "create_ticket")
    _mock_role(monkeypatch, "user")
    spec = _spec(["get_my_id"])
    tools, _ = asyncio.run(_assemble_tools(spec, user_id="u_user"))
    t = next(x for x in tools if x.name == "get_my_id")
    assert "无权限" not in (getattr(t, "description", "") or "")


def test_assemble_non_admin_empty_whitelist_no_wrapping(monkeypatch):
    """空白名单 = 不限制，非 admin 也拿真实工具。"""
    guard.set_setting("admin_only_tools", "")
    _mock_role(monkeypatch, "user")
    spec = _spec(["create_ticket"])
    tools, _ = asyncio.run(_assemble_tools(spec, user_id="u_user"))
    t = next(x for x in tools if x.name == "create_ticket")
    assert "无权限" not in (getattr(t, "description", "") or "")


def test_assemble_no_user_id_defaults_admin(monkeypatch):
    """user_id=None 时默认按 admin 处理（无越权风险）。"""
    guard.set_setting("admin_only_tools", "create_ticket")
    spec = _spec(["create_ticket"])
    tools, _ = asyncio.run(_assemble_tools(spec, user_id=None))
    t = next(x for x in tools if x.name == "create_ticket")
    assert "无权限" not in (getattr(t, "description", "") or "")


# ---------- 通用工具注入 ----------

def test_assemble_global_tools_always_injected():
    """GLOBAL_TOOL_NAMES 无条件注入，即使 spec.tools 不声明。"""
    guard.set_setting("admin_only_tools", "")
    spec = _spec([])  # 空工具列表
    tools, _ = asyncio.run(_assemble_tools(spec, user_id=None))
    names = {t.name for t in tools}
    for g in GLOBAL_TOOL_NAMES:
        assert g in names, f"通用工具 {g} 应被无条件注入"


def test_assemble_global_tools_not_duplicated():
    """spec.tools 已声明通用工具，去重避免重复。"""
    guard.set_setting("admin_only_tools", "")
    spec = _spec(["get_current_time"])
    tools, _ = asyncio.run(_assemble_tools(spec, user_id=None))
    count = sum(1 for t in tools if t.name == "get_current_time")
    assert count == 1


# ---------- 未注册工具 ----------

def test_assemble_unknown_tool_silently_skipped():
    """spec.tools 中声明的工具名不在 ALL_LOCAL_TOOLS → 静默跳过。"""
    guard.set_setting("admin_only_tools", "")
    spec = _spec(["nonexistent_tool_xyz"])
    tools, _ = asyncio.run(_assemble_tools(spec, user_id=None))
    names = {t.name for t in tools}
    assert "nonexistent_tool_xyz" not in names


# ---------- 闭包工具注入 ----------

def test_assemble_kb_search_closure_injected(monkeypatch):
    """声明 kb_search → 注入闭包工具（运行时读 catalog）。"""
    guard.set_setting("admin_only_tools", "")
    spec = _spec(["kb_search"], id="kb_emp")
    tools, _ = asyncio.run(_assemble_tools(spec, user_id=None))
    assert any(t.name == "kb_search" for t in tools)


def test_assemble_ontology_tools_injected(monkeypatch):
    """声明 ontology_find_entities 或 ontology_query_relations → 两个都注入。"""
    guard.set_setting("admin_only_tools", "")
    spec = _spec(["ontology_find_entities"], id="ont_emp")
    tools, _ = asyncio.run(_assemble_tools(spec, user_id=None))
    names = {t.name for t in tools}
    assert "ontology_find_entities" in names
    assert "ontology_query_relations" in names


# ---------- ALL_LOCAL_TOOLS 注册表完整性 ----------

def test_all_local_tools_values_are_tool_like():
    """ALL_LOCAL_TOOLS 所有值必须是可调用或 BaseTool 对象。"""
    assert len(ALL_LOCAL_TOOLS) > 0
    for name, t in ALL_LOCAL_TOOLS.items():
        assert callable(t) or hasattr(t, "invoke"), f"{name} 不是工具对象"


def test_global_tool_names_subset_of_all_local_tools():
    """GLOBAL_TOOL_NAMES 必须是 ALL_LOCAL_TOOLS 的子集，否则注入分支落空。"""
    for g in GLOBAL_TOOL_NAMES:
        assert g in ALL_LOCAL_TOOLS, f"通用工具 {g} 未在 ALL_LOCAL_TOOLS 注册"
