#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""全局配置管理

支持环境变量覆盖，所有默认配置集中在此处。
环境变量前缀: FINFEED_
例如: FINFEED_WEB_PORT=9000 覆盖 DEFAULT_WEB_PORT
"""

import os
from typing import Dict, Optional, Any


def _get_env(name: str, default: Any, type_cast: type = str) -> Any:
    """从环境变量获取配置，支持类型转换"""
    val = os.environ.get(f"FINFEED_{name}")
    if val is None:
        return default
    try:
        if type_cast is bool:
            return val.lower() in ("1", "true", "yes", "on")
        return type_cast(val)
    except (ValueError, TypeError):
        return default


# ============================================================
# Web 仪表盘配置
# ============================================================
DEFAULT_WEB_PORT: int = _get_env("WEB_PORT", 8866, int)

# ============================================================
# 抓取配置
# ============================================================
DEFAULT_INTERVAL: int = _get_env("INTERVAL", 5, int)
MAX_NEWS_CACHE: int = 500
FETCH_CONCURRENCY: int = _get_env("FETCH_CONCURRENCY", 6, int)

SOURCE_RATE_LIMITS: Dict[str, float] = {}

# ============================================================
# 数据库配置
# ============================================================
DB_FILENAME: str = _get_env("DB_FILENAME", "news_monitor.db")
DB_PATH: str = _get_env(
    "DB_PATH",
    os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), DB_FILENAME),
)

USE_WAL_MODE: bool = _get_env("USE_WAL_MODE", True, bool)

# ============================================================
# 日志配置
# ============================================================
LOG_FILENAME: str = _get_env("LOG_FILENAME", "finfeed.log")
LOG_LEVEL: str = _get_env("LOG_LEVEL", "INFO")
LOG_PATH: str = _get_env(
    "LOG_PATH",
    os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), LOG_FILENAME),
)
LOG_MAX_BYTES: int = 10 * 1024 * 1024
LOG_BACKUP_COUNT: int = 5

# ============================================================
# 分级调度配置
# ============================================================
SOURCE_TIERS: Dict[str, int] = {
    "新浪财经": 1, "金十数据": 1, "格隆汇快讯": 1,
    "雪球": 6, "格隆汇文章": 6, "法布财经": 6,
    "21经济网": 12, "第一财经": 6,
}

# ============================================================
# 来源超时配置
# ============================================================
SOURCE_TIMEOUTS: Dict[str, float] = {
    "雪球": 12.0,
    "金十数据": 10.0,
    "格隆汇文章": 12.0,
    "格隆汇快讯": 10.0,
    "法布财经": 12.0,
    "微博财经热搜": 8.0,
    "东财人气榜": 10.0,
    "热门股吧": 15.0,
    "东财股吧热帖": 15.0,
    "同花顺论股堂": 12.0,
    "新浪股吧": 12.0,
}
DEFAULT_TIMEOUT: float = 8.0

# ============================================================
# 来源显示名称映射（多个内部源共享同一显示标签）
# ============================================================
SOURCE_DISPLAY_NAMES: Dict[str, str] = {
    "格隆汇文章": "格隆汇",
    "格隆汇快讯": "格隆汇",
    "东财人气榜": "东方财富",
    "热门股吧": "东方财富",
    "东财股吧热帖": "东方财富",
    "同花顺论股堂": "同花顺",
    "新浪股吧": "新浪财经",
}

# ============================================================
# 来源颜色配置（终端和 Web 使用）
# ============================================================
SOURCE_COLORS: Dict[str, str] = {
    "新浪财经": "#55aaff",
    "东方财富": "#ff9500",
    "同花顺": "#e74c3c",
    "21经济网": "#0078ff",
    "金十数据": "#ff9500",
    "格隆汇": "#68af00",
    "法布财经": "#00a0e9",
    "第一财经": "#c41e3a",
    "微博财经热搜": "#e6162d",
}

SOURCE_SKIP_REQ_TRACE = set()

# ============================================================
# 离线补抓配置
# ============================================================
MAX_CATCH_UP_CYCLES: int = 10
CATCH_UP_INTERVAL: int = 2
CATCH_UP_CYCLE_INTERVAL: int = 3
OFFLINE_GAP_THRESHOLD: int = 60
CATCH_UP_MAX_DAYS: int = 7

CATCH_UP_CONCURRENCY: int = 2
CATCH_UP_BATCH_SIZE: int = 50
CATCH_UP_MIN_INTERVAL: int = 3
CATCH_UP_SOURCES_PER_CYCLE: int = 3

# ============================================================
# 断路器配置
# ============================================================
CIRCUIT_BREAKER_FAILURE_THRESHOLD: int = 5
CIRCUIT_BREAKER_RECOVERY_TIME: int = 300

# ============================================================
# API缓存配置
# ============================================================
API_CACHE_TTL: int = 2


def get_source_tier(source_name: str) -> int:
    return SOURCE_TIERS.get(source_name, 1)


def should_skip_source(source_name: str, cycle: int) -> bool:
    tier = get_source_tier(source_name)
    if tier <= 1:
        return False
    return cycle % tier != 0


def get_source_timeout(source_name: str) -> float:
    return SOURCE_TIMEOUTS.get(source_name, DEFAULT_TIMEOUT)


def get_display_name(internal_name: str) -> str:
    return SOURCE_DISPLAY_NAMES.get(internal_name, internal_name)


def get_source_color(source_name: str) -> str:
    return SOURCE_COLORS.get(source_name, "#aaaaaa")
