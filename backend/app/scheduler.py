"""定时调度循环：扫描 automations 的到期 cron 任务并执行。

随应用 lifespan 启动（AUTOMATIONS_DISABLED=1 可跳过）。单 worker 部署
即可正常工作；多实例下靠 next_fire_at 的 CAS 抢占（claim_next）保证
同一触发点只执行一次。停机期间错过的触发点只补跑一次（执行后从
当前时间重算 next_fire_at，不追历史）。
"""
import asyncio
import logging
import os
from datetime import datetime

from app import automations

log = logging.getLogger("app.scheduler")

_task: asyncio.Task | None = None
INTERVAL = 30  # 扫描周期（秒）


async def run_due(auto: dict, now: datetime) -> None:
    """抢占并执行一个到期任务。"""
    nxt = automations.next_fire(auto["cron_expr"], now)
    if not automations.claim_next(
            auto["id"], auto["next_fire_at"],
            nxt.strftime(automations.TS) if nxt else None):
        return  # 已被其他实例/上一轮慢执行抢占
    result = await automations.execute(auto, trigger="cron")
    if result["status"] == "ok":
        log.info("自动任务完成 id=%s name=%s conv=%s",
                 auto["id"], auto["name"], result["conversation_id"])
    else:
        log.warning("自动任务失败 id=%s name=%s err=%s",
                    auto["id"], auto["name"], result["error"])


async def _tick() -> None:
    now = datetime.now()
    for auto in automations.due_crons(now.strftime(automations.TS)):
        try:
            await run_due(auto, now)
        except Exception:
            log.exception("自动任务执行异常 id=%s", auto["id"])


async def _loop() -> None:
    log.info("自动任务调度器已启动（每 %ss 扫描一次）", INTERVAL)
    while True:
        try:
            await _tick()
        except Exception:
            log.exception("调度 tick 异常")
        await asyncio.sleep(INTERVAL)


def start() -> None:
    global _task
    if os.environ.get("AUTOMATIONS_DISABLED") == "1":
        log.info("AUTOMATIONS_DISABLED=1，跳过自动任务调度器")
        return
    if _task is None or _task.done():
        _task = asyncio.create_task(_loop())


async def stop() -> None:
    global _task
    if _task:
        _task.cancel()
        try:
            await _task
        except asyncio.CancelledError:
            pass
        _task = None
        log.info("自动任务调度器已停止")
