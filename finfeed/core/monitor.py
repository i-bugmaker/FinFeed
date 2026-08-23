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
import logging
import time
from typing import Callable, Optional

from finfeed.config.settings import (
    CATCH_UP_CYCLE_INTERVAL,
    CATCH_UP_HARD_TIMEOUT,
    CATCH_UP_SOURCES_PER_CYCLE,
    CATCH_UP_ZERO_STREAK_LIMIT,
)
from finfeed.config.settings import DEFAULT_INTERVAL as FETCH_INTERVAL
from finfeed.config.sources import get_enabled_sources
from finfeed.core.health import get_health_monitor
from finfeed.storage.database import (
    db_get_all_source_last_ts,
    db_get_last_exit_ts,
    db_set_last_exit_ts,
    db_set_source_last_ts,
)

from .fetcher import fetch_all_news, get_fetcher
from .pipeline import process_and_store

logger = logging.getLogger("news_monitor")


class NewsMonitor:
    """新闻监控器"""

    def __init__(self):
        self._running = False
        self._shutdown_event = asyncio.Event()
        self._push_callback: Optional[Callable] = None
        self._fetch_count = 0
        self._total_new = 0

    def set_push_callback(self, callback: Callable) -> None:
        """设置推送回调函数

        回调签名: async def callback(total_new: int) -> None
        回调只收到「本轮新增条数」，具体新增了哪些条目由 Web 层按数据库
        自增 id 水位线自行确定（见 ui.web.shared.broadcast_new_news）。
        """
        self._push_callback = callback

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

    async def _process_fetched(self, all_news: list, fetcher) -> int:
        """处理抓取到的新闻：写入源时间戳、分类、入库、推送

        三种抓取模式（catch_up / single / 主循环）共用的核心处理逻辑。
        返回新增条数。

        分类分桶：按 NewsItem.category 划分（由解析器按来源归属打标）：
          - flash  快讯类（7×24 实时短消息）
          - article 文章类（长文/深度内容）
          - forum  舆情论坛类（UGC 内容）
        """
        for src_name, parser in fetcher._parsers.items():
            db_set_source_last_ts(src_name, parser.last_ts)

        flash_items = []
        article_items = []
        forum_items = []
        for item in all_news:
            cat = item.category or "flash"
            if cat == "forum":
                forum_items.append(item)
            elif cat == "article":
                article_items.append(item)
            else:
                flash_items.append(item)

        total_new = 0
        if flash_items:
            n = await process_and_store(flash_items, source_name="flash")
            total_new += n
        if article_items:
            n = await process_and_store(article_items, source_name="article")
            total_new += n
        if forum_items:
            n = await process_and_store(forum_items, source_name="forum")
            total_new += n
        return total_new

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

        # 全源覆盖保护：切片模式下（CATCH_UP_SOURCES_PER_CYCLE > 0）需保证
        # 轮次足够覆盖全部启用源至少一次，避免长离线时只回补了部分源。
        # CATCH_UP_SOURCES_PER_CYCLE == 0 时每轮全量，一轮即覆盖，无需上调。
        if CATCH_UP_SOURCES_PER_CYCLE > 0:
            total = len(get_enabled_sources())
            needed = (total + CATCH_UP_SOURCES_PER_CYCLE - 1) // CATCH_UP_SOURCES_PER_CYCLE
            if needed > max_cycles:
                logger.info(
                    f"补抓轮次上调至 {needed}（保证覆盖全部 {total} 个源，"
                    f"每轮 {CATCH_UP_SOURCES_PER_CYCLE} 个）"
                )
                max_cycles = needed

        logger.info(f"开始离线补抓：离线 {offline_seconds/3600:.1f} 小时，计划 {max_cycles} 轮")
        total_catchup = 0

        saved_last_ts = db_get_all_source_last_ts()
        fetcher = get_fetcher()
        for src_name, ts in saved_last_ts.items():
            fetcher.set_parser_last_ts(src_name, ts)

        # 加固(2026-08-24)：补抓不得无限期阻塞实时主循环——
        # 1) 连续 2 轮零新增即提前终止（离线缺口大概率已无可补内容）；
        # 2) 单次补抓总耗时超过 CATCH_UP_HARD_TIMEOUT 秒强制切回实时轮次，
        #    避免慢源（浏览器渲染/大分页补抓）把主循环饿死数小时。
        catch_up_started = time.time()
        zero_streak = 0
        for cycle in range(1, max_cycles + 1):
            if not self._running and self._shutdown_event.is_set():
                break
            if time.time() - catch_up_started > CATCH_UP_HARD_TIMEOUT:
                logger.info(f"补抓已持续超过 {CATCH_UP_HARD_TIMEOUT}s 硬上限，强制进入实时轮次")
                break
            try:
                logger.info(f"补抓轮次 {cycle}/{max_cycles}...")
                all_news, _ = await fetch_all_news(
                    cycle=cycle,
                    catch_up_mode=True,
                    sources_per_cycle=CATCH_UP_SOURCES_PER_CYCLE,
                )
                cycle_new = await self._process_fetched(all_news, fetcher)
                total_catchup += cycle_new
                logger.info(f"补抓轮次 {cycle} 完成，本轮新增 {cycle_new} 条")

                if cycle_new == 0:
                    zero_streak += 1
                    if zero_streak >= CATCH_UP_ZERO_STREAK_LIMIT:
                        logger.info(
                            f"连续 {zero_streak} 轮补抓无新增，提前结束补抓进入实时轮次"
                        )
                        break
                else:
                    zero_streak = 0

                if cycle < max_cycles:
                    await asyncio.sleep(CATCH_UP_CYCLE_INTERVAL)
            except asyncio.CancelledError:
                raise
            except Exception as e:
                logger.error(f"补抓轮次 {cycle} 异常: {e}")
                await asyncio.sleep(2)

        get_health_monitor()
        logger.info(f"补抓完成，共新增 {total_catchup} 条新闻")

        if total_catchup > 0 and self._push_callback:
            try:
                await self._push_callback(total_catchup)
            except Exception as e:
                logger.error(f"补抓推送失败: {e}", exc_info=True)

        return total_catchup

    async def run_single_fetch(self) -> int:
        """执行单次抓取（用于手动触发/TUI单次模式）"""
        try:
            all_news, _ = await fetch_all_news(cycle=self._fetch_count + 1)
            fetcher = get_fetcher()
            total_new = await self._process_fetched(all_news, fetcher)

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

        try:
            await self.run_catch_up()
        except Exception as e:
            logger.error(f"补抓异常: {e}")

        fetcher = get_fetcher()
        while self._running:
            try:
                self._fetch_count += 1
                cycle_start = time.time()

                all_news, _ = await fetch_all_news(cycle=self._fetch_count)
                total_new = await self._process_fetched(all_news, fetcher)

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

        for src_name, parser in fetcher._parsers.items():
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
