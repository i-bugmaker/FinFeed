#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""财经日历模块

整合东方财富四大日历数据源，提供统一的按日期查询能力：

    finance  财经日历中心   https://data.eastmoney.com/cjrl/default.html
    stock    股市日历       https://data.eastmoney.com/gsrl/default.html
    ipo      新股申购日历   https://data.eastmoney.com/xg/xg/calendar.html
    global   全球经济日历   https://forex.eastmoney.com/FC.html

模块自洽，不侵入 news 表与抓取主循环：
  - 独立数据表 calendar_events / calendar_sync（复用主库连接）
  - 独立异步抓取器，按「日」为粒度增量同步 + TTL 缓存
  - 以前缀路由 /api/calendar/* 挂载到 Web 服务

对外入口：
    from finfeed.ecal import api as calendar_api
    api.handle_get(path, query_dict)  -> (status, dict) | None
    api.handle_post(path, json_body)  -> (status, dict) | None
"""

from .sources import (
    CAL_TYPES,
    FINANCE_CATEGORIES,
    STOCK_CATEGORIES,
    IPO_CATEGORIES,
    GLOBAL_COUNTRIES,
    IMPORTANCE_LABELS,
)
from .models import CalendarEvent
from .schema import ensure_tables

__all__ = [
    "CAL_TYPES",
    "FINANCE_CATEGORIES",
    "STOCK_CATEGORIES",
    "IPO_CATEGORIES",
    "GLOBAL_COUNTRIES",
    "IMPORTANCE_LABELS",
    "CalendarEvent",
    "ensure_tables",
]
