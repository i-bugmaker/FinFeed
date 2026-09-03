# -*- coding: utf-8 -*-
"""全市场资金流与板块轮动监控大屏 —— 数据模型。

与 easy-tdx / pandas 解耦的纯数据容器，直接序列化为 JSON 供前端消费。
金额单位统一为「元」，涨跌幅单位为「%」。
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


def to_dict(obj: Any) -> dict[str, Any]:
    """dataclass → dict（递归）。"""
    return asdict(obj)


# --------------------------------------------------------------------------- #
# 个股
# --------------------------------------------------------------------------- #

@dataclass
class StockFlow:
    """单只股票的资金流与行情。

    说明：通达信 MAC 协议不直接提供当日「超大单/大单/中单/小单」四档拆分，
    协议口径为两档——主力(≈超大单+大单) 与 散户(≈中单+小单)；
    另提供 5 日维度的大单/中单净额（来自 0x1218 资金流接口）。
    """

    market: int = 0
    code: str = ""
    name: str = ""
    price: float = 0.0              # 现价
    change_pct: float = 0.0         # 涨跌幅 %
    amount: float = 0.0             # 成交额(元)
    turnover: float = 0.0           # 换手率 %
    main_net: float = 0.0           # 今日主力净流入(元)  ≈ 超大单+大单
    main_net_ratio: float = 0.0     # 主力净比 %
    main_net_5m: float = 0.0        # 5分钟主力净额(元)
    main_net_3d: float = 0.0        # 近3日主力净额(元)
    main_net_5d: float = 0.0        # 近5日主力净额(元)

    # ---- 以下为逐股资金流详情（0x1218），低频补全，可能为 None ----
    main_in: float | None = None    # 当日主力流入(元)
    main_out: float | None = None   # 当日主力流出(元)
    retail_in: float | None = None  # 当日散户流入(元) ≈ 中单+小单
    retail_out: float | None = None # 当日散户流出(元)
    large_net_5d: float | None = None  # 5日大单净额(元)
    mid_net_5d: float | None = None    # 5日中单净额(元)


# --------------------------------------------------------------------------- #
# 板块
# --------------------------------------------------------------------------- #

@dataclass
class BoardFlow:
    """板块资金流与涨跌概况（行业/概念）。"""

    code: str = ""
    name: str = ""
    board_type: str = "HY"          # HY=行业 GN=概念
    change_pct: float = 0.0         # 板块涨跌幅 %
    amount: float = 0.0             # 板块成交额(元)
    vol: float = 0.0                # 板块成交量
    main_net: float = 0.0           # 主力净流入(元)
    up_count: int = 0               # 上涨家数
    down_count: int = 0             # 下跌家数
    member_count: int = 0           # 成分股数量
    # 资金状态（由 rotation 引擎填充）
    status: str = ""                # strong/weak/diverge/accumulate/neutral
    rank_delta: int = 0             # 主力净流入排名相对上一采样变化
    trend: list[float] = field(default_factory=list)  # 主力净占比时间序列


# --------------------------------------------------------------------------- #
# 指数 / 场内基金 / 市场概况
# --------------------------------------------------------------------------- #

@dataclass
class IndexQuote:
    code: str = ""
    name: str = ""
    price: float = 0.0
    change_pct: float = 0.0
    amount: float = 0.0


@dataclass
class FundFlow:
    """场内基金（ETF/LOF 等）资金排行条目。

    数据源为东方财富 push2 clist（fid=f62 按主力净额排序），与通达信
    全市场两档口径相互独立；金额单位统一为「元」，涨跌幅为「%」。
    f62 为东财大单口径「主力净额」，f184 为其净占比。
    """

    code: str = ""
    name: str = ""
    price: float = 0.0          # 现价(元)
    change_pct: float = 0.0     # 涨跌幅 %
    main_net: float = 0.0       # 主力净额(元)
    main_net_ratio: float = 0.0  # 主力净占比 %


@dataclass
class MarketBreadth:
    up: int = 0        # 上涨家数
    down: int = 0      # 下跌家数
    flat: int = 0      # 平盘
    total: int = 0     # 总家数
    limit_up: int = 0  # 涨停家数
    limit_down: int = 0  # 跌停家数


@dataclass
class MarketStats:
    total_amount: float = 0.0   # 全市场总成交额(元)
    total_main_net: float = 0.0 # 全市场主力净流入合计(元)
    main_in_stocks: int = 0     # 主力净流入家数
    main_out_stocks: int = 0    # 主力净流出家数


# --------------------------------------------------------------------------- #
# 轮动分析
# --------------------------------------------------------------------------- #

@dataclass
class RotationSignal:
    """板块轮动切换信号。"""

    board_code: str = ""
    board_name: str = ""
    board_type: str = "HY"
    signal: str = ""             # rotate_in / rotate_out / diverge / accumulate
    signal_label: str = ""
    change_pct: float = 0.0      # 板块涨跌幅 %
    main_net: float = 0.0        # 主力净流入(元)
    rank_delta: int = 0          # 排名变化
    prev_rank: int = 0
    cur_rank: int = 0
    confidence: float = 0.0      # 0~1 置信度


@dataclass
class RotationReport:
    """一次完整的板块轮动分析结果。"""

    ts: str = ""
    signals: list[RotationSignal] = field(default_factory=list)
    leader: list[dict] = field(default_factory=list)    # 领涨+资金流入板块
    laggard: list[dict] = field(default_factory=list)   # 领跌+资金流出板块
    # 热力图：boards(纵轴) x times(横轴) -> values
    heatmap_boards: list[str] = field(default_factory=list)
    # 热力图纵轴板块名称（与 heatmap_boards 平行；避免前端依赖板块榜推送范围导致缺名）
    heatmap_board_names: list[str] = field(default_factory=list)
    heatmap_times: list[str] = field(default_factory=list)
    heatmap_values: list[list[float]] = field(default_factory=list)
    # 趋势：focus 板块主力净占比时间序列
    trend_boards: list[str] = field(default_factory=list)
    trend_series: list[dict] = field(default_factory=list)


# --------------------------------------------------------------------------- #
# 市场快照
# --------------------------------------------------------------------------- #

@dataclass
class MarketSnapshot:
    """一轮采集的完整快照。"""

    ts: str = ""                              # ISO 时间戳
    ts_label: str = ""                        # HH:MM:SS
    indices: list[IndexQuote] = field(default_factory=list)
    stocks: list[StockFlow] = field(default_factory=list)     # 全市场(仅含关键字段)
    boards: list[BoardFlow] = field(default_factory=list)     # 行业+概念
    breadth: MarketBreadth = field(default_factory=MarketBreadth)
    stats: MarketStats = field(default_factory=MarketStats)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
