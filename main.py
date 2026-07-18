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

from config.settings import (
    DEFAULT_WEB_PORT, DEFAULT_INTERVAL, LOG_PATH, LOG_LEVEL,
)
from storage.database import init_db, db_set_last_exit_ts
from storage.exporter import export_to_json, export_to_csv, export_to_excel, export_to_markdown, get_default_export_path
from core.monitor import MonitorManager
from ui.terminal import print_once_result
from ui.web.server import start_web_server

logger = logging.getLogger("news_monitor")


def setup_logging():
    """配置日志"""
    file_handler = logging.FileHandler(LOG_PATH, encoding="utf-8")
    file_handler.setFormatter(
        logging.Formatter("%(asctime)s [%(levelname)s] %(message)s", "%Y-%m-%d %H:%M:%S")
    )
    root_logger = logging.getLogger()
    root_logger.addHandler(file_handler)
    root_logger.setLevel(getattr(logging, LOG_LEVEL, logging.WARNING))


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
        monitor = MonitorManager()

        def signal_handler(sig, frame):
            logger.info(f"收到信号 {sig}，准备优雅关闭...")
            monitor.shutdown()

        try:
            for sig in (signal.SIGINT, signal.SIGTERM):
                signal.signal(sig, signal_handler)

            web_server = start_web_server(port=args.port)

            if args.once:
                total_inserted, total_news, catch_up_cycles = asyncio.run(monitor.run_once())
                print_once_result(monitor.all_collected_news, total_inserted, monitor.total_in_db, catch_up_cycles)
            else:
                asyncio.run(monitor.run_continuous(interval=args.interval, web_port=args.port))

        except KeyboardInterrupt:
            logging.info("\n用户中断，正在退出...")
            print(f"\n监控已停止。数据已持久化。")
        finally:
            db_set_last_exit_ts(int(time.time()))
            if web_server:
                web_server.shutdown()


if __name__ == "__main__":
    main()