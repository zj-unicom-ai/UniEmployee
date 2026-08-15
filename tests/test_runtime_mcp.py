"""#7 MCP stdio client 退出清理测试。"""

import asyncio

from app import runtime


def test_shutdown_mcp_closes_clients(monkeypatch):
    closed = []

    class FakeClient:
        async def aclose(self):
            closed.append(self)

    client = FakeClient()
    monkeypatch.setattr(runtime, "_mcp_clients", {"emp": client})
    monkeypatch.setattr(runtime, "_agents", {"emp": ("agent", [])})

    asyncio.run(runtime.shutdown_mcp())

    assert closed == [client]
    assert runtime._mcp_clients == {}
    assert runtime._agents == {}
