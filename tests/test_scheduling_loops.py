"""finfeed.scheduling.loops 周期轮询原语的行为测试（无 pytest-asyncio 依赖，
统一用 asyncio.run 同步包装）。"""
import asyncio

from finfeed.scheduling.loops import run_forever, run_interval_loop


def test_normal_interval_ticks():
    """正常周期：280ms / 50ms 间隔应执行 5-6 轮。"""
    async def main():
        ticks = []

        async def fn():
            ticks.append(asyncio.get_event_loop().time())

        task = asyncio.create_task(run_forever(fn, 0.05, name="test"))
        await asyncio.sleep(0.28)
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
        assert 4 <= len(ticks) <= 7, len(ticks)

    asyncio.run(main())


def test_exception_does_not_kill_loop():
    """异常隔离：单轮抛异常后循环继续。"""
    async def main():
        n = [0]

        async def bad():
            n[0] += 1
            if n[0] == 1:
                raise RuntimeError("boom")

        task = asyncio.create_task(run_forever(bad, 0.03, name="bad"))
        await asyncio.sleep(0.12)
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
        assert n[0] >= 3, n[0]

    asyncio.run(main())


def test_missed_tick_compensation():
    """错过补偿：任务慢于间隔时立即补跑，不叠加漂移。"""
    async def main():
        times = []

        async def slow():
            times.append(asyncio.get_event_loop().time())
            await asyncio.sleep(0.08)

        task = asyncio.create_task(run_forever(slow, 0.05, name="slow"))
        await asyncio.sleep(0.45)
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
        gaps = [times[i + 1] - times[i] for i in range(len(times) - 1)]
        # 无补偿的写法间隔会漂移到 ~0.13（80ms 任务 + 50ms sleep）
        assert gaps and all(g < 0.12 for g in gaps), gaps

    asyncio.run(main())


def test_interval_loop_stop_handle():
    """run_interval_loop 返回的 stop() 幂等且能真正停循环。"""
    async def main():
        n = [0]

        async def fn():
            n[0] += 1

        stop = await run_interval_loop(fn, 0.03, name="stoppable")
        await asyncio.sleep(0.1)
        await stop()
        count_at_stop = n[0]
        await asyncio.sleep(0.1)
        assert n[0] == count_at_stop  # 停止后不再执行
        await stop()  # 幂等

    asyncio.run(main())
