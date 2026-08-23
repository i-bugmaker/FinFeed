#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""选股模块数据模型。

与 easy-tdx / pandas 解耦的纯数据容器，便于序列化（JSON / Markdown 报告）。
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass
class RawStock:
    """单只股票的原始行情/基本面快照（来自 easy-tdx）。"""

    market: int = 0                 # 1=SH 0=SZ 2=BJ
    code: str = ""
    name: str = ""
    pre_close: float = 0.0
    open: float = 0.0
    high: float = 0.0
    low: float = 0.0
    close: float = 0.0              # 现价
    vol: float = 0.0
    vol_ratio: float = 0.0          # 量比
    amount: float = 0.0             # 成交额(元)
    total_shares: float = 0.0
    float_shares: float = 0.0       # 单位：万股
    eps: float = 0.0
    total_market_cap: float = 0.0   # 总市值(元)
    dividend_yield: float = 0.0
    turnover: float = 0.0           # 换手率 %
    circulating_capital_z: float = 0.0
    pe_ttm: float = 0.0
    main_net_amount: float = 0.0    # 今日主力净流入(元)
    main_net_ratio: float = 0.0    # 今日主力净比 %
    main_net_5d_amount: float = 0.0 # 近5日主力净流入(元)
    change_5d_pct: float = 0.0
    change_20d_pct: float = 0.0
    change_60d_pct: float = 0.0
    change_1y_pct: float = 0.0


@dataclass
class StockScore:
    """单只股票的评分结果。"""

    code: str = ""
    name: str = ""
    market: int = 0
    board: str = ""                    # main / kcb / cyb / bj
    price: float = 0.0
    change_pct: float = 0.0          # 当日涨跌幅 %
    pe_ttm: float = 0.0
    amplitude: float = 0.0           # 当日振幅 %
    amount: float = 0.0

    # 维度子分（0~100）
    capital_score: float = 0.0
    momentum_score: float = 0.0
    valuation_score: float = 0.0
    liquidity_score: float = 0.0
    quality_score: float = 0.0
    sentiment_score: float = 0.0   # 情绪/事件（涨停基因/连涨/大单动向/量速）

    # 综合分与评级
    total_score: float = 0.0
    tier: str = ""                   # strong / watch / observe / none
    eligible: bool = True            # 是否通过硬性过滤

    # 选股逻辑说明
    rationale: str = ""

    # 主要贡献因子（用于解释）
    highlights: list[str] = field(default_factory=list)
    guardrail_failures: list[str] = field(default_factory=list)

    # 技术面（可选，来自 K 线富化）
    realized_vol_ann: float | None = None     # 年化波动率 %
    ma_align: bool = False                    # 收盘价 > MA20 > MA60
    drawdown_from_high: float | None = None   # 距52周高点回撤 %

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class ScreenerResult:
    """一次完整筛选的结果。"""

    generated_at: str = ""
    data_source: str = ""
    snapshot_time: str = ""          # 行情快照时间（真实数据时间，见 as_of_kind）
    as_of_kind: str = "local"        # realtime=盘中实时 / trade_date=交易日收盘 / local=本地兜底
    fallback_chain: list[str] = field(default_factory=list)  # 实际数据源降级链
    coverage: float = 1.0            # 数据覆盖率 0~1
    universe_size: int = 0           # 全市场过滤前数量
    screened_size: int = 0           # 通过硬性过滤数量
    scored_size: int = 0             # 实际评分数量
    technical_enabled: bool = False
    config_summary: dict[str, Any] = field(default_factory=dict)
    scores: list[StockScore] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "generated_at": self.generated_at,
            "data_source": self.data_source,
            "snapshot_time": self.snapshot_time,
            "as_of_kind": self.as_of_kind,
            "fallback_chain": self.fallback_chain,
            "coverage": self.coverage,
            "universe_size": self.universe_size,
            "screened_size": self.screened_size,
            "scored_size": self.scored_size,
            "technical_enabled": self.technical_enabled,
            "config_summary": self.config_summary,
            "scores": [s.to_dict() for s in self.scores],
        }
