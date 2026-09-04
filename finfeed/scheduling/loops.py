"""周期轮询循环的统一实现。

用法::

    from finfeed.scheduling.loops import run_interval_loop

    async def main():
        stop = await run_interval_loop(
            backfill_content_batch, interval=300, name="content-backfill"
        )
        # 需要停止时：await stop()

特性：
  * 错过补偿：以「下一次应执行时刻」为基准推进，任务慢于间隔时立即补跑
    而不是间隔叠加漂移
  * 取消语义：asyncio.CancelledError 优雅退出（含 sleep 中被取消）
  * 异常隔离：单轮失败记日志继续下一轮，不杀死循环
  * 可观测：启动/退出/异常均有日志，name 作为循环标识
"""
from __future__ import annotations

import asyncio
import logging
import time
from typing import Awaitable, Callable, Optional

logger = logging.getLogger(__name__)


async def run_forever(
    fn: Callable[[], Awaitable],
    interval: float,
    *,
    name: str = "interval-loop",
    first_delay: float = 0.0,
) -> None:
    """阻塞式周期循环：永不返回，直到协程被 cancel。

    适合交给 ``asyncio.create_task()`` 托管的常驻后台任务。
    """
    if interval <= 0:
        raise ValueError(f"interval 必须 > 0，收到 {interval}")
    stop_event = asyncio.Event()
    await _run(fn, interval, name, stop_event, first_delay)


async def run_interval_loop(
    fn: Callable[[], Awaitable],
    interval: float,
    *,
    name: str = "interval-loop",
    first_delay: float = 0.0,
) -> Callable[[], Awaitable]:
    """启动周期循环，返回停止函数。

    Args:
        fn: 每轮执行的协程函数（无参数；需要参数请用闭包）
        interval: 轮询间隔秒数（>0）
        name: 循环标识（日志用）
        first_delay: 首轮延迟秒数（默认立即执行）

    Returns:
        stop(): 异步函数，置停止位并等待循环退出（幂等）。
    """
    if interval <= 0:
        raise ValueError(f"interval 必须 > 0，收到 {interval}")

    task: Optional[asyncio.Task] = asyncio.current_task()
    stop_event = asyncio.Event()
    runner = asyncio.create_task(_run(fn, interval, name, stop_event, first_delay))

    async def stop() -> None:
        stop_event.set()
        if runner is not None and not runner.done():
            try:
                await asyncio.wait_for(runner, timeout=interval + 5)
            except asyncio.TimeoutError:
                runner.cancel()

    # 供调用方在自身协程内直接 await 的场景
    async def _join() -> None:
        await runner

    stop.join = _join  # type: ignore[attr-defined]
    del task
    return stop


async def _run(
    fn: Callable[[], Awaitable],
    interval: float,
    name: str,
    stop_event: asyncio.Event,
    first_delay: float,
) -> None:
    logger.info("周期循环[%s] 启动，间隔 %.1fs", name, interval)
    try:
        if first_delay > 0:
            await _sleep_or_stop(first_delay, stop_event)
        # 错过补偿：deadline 按固定步长推进；任务超时则下一轮立即执行
        deadline = time.monotonic()
        while not stop_event.is_set():
            try:
                await fn()
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # noqa: BLE001
                logger.warning("周期循环[%s] 单轮异常（继续下一轮）: %s", name, exc)
            deadline += interval
            wait = deadline - time.monotonic()
            if wait > 0:
                if not await _sleep_or_stop(wait, stop_event):
                    break
            # wait <= 0：本轮已超时，跳过 sleep 立即补跑
    except asyncio.CancelledError:
        pass
    finally:
        logger.info("周期循环[%s] 退出", name)


async def _sleep_or_stop(seconds: float, stop_event: asyncio.Event) -> bool:
    """睡眠 seconds 秒；期间若置停止位则提前返回 False。"""
    stop_task = asyncio.ensure_future(stop_event.wait())
    try:
        done, _ = await asyncio.wait(
            (stop_task, asyncio.ensure_future(asyncio.sleep(seconds))),
            return_when=asyncio.FIRST_COMPLETED,
        )
        return not stop_event.is_set()
    finally:
        stop_task.cancel()
