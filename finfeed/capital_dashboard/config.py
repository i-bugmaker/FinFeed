# -*- coding: utf-8 -*-
"""全市场资金流与板块轮动监控大屏 —— 配置模块。

集中管理所有可调参数；修改后重启服务生效。
"""

from __future__ import annotations

import os

# --------------------------------------------------------------------------- #
# TDX 行情服务器
# --------------------------------------------------------------------------- #
# 留空(None)时自动测速选择最佳 MAC 服务器；可指定 IP 例如 "119.147.212.81"
TDX_HOST: str | None = os.environ.get("TDX_HOST") or None
TDX_PORT: int = int(os.environ.get("TDX_PORT", "7709"))
TDX_TIMEOUT: float = float(os.environ.get("TDX_TIMEOUT", "8.0"))

# --------------------------------------------------------------------------- #
# 刷新机制
# --------------------------------------------------------------------------- #
# 主数据(全市场资金流/板块/指数)轮询周期，单位秒。交易时段建议 5~15，
# 非交易时段可调大。0 表示关闭后台刷新(仅手动触发)。
REFRESH_INTERVAL: int = int(os.environ.get("REFRESH_INTERVAL", "8"))

# 个股资金流详情(当日主力/散户流入流出)为逐股查询，成本较高，低频补全：
# 每 DETAIL_REFRESH_EVERY 秒对榜单前 DETAIL_TOP_N 只股票补全一次。
DETAIL_REFRESH_EVERY: int = int(os.environ.get("DETAIL_REFRESH_EVERY", "30"))
DETAIL_TOP_N: int = int(os.environ.get("DETAIL_TOP_N", "20"))

# --------------------------------------------------------------------------- #
# 榜单规模
# --------------------------------------------------------------------------- #
# 个股榜单展示数量(净流入/净流出各 N 只)
STOCK_TOP_N: int = int(os.environ.get("STOCK_TOP_N", "15"))
# 板块榜单展示数量(行业/概念各 N 个)
BOARD_TOP_N: int = int(os.environ.get("BOARD_TOP_N", "20"))

# --------------------------------------------------------------------------- #
# ETF/基金资金排行（东财 push2 独立链路，与 TDX 主数据解耦）
# --------------------------------------------------------------------------- #
# 场内基金资金排行刷新周期(秒)。东财 push2 限流敏感(组内最小间隔 1.5s/请求)，
# 每轮每基金池需 2 次请求(净流入/净流出)，周期过短会加重上游压力。
FUND_REFRESH_INTERVAL: int = int(os.environ.get("FUND_REFRESH_INTERVAL", "20"))
# 每个基金池展示的基金数量(净流入/净流出各 N 只)
FUND_TOP_N: int = int(os.environ.get("FUND_TOP_N", "12"))
# 板块轮动分析关注板块数(按资金活跃度取前 M 个)
ROTATION_FOCUS_N: int = int(os.environ.get("ROTATION_FOCUS_N", "12"))
# 轮动信号判定：板块主力净流入排名相对上一次采样的上升/下降位次阈值
ROTATION_RANK_DELTA: int = int(os.environ.get("ROTATION_RANK_DELTA", "4"))
# 保留的历史采样点数量(用于轮动趋势/热力图)，@8s 刷新约 16 分钟
HISTORY_LEN: int = int(os.environ.get("HISTORY_LEN", "120"))

# --------------------------------------------------------------------------- #
# Web 服务
# --------------------------------------------------------------------------- #
HOST: str = os.environ.get("DASH_HOST", "0.0.0.0")
PORT: int = int(os.environ.get("DASH_PORT", "8090"))

# 概念板块排行聚合 top_n（概念板块 260+ 个，聚合成本高，控制数量）
GN_RANKING_TOP: int = int(os.environ.get("GN_RANKING_TOP", "40"))

# 主要指数过滤白名单（用于大屏顶部指数卡，按显示顺序排列）
# 注：中证500 在 TDX ZS 分类下代码为 000905（399905 不存在）
MAIN_INDEX_CODES: tuple[str, ...] = (
    "999999",  # 上证指数
    "399001",  # 深证成指
    "399006",  # 创业板指
    "000688",  # 科创50
    "000300",  # 沪深300
    "000905",  # 中证500
)
