# -*- coding: utf-8 -*-
"""板块分时 —— 配置模块。

集中管理所有可调参数；修改后重启服务生效。
"""

from __future__ import annotations

import os

# --------------------------------------------------------------------------- #
# TDX 行情服务器（连接管理复用 capital_dashboard 的全局单例）
# --------------------------------------------------------------------------- #
TDX_HOST: str | None = os.environ.get("TDX_HOST") or None
TDX_PORT: int = int(os.environ.get("TDX_PORT", "7709"))
TDX_TIMEOUT: float = float(os.environ.get("TDX_TIMEOUT", "8.0"))

# --------------------------------------------------------------------------- #
# 后台自动刷新机制
# --------------------------------------------------------------------------- #
# 交易时段分时/板块列表刷新间隔（秒）。前端提供 15/30/60 档位，默认 30。
REFRESH_INTERVAL: int = int(os.environ.get("SECTOR_MIN_REFRESH_INTERVAL", "30"))

# 非交易时段轮询间隔（秒）：非交易日/收盘后不再高频拉取，仅冷启动补一次数据。
IDLE_INTERVAL: int = int(os.environ.get("SECTOR_MIN_IDLE_INTERVAL", "60"))

# 板块列表缓存刷新周期（秒）——列表涨幅/涨速需周期性更新。
BOARD_LIST_TTL: int = int(os.environ.get("SECTOR_MIN_BOARD_LIST_TTL", "60"))

# 个股池刷新周期（秒）——全市场个股列表(约5500只)成本高，低频刷新。
STOCK_POOL_TTL: int = int(os.environ.get("SECTOR_MIN_STOCK_POOL_TTL", "300"))

# --------------------------------------------------------------------------- #
# 风控与性能
# --------------------------------------------------------------------------- #
# 单屏最大同时展示标的数量上限（避免前端性能过载）。
# 注意：前端 SectorMinuteView.vue 的 MAX_TARGETS 需与本值保持一致。
MAX_TARGETS: int = int(os.environ.get("SECTOR_MIN_MAX_TARGETS", "50"))

# 串行刷新时相邻两个标的的请求间隔（秒），错峰避免瞬间集中请求触发风控。
SLEEP_BETWEEN_REQUESTS: float = float(os.environ.get("SECTOR_MIN_SLEEP", "0.3"))

# 分时简图：单次懒加载抓取数量上限。仅对「未命中缓存」的标的按需抓取，
# 命中 store 缓存时秒回不触网；上限用于控制一次请求的抓取压力。
MAX_LAZY_SPARKS: int = int(os.environ.get("SECTOR_MIN_MAX_LAZY_SPARKS", "12"))

# --------------------------------------------------------------------------- #
# 历史日期分时（日期切换组件）
# --------------------------------------------------------------------------- #
# 内存中最多保留的历史日期分时缓存天数（LRU 淘汰，超出后丢弃最旧日期）。
MAX_HIST_DATES: int = int(os.environ.get("SECTOR_MIN_MAX_HIST_DATES", "10"))

# 历史日期整批抓取时相邻两个标的的请求间隔（秒）。
# 与实时后台刷新错峰 0.3s 不同：日期切换是用户主动操作，取小间隔换取更快出图。
HIST_FETCH_SLEEP: float = float(os.environ.get("SECTOR_MIN_HIST_SLEEP", "0.1"))

# 历史分时可回溯的最大天数（前端日期选择器的下限；超出时后端返回空数据）。
HIST_MAX_LOOKBACK_DAYS: int = int(os.environ.get("SECTOR_MIN_HIST_LOOKBACK", "365"))

# --------------------------------------------------------------------------- #
# Web 服务
# --------------------------------------------------------------------------- #
HOST: str = os.environ.get("DASH_HOST", "0.0.0.0")
PORT: int = int(os.environ.get("SECTOR_MIN_PORT", "8091"))
