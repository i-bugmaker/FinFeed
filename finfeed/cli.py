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
import logging

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

logger = logging.getLogger("news_monitor")

from finfeed.config.settings import (
    DEFAULT_WEB_PORT, DEFAULT_INTERVAL,
)
from finfeed.storage.database import init_db, db_set_last_exit_ts
from finfeed.storage.exporter import export_to_json, export_to_csv, export_to_excel, export_to_markdown, get_default_export_path
from finfeed.core.monitor import get_monitor
from finfeed.ui.terminal import print_once_result, TerminalUI
from finfeed.ui.web.server import (
    start_web_server, stop_web_server, update_web_state, broadcast_new_news,
)


async def run_once():
    """单次抓取模式"""
    monitor = get_monitor()
    total_new = await monitor.run_single_fetch()
    return total_new


async def run_continuous(interval: int, web_port: int):
    """持续监控模式（带TUI）"""
    monitor = get_monitor()
    terminal_ui = TerminalUI(interval=interval, web_port=web_port)

    from finfeed.storage.database import db_get_recent_news, db_get_statistics, db_get_all_source_last_ts

    def _build_source_stats() -> dict:
        return {src: 1 for src in db_get_all_source_last_ts()}

    async def push_callback(total_new):
        """抓取轮结束后的即时推送。

        增量条目由 broadcast_new_news() 依据数据库自增 id 水位线自行确定，
        这里不再自行猜测「哪几条是新的」——此前用
        db_get_recent_news(limit=total_new) 按 publish_ts 取前 N 条，
        新抓到的条目若发布时间偏旧就会被挤出该窗口，导致 Web 端漏更新。
        """
        try:
            broadcast_new_news()
        except Exception as e:
            logger.error(f"SSE 增量推送失败: {e}", exc_info=True)

        stats = db_get_statistics()
        update_web_state(
            news=[],
            stats=_build_source_stats(),
            cycle=monitor.fetch_count,
            total=stats.get("total", 0),
            new_count=total_new,
            status=f"第{monitor.fetch_count}轮" if monitor.fetch_count > 0 else "运行中",
        )

    monitor.set_push_callback(push_callback)

    shutdown_event = asyncio.Event()

    def _signal_handler(signum, frame):
        shutdown_event.set()

    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            signal.signal(sig, _signal_handler)
        except (ValueError, OSError):
            pass

    async def update_tui():
        while not shutdown_event.is_set():
            try:
                news = db_get_recent_news(limit=200, category="finance")
                stats = db_get_statistics()
                source_stats = _build_source_stats()

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

                update_web_state(
                    news=[],
                    stats=source_stats,
                    cycle=monitor.fetch_count,
                    total=stats.get("total", 0),
                    new_count=monitor.total_new_count,
                    status=status,
                )

                # 兜底对账：push_callback 若因异常/时序问题漏推，这里 5 秒内补齐。
                # broadcast_new_news 幂等（水位线单调），与即时推送并存不会重复。
                broadcast_new_news()
            except Exception as e:
                logger.debug(f"TUI 更新异常: {e}")
            await asyncio.sleep(5)

    tui_task = asyncio.create_task(terminal_ui.run())
    update_task = asyncio.create_task(update_tui())
    monitor_task = asyncio.create_task(monitor.run())

    await shutdown_event.wait()

    terminal_ui.stop()
    await monitor.shutdown()

    for task in (monitor_task, tui_task, update_task):
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

    stop_web_server()
    db_set_last_exit_ts(int(time.time()))


def _setup_logging():
    """配置日志系统"""
    log_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "logs")
    os.makedirs(log_dir, exist_ok=True)
    log_file = os.path.join(log_dir, "finfeed.log")
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(levelname)s - %(message)s',
        handlers=[logging.FileHandler(log_file, encoding='utf-8')],
    )


def _run_market_action(args):
    """事实层 CLI 调度。"""
    from finfeed.market import service as mkt
    from finfeed.analysis import crossref
    from finfeed.market import report as mk_report
    from finfeed.market import alerts as mk_alerts

    mkt.init_market()
    action = args.market
    date = args.date
    if action == "init":
        print("事实层数据表已就绪")
    elif action == "universe":
        res = mkt.run_universe_sync()
        print(f"股票池/板块刷新: {res}")
    elif action == "snapshot":
        res = mkt.run_daily_snapshot_sync(date)
        print(f"盘后快照: {res}")
    elif action == "bars":
        # collect_bars_sync 返回 {codes, done, rows, aborted}，不是行数
        res = mkt.collect_bars_sync(date, args.limit or None)
        msg = (f"日线采集: 计划 {res['codes']} 只 / 完成 {res['done']} 只 / "
               f"写入 {res['rows']} 行")
        if res.get("aborted"):
            msg += "（因 push2his 限流提前中断）"
        print(msg)
    elif action == "backfill":
        n = crossref.run_backfill()
        print(f"news_stock_link 回填 {n} 条")
    elif action == "calibrate":
        rep = crossref.run_calibrate()
        print("情感闭环校准结果:")
        print(f"  样本数: {rep.get('sample')}")
        for label, v in rep.get("by_label", {}).items():
            print(f"  [{label}] n={v['n']} 平均T+1收益={v['avg_ret']} 胜率={v['win_rate']}")
    elif action == "report":
        print(mk_report.run_report(date))
    elif action == "alerts":
        print(mk_alerts.regime_summary(date))
    else:
        print(f"未知事实层指令: {action}")


def main():
    _setup_logging()

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
    parser.add_argument(
        "--market", metavar="ACTION",
        choices=["init", "universe", "snapshot", "bars", "backfill", "calibrate", "report", "alerts"],
        help="事实层指令: init(建表) universe(股票池+板块) snapshot(盘后快照) "
             "bars(日线回补) backfill(历史新闻关联) calibrate(情感校准) report(涨停归因) alerts(市场状态)",
    )
    parser.add_argument("--date", help="事实层指令所用交易日 (YYYY-MM-DD)")
    parser.add_argument("--limit", type=int, default=0, help="bars 回补数量上限")

    args = parser.parse_args()

    init_db()

    if args.market:
        _run_market_action(args)
        return

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
        return

    monitor = get_monitor()

    def _signal_handler(signum, frame):
        asyncio.get_event_loop().call_soon_threadsafe(
            lambda: asyncio.create_task(monitor.shutdown())
        )

    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            signal.signal(sig, _signal_handler)
        except (ValueError, OSError):
            pass

    try:
        start_web_server(port=args.port)

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
