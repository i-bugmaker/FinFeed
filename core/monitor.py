#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""监控管理器

封装监控循环、补抓逻辑和状态管理。
"""

import time
import logging
import asyncio
from typing import Optional, Dict, List, Callable

from config.settings import (
    DEFAULT_WEB_PORT, DEFAULT_INTERVAL, MAX_NEWS_CACHE,
    MAX_CATCH_UP_CYCLES, CATCH_UP_INTERVAL, OFFLINE_GAP_THRESHOLD,
)
from storage.database import (
    db_get_recent_news, db_count_news,
    db_get_last_exit_ts, db_set_last_exit_ts,
    db_get_all_source_last_ts,
)
from storage.models import NewsItem
from core.pipeline import get_pipeline
from core.fetcher import set_parser_last_ts, init_all_parsers, get_fetcher
from core.health import get_health_monitor
from ui.terminal import console, build_display, build_news_table
from ui.web.server import update_web_state
from utils.common import jitter_interval

logger = logging.getLogger("news_monitor")

CATCH_UP_MAX_DAYS = 7


class MonitorManager:
    """监控管理器"""

    def __init__(self):
        self._pipeline = None
        self._health_monitor = None
        self._fetcher = None
        self._all_collected_news: List[NewsItem] = []
        self._source_stats: Dict[str, int] = {}
        self._total_in_db = 0
        self._last_new_count = 0
        self._cycle = 0
        self._shutdown_event = asyncio.Event()
        self._last_exit_save_ts = 0

    def _setup_catch_up(self) -> tuple[bool, str]:
        """设置离线补抓状态"""
        now_ts = int(time.time())
        last_exit_ts = db_get_last_exit_ts()
        offline_gap_sec = max(0, now_ts - last_exit_ts) if last_exit_ts > 0 else 0
        catch_up_needed = offline_gap_sec > OFFLINE_GAP_THRESHOLD
        catch_up_status = ""

        max_back_ts = now_ts - CATCH_UP_MAX_DAYS * 24 * 3600

        if catch_up_needed:
            from config.sources import get_enabled_sources, THSYC_CHANNELS

            source_last_ts_map = db_get_all_source_last_ts()

            for src in get_enabled_sources():
                saved_ts = source_last_ts_map.get(src.name, last_exit_ts)
                effective_ts = min(saved_ts, last_exit_ts) if saved_ts > 0 else last_exit_ts
                effective_ts = max(effective_ts, max_back_ts)
                set_parser_last_ts(src.name, effective_ts)

            parsers = get_fetcher()._parsers
            if "同花顺原创" in parsers:
                parser = parsers["同花顺原创"]
                if hasattr(parser, '_channel_last_ts'):
                    for ch in THSYC_CHANNELS:
                        parser._channel_last_ts[ch["name"]] = max(last_exit_ts, max_back_ts)

            gap_min = int(offline_gap_sec // 60)
            gap_hour = gap_min // 60
            if gap_hour > 0:
                catch_up_status = f"离线 {gap_hour}h{gap_min % 60}min，正在补抓..."
            else:
                catch_up_status = f"离线 {gap_min}min，正在补抓..."

        return catch_up_needed, catch_up_status

    def _merge_news(self, new_items: List[NewsItem]) -> None:
        """合并新闻列表，去重并保持按时间倒序"""
        if not new_items:
            return

        seen_titles = {n.title for n in self._all_collected_news}
        unique_new = [n for n in new_items if n.title not in seen_titles]

        if unique_new:
            unique_new.sort(key=lambda x: x.publish_ts, reverse=True)
            self._all_collected_news = unique_new + [
                n for n in self._all_collected_news
                if n.title not in {x.title for x in unique_new}
            ]
            self._all_collected_news.sort(key=lambda x: x.publish_ts, reverse=True)

        if len(self._all_collected_news) > MAX_NEWS_CACHE:
            self._all_collected_news = self._all_collected_news[:MAX_NEWS_CACHE]

    async def _run_catch_up(self, render: Callable) -> int:
        """执行离线补抓"""
        catch_up_total = 0

        for cu_cycle in range(1, MAX_CATCH_UP_CYCLES + 1):
            cu_status = f"补抓 {cu_cycle}/{MAX_CATCH_UP_CYCLES} | 已补 {catch_up_total} 条"
            table = build_news_table(self._all_collected_news, max_rows=max(10, console.size[1] - 15))
            render(self._all_collected_news, 0, self._total_in_db, catch_up_total,
                   self._source_stats, DEFAULT_INTERVAL, cu_status, table)

            all_news, stats, inserted = await self._pipeline.run_cycle(cycle=cu_cycle, catch_up_mode=True)
            catch_up_total += inserted
            self._source_stats = stats
            self._total_in_db += inserted

            self._merge_news(all_news)

            cu_status2 = f"补抓 {cu_cycle}/{MAX_CATCH_UP_CYCLES} | 本轮 +{inserted} | 累计 +{catch_up_total}"
            table = build_news_table(self._all_collected_news, max_rows=max(10, console.size[1] - 15))
            render(self._all_collected_news, 0, self._total_in_db, catch_up_total,
                   self._source_stats, DEFAULT_INTERVAL, cu_status2, table)
            update_web_state(self._all_collected_news, self._source_stats, 0,
                             self._total_in_db, catch_up_total, cu_status2)

            if inserted == 0 and cu_cycle > 1:
                break
            await asyncio.sleep(CATCH_UP_INTERVAL)

        self._last_exit_save_ts = int(time.time())
        db_set_last_exit_ts(self._last_exit_save_ts)

        return catch_up_total

    async def _run_normal_cycle(self, interval: int, render: Callable) -> bool:
        """执行正常抓取周期"""
        self._cycle += 1
        table = build_news_table(self._all_collected_news, max_rows=max(10, console.size[1] - 15))
        render(self._all_collected_news, self._cycle, self._total_in_db, self._last_new_count,
               self._source_stats, interval, "抓取中...", table)

        fetch_task = asyncio.create_task(self._pipeline.run_cycle(cycle=self._cycle, catch_up_mode=False))
        last_fetch_sec = -1
        cached_table = table

        while not fetch_task.done() and not self._shutdown_event.is_set():
            await asyncio.sleep(0.5)
            cur_sec = int(time.time())
            if cur_sec != last_fetch_sec:
                last_fetch_sec = cur_sec
                render(self._all_collected_news, self._cycle, self._total_in_db, self._last_new_count,
                       self._source_stats, interval, "抓取中...", cached_table)

        if self._shutdown_event.is_set():
            return False

        try:
            all_news, stats, inserted = fetch_task.result()
        except Exception as e:
            logger.error(f"抓取周期失败: {e}")
            return True

        self._source_stats = stats
        self._total_in_db += inserted
        self._last_new_count = inserted

        self._merge_news(all_news)

        now_ts = int(time.time())
        if now_ts - self._last_exit_save_ts >= 60:
            self._last_exit_save_ts = now_ts
            db_set_last_exit_ts(now_ts)

        wait_sec = jitter_interval(interval)
        status = f"新增{inserted}条" if inserted > 0 else "无新内容"
        update_web_state(
            self._all_collected_news, self._source_stats, self._cycle,
            self._total_in_db, self._last_new_count, f"{status} | {wait_sec:.1f}s后一轮"
        )

        wait_end = time.time() + wait_sec
        table = build_news_table(self._all_collected_news, max_rows=max(10, console.size[1] - 15))
        render(self._all_collected_news, self._cycle, self._total_in_db, self._last_new_count,
               self._source_stats, interval, f"{status} | {wait_sec:.0f}s后一轮", table)

        last_wait_sec = -1
        while time.time() < wait_end and not self._shutdown_event.is_set():
            await asyncio.sleep(0.5)
            cur_sec = int(time.time())
            if cur_sec != last_wait_sec:
                last_wait_sec = cur_sec
                remaining = max(0, wait_end - time.time())
                render(self._all_collected_news, self._cycle, self._total_in_db, self._last_new_count,
                       self._source_stats, interval, f"{status} | {remaining:.0f}s后一轮", table)

        return not self._shutdown_event.is_set()

    async def _run_cycles(self, interval: int, render: Callable, catch_up_needed: bool) -> None:
        """运行监控循环"""
        if catch_up_needed:
            await self._run_catch_up(render)

        while True:
            if not await self._run_normal_cycle(interval, render):
                break

    async def run_once(self) -> tuple[int, int, int]:
        """只抓取一次"""
        self._pipeline = get_pipeline()
        self._health_monitor = get_health_monitor()
        self._health_monitor.load_from_db()
        self._fetcher = get_fetcher()
        init_all_parsers()

        try:
            self._total_in_db = db_count_news()
        except Exception:
            pass

        self._all_collected_news = db_get_recent_news(limit=MAX_NEWS_CACHE)

        catch_up_needed, _ = self._setup_catch_up()

        max_cycles = MAX_CATCH_UP_CYCLES if catch_up_needed else 1
        total_inserted = 0

        for cycle in range(max_cycles):
            all_news, stats, inserted = await self._pipeline.run_cycle(cycle=cycle + 1, catch_up_mode=catch_up_needed)
            total_inserted += inserted
            self._source_stats = stats
            self._merge_news(all_news)
            self._total_in_db += inserted
            if inserted == 0 and cycle > 0:
                break

        db_set_last_exit_ts(int(time.time()))

        return total_inserted, len(self._all_collected_news), max_cycles if catch_up_needed else 0

    async def run_continuous(self, interval: int = DEFAULT_INTERVAL, web_port: int = DEFAULT_WEB_PORT) -> None:
        """连续监控"""
        self._pipeline = get_pipeline()
        self._health_monitor = get_health_monitor()
        self._health_monitor.load_from_db()
        self._fetcher = get_fetcher()
        init_all_parsers()

        try:
            self._total_in_db = db_count_news()
        except Exception:
            pass

        self._all_collected_news = db_get_recent_news(limit=MAX_NEWS_CACHE)

        catch_up_needed, catch_up_status = self._setup_catch_up()

        update_web_state(
            self._all_collected_news, self._source_stats, 0, self._total_in_db,
            0, catch_up_status or "抓取中..."
        )

        def live_render(news, cyc, total, new_ct, stats, itv, st, table):
            from rich.live import Live
            nonlocal live
            live.update(build_display(news, cyc, total, new_ct, stats, itv, st, web_port=web_port, table=table))

        def simple_render(news, cyc, total, new_ct, stats, itv, st, table):
            nonlocal last_print
            now = time.time()
            if now - last_print >= 10:
                last_print = now
                console.clear()
                console.print(build_display(news, cyc, total, new_ct, stats, itv, st, web_port=web_port, table=table))

        root_logger = logging.getLogger()
        root_orig_handlers = list(root_logger.handlers)
        nm_logger = logging.getLogger("news_monitor")
        nm_orig_handlers = list(nm_logger.handlers)
        nm_orig_propagate = nm_logger.propagate

        def restore_logging():
            nonlocal logging_restored
            if logging_restored:
                return
            logging_restored = True
            for h in list(root_logger.handlers):
                root_logger.removeHandler(h)
            for h in root_orig_handlers:
                root_logger.addHandler(h)
            for h in list(nm_logger.handlers):
                nm_logger.removeHandler(h)
            for h in nm_orig_handlers:
                nm_logger.addHandler(h)
            nm_logger.propagate = nm_orig_propagate

        logging_restored = False
        last_print = 0.0

        try:
            from rich.live import Live
            with Live(
                build_display(self._all_collected_news, 0, self._total_in_db, 0,
                              self._source_stats, interval, "启动中...", web_port=web_port),
                console=console,
                refresh_per_second=4,
                screen=True,
            ) as live:
                await self._run_cycles(interval, live_render, catch_up_needed)
        except Exception:
            restore_logging()
            logging.warning("Live 显示模式异常，降级为简单轮询模式", exc_info=True)
            await self._run_cycles(interval, simple_render, catch_up_needed)
        finally:
            restore_logging()
            db_set_last_exit_ts(int(time.time()))

    def shutdown(self):
        """停止监控"""
        self._shutdown_event.set()

    @property
    def all_collected_news(self) -> List[NewsItem]:
        """获取所有收集的新闻"""
        return self._all_collected_news

    @property
    def source_stats(self) -> Dict[str, int]:
        """获取各源统计"""
        return self._source_stats

    @property
    def total_in_db(self) -> int:
        """获取数据库总条数"""
        return self._total_in_db