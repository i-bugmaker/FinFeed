#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""normalize.py 标准化原语单元测试。

覆盖：缺失中位数填充、Winsorize、中性化残差、秩标准化 [-1,1]、
单因子预处理管道、维度正交化。
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from finfeed.screener.normalize import (
    fill_missing_median,
    winsorize,
    neutralize,
    rank_standardize,
    zscore,
    preprocess_factor,
    orthogonalize_dimensions,
)


def _series(*vals):
    return pd.Series(vals, dtype=float)


def test_fill_missing_median():
    s = _series(1.0, float("nan"), 3.0, 5.0)
    out = fill_missing_median(s)
    assert out.iloc[1] == 3.0  # 中位数 (1,3,5)->3
    assert not out.isna().any()


def test_winsorize():
    s = _series(0.0, 1.0, 2.0, 3.0, 100.0)
    out = winsorize(s, 0.01, 0.99)
    # 极端值被夹到分位边界（不恰好 0/100，但被裁剪）
    assert out.max() < 100.0
    assert out.min() > 0.0
    # 内部点不受影响
    assert out.iloc[2] == 2.0


def test_rank_standardize_range():
    rng = np.random.default_rng(0)
    s = _series(*rng.normal(size=200))
    out = rank_standardize(s)
    assert out.min() >= -1.0 - 1e-9
    assert out.max() <= 1.0 + 1e-9
    assert abs(out.mean()) < 0.05  # 大致对称


def test_zscore_zero_mean_unit_std():
    rng = np.random.default_rng(1)
    s = _series(*rng.normal(10.0, 2.0, 300))
    z = zscore(s)
    assert abs(z.mean()) < 1e-6
    assert abs(z.std(ddof=0) - 1.0) < 1e-6


def test_neutralize_removes_mean():
    rng = np.random.default_rng(2)
    y = _series(*rng.normal(size=200))
    # X 为常数 -> 残差应为去均值
    X = pd.DataFrame({"c": 1.0}, index=y.index)
    resid = neutralize(y, X)
    assert abs(resid.mean()) < 1e-6


def test_neutralize_removes_industry_effect():
    # y 完全由行业哑变量决定 -> 中性化后残差≈0
    n = 120
    rng = np.random.default_rng(3)
    industry = pd.Series(["a"] * 60 + ["b"] * 60)
    df = pd.DataFrame({"industry": industry})
    y = _series(*([5.0] * 60 + [15.0] * 60))
    # 加入微小噪声便于 OLS 求解
    y = y + _series(*rng.normal(0, 0.01, n))
    X = pd.get_dummies(df["industry"]).astype(float)
    resid = neutralize(y, X)
    assert resid.abs().max() < 0.1


def test_preprocess_factor_rank_in_range():
    rng = np.random.default_rng(4)
    n = 300
    df = pd.DataFrame({
        "code": [f"{i:06d}" for i in range(n)],
        "pe_ttm": rng.normal(20.0, 10.0, n),
        "industry": np.where(rng.normal(size=n) > 0, "tech", "fin"),
        "total_market_cap": 10.0 ** rng.uniform(9.0, 12.0, n),
    })
    out = preprocess_factor(df, "pe_ttm", method="rank")
    assert (out.abs() <= 1.0 + 1e-9).all()
    # 行业/市值中性化后，组间系统性差异被削弱（std 不超过原始秩标准化太多）
    assert out.std(ddof=0) <= 1.0 + 1e-6


def test_orthogonalize_dimensions_bounded_and_reduces_redundancy():
    rng = np.random.default_rng(5)
    n = 400
    base = rng.normal(size=n)
    # quality 完全由 capital 线性决定（高度冗余）
    dim_df = pd.DataFrame({
        "capital": 50.0 + 20.0 * base + rng.normal(0, 1, n),
        "momentum": 50.0 + rng.normal(0, 15, n),
        "valuation": 50.0 + rng.normal(0, 15, n),
        "liquidity": 50.0 + rng.normal(0, 15, n),
        "quality": 50.0 + 20.0 * base + rng.normal(0, 1, n),
        "sentiment": 50.0 + rng.normal(0, 15, n),
    })
    out = orthogonalize_dimensions(dim_df)
    # 量纲保持 0~100
    assert (out >= 0.0 - 1e-9).all().all()
    assert (out <= 100.0 + 1e-9).all().all()
    # 正交化后 quality 与 capital 相关性应显著下降
    before = dim_df["capital"].corr(dim_df["quality"])
    after = out["capital"].corr(out["quality"])
    assert abs(after) < abs(before)
