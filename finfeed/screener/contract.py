#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""选股模块数据契约层。

职责：
- 定义跨数据源统一的快照容器 SnapshotBundle（规范列 + 数据时间 + 来源 + 回退链 + 覆盖率）。
- 定义列契约（必填列 / 单位 / 缺失语义）与数据校验函数。
- 确保「数据缺失」与「真实基本面（停牌/亏损）」可区分：缺失列一律以 NaN 表示，
  禁止用 0 冒充，避免评分引擎系统性误杀。

单位约定（与 easy-tdx / 东财 datacenter 对齐）：
    price 元；amount/市值/主力净流入 元；shares 万股；pct/turnover/ratio %；
    dividend_yield %；PE_TTM 倍。
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

import pandas as pd

logger = logging.getLogger("finfeed.screener.contract")

# 规范数值列（缺失则置 NaN，评分层按缺失语义处理；name 为字符串单独处理）
REQUIRED_COLS = [
    "market", "code", "pre_close", "open", "high", "low", "close",
    "vol", "vol_ratio", "amount", "total_shares", "float_shares", "eps",
    "total_market_cap", "dividend_yield", "turnover", "circulating_capital_z",
    "pe_ttm", "main_net_amount", "main_net_ratio", "main_net_5d_amount",
    "change_5d_pct", "change_10d_pct", "change_20d_pct", "change_60d_pct", "change_1y_pct",
    # 情绪/事件字段（easy-tdx 快照，位号 ≤127 可用）
    "annual_limit_up_days", "consecutive_up_days", "ddx", "vol_speed_pct",
]

# 快照健康下限：低于此值判定为数据源异常，触发回退
MIN_SNAPSHOT_ROWS = 3000

# 冒烟校验标的（价格量级校验用；偏差 >5% 判源异常）
_SMOKE_TICKERS = {"600519": "贵州茅台", "000001": "平安银行", "600036": "招商银行"}
_SMOKE_PRICE_FLOOR = 1.0   # 冒烟标的正常价格应 >1 元
_SMOKE_PRICE_CEIL = 3000.0  # 冒烟标的正常价格应 <3000 元


@dataclass
class SnapshotBundle:
    """一次行情快照的完整载体（跨数据源统一契约）。

    df:            规范列 DataFrame（缺失为 NaN，绝不为 0 冒充）。
    as_of:         数据时间（字符串，随 as_of_kind 语义不同）。
    as_of_kind:    "realtime" 盘中实时 / "trade_date" 交易日收盘 / "local" 本地时间兜底。
    source:        实际采用的数据源标签（如 "easy-tdx" / "eastmoney"）。
    fallback_chain: 本次实际降级链（如 ["easy-tdx", "eastmoney"]）。
    coverage:      有效数据覆盖率（0~1，非缺失行比例）。
    missing_mask:  布尔 DataFrame，True 表示该格缺失。
    """

    df: pd.DataFrame
    as_of: str = ""
    as_of_kind: str = "local"
    source: str = ""
    fallback_chain: list[str] = field(default_factory=list)
    coverage: float = 1.0
    missing_mask: pd.DataFrame | None = None

    def describe(self) -> str:
        """人类可读的数据源描述（报告/前端展示）。"""
        if self.fallback_chain:
            chain = " → ".join(self.fallback_chain)
            return f"{self.source}（回退链：{chain}）"
        return self.source


def normalize_frame(raw: pd.DataFrame, source: str) -> pd.DataFrame:
    """把任意来源的 DataFrame 归一化为规范列（列缺失 → NaN，数值化）。

    列名统一小写；`name` 强制为字符串；数值列 to_numeric(errors="coerce")，
    **保留 NaN 缺失语义**（不 fillna(0)）。
    """
    df = raw.copy()
    df.columns = [str(c).lower() for c in df.columns]

    if "name" not in df.columns:
        df["name"] = ""
    else:
        df["name"] = df["name"].astype(str).fillna("")

    # 行业字段（字符串）：用于行业中性化；缺失补空串（分组时回退板块）
    for col in ("industry", "industry_sub"):
        if col not in df.columns:
            df[col] = ""
        else:
            df[col] = df[col].astype(str).fillna("")

    for c in REQUIRED_COLS:
        if c not in df.columns:
            df[c] = float("nan")
        else:
            df[c] = pd.to_numeric(df[c], errors="coerce")
    return df


def build_missing_mask(df: pd.DataFrame) -> pd.DataFrame:
    """返回缺失标记（True=缺失），仅覆盖规范数值列。"""
    cols = [c for c in REQUIRED_COLS if c in df.columns]
    return df[cols].isna()


def coverage_ratio(mask: pd.DataFrame | None) -> float:
    """有效数据覆盖率：非缺失格 / 总格。"""
    if mask is None or mask.empty:
        return 1.0
    return float(1.0 - mask.to_numpy().mean())


def validate_snapshot(df: pd.DataFrame, source: str) -> list[str]:
    """对快照做健康校验，返回问题列表（空列表=通过）。

    校验项：
    1. 行数下限（MIN_SNAPSHOT_ROWS）—— 判数据源故障；
    2. 价格零值/缺失率（>5% 判字段故障）；
    3. 冒烟标的量级校验（600519/000001/600036 价格须在合理区间）。
    """
    problems: list[str] = []
    if df is None or len(df) == 0:
        return [f"{source}: 快照为空"]

    if len(df) < MIN_SNAPSHOT_ROWS:
        problems.append(f"{source}: 行数 {len(df)} < 下限 {MIN_SNAPSHOT_ROWS}")

    close = pd.to_numeric(df.get("close"), errors="coerce")
    if close is not None and len(close) > 0:
        invalid = close.isna() | (close <= 0)
        invalid_ratio = float(invalid.mean())
        if invalid_ratio > 0.05:
            problems.append(f"{source}: 无效价格占比 {invalid_ratio:.1%} > 5%")

    code_col = df.get("code")
    if code_col is not None:
        codes = {str(c).zfill(6) for c in code_col.dropna()}
        smoke = codes.intersection(_SMOKE_TICKERS)
        if smoke:
            sub = df[df["code"].astype(str).str.zfill(6).isin(smoke)]
            prices = pd.to_numeric(sub.get("close"), errors="coerce")
            bad = [c for c, p in zip(sub["code"], prices)
                   if pd.notna(p) and not (_SMOKE_PRICE_FLOOR <= p <= _SMOKE_PRICE_CEIL)]
            if bad:
                problems.append(f"{source}: 冒烟标的量级异常 {bad[:3]}")

    return problems


def summarize_metrics(bundle: "SnapshotBundle") -> dict[str, Any]:
    """输出数据质量指标（审计/监控用）。"""
    return {
        "source": bundle.source,
        "fallback_chain": bundle.fallback_chain,
        "as_of": bundle.as_of,
        "as_of_kind": bundle.as_of_kind,
        "rows": int(len(bundle.df)) if bundle.df is not None else 0,
        "coverage": round(bundle.coverage, 4),
    }
