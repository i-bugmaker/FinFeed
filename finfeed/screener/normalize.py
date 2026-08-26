#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""因子预处理标准化库（新选股管线基石）。

提供稳健、可复现的截面因子处理原语，替代旧管线中脆弱的 sigmoid / bell
绝对阈值映射：

    Winsorize(p1,p99) → 行业 + 市值中性化(OLS 残差) → 截面 rank→[-1,1] / z-score

设计依据（见 docs/screener_refactor_design.md）：
- rank→[-1,1] 标准化来自 Gu-Kelly-Xiu(2020)，对量纲与异常值最稳健；
- 行业 + 市值中性化消除系统性偏离，使跨组可比（海通/中金/信达实证）；
- 缺失用截面中位数填充，绝不以 0 冒充真实零值。

所有函数均为纯函数，便于单元测试与离线回测复用。
"""

from __future__ import annotations

import numpy as np
import pandas as pd


def fill_missing_median(s: pd.Series) -> pd.Series:
    """缺失用截面中位数填充（保留索引对齐）。"""
    med = s.median()
    return s.fillna(med)


def winsorize(s: pd.Series, p_low: float = 0.01, p_high: float = 0.99) -> pd.Series:
    """截尾：将低于 p_low 分位 / 高于 p_high 分位的值夹到分位边界。"""
    lo, hi = s.quantile(p_low), s.quantile(p_high)
    return s.clip(lower=lo, upper=hi)


def neutralize(y: pd.Series, X: pd.DataFrame) -> pd.Series:
    """对设计矩阵 X 做横截面 OLS 取残差，消除 X 解释的系统性部分。

    y / X 必须同索引；缺失行被剔除后再回写。样本不足时退化为「去均值」。
    X 通常含行业哑变量 + log(市值) 列。
    """
    df = pd.concat([y.rename("y"), X], axis=1).dropna()
    out = y.copy()
    if len(df) < max(30, X.shape[1] + 5):
        out.loc[df.index] = df["y"] - df["y"].mean()
        return out
    Xd = pd.concat([pd.Series(1.0, index=df.index, name="__const"),
                    df[X.columns].astype(float)], axis=1)
    beta, *_ = np.linalg.lstsq(Xd.values, df["y"].values, rcond=None)
    resid = df["y"].values - Xd.values @ beta
    out.loc[df.index] = resid
    return out


def rank_standardize(s: pd.Series) -> pd.Series:
    """截面秩标准化到 [-1, 1]（Gu-Kelly-Xiu 做法），对异常值最稳健。"""
    r = s.rank(method="average", pct=True)  # 0..1
    return r * 2.0 - 1.0


def zscore(s: pd.Series, eps: float = 1e-9) -> pd.Series:
    """截面 z-score（均值 0、标准差 1）。"""
    mu = s.mean()
    sd = s.std(ddof=0)
    return (s - mu) / (sd + eps)


def preprocess_factor(
    df: pd.DataFrame,
    col: str,
    industry_col: str = "industry",
    size_col: str = "total_market_cap",
    winsor: tuple[float, float] = (0.01, 0.99),
    method: str = "rank",
) -> pd.Series:
    """单因子完整预处理：缺失中位数填充 → Winsorize → 行业+市值中性化 → 标准化。

    返回与 df 同索引的标准化因子（rank 或 z-score）。
    中性化设计矩阵：申万行业哑变量 + log10(总市值)；任一缺失则回退纯截面。
    """
    if col not in df.columns:
        return pd.Series(0.0, index=df.index)
    s = pd.to_numeric(df[col], errors="coerce")
    s = fill_missing_median(s)
    s = winsorize(s, *winsor)

    X = pd.DataFrame(index=df.index)
    if industry_col in df.columns:
        dummies = pd.get_dummies(df[industry_col].fillna(""), prefix="ind").astype(float)
        X = pd.concat([X, dummies], axis=1)
    if size_col in df.columns:
        sz = pd.to_numeric(df[size_col], errors="coerce").replace(0.0, np.nan)
        X["size"] = np.log10(sz)

    if X.shape[1] == 0:
        return rank_standardize(s) if method == "rank" else zscore(s)

    resid = neutralize(s, X)
    return rank_standardize(resid) if method == "rank" else zscore(resid)


def orthogonalize_dimensions(dim_df: pd.DataFrame) -> pd.DataFrame:
    """维度分横截面正交化：对每个维度回归剔除其余维度信息，降低冗余。

    dim_df 列为各维度子分（0~100）。输出保持 0~100 量纲（残差重缩放到
    ±2σ → 0~100），使正交后仍可直接加权合成分。样本不足时原样返回。
    """
    cols = list(dim_df.columns)
    if len(cols) < 2:
        return dim_df.astype(float)
    out = dim_df.astype(float).copy()
    for d in cols:
        others = [c for c in cols if c != d]
        y = dim_df[d]
        X = dim_df[others]
        df2 = pd.concat([y.rename("y"), X], axis=1).dropna()
        if len(df2) < 30:
            continue
        Xd = pd.concat([pd.Series(1.0, index=df2.index, name="c"), df2[others]], axis=1)
        beta, *_ = np.linalg.lstsq(Xd.values, df2["y"].values, rcond=None)
        resid = df2["y"].values - Xd.values @ beta
        sd = resid.std(ddof=0) or 1.0
        scaled = 50.0 + (resid - resid.mean()) / (sd * 2.0) * 50.0
        out.loc[df2.index, d] = np.clip(scaled, 0.0, 100.0)
    return out
