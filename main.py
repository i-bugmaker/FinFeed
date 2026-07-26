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
import argparse
import asyncio

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from finfeed.config.settings import (
    DEFAULT_WEB_PORT, DEFAULT_INTERVAL,
)
from finfeed.storage.database import init_db, db_set_last_exit_ts
from finfeed.storage.exporter import export_to_json, export_to_csv, export_to_excel, export_to_markdown, get_default_export_path
from finfeed.core.monitor import get_monitor
from finfeed.ui.terminal import print_once_result, TerminalUI
from finfeed.ui.web.server import start_web_server, stop_web_server


async def run_once():
    """单次抓取模式"""
    monitor = get_monitor()
    total_new = await monitor.run_single_fetch()
    return total_new


async def run_continuous(interval: int, web_port: int):
    """持续监控模式（带TUI）"""
    monitor = get_monitor()
    terminal_ui = TerminalUI(interval=interval, web_port=web_port)
    
    shutdown_event = asyncio.Event()
    
    def signal_handler():
        shutdown_event.set()
    
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            signal.signal(sig, lambda s, f: signal_handler())
        except (ValueError, OSError):
            pass
    
    from finfeed.storage.database import db_get_recent_news, db_get_statistics, db_get_all_source_last_ts
    
    async def update_tui():
        while not shutdown_event.is_set():
            try:
                news = db_get_recent_news(limit=50, category="finance")
                stats = db_get_statistics()
                source_last_ts = db_get_all_source_last_ts()
                source_stats = {}
                for src in source_last_ts:
                    source_stats[src] = source_stats.get(src, 0) + 1
                
                status = "运行中" if monitor.is_running else "准备中"
                if monitor.fetch_count > 0:
                    status = f"第{monitor.fetch_count}轮"
                
                terminal_ui.update_data(
                    news_list=news,
                    cycle=monitor.fetch_count,
                    total_news=stats.get("total", 0),
                    new_count=monitor.total_new_count,
                    source_stats=source_stats,
                    status=status,
                )
            except Exception:
                pass
            await asyncio.sleep(5)
    
    tui_task = asyncio.create_task(terminal_ui.run())
    update_task = asyncio.create_task(update_tui())
    monitor_task = asyncio.create_task(monitor.run())
    
    await shutdown_event.wait()
    
    terminal_ui.stop()
    await monitor.shutdown()
    
    monitor_task.cancel()
    try:
        await monitor_task
    except asyncio.CancelledError:
        pass
    
    tui_task.cancel()
    try:
        await tui_task
    except asyncio.CancelledError:
        pass
    
    update_task.cancel()
    try:
        await update_task
    except asyncio.CancelledError:
        pass
    
    stop_web_server()
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
        monitor = get_monitor()

        def signal_handler(sig, frame):
            asyncio.get_event_loop().call_soon_threadsafe(
                lambda: asyncio.create_task(monitor.shutdown())
            )

        try:
            for sig in (signal.SIGINT, signal.SIGTERM):
                try:
                    signal.signal(sig, signal_handler)
                except (ValueError, OSError):
                    pass

            web_server = start_web_server(port=args.port)

            if args.once:
                total_new = asyncio.run(run_once())
                print_once_result([], total_new, 0, 0)
            else:
                asyncio.run(run_continuous(interval=args.interval, web_port=args.port))

        except KeyboardInterrupt:
            print(f"\n监控已停止。数据已持久化。")
        finally:
            if not args.once:
                stop_web_server()
            db_set_last_exit_ts(int(time.time()))


if __name__ == "__main__":
    main()
