"""每次 Agent run 的 task 子代理调用次数与并发上限。

通过 deepagents 使用的公开 LangChain AgentMiddleware 扩展点拦截 task 工具；
不修改 deepagents/langgraph 第三方源码。默认限制关闭，策略通过环境变量显式配置。
"""

from __future__ import annotations

import asyncio
import contextvars
import os
import time
from dataclasses import dataclass, field

from langchain.agents.middleware import AgentMiddleware
from langchain_core.messages import ToolMessage


def policy() -> dict:
    return {
        "max_calls_per_run": max(0, int(os.environ.get("SUBAGENT_MAX_CALLS_PER_RUN", "0"))),
        "max_concurrent_per_run": max(0, int(os.environ.get("SUBAGENT_MAX_CONCURRENT_PER_RUN", "0"))),
        "queue_timeout_sec": max(0.0, float(os.environ.get("SUBAGENT_QUEUE_TIMEOUT_SEC", "15"))),
        "scope": "agent-run",
    }


@dataclass
class RunBudget:
    limits: dict
    calls: int = 0
    rejected: int = 0
    active: int = 0
    peak_concurrent: int = 0
    wait_ms_total: float = 0.0
    semaphore: asyncio.Semaphore | None = field(default=None)

    def __post_init__(self):
        limit = self.limits["max_concurrent_per_run"]
        if limit > 0:
            self.semaphore = asyncio.Semaphore(limit)


_current_budget: contextvars.ContextVar[RunBudget | None] = contextvars.ContextVar(
    "uniemployee_subagent_budget", default=None)


def begin_run() -> tuple[RunBudget, contextvars.Token]:
    budget = RunBudget(policy())
    return budget, _current_budget.set(budget)


def end_run(token: contextvars.Token, budget: RunBudget) -> None:
    _current_budget.reset(token)


def snapshot(budget: RunBudget) -> dict:
    return {"calls": budget.calls, "rejected": budget.rejected,
            "peak_concurrent": budget.peak_concurrent,
            "wait_ms_total": round(budget.wait_ms_total, 1), **budget.limits}


class SubagentBudgetMiddleware(AgentMiddleware):
    """按一次主 Agent 运行限制 `task` 调用次数与并发。"""

    name = "UniEmployeeSubagentBudgetMiddleware"

    def __init__(self, *, enforce_concurrency: bool = True):
        super().__init__()
        self._enforce_concurrency = enforce_concurrency

    async def awrap_tool_call(self, request, handler):
        call = request.tool_call or {}
        if call.get("name") != "task":
            return await handler(request)
        budget = _current_budget.get()
        if budget is None:
            return await handler(request)

        max_calls = budget.limits["max_calls_per_run"]
        if max_calls > 0 and budget.calls >= max_calls:
            budget.rejected += 1
            return ToolMessage(
                content=f"本次运行的子代理调用已达到上限（{max_calls}）；请基于已取得的信息继续处理。",
                tool_call_id=call.get("id", ""), name="task", status="error")
        budget.calls += 1

        semaphore = budget.semaphore if self._enforce_concurrency else None
        acquired = False
        if semaphore is not None:
            started = time.monotonic()
            try:
                timeout = budget.limits["queue_timeout_sec"]
                if semaphore.locked() and timeout <= 0:
                    raise asyncio.TimeoutError
                if timeout > 0:
                    await asyncio.wait_for(semaphore.acquire(), timeout=timeout)
                else:
                    await semaphore.acquire()
                acquired = True
                budget.wait_ms_total += (time.monotonic() - started) * 1000
            except asyncio.TimeoutError:
                budget.rejected += 1
                return ToolMessage(
                    content="子代理并发等待超时，本次委派未启动；请减少并行委派或稍后重试。",
                    tool_call_id=call.get("id", ""), name="task", status="error")

        budget.active += 1
        budget.peak_concurrent = max(budget.peak_concurrent, budget.active)
        try:
            return await handler(request)
        finally:
            budget.active = max(0, budget.active - 1)
            if acquired:
                semaphore.release()
