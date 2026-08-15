"""MCP 连接器 stdio 装配测试：验证 compiler 对 node/npx 型连接器透传 command/args/env，
同时 ${PYTHON_BIN} 纯 Python 连接器保持旧行为（换成本项目解释器 + ROOT 相对路径）。"""
import asyncio
import sys

from app import compiler
from app.spec import EmployeeSpec
from app.catalog import seeds


class _FakeMCPClient:
    """捕获 MultiServerMCPClient 收到的 servers 配置，不真实拉起子进程。"""

    def __init__(self, servers):
        self.captured_servers = servers

    async def get_tools(self):
        return []


def _run(spec):
    captured = {}

    def fake_factory(servers):
        captured["servers"] = servers
        return _FakeMCPClient(servers)

    compiler.MultiServerMCPClient = fake_factory
    try:
        tools, client = asyncio.run(
            compiler._assemble_tools(spec, checkpointer=None))
    finally:
        # 恢复，避免污染其它测试
        from langchain_mcp_adapters.client import MultiServerMCPClient
        compiler.MultiServerMCPClient = MultiServerMCPClient
    return captured["servers"]


def test_newsnow_npx_passthrough():
    """newsnow 用 npx + env 的 stdio 配置应原样透传，command 不被改成 python。"""
    _, _, _, newsnow_cfg = next(
        c for c in seeds.CONNECTOR_SEEDS if c[0] == "newsnow")
    spec = EmployeeSpec(
        id="emp_mcp", name="测试", role="测试",
        model="dummy-model", persona="人设",
        mcp_servers={"newsnow": newsnow_cfg},
    )
    servers = _run(spec)
    n = servers["newsnow"]
    assert n["transport"] == "stdio"
    assert n["command"] == "npx"
    assert n["args"] == ["-y", "newsnow-mcp-server"]
    assert n["env"] == {
        "BASE_URL": "http://localhost:4444",
        # 静默 dotenv banner，避免 stdio MCP 通道被非 JSON 日志污染
        "DOTENV_CONFIG_QUIET": "true",
    }
    assert n["cwd"] == "/tmp"


def test_python_bin_connector_backward_compat():
    """${PYTHON_BIN} 连接器（如 crm）仍解析为本项目解释器 + ROOT 相对路径。"""
    _, _, _, crm_cfg = next(c for c in seeds.CONNECTOR_SEEDS if c[0] == "crm")
    spec = EmployeeSpec(
        id="emp_mcp2", name="测试", role="测试",
        model="dummy-model", persona="人设",
        mcp_servers={"crm": crm_cfg},
    )
    servers = _run(spec)
    c = servers["crm"]
    assert c["command"] == sys.executable
    assert c["args"] == [str(compiler.ROOT / "app/connectors/crm_server.py")]
