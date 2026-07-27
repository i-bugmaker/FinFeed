#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""重置补抓状态工具（等价于 set_4am.py --clear）

将 last_exit_ts 重置到"今天 04:00 北京时间"并清空 source_last_ts，
下次启动程序时将触发从 04:00 开始的全量补抓。

这是 set_4am.py 的快捷别名，等价于:
    python set_4am.py --clear

依赖 settings.DB_PATH 自动读取实际数据库路径，无需硬编码。
"""

import sys
import os

# 复用 set_4am.py 的实现
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from set_4am import reset
from datetime import datetime, timezone, timedelta

TZ_BJ = timezone(timedelta(hours=8))


def main():
    # 默认重置到今天 04:00，并清空 source_last_ts
    now = datetime.now(TZ_BJ)
    target_dt = now.replace(hour=4, minute=0, second=0, microsecond=0)
    if now.hour < 4:
        # 若当前在 04:00 之前，使用昨天 04:00
        target_dt = target_dt - timedelta(days=1)
    to_ts = int(target_dt.timestamp())
    reset(to_ts, clear_source_ts=True)


if __name__ == "__main__":
    main()
