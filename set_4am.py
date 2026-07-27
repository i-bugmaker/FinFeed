#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""重置补抓状态工具

将 last_exit_ts 重置到指定时间，下次启动程序时将触发从该时间开始的补抓。
默认重置到"今天 04:00 北京时间"。

用法:
    python set_4am.py                  # 重置到今天 04:00
    python set_4am.py --date 2026-07-26 # 重置到指定日期 04:00
    python set_4am.py --clear           # 同时清空 source_last_ts（强制全量补抓）

依赖 settings.DB_PATH 自动读取实际数据库路径，无需硬编码。
"""

import argparse
import sys
import os
import sqlite3
import time
from datetime import datetime, timedelta, timezone

TZ_BJ = timezone(timedelta(hours=8))

# 加入项目根目录以导入 settings
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
try:
    from finfeed.config.settings import DB_PATH
except ImportError:
    DB_PATH = "news_monitor.db"


def reset(to_ts: int, clear_source_ts: bool = False) -> None:
    """重置 last_exit_ts 到 to_ts

    Args:
        to_ts: 目标时间戳（秒）
        clear_source_ts: 是否同时清空 source_last_ts 表
    """
    conn = sqlite3.connect(DB_PATH)
    try:
        c = conn.cursor()
        c.execute(
            "INSERT OR REPLACE INTO metadata (key, value) VALUES ('last_exit_ts', ?)",
            (str(to_ts),),
        )
        bj_str = datetime.fromtimestamp(to_ts, TZ_BJ).strftime("%Y-%m-%d %H:%M:%S")
        print(f"设置 last_exit_ts = {to_ts} -> {bj_str} (北京时间)")

        if clear_source_ts:
            c.execute("DELETE FROM source_last_ts")
            print("已清空 source_last_ts 表")
    finally:
        conn.commit()
        conn.close()


def main():
    parser = argparse.ArgumentParser(description="重置 FinFeed 补抓状态")
    parser.add_argument(
        "--date", "-d",
        help="目标日期 (YYYY-MM-DD)，默认今天。时间会被设置为该日 04:00 北京时间",
    )
    parser.add_argument(
        "--clear", action="store_true",
        help="同时清空 source_last_ts 表（强制全量补抓）",
    )
    parser.add_argument(
        "--hour", type=int, default=4,
        help="目标小时（默认 4，即 04:00）",
    )
    args = parser.parse_args()

    # 计算目标时间戳
    if args.date:
        try:
            target_date = datetime.strptime(args.date, "%Y-%m-%d")
        except ValueError:
            print(f"日期格式错误: {args.date}，应为 YYYY-MM-DD")
            sys.exit(1)
    else:
        target_date = datetime.now(TZ_BJ)
    target_dt = target_date.replace(
        hour=args.hour, minute=0, second=0, microsecond=0,
        tzinfo=TZ_BJ if target_date.tzinfo is None else target_date.tzinfo,
    )
    to_ts = int(target_dt.timestamp())
    reset(to_ts, clear_source_ts=args.clear)
    print(f"完成。DB 路径: {DB_PATH}")


if __name__ == "__main__":
    main()
