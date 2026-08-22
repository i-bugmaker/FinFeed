#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""easy-tdx 数据源层。

职责：
- 通过 easy-tdx（MacClient）拉取全 A 股实时行情/基本面快照。
- 为候选股补充技术面（K 线：年化波动率 / 均线排列 / 距高点回撤）。
- 支持快照落盘为 CSV 与离线回放（便于无网环境复现与测试）。

复用项目既有的 TDX 连接单例（finfeed.capital_dashboard.tdx），避免重复建连。
"""

from __future__ import annotations

import logging
import math
from typing import Any

import numpy as np
import pandas as pd
from easy_tdx import Adjust, Category, MacClient, Period, SortOrder, SortType
from easy_tdx.codec.bitmap import FieldBit, PresetField

from finfeed.capital_dashboard.tdx import close as close_tdx
from finfeed.capital_dashboard.tdx import ensure_alive, get_client

logger = logging.getLogger("finfeed.screener.datasource")

# 批量报价请求字段：基础 OHLC + 量额 + 估值 + 资金流 + 动量 + 股本
SCREENER_FIELDS = (
    PresetField.BASIC
    + PresetField.VOLUME
    + FieldBit.AMOUNT
    + FieldBit.TURNOVER
    + FieldBit.PE_TTM
    + FieldBit.MAIN_NET_AMOUNT
    + FieldBit.MAIN_NET_RATIO
    + FieldBit.MAIN_NET_5D_AMOUNT
    + FieldBit.FLOAT_SHARES
    + FieldBit.TOTAL_SHARES
    + FieldBit.EPS
    + FieldBit.DIVIDEND_YIELD
    + FieldBit.CHANGE_5D_PCT
    + FieldBit.CHANGE_20D_PCT
    + FieldBit.CHANGE_60D_PCT
    + FieldBit.CHANGE_1Y_PCT
    + FieldBit.CIRCULATING_CAPITAL_Z
    + FieldBit.TOTAL_MARKET_CAP_AB
    + FieldBit.VOL_RATIO
)

# 列名归一化（easy-tdx 返回列 -> 规范列）
_COL_RENAME = {
    "total_market_cap_ab": "total_market_cap",
}

# 规范数值列（缺失则补 0，保证评分可降级）。注意：name 为字符串，不可纳入数值化。
_REQUIRED_COLS = [
    "market", "code", "pre_close", "open", "high", "low", "close",
    "vol", "vol_ratio", "amount", "total_shares", "float_shares", "eps",
    "total_market_cap", "dividend_yield", "turnover", "circulating_capital_z",
    "pe_ttm", "main_net_amount", "main_net_ratio", "main_net_5d_amount",
    "change_5d_pct", "change_20d_pct", "change_60d_pct", "change_1y_pct",
]


def fetch_universe(count: int = 12000) -> pd.DataFrame:
    """拉取全 A 股实时快照，返回规范列 DataFrame。"""
    ensure_alive()
    client = get_client()
    df = client.get_stock_quotes_list(
        Category.A,
        count=count,
        sort_type=SortType.CODE,
        sort_order=SortOrder.ASC,
        fields=SCREENER_FIELDS,
    )
    if df is None or len(df) == 0:
        raise RuntimeError("easy-tdx 返回空行情，可能网络异常")

    df = df.rename(columns=_COL_RENAME)
    df.columns = [str(c).lower() for c in df.columns]
    # name 为字符串，单独处理（确保存在且为字符串）
    if "name" not in df.columns:
        logger.warning("行情缺少列 name，已补空串")
        df["name"] = ""
    else:
        df["name"] = df["name"].astype(str).fillna("")
    for c in _REQUIRED_COLS:
        if c not in df.columns:
            logger.warning("行情缺少列 %s，已补 0", c)
            df[c] = 0.0
    # 数值化（不含 name）
    for c in _REQUIRED_COLS:
        df[c] = pd.to_numeric(df[c], errors="coerce").fillna(0.0)
    df = _add_derived(df)
    return df


def _add_derived(df: pd.DataFrame) -> pd.DataFrame:
    """计算派生字段：当日涨跌幅、振幅、流通市值、5日主力净流入占流通比。"""
    close = pd.to_numeric(df["close"], errors="coerce").fillna(0.0)
    pre = pd.to_numeric(df["pre_close"], errors="coerce").fillna(0.0)
    high = pd.to_numeric(df["high"], errors="coerce").fillna(0.0)
    low = pd.to_numeric(df["low"], errors="coerce").fillna(0.0)
    fs = pd.to_numeric(df["float_shares"], errors="coerce").fillna(0.0)
    df["chg_today"] = np.where(pre > 0, (close - pre) / pre * 100.0, 0.0)
    df["amplitude"] = np.where(pre > 0, (high - low) / pre * 100.0, 0.0)
    circ = fs * 1e4 * close
    df["circ_cap"] = circ
    net5 = pd.to_numeric(df["main_net_5d_amount"], errors="coerce").fillna(0.0)
    df["main_net_5d_pct"] = np.where(circ > 0, net5 / circ * 100.0, 0.0)
    return df


def _kline_metrics(market: int, code: str, kline_count: int) -> dict[str, Any]:
    """取日线 K 线，计算技术面指标。"""
    client = get_client()
    df = client.get_stock_kline(
        market, code, Period.DAILY, count=kline_count, adjust=Adjust.QFQ
    )
    if df is None or len(df) < 2:
        return {"realized_vol_ann": None, "ma_align": False, "drawdown_from_high": None}

    # 规范列名（不同版本可能用 datetime/vol）
    cols = {str(c).lower(): c for c in df.columns}
    close = df[cols.get("close", "close")].astype(float)
    high = df[cols.get("high", "high")].astype(float)
    if len(close) < 2:
        return {"realized_vol_ann": None, "ma_align": False, "drawdown_from_high": None}

    rets = close.pct_change().dropna()
    realized_vol_ann = None
    if len(rets) >= 5:
        std = float(rets.std())
        if math.isfinite(std):
            realized_vol_ann = std * math.sqrt(242.0) * 100.0

    ma_align = False
    if len(close) >= 60:
        ma20 = float(close.tail(20).mean())
        ma60 = float(close.tail(60).mean())
        ma_align = bool(close.iloc[-1] > ma20 > ma60)

    drawdown_from_high = None
    if len(high) >= 20:
        peak = float(high.max())
        if peak > 0:
            drawdown_from_high = (float(close.iloc[-1]) - peak) / peak * 100.0

    return {
        "realized_vol_ann": realized_vol_ann,
        "ma_align": ma_align,
        "drawdown_from_high": drawdown_from_high,
    }


def enrich_technical(df: pd.DataFrame, top_n: int = 200, kline_count: int = 120) -> pd.DataFrame:
    """为排名靠前的候选股补充技术面指标（就地新增列）。

    仅对「廉价复合排序」前 top_n 只抓取 K 线，控制请求量；
    其余标的 technical 字段留空，质量维度自动回退到振幅代理。
    """
    out = df.copy()
    out["realized_vol_ann"] = None
    out["ma_align"] = False
    out["drawdown_from_high"] = None

    rank = (
        out["change_20d_pct"].fillna(0.0) * 0.5
        + out["main_net_5d_pct"].fillna(0.0) * 0.5
    ) if "main_net_5d_pct" in out.columns else out["change_20d_pct"].fillna(0.0)
    top_idx = rank.sort_values(ascending=False).head(top_n).index

    done = 0
    for i in top_idx:
        m = int(out.at[i, "market"])
        code = str(out.at[i, "code"])
        try:
            met = _kline_metrics(m, code, kline_count)
        except Exception as exc:  # noqa: BLE001
            logger.debug("K线富化失败 %s: %s", code, exc)
            continue
        out.at[i, "realized_vol_ann"] = met["realized_vol_ann"]
        out.at[i, "ma_align"] = met["ma_align"]
        out.at[i, "drawdown_from_high"] = met["drawdown_from_high"]
        done += 1
    logger.info("技术面富化完成：%d/%d 只", done, len(top_idx))
    return out


def save_snapshot_csv(df: pd.DataFrame, path: str) -> None:
    """保存原始行情快照为 CSV（离线回放用）。"""
    df.to_csv(path, index=False, encoding="utf-8-sig")


def load_snapshot_csv(path: str) -> pd.DataFrame:
    """从 CSV 读取行情快照（列名需与规范列一致）。"""
    df = pd.read_csv(path, encoding="utf-8-sig")
    df.columns = [str(c).lower() for c in df.columns]
    for c in _REQUIRED_COLS:
        if c in df.columns:
            df[c] = pd.to_numeric(df[c], errors="coerce").fillna(0.0)
    return df


def close() -> None:
    """关闭底层 TDX 连接。"""
    try:
        close_tdx()
    except Exception:  # noqa: BLE001
        pass
