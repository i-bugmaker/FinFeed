#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""ic_engine.py IC 加权引擎单元测试。

覆盖：resolve_weights 特性开关（fixed/degraded）、半衰期权重、ICIR、
由真实快照历史计算权重（动量维度应获最高权重）。
"""

from __future__ import annotations

import numpy as np
import pandas as pd
from finfeed.screener.config import ScreenerConfig
from finfeed.screener.ic_engine import (
    DIMS,
    compute_engine_weights,
    halflife_weights,
    icir_by_dim,
    resolve_weights,
)


def _make_factor_df(n: int, seed: int, signal: np.ndarray | None = None) -> pd.DataFrame:
    """构造含 vector.dimension_scores_vec 所需全部列的快照 DataFrame。

    signal: 长度 n 的数组（-1~1），驱动动量维度；前瞻收益与其正相关。
    """
    rng = np.random.default_rng(seed)
    if signal is None:
        signal = rng.uniform(-1.0, 1.0, n)
    codes = [f"{i:06d}" for i in range(n)]
    df = pd.DataFrame({
        "code": codes,
        "close": 10.0,
        "name": ["测试" + c for c in codes],
        "market": 1,
        "main_net_ratio": 0.0,
        "main_net_5d_pct": 0.0,
        "change_5d_pct": signal * 20.0,
        "change_10d_pct": signal * 30.0,
        "change_20d_pct": signal * 40.0,
        "change_60d_pct": signal * 50.0,
        "pe_ttm": 20.0,
        "dividend_yield": 0.0,
        "amount": 1e9,
        "turnover": 2.0,
        "eps": 1.0,
        "realized_vol_ann": 40.0,
        "amplitude": 2.5,
        "total_market_cap": 1e11,
        "annual_limit_up_days": 0.0,
        "consecutive_up_days": 0.0,
        "ddx": 0.0,
        "vol_speed_pct": 0.0,
    })
    return df


def _make_history(n: int, seed: int, horizon: int = 1):
    """构造 (date, df) 历史，含前瞻收益（与 signal 正相关）。"""
    rng = np.random.default_rng(seed)
    signal = rng.uniform(-1.0, 1.0, n)
    today = _make_factor_df(n, seed, signal)
    future = today.copy()
    # 前瞻收益与 signal 正相关
    future["close"] = today["close"] * (1.0 + signal * 0.1)
    history = []
    for k in range(horizon + 1):
        # 多期时复用同一截面（仅用于驱动 IC 计算路径，不追求真实时序）
        history.append((f"2026-01-{k+1:02d}", today if k == 0 else future))
    return history


def test_resolve_weights_fixed_returns_config_weights_and_no_store():
    cfg = ScreenerConfig()
    assert cfg.engine["mode"] == "fixed"
    weights, mode, diag = resolve_weights(cfg, store=None)
    assert mode == "fixed"
    # 固定模式下权重与配置一致（不访问数据源）
    assert abs(sum(weights.values()) - 1.0) < 1e-9
    for d in DIMS:
        assert abs(weights[d] - cfg.weights[d]) < 1e-12
    assert "note" in diag


def test_resolve_weights_degraded_when_ic_mode_but_no_store():
    cfg = ScreenerConfig()
    cfg.engine["mode"] = "ic"
    weights, mode, diag = resolve_weights(cfg, store=None)
    assert mode == "degraded"
    assert "reason" in diag
    # 降级时回退固定权重
    for d in DIMS:
        assert abs(weights[d] - cfg.weights[d]) < 1e-12


def test_halflife_weights_recent_and_positive():
    # momentum: IC 近期走高；valuation: 全负 -> 权重 0
    ic_by_dim = {
        "momentum": [0.02, 0.03, 0.10],   # 近期 IC 更高
        "valuation": [-0.05, -0.04, -0.03],
        "capital": [0.01, 0.01, 0.02],
    }
    w = halflife_weights(ic_by_dim, halflife=2, dims=("momentum", "valuation", "capital"))
    assert w["valuation"] == 0.0  # 负 IC 置 0
    assert w["momentum"] > 0.0
    # 近期 IC 更高 -> momentum 权重应高于全期均值的简单等权对比
    assert abs(sum(w.values()) - 1.0) < 1e-9


def test_icir_by_dim_basic():
    ic_by_dim = {"momentum": [0.05, 0.06, 0.04, 0.07], "valuation": [-0.02, -0.01]}
    ir = icir_by_dim(ic_by_dim)
    assert ir["momentum"] > 0.0
    assert ir["valuation"] < 0.0
    # 单样本维度 ICIR 退化为 0
    assert icir_by_dim({"x": [0.1]})["x"] == 0.0


def test_compute_engine_weights_momentum_dominant():
    n = 500
    history = _make_history(n, seed=7, horizon=1)
    weights, diag = compute_engine_weights(history, ScreenerConfig(), dims=DIMS,
                                           scheme="halflife_ic", halflife=1, horizon=1)
    assert abs(sum(weights.values()) - 1.0) < 1e-9
    # 前瞻收益与动量维度正相关 -> 动量应获最高权重且显著
    assert weights["momentum"] == max(weights.values())
    assert weights["momentum"] > 0.5
    # 诊断含 IC 均值
    assert "ic_mean_by_dim" in diag
    assert diag["ic_mean_by_dim"]["momentum"] > 0.0


def test_compute_engine_weights_icir_scheme_normalized():
    n = 500
    history = _make_history(n, seed=11, horizon=1)
    weights, diag = compute_engine_weights(history, ScreenerConfig(), dims=DIMS,
                                           scheme="icir", halflife=1, horizon=1)
    assert abs(sum(weights.values()) - 1.0) < 1e-9
    # momentum 在 ICIR 方案下亦应占优（IC 稳定为正）
    assert weights["momentum"] == max(weights.values())
