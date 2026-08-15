#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""全局配置管理

支持环境变量覆盖，所有默认配置集中在此处。
环境变量前缀: FINFEED_
例如: FINFEED_WEB_PORT=9000 覆盖 DEFAULT_WEB_PORT
"""

import os
from typing import Dict, Any



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
FETCH_CONCURRENCY: int = _get_env("FETCH_CONCURRENCY", 10, int)

SOURCE_RATE_LIMITS: Dict[str, float] = {
    "雪球": 20.0,
    "同花顺股吧": 15.0,
    "百度财经热搜": 30.0,
    "知乎财经热榜": 30.0,
    "淘股吧": 20.0,
    "集思录": 20.0,
}

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
    "新浪财经": 1, "金十数据": 1, "格隆汇快讯": 1, "同花顺原创": 1, "同花顺财经": 1, "新华财经": 1,
    "雪球": 6, "格隆汇文章": 6, "法布财经": 6, "第一财经": 6,
    "21经济网": 12, "中证快讯": 6,
    "同花顺股吧": 1, "百度财经热搜": 6, "知乎财经热榜": 6,
    "淘股吧": 6, "集思录": 6,
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
    "同花顺原创": 20.0,
    "同花顺财经": 20.0,
    "新华财经": 25.0,
    "新浪股吧": 12.0,
    "雪球": 12.0,
    "同花顺股吧": 12.0,
    "百度财经热搜": 10.0,
    "知乎财经热榜": 10.0,
    "淘股吧": 12.0,
    "集思录": 12.0,
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
    "同花顺股吧": "同花顺",
    "新浪股吧": "新浪财经",
    "雪球": "雪球",
    "百度财经热搜": "百度热搜",
    "知乎财经热榜": "知乎",
    "淘股吧": "淘股吧",
    "集思录": "集思录",
}

# ============================================================
# 来源颜色配置（终端和 Web 使用）
# ============================================================
SOURCE_COLORS: Dict[str, str] = {
    "财联社": "#ef4444",
    "新浪财经": "#55aaff",
    "东方财富": "#ff9500",
    "同花顺": "#e74c3c",
    "同花顺原创": "#c0392b",
    "同花顺财经": "#d35400",
    "21经济网": "#0078ff",
    "金十数据": "#ff9500",
    "格隆汇": "#68af00",
    "法布财经": "#00a0e9",
    "第一财经": "#c41e3a",
    "新华财经": "#cc0000",
    "金融界": "#16a085",
    "华尔街见闻": "#2d3748",
    "巨潮公告": "#2563eb",
    "微博财经热搜": "#e6162d",
    "中证快讯": "#005bac",
    "雪球": "#2598d4",
    "百度热搜": "#2932e1",
    "知乎": "#0066ff",
    "淘股吧": "#d2691e",
    "集思录": "#8e44ad",
}

SOURCE_SKIP_REQ_TRACE = set()

# ============================================================
# 多级去重配置
# ============================================================
# 来源优先级：数值越大优先级越高（重复时保留高优先级源）
SOURCE_PRIORITY: Dict[str, int] = {
    "财联社": 100, "金十数据": 98, "新华财经": 95, "新浪财经": 90,
    "东方财富": 88, "同花顺": 86, "同花顺财经": 85, "同花顺原创": 85,
    "华尔街见闻": 82, "21经济网": 80, "第一财经": 80, "中证快讯": 78,
    "上海证券报": 78, "格隆汇快讯": 75, "凤凰财经": 70, "界面新闻": 70,
    "澎湃新闻": 70, "每经网": 70, "和讯网": 68, "格隆汇文章": 65,
    "法布财经": 60, "萝卜投研": 55, "韭研公社": 50, "企查查": 45, "金融界": 55,
    "cnBeta": 40, "雅虎财经": 60,
    "巨潮公告": 95,  # 公告类优先级高，不参与跨源去重
    "雪球": 84, "同花顺股吧": 86, "百度财经热搜": 30, "知乎财经热榜": 30,
    "淘股吧": 82, "集思录": 72,
}
DEFAULT_SOURCE_PRIORITY: int = 50

# 舆情论坛类源（UGC内容不做跨源语义去重，仅精确URL去重）
FORUM_DEDUP_EXEMPT: set = {
    "东财人气榜", "热门股吧", "东财股吧热帖", "同花顺论股堂",
    "微博财经热搜", "新浪股吧",
    "雪球", "同花顺股吧", "百度财经热搜", "知乎财经热榜",
    "淘股吧", "集思录",
}

# 跨源语义去重豁免（新闻类源）
# 这些低优先级、且内容多为转载快讯的信源，若参与跨源语义去重，会被高优先级源
# （财联社/金十数据/东方财富）合并掉，导致其独立时间线长期停滞（如法布财经停在 7-25）。
# 豁免后它们仍做 L1 URL 精确去重，但跳过 L2/L3/L4 跨源语义去重，从而保留自身完整时间线。
# 如需调整，增删此集合中的信源名称即可。
CROSS_SOURCE_DEDUP_EXEMPT: set = {
    "法布财经", "企查查", "萝卜投研", "韭研公社", "金融界",
}

# SimHash 去重阈值（汉明距离 <= 此值判定为语义重复）
# 注：中文短文本使用字符级SimHash，相似新闻距离约10-18，完全不同新闻约28-40
SIMHASH_THRESHOLD: int = 18
# L4 去重：时间窗口（秒）
DEDUP_TIME_WINDOW: int = 600  # 10分钟内
# L4 去重：关键词/股票重合度阈值
DEDUP_KEYWORD_OVERLAP: float = 0.6
# 滑动窗口大小（内存中保留最近N条新闻的simhash用于快速比对）
DEDUP_SLIDING_WINDOW_SIZE: int = 8000
# 滑动窗口时间范围（秒）
DEDUP_SLIDING_WINDOW_TTL: int = 86400  # 24小时

def get_source_priority(source_name: str) -> int:
    return SOURCE_PRIORITY.get(source_name, DEFAULT_SOURCE_PRIORITY)

def is_forum_source(source_name: str) -> bool:
    return source_name in FORUM_DEDUP_EXEMPT


def is_cross_source_exempt(source_name: str) -> bool:
    """信源是否豁免跨源语义去重（保留自身独立时间线）"""
    return source_name in CROSS_SOURCE_DEDUP_EXEMPT

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
