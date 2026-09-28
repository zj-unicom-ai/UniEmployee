"""单进程、按模型隔离的 Agent 请求准入。

这是负载保护阀，不是分布式配额或费用账单。默认关闭；配置
MODEL_MAX_CONCURRENT>0 后才限制并发，超出并发的请求最多排队
MODEL_QUEUE_TIMEOUT_SEC 秒，队列人数受 MODEL_MAX_QUEUE 限制。
"""

from __future__ import annotations

import asyncio
import os
import time
from dataclasses import dataclass, field


class AdmissionRejected(Exception):
    """模型请求超过本进程的准入/排队上限。"""


@dataclass
class _State:
    limit: int
    semaphore: asyncio.Semaphore
    active: int = 0
    waiting: int = 0
    admitted: int = 0
    rejected: int = 0
    wait_ms_total: float = 0.0
    wait_ms_max: float = 0.0
    wait_times: list[float] = field(default_factory=list)


_states: dict[tuple[int, str], _State] = {}


def _configuration() -> tuple[int, int, float]:
    limit = max(0, int(os.environ.get("MODEL_MAX_CONCURRENT", "0")))
    queue_limit = max(0, int(os.environ.get("MODEL_MAX_QUEUE", "20")))
    queue_timeout = max(0.0, float(os.environ.get("MODEL_QUEUE_TIMEOUT_SEC", "15")))
    return limit, queue_limit, queue_timeout


def _state(model: str, limit: int) -> _State:
    loop = asyncio.get_running_loop()
    key = (id(loop), model)
    state = _states.get(key)
    if state is None or state.limit != limit:
        if state and (state.active or state.waiting):
            raise RuntimeError("MODEL_MAX_CONCURRENT 变更时仍有活动请求；请重启服务后再应用配置")
        state = _State(limit=limit, semaphore=asyncio.Semaphore(limit))
        _states[key] = state
    return state


async def acquire(model: str) -> dict:
    """获取一个模型执行槽；返回需交给 release 的租约字典。"""
    limit, queue_limit, queue_timeout = _configuration()
    if limit <= 0:
        return {"state": None, "wait_ms": 0.0, "model": model or "default"}
    model = (model or "default").strip()[:160]
    state = _state(model, limit)
    queued = state.semaphore.locked()
    if queued and state.waiting >= queue_limit:
        state.rejected += 1
        raise AdmissionRejected("模型并发已满且等待队列已满")
    started = time.monotonic()
    if queued:
        state.waiting += 1
    try:
        if queued and queue_timeout <= 0:
            raise AdmissionRejected("模型并发已满且未配置排队等待时间")
        if queue_timeout <= 0:
            await state.semaphore.acquire()
        else:
            await asyncio.wait_for(state.semaphore.acquire(), timeout=queue_timeout)
    except AdmissionRejected:
        state.rejected += 1
        raise
    except asyncio.TimeoutError as exc:
        state.rejected += 1
        raise AdmissionRejected("等待模型执行槽超时") from exc
    finally:
        if queued:
            state.waiting = max(0, state.waiting - 1)
    wait_ms = (time.monotonic() - started) * 1000
    state.active += 1
    state.admitted += 1
    state.wait_ms_total += wait_ms
    state.wait_ms_max = max(state.wait_ms_max, wait_ms)
    state.wait_times.append(wait_ms)
    if len(state.wait_times) > 1000:
        del state.wait_times[:500]
    return {"state": state, "wait_ms": round(wait_ms, 1), "model": model}


def release(lease: dict) -> None:
    state = lease.get("state")
    if state is None:
        return
    state.active = max(0, state.active - 1)
    state.semaphore.release()


def stats() -> dict:
    limit, queue_limit, queue_timeout = _configuration()
    items = []
    for (_, model), state in _states.items():
        waits = sorted(state.wait_times)
        p95 = waits[min(len(waits) - 1, int((len(waits) - 1) * 0.95))] if waits else 0
        items.append({
            "model": model, "max_concurrent": state.limit, "active": state.active,
            "waiting": state.waiting, "admitted": state.admitted,
            "rejected": state.rejected,
            "avg_wait_ms": round(state.wait_ms_total / state.admitted, 1) if state.admitted else 0,
            "max_wait_ms": round(state.wait_ms_max, 1), "p95_wait_ms": round(p95, 1),
        })
    return {"enabled": limit > 0, "configured_max_concurrent": limit,
            "max_queue": queue_limit, "queue_timeout_sec": queue_timeout,
            "scope": "process-local", "models": sorted(items, key=lambda x: x["model"])}


def reset_for_tests() -> None:
    _states.clear()
