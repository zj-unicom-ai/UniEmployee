"""通用时间工具 get_current_time 的测试。

覆盖三点：
  1. 工具本身能返回真实当前日期（东八区）；
  2. 已登记进 ALL_LOCAL_TOOLS 注册表；
  3. 编译期对所有员工无条件注入（即使 tools=[] 也有，且不重复）。
"""
import asyncio
from datetime import datetime
from zoneinfo import ZoneInfo

from app.compiler import ALL_LOCAL_TOOLS, _assemble_tools
from app.spec import EmployeeSpec
from app.tools.time_tools import get_current_time


def _make_spec(tools=None):
    return EmployeeSpec(
        id="t_time",
        name="时间测试员工",
        role="tester",
        model="openai:deepseek-chat",
        persona="你是一个用于测试时间工具的员工。",
        tools=tools or [],
    )


def test_get_current_time_returns_today():
    out = get_current_time.invoke({})
    assert isinstance(out, str)
    assert "当前时间" in out
    assert "星期" in out
    # 今天的东八区日期应出现在返回中（避免模型凭记忆乱答）
    today = datetime.now(ZoneInfo("Asia/Shanghai")).strftime("%Y年%m月%d日")
    assert today in out


def test_get_current_time_in_registry():
    assert "get_current_time" in ALL_LOCAL_TOOLS


def test_assemble_injects_global_tool_for_empty_tools():
    # 即使员工 tools=[]，也应自动拥有 get_current_time
    tools, _mcp = asyncio.run(_assemble_tools(_make_spec(tools=[])))
    names = [t.name for t in tools]
    assert "get_current_time" in names


def test_assemble_no_duplicate_when_explicit():
    # 即便员工显式声明 get_current_time，也不应重复注入
    tools, _mcp = asyncio.run(_assemble_tools(_make_spec(tools=["get_current_time"])))
    names = [t.name for t in tools]
    assert names.count("get_current_time") == 1
