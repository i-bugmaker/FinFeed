#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
FinFeed 实时新闻监控 - 主入口
===============================
模块化架构的新闻抓取、分析、推送系统。

用法:
    python main.py                     # 启动实时监控
    python main.py --interval 60       # 自定义抓取间隔
    python main.py --once              # 只抓取一次
    python main.py --export json       # 导出所有新闻为JSON
    python main.py --export csv        # 导出所有新闻为CSV
"""

import os
import sys
import time
import signal
import logging
import argparse
import asyncio
from typing import Optional

from config.settings import (
    DEFAULT_WEB_PORT, DEFAULT_INTERVAL, MAX_NEWS_CACHE,
    MAX_CATCH_UP_CYCLES, CATCH_UP_INTERVAL, OFFLINE_GAP_THRESHOLD,
    LOG_PATH, LOG_LEVEL,
)
from storage.database import (
    init_db, db_get_recent_news, db_count_news,
    db_get_last_exit_ts, db_set_last_exit_ts,
)
from storage.exporter import export_to_json, export_to_csv, export_to_excel, export_to_markdown, get_default_export_path
from core.pipeline import get_pipeline
from core.fetcher import set_parser_last_ts, init_all_parsers
from core.health import get_health_monitor
from ui.terminal import (
    console, build_display, build_news_table,
    print_once_result,
)
from ui.web.server import start_web_server, update_web_state
from utils.common import jitter_interval

from rich.live import Live

logger = logging.getLogger("news_monitor")

_shutdown_event = asyncio.Event()


def _setup_signal_handlers(loop: asyncio.AbstractEventLoop):
    """设置信号处理器，支持优雅关闭"""
    def _signal_handler(sig, frame):
        logger.info(f"收到信号 {sig}，准备优雅关闭...")
        _shutdown_event.set()

    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, _signal_handler, sig, None)
        except NotImplementedError:
            signal.signal(sig, _signal_handler)


def _merge_news_list(existing: list, new_items: list, max_count: int) -> list:
    """合并新闻列表，去重并保持按时间倒序"""
    if not new_items:
        return existing
    if not existing:
        return new_items[:max_count]

    seen_titles = {n.title for n in existing}
    unique_new = [n for n in new_items if n.title not in seen_titles]
    if not unique_new:
        return existing

    merged = unique_new + existing
    merged.sort(key=lambda x: x.publish_ts, reverse=True)
    return merged[:max_count]


def _setup_catch_up(last_exit_ts: int) -> tuple[bool, str]:
    """设置离线补抓状态"""
    now_ts = int(time.time())
    offline_gap_sec = max(0, now_ts - last_exit_ts) if last_exit_ts > 0 else 0
    catch_up_needed = offline_gap_sec > OFFLINE_GAP_THRESHOLD
    catch_up_status = ""

    if catch_up_needed:
        from config.sources import get_enabled_sources, THSYC_CHANNELS
        from core.fetcher import _parsers

        for src in get_enabled_sources():
            set_parser_last_ts(src.name, last_exit_ts)

        if "同花顺原创" in _parsers:
            parser = _parsers["同花顺原创"]
            if hasattr(parser, '_channel_last_ts'):
                for ch in THSYC_CHANNELS:
                    parser._channel_last_ts[ch["name"]] = last_exit_ts

        gap_min = int(offline_gap_sec // 60)
        gap_hour = gap_min // 60
        if gap_hour > 0:
            catch_up_status = f"离线 {gap_hour}h{gap_min % 60}min，正在补抓..."
        else:
            catch_up_status = f"离线 {gap_min}min，正在补抓..."

    return catch_up_needed, catch_up_status


def setup_logging():
    """配置日志"""
    file_handler = logging.FileHandler(LOG_PATH, encoding="utf-8")
    file_handler.setFormatter(
        logging.Formatter("%(asctime)s [%(levelname)s] %(message)s", "%Y-%m-%d %H:%M:%S")
    )
    root_logger = logging.getLogger()
    root_logger.addHandler(file_handler)
    root_logger.setLevel(getattr(logging, LOG_LEVEL, logging.WARNING))


async def monitor_loop(interval: int = 5, once: bool = False, web_port: int = DEFAULT_WEB_PORT):
    """主监控循环"""
    cycle = 0
    all_collected_news = []
    source_stats = {}
    total_in_db = 0
    last_new_count = 0

    pipeline = get_pipeline()
    health_monitor = get_health_monitor()
    health_monitor.load_from_db()
    init_all_parsers()

    try:
        total_in_db = db_count_news()
    except Exception:
        pass

    all_collected_news = db_get_recent_news(limit=MAX_NEWS_CACHE)

    _last_exit_ts = db_get_last_exit_ts()
    _now_ts = int(time.time())
    _offline_gap_sec = max(0, _now_ts - _last_exit_ts) if _last_exit_ts > 0 else 0
    _catch_up_needed = _offline_gap_sec > OFFLINE_GAP_THRESHOLD
    _catch_up_status = ""

    if _catch_up_needed:
        from config.sources import get_enabled_sources
        for src in get_enabled_sources():
            set_parser_last_ts(src.name, _last_exit_ts)
        from config.sources import THSYC_CHANNELS
        from core.fetcher import _parsers
        if "同花顺原创" in _parsers:
            parser = _parsers["同花顺原创"]
            if hasattr(parser, '_channel_last_ts'):
                for ch in THSYC_CHANNELS:
                    parser._channel_last_ts[ch["name"]] = _last_exit_ts
        gap_min = int(_offline_gap_sec // 60)
        gap_hour = gap_min // 60
        if gap_hour > 0:
            _catch_up_status = f"离线 {gap_hour}h{gap_min % 60}min，正在补抓..."
        else:
            _catch_up_status = f"离线 {gap_min}min，正在补抓..."

    update_web_state(
        all_collected_news, source_stats, 0, total_in_db,
        0, _catch_up_status or "抓取中..."
    )

    _last_exit_save_ts = 0

    if once:
        _once_max_cycles = MAX_CATCH_UP_CYCLES if _catch_up_needed else 1
        _once_total_inserted = 0
        for _oc in range(_once_max_cycles):
            all_news, stats, inserted = await pipeline.run_cycle(cycle=_oc + 1)
            _once_total_inserted += inserted
            source_stats = stats
            all_collected_news.extend(all_news)
            all_collected_news.sort(key=lambda x: x.publish_ts, reverse=True)
            seen = set()
            unique_news = []
            for n in all_collected_news:
                if n.title not in seen:
                    seen.add(n.title)
                    unique_news.append(n)
            all_collected_news = unique_news[:MAX_NEWS_CACHE]
            total_in_db += inserted
            if inserted == 0 and _oc > 0:
                break
        last_new_count = _once_total_inserted
        db_set_last_exit_ts(int(time.time()))

        print_once_result(
            all_collected_news, _once_total_inserted, total_in_db,
            _once_max_cycles if _catch_up_needed else 0
        )
        return

    async def _run_cycles(render):
        nonlocal cycle, all_collected_news, source_stats, total_in_db, last_new_count
        nonlocal _last_exit_save_ts

        _cached_table = None
        _last_table_key = ""

        def _rebuild_table_if_needed(news, force=False):
            nonlocal _cached_table, _last_table_key
            term_w, term_h = console.size
            key = f"{len(news)}|{news[0].title if news else ''}|{term_w}x{term_h}"
            if force or key != _last_table_key:
                _last_table_key = key
                max_rows = max(10, term_h - 12)
                _cached_table = build_news_table(news, max_rows=max_rows)
            return _cached_table

        if _catch_up_needed:
            catch_up_total = 0
            for cu_cycle in range(1, MAX_CATCH_UP_CYCLES + 1):
                table = _rebuild_table_if_needed(all_collected_news, force=True)
                cu_status = f"补抓 {cu_cycle}/{MAX_CATCH_UP_CYCLES} | 已补 {catch_up_total} 条"
                render(all_collected_news, 0, total_in_db, 0, source_stats, interval, cu_status, table)

                all_news, stats, inserted = await pipeline.run_cycle(cycle=cu_cycle)
                catch_up_total += inserted
                source_stats = stats

                if all_news:
                    seen_titles = {n.title for n in all_collected_news}
                    new_items = [n for n in all_news if n.title not in seen_titles]
                    if new_items:
                        new_items.sort(key=lambda x: x.publish_ts, reverse=True)
                        all_collected_news = new_items + [
                            n for n in all_collected_news
                            if n.title not in {x.title for x in new_items}
                        ]
                        all_collected_news.sort(key=lambda x: x.publish_ts, reverse=True)
                if len(all_collected_news) > MAX_NEWS_CACHE:
                    all_collected_news = all_collected_news[:MAX_NEWS_CACHE]
                total_in_db += inserted

                cu_status2 = f"补抓 {cu_cycle}/{MAX_CATCH_UP_CYCLES} | 本轮 +{inserted} | 累计 +{catch_up_total}"
                table = _rebuild_table_if_needed(all_collected_news, force=True)
                render(all_collected_news, 0, total_in_db, catch_up_total, source_stats, interval, cu_status2, table)
                update_web_state(all_collected_news, source_stats, 0, total_in_db, catch_up_total, cu_status2)

                if inserted == 0 and cu_cycle > 1:
                    break
                await asyncio.sleep(CATCH_UP_INTERVAL)

            _last_exit_save_ts = int(time.time())
            db_set_last_exit_ts(_last_exit_save_ts)

        while True:
            cycle += 1
            table = _rebuild_table_if_needed(all_collected_news, force=True)
            render(all_collected_news, cycle, total_in_db, 0, source_stats, interval, "抓取中...", table)

            fetch_task = asyncio.create_task(pipeline.run_cycle(cycle=cycle))
            _last_fetch_sec = -1
            while not fetch_task.done():
                await asyncio.sleep(0.5)
                _old_key = _last_table_key
                _rebuild_table_if_needed(all_collected_news)
                cur_sec = int(time.time())
                if cur_sec != _last_fetch_sec or _last_table_key != _old_key:
                    _last_fetch_sec = cur_sec
                    render(all_collected_news, cycle, total_in_db, last_new_count, source_stats, interval, "抓取中...", _cached_table)
            all_news, stats, inserted = fetch_task.result()
            source_stats = stats

            if all_news:
                seen_titles = {n.title for n in all_collected_news}
                new_items = [n for n in all_news if n.title not in seen_titles]
                if new_items:
                    new_items.sort(key=lambda x: x.publish_ts, reverse=True)
                    all_collected_news = new_items + [
                        n for n in all_collected_news
                        if n.title not in {x.title for x in new_items}
                    ]
                    all_collected_news.sort(key=lambda x: x.publish_ts, reverse=True)
            if len(all_collected_news) > MAX_NEWS_CACHE:
                all_collected_news = all_collected_news[:MAX_NEWS_CACHE]
            total_in_db += inserted
            last_new_count = inserted

            _now_ts = int(time.time())
            if _now_ts - _last_exit_save_ts >= 60:
                _last_exit_save_ts = _now_ts
                db_set_last_exit_ts(_now_ts)

            wait_sec = jitter_interval(interval)
            status = f"新增{inserted}条" if inserted > 0 else "无新内容"
            update_web_state(
                all_collected_news, source_stats, cycle, total_in_db,
                last_new_count, f"{status} | {wait_sec:.1f}s后一轮"
            )

            wait_end = time.time() + wait_sec
            table = _rebuild_table_if_needed(all_collected_news, force=True)
            render(all_collected_news, cycle, total_in_db, last_new_count, source_stats, interval,
                   f"{status} | {wait_sec:.0f}s后一轮", table)
            _last_wait_sec = -1
            while time.time() < wait_end:
                await asyncio.sleep(0.5)
                _rebuild_table_if_needed(all_collected_news)
                cur_sec = int(time.time())
                if cur_sec != _last_wait_sec:
                    _last_wait_sec = cur_sec
                    remaining = max(0, wait_end - time.time())
                    render(all_collected_news, cycle, total_in_db, last_new_count, source_stats, interval,
                           f"{status} | {remaining:.0f}s后一轮", _cached_table)

    _live_simple_last_print = 0.0

    def _live_render(news, cyc, total, new_ct, stats, itv, st, table):
        live.update(build_display(news, cyc, total, new_ct, stats, itv, st, web_port=web_port, table=table))

    def _simple_render(news, cyc, total, new_ct, stats, itv, st, table):
        nonlocal _live_simple_last_print
        now = time.time()
        if now - _live_simple_last_print >= 10:
            _live_simple_last_print = now
            console.clear()
            console.print(build_display(news, cyc, total, new_ct, stats, itv, st, web_port=web_port, table=table))

    _root_logger = logging.getLogger()
    _root_orig_handlers = list(_root_logger.handlers)
    _nm_logger = logging.getLogger("news_monitor")
    _nm_orig_handlers = list(_nm_logger.handlers)
    _nm_orig_propagate = _nm_logger.propagate

    _logging_restored = False

    def _restore_logging():
        nonlocal _logging_restored
        if _logging_restored:
            return
        _logging_restored = True
        for h in list(_root_logger.handlers):
            _root_logger.removeHandler(h)
        for h in _root_orig_handlers:
            _root_logger.addHandler(h)
        for h in list(_nm_logger.handlers):
            _nm_logger.removeHandler(h)
        for h in _nm_orig_handlers:
            _nm_logger.addHandler(h)
        _nm_logger.propagate = _nm_orig_propagate

    try:
        with Live(
            build_display(all_collected_news, 0, total_in_db, 0, source_stats, interval, "启动中...", web_port=web_port),
            console=console,
            refresh_per_second=4,
            screen=True,
        ) as live:
            await _run_cycles(_live_render)
    except Exception:
        _restore_logging()
        logging.warning("Live 显示模式异常，降级为简单轮询模式", exc_info=True)
        await _run_cycles(_simple_render)
    finally:
        _restore_logging()
        db_set_last_exit_ts(int(time.time()))


def main():
    parser = argparse.ArgumentParser(
        description="FinFeed 实时新闻监控",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  python main.py                      # 启动实时监控
  python main.py --interval 60        # 每60秒抓取一次
  python main.py --once               # 只抓取一次
  python main.py --export json        # 导出为JSON
  python main.py --export csv         # 导出为CSV
  python main.py --export json --start 2024-01-01 --end 2024-01-31
        """
    )
    parser.add_argument("--port", type=int, default=DEFAULT_WEB_PORT, help=f"Web 仪表盘端口（默认 {DEFAULT_WEB_PORT}）")
    parser.add_argument("--interval", type=int, default=DEFAULT_INTERVAL, help=f"抓取间隔（秒），默认{DEFAULT_INTERVAL}")
    parser.add_argument("--once", action="store_true", help="只抓取一次后退出")
    parser.add_argument("--export", choices=["json", "csv", "excel", "markdown", "md"], help="导出格式 (json/csv/excel/markdown)")
    parser.add_argument("--output", "-o", help="导出文件路径（默认自动生成）")
    parser.add_argument("--start", help="导出起始日期 (YYYY-MM-DD)")
    parser.add_argument("--end", help="导出截止日期 (YYYY-MM-DD)")

    args = parser.parse_args()

    init_db()
    setup_logging()

    if args.export:
        fmt = "markdown" if args.export == "md" else args.export
        output_path = args.output or get_default_export_path(fmt)
        if fmt == "json":
            count = export_to_json(output_path, args.start, args.end)
        elif fmt == "csv":
            count = export_to_csv(output_path, args.start, args.end)
        elif fmt == "excel":
            count = export_to_excel(output_path, args.start, args.end)
        elif fmt == "markdown":
            count = export_to_markdown(output_path, args.start, args.end)
        else:
            count = 0
        print(f"\n导出完成: {count} 条新闻已保存到 {output_path}")
    else:
        web_server = None
        try:
            web_server = start_web_server(port=args.port)
            asyncio.run(monitor_loop(interval=args.interval, once=args.once, web_port=args.port))
        except KeyboardInterrupt:
            logging.info("\n用户中断，正在退出...")
            print(f"\n监控已停止。数据已持久化。")
        finally:
            db_set_last_exit_ts(int(time.time()))
            if web_server:
                web_server.shutdown()


if __name__ == "__main__":
    main()
