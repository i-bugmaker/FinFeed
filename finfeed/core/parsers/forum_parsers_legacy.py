#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""论坛舆情解析器（LEGACY - 已迁移至 forum_parsers/ 包）

本文件已不再使用。所有解析器已迁移至：
- forum_parsers/base.py : BrowserManager + 基类
- forum_parsers/eastmoney.py : 东方财富系列解析器
- forum_parsers/sina.py : 新浪股吧解析器
- forum_parsers/ths.py : 同花顺相关解析器
- forum_parsers/weibo.py : 微博财经热搜解析器

保留此文件仅为向后兼容，无实际功能代码。
"""

import logging

logger = logging.getLogger("news_monitor")
logger.debug("forum_parsers_legacy 已废弃，使用 forum_parsers 包")
