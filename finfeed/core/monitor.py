#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""新闻监控主循环

功能：
- 定时抓取新闻
- 离线补抓（动态轮次，基于离线时长）
- 状态推送（WebSocket/SSE）
- 优雅关闭
"""

import asyncio
import time
import logging
from typing import Callable, Optional, List, Dict

from finfeed.config.settings import DEFAULT_INTERVAL as FETCH_INTERVAL, CATCH_UP_CYCLE_INTERVAL, CATCH_UP_SOURCES_PER_CYCLE
from .fetcher import get_fetcher, fetch_all_news
from .pipeline import process_and_store
from finfeed.storage.database import db_get_last_exit_ts, db_set_last_exit_ts, db_get_all_source_last_ts, db_get_statistics
from finfeed.core.health import get_health_monitor
from finfeed.config.sources import get_forum_source_names

logger = logging.getLogger("news_monitor")


class NewsMonitor:
    """新闻监控器"""

    def __init__(self):
        self._running = False
        self._shutdown_event = asyncio.Event()
        self._push_callback: Optional[Callable] = None
        self._push_queue: asyncio.Queue = asyncio.Queue()
        self._push_task: Optional[asyncio.Task] = None
        self._fetch_count = 0
        self._total_new = 0

    def set_push_callback(self, callback: Callable) -> None:
        """设置推送回调函数"""
        self._push_callback = callback

    async def _push_worker(self) -> None:
        """推送工作协程：批量处理推送队列，避免阻塞抓取"""
        while self._running or not self._push_queue.empty():
            try:
                items: List[Dict] = []
                try:
                    first = await asyncio.wait_for(self._push_queue.get(), timeout=0.5)
                    items.append(first)
                except asyncio.TimeoutError:
                    if not self._running and self._push_queue.empty():
                        break
                    continue

                while len(items) < 20:
                    try:
                        item = self._push_queue.get_nowait()
                        items.append(item)
                    except asyncio.QueueEmpty:
                        break

                if self._push_callback and items:
                    try:
                        await self._push_callback(items)
                    except Exception as e:
                        logger.debug(f"推送回调异常: {e}")

                for _ in items:
                    self._push_queue.task_done()
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.debug(f"推送工作协程异常: {e}")
                await asyncio.sleep(0.1)

    def _push_news_batch(self, news_items, category: str) -> None:
        """将新闻条目推送到 Web 端（直接调用）"""
        logger.info(f"_push_news_batch 被调用: news_items={len(news_items) if news_items else 0}, callback={self._push_callback is not None}")
        if not news_items or not self._push_callback:
            if not self._push_callback:
                logger.warning("_push_callback 为 None，无法推送")
            return
        forum_sources = set(get_forum_source_names())
        items = []
        for item in news_items:
            try:
                item_category = category
                if not item_category:
                    item_category = "forum" if item.source in forum_sources else "finance"
                d = item.to_dict()
                d["category"] = item_category
                items.append(d)
            except Exception as e:
                logger.error(f"转换新闻失败: {e}")
        
        if items:
            try:
                asyncio.create_task(self._push_callback(items))
                logger.info(f"推送 {len(items)} 条新闻到 Web 端")
            except Exception as e:
                logger.error(f"推送失败: {e}")
        else:
            logger.info("items 为空，跳过推送")

    def _calculate_catchup_cycles(self, offline_seconds: int) -> int:
        """根据离线时长动态计算需要的补抓轮次

        规则：
        - <30分钟：无需补抓（实时数据覆盖）
        - 30分钟-4小时：2轮
        - 4小时-24小时：5轮
        - >24小时：10轮（最多）
        """
        if offline_seconds < 1800:
            return 0
        elif offline_seconds < 14400:
            return 2
        elif offline_seconds < 86400:
            return 5
        else:
            return 10

    async def run_catch_up(self) -> int:
        """执行离线补抓，返回补抓到的新闻总数

        自动根据上次退出时间计算需要的轮次
        """
        last_ts = db_get_last_exit_ts()
        now_ts = int(time.time())

        if last_ts <= 0:
            logger.info("首次启动，执行初始化补抓")
            offline_seconds = 86400
        else:
            offline_seconds = now_ts - last_ts
        max_cycles = self._calculate_catchup_cycles(offline_seconds)

        if max_cycles <= 0:
            logger.info(f"离线时长 {offline_seconds}s，无需补抓")
            return 0

        logger.info(f"开始离线补抓：离线 {offline_seconds/3600:.1f} 小时，计划 {max_cycles} 轮")
        total_catchup = 0

        saved_last_ts = db_get_all_source_last_ts()
        fetcher = get_fetcher()
        for src_name, ts in saved_last_ts.items():
            fetcher.set_parser_last_ts(src_name, ts)

        for cycle in range(1, max_cycles + 1):
            if not self._running and self._shutdown_event.is_set():
                break
            try:
                logger.info(f"补抓轮次 {cycle}/{max_cycles}...")
                all_news, source_stats = await fetch_all_news(
                    cycle=cycle,
                    catch_up_mode=True,
                    sources_per_cycle=CATCH_UP_SOURCES_PER_CYCLE,
                )

                cycle_new = 0
                finance_items = []
                forum_items = []
                forum_sources = set(get_forum_source_names())

                for src_name, parser in fetcher._parsers.items():
                    db_set_last_ts = parser.last_ts
                    from finfeed.storage.database import db_set_source_last_ts
                    db_set_source_last_ts(src_name, db_set_last_ts)

                for item in all_news:
                    if item.source in forum_sources:
                        forum_items.append(item)
                    else:
                        finance_items.append(item)

                if finance_items:
                    n = await process_and_store(finance_items, source_name="finance")
                    cycle_new += n
                    if n > 0:
                        self._push_news_batch(finance_items, "finance")
                if forum_items:
                    n = await process_and_store(forum_items, source_name="forum")
                    cycle_new += n
                    if n > 0:
                        self._push_news_batch(forum_items, "forum")

                total_catchup += cycle_new
                logger.info(f"补抓轮次 {cycle} 完成，本轮新增 {cycle_new} 条")

                if cycle < max_cycles:
                    await asyncio.sleep(CATCH_UP_CYCLE_INTERVAL)
            except asyncio.CancelledError:
                raise
            except Exception as e:
                logger.error(f"补抓轮次 {cycle} 异常: {e}")
                await asyncio.sleep(2)

        get_health_monitor()
        logger.info(f"补抓完成，共新增 {total_catchup} 条新闻")
        return total_catchup

    async def run_single_fetch(self) -> int:
        """执行单次抓取（用于手动触发/TUI单次模式）"""
        try:
            all_news, source_stats = await fetch_all_news(cycle=self._fetch_count + 1)

            finance_items = []
            forum_items = []
            forum_sources = set(get_forum_source_names())

            fetcher = get_fetcher()
            for src_name, parser in fetcher._parsers.items():
                from finfeed.storage.database import db_set_source_last_ts
                db_set_source_last_ts(src_name, parser.last_ts)

            for item in all_news:
                if item.source in forum_sources:
                    forum_items.append(item)
                else:
                    finance_items.append(item)

            total_new = 0
            if finance_items:
                n = await process_and_store(finance_items, source_name="finance")
                total_new += n
                if n > 0:
                    self._push_news_batch(finance_items, "finance")
            if forum_items:
                n = await process_and_store(forum_items, source_name="forum")
                total_new += n
                if n > 0:
                    self._push_news_batch(forum_items, "forum")

            self._fetch_count += 1
            db_set_last_exit_ts(int(time.time()))
            return total_new
        except Exception as e:
            logger.error(f"单次抓取失败: {e}")
            return 0

    async def run(self) -> None:
        """启动监控主循环"""
        if self._running:
            return
        self._running = True
        self._shutdown_event.clear()

        logger.info("新闻监控启动")

        self._push_task = asyncio.create_task(self._push_worker())

        try:
            await self.run_catch_up()
        except Exception as e:
            logger.error(f"补抓异常: {e}")

        while self._running:
            try:
                self._fetch_count += 1
                cycle_start = time.time()

                all_news, source_stats = await fetch_all_news(cycle=self._fetch_count)

                finance_items = []
                forum_items = []
                forum_sources = set(get_forum_source_names())

                fetcher = get_fetcher()
                for src_name, parser in fetcher._parsers.items():
                    from finfeed.storage.database import db_set_source_last_ts
                    db_set_source_last_ts(src_name, parser.last_ts)

                for item in all_news:
                    if item.source in forum_sources:
                        forum_items.append(item)
                    else:
                        finance_items.append(item)

                total_new = 0
                if finance_items:
                    n = await process_and_store(finance_items, source_name="finance")
                    total_new += n
                    logger.info(f"第 {self._fetch_count} 轮: finance 处理 {len(finance_items)} 条, 新增 {n} 条")
                if forum_items:
                    n = await process_and_store(forum_items, source_name="forum")
                    total_new += n
                    logger.info(f"第 {self._fetch_count} 轮: forum 处理 {len(forum_items)} 条, 新增 {n} 条")

                self._total_new += total_new
                db_set_last_exit_ts(int(time.time()))

                if total_new > 0 and self._push_callback:
                    try:
                        await self._push_callback(total_new)
                    except Exception as e:
                        logger.error(f"第 {self._fetch_count} 轮: 推送失败: {e}", exc_info=True)

                elapsed = time.time() - cycle_start
                logger.info(f"第 {self._fetch_count} 轮完成，新增 {total_new} 条，耗时 {elapsed:.2f}s")

                sleep_time = max(0.5, FETCH_INTERVAL - elapsed)
                try:
                    await asyncio.wait_for(self._shutdown_event.wait(), timeout=sleep_time)
                except asyncio.TimeoutError:
                    pass

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"主循环异常: {e}")
                try:
                    await asyncio.wait_for(self._shutdown_event.wait(), timeout=5)
                except asyncio.TimeoutError:
                    pass

        if self._push_task:
            await self._push_queue.join()
            self._push_task.cancel()
            try:
                await self._push_task
            except asyncio.CancelledError:
                pass

        for src_name, parser in get_fetcher()._parsers.items():
            from finfeed.storage.database import db_set_source_last_ts
            db_set_source_last_ts(src_name, parser.last_ts)

        db_set_last_exit_ts(int(time.time()))
        logger.info("新闻监控已停止")

    async def shutdown(self) -> None:
        """优雅关闭监控"""
        if not self._running:
            return
        logger.info("正在停止新闻监控...")
        self._running = False
        self._shutdown_event.set()

    @property
    def is_running(self) -> bool:
        return self._running

    @property
    def fetch_count(self) -> int:
        return self._fetch_count

    @property
    def total_new_count(self) -> int:
        return self._total_new


_global_monitor: Optional[NewsMonitor] = None


def get_monitor() -> NewsMonitor:
    """获取全局监控器单例"""
    global _global_monitor
    if _global_monitor is None:
        _global_monitor = NewsMonitor()
    return _global_monitor
