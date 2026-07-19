#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""全局配置管理

所有默认配置集中在此处，后续可扩展支持 YAML 配置文件、环境变量覆盖等。
"""

import os

# ============================================================
# Web 仪表盘配置
# ============================================================
DEFAULT_WEB_PORT = 8866

# ============================================================
# 抓取配置
# ============================================================
DEFAULT_INTERVAL = 5
MAX_NEWS_CACHE = 500
FETCH_CONCURRENCY = 6

# 每个源的最小请求间隔（秒），0 表示不限速
SOURCE_RATE_LIMITS: dict[str, float] = {}

# ============================================================
# 数据库配置
# ============================================================
DB_FILENAME = "news_monitor.db"
DB_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), DB_FILENAME)

# 增量哈希加载：只加载最近 N 天的哈希，更早数据用数据库查询兜底
DEDUP_RECENT_DAYS = 7

# SQLite WAL 模式
USE_WAL_MODE = True

# ============================================================
# 去重配置
# ============================================================
# 语义去重汉明距离阈值（越小越严格，3是经验值）
SIMHASH_THRESHOLD = 3
# 是否启用语义去重
ENABLE_SEMANTIC_DEDUP = True

# ============================================================
# 日志配置
# ============================================================
LOG_FILENAME = "news_monitor.log"
LOG_LEVEL = "WARNING"
LOG_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), LOG_FILENAME)

# ============================================================
# 分级调度配置
# ============================================================
# fast(1)=每轮, medium(6)=每6轮, slow(12)=每12轮
SOURCE_TIERS: dict[str, int] = {
    "新浪财经": 1, "财联社": 1, "同花顺": 1, "东方财富": 1,
    "华尔街见闻": 1, "金十数据": 1, "格隆汇快讯": 1,
    "雪球": 6, "格隆汇文章": 6, "法布财经": 6,
    "同花顺原创": 6, "巨潮公告": 6, "企查查": 6,
    "雅虎财经": 12, "21经济网": 12, "cnBeta": 12,
}

# ============================================================
# 来源超时配置
# ============================================================
SOURCE_TIMEOUTS: dict[str, float] = {
    "雪球": 12.0,
    "金十数据": 10.0,
    "格隆汇文章": 12.0,
    "格隆汇快讯": 10.0,
    "法布财经": 12.0,
    "同花顺原创": 15.0,
    "巨潮公告": 12.0,
}
DEFAULT_TIMEOUT = 8.0

# ============================================================
# 来源显示名称映射（多个内部源共享同一显示标签）
# ============================================================
SOURCE_DISPLAY_NAMES: dict[str, str] = {
    "格隆汇文章": "格隆汇",
    "格隆汇快讯": "格隆汇",
}

# ============================================================
# 来源颜色配置（终端和 Web 使用）
# ============================================================
SOURCE_COLORS: dict[str, str] = {
    "新浪财经": "#55aaff",
    "财联社": "#ff3b30",
    "同花顺": "red",
    "东方财富": "#ff9500",
    "雅虎财经": "#aaaaaa",
    "21经济网": "#0078ff",
    "华尔街见闻": "#00d4ff",
    "雪球": "#0066ff",
    "金十数据": "#ff9500",
    "格隆汇": "#68af00",
    "法布财经": "#00a0e9",
    "企查查": "magenta",
    "同花顺原创": "#e74c3c",
    "巨潮公告": "#ff6600",
    "cnBeta": "#00b0ff",
}

# ============================================================
# 跳过 req_trace 的源
# ============================================================
SOURCE_SKIP_REQ_TRACE = {"21经济网", "巨潮公告", "格隆汇快讯"}

# ============================================================
# 离线补抓配置
# ============================================================
MAX_CATCH_UP_CYCLES = 10
CATCH_UP_INTERVAL = 1
OFFLINE_GAP_THRESHOLD = 60
CATCH_UP_MAX_DAYS = 7

# ============================================================
# 断路器配置
# ============================================================
# 连续失败 N 次后熔断
CIRCUIT_BREAKER_FAILURE_THRESHOLD = 5
# 熔断后多久尝试恢复（秒）
CIRCUIT_BREAKER_RECOVERY_TIME = 300


def get_source_tier(source_name: str) -> int:
    """获取来源的调度层级"""
    return SOURCE_TIERS.get(source_name, 1)


def should_skip_source(source_name: str, cycle: int) -> bool:
    """判断当前轮次是否跳过该源"""
    tier = get_source_tier(source_name)
    if tier <= 1:
        return False
    return cycle % tier != 0


def get_source_timeout(source_name: str) -> float:
    """获取来源的超时时间"""
    return SOURCE_TIMEOUTS.get(source_name, DEFAULT_TIMEOUT)


def get_display_name(internal_name: str) -> str:
    """获取来源的显示名称"""
    return SOURCE_DISPLAY_NAMES.get(internal_name, internal_name)


def get_source_color(source_name: str) -> str:
    """获取来源的显示颜色"""
    return SOURCE_COLORS.get(source_name, "#aaaaaa")
