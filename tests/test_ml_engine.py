#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""P5 ML 层单元测试。

覆盖：
- 依赖免费 NumPy 逻辑回归在可分数据上的分离能力；
- train_walkforward / predict_ml 端到端产出 [0,1] 概率；
- run_ml_layer 在合成历史上能学到信号（OOS AUC > 0.5），并优雅降级（历史不足）；
- score_frame 在 engine.mode=ml 下正确填充 ml_prob 与 model_status。
"""

from __future__ import annotations

import numpy as np
import pandas as pd
from finfeed.screener import ml_engine, scoring
from finfeed.screener.config import ScreenerConfig
from finfeed.screener.ml_engine import _NumpyLogistic


def _make_history(n_stocks: int = 300, n_dates: int = 120, horizon: int = 20, seed: int = 0):
    """合成历史快照：隐藏质量 q 同时驱动时序收益与 change_20d_pct（信号维度）。"""
    rng = np.random.default_rng(seed)
    codes = [f"{i:06d}" for i in range(n_stocks)]
    q = rng.uniform(0, 1, size=n_stocks)
    dates = [f"2024-{1 + m // 28:02d}-{1 + m % 28:02d}" for m in range(n_dates)]
    base = rng.uniform(5, 50, size=n_stocks)
    closes = np.zeros((n_dates, n_stocks))
    closes[0] = base
    for t in range(1, n_dates):
        ret = 0.001 * (q - 0.5) + rng.normal(0, 0.01, size=n_stocks)
        closes[t] = closes[t - 1] * (1 + ret)
    history = []
    for t in range(n_dates):
        pre = closes[t - 1] if t > 0 else closes[t]
        df = pd.DataFrame({
            "code": codes,
            "name": [f"股票{c}" for c in codes],
            "market": [1] * n_stocks,
            "close": closes[t],
            "pre_close": pre,
            "high": closes[t] * 1.01,
            "low": closes[t] * 0.99,
            "float_shares": rng.uniform(1e5, 3e6, size=n_stocks),
            "amount": rng.uniform(1e8, 1e10, size=n_stocks),
            "turnover": rng.uniform(0.5, 5, size=n_stocks),
            "pe_ttm": rng.uniform(5, 80, size=n_stocks),
            "dividend_yield": rng.uniform(0, 3, size=n_stocks),
            "eps": rng.uniform(0.1, 3, size=n_stocks),
            "total_market_cap": rng.uniform(1e10, 1e12, size=n_stocks),
            "realized_vol_ann": rng.uniform(20, 60, size=n_stocks),
            "amplitude": rng.uniform(1, 5, size=n_stocks),
            "main_net_ratio": rng.uniform(-2, 2, size=n_stocks),
            "main_net_5d_amount": rng.uniform(-1e8, 1e8, size=n_stocks),
            "main_net_5d_pct": rng.uniform(-1, 1, size=n_stocks),
            "change_5d_pct": rng.uniform(-5, 5, size=n_stocks),
            "change_10d_pct": rng.uniform(-8, 8, size=n_stocks),
            "change_20d_pct": 20 * (q - 0.5) + rng.normal(0, 3, size=n_stocks),
            "change_60d_pct": rng.uniform(-15, 20, size=n_stocks),
            "annual_limit_up_days": rng.uniform(0, 10, size=n_stocks),
            "consecutive_up_days": rng.uniform(0, 5, size=n_stocks),
            "ddx": rng.uniform(-0.5, 0.5, size=n_stocks),
            "vol_speed_pct": rng.uniform(0.5, 3, size=n_stocks),
        })
        history.append((dates[t], df))
    return history


class _FakeStore:
    def __init__(self, history):
        self.history = history

    def available_dates(self):
        return [d for d, _ in self.history]

    def load_date(self, d):
        return dict(self.history).get(d)


def test_numpy_logistic_separates():
    rng = np.random.default_rng(1)
    X = np.vstack([
        rng.normal(-2, 0.5, size=(60, 4)),
        rng.normal(2, 0.5, size=(60, 4)),
    ])
    y = np.array([0] * 60 + [1] * 60)
    m = _NumpyLogistic(C=1.0).fit(X, y)
    p = m.predict_proba(X)[:, 1]
    assert p[:60].max() < 0.1, "负类概率应接近 0"
    assert p[60:].min() > 0.9, "正类概率应接近 1"
    assert m.backend == "numpy_logistic"


def test_train_predict_end_to_end():
    history = _make_history()
    cfg = ScreenerConfig()
    model = ml_engine.train_walkforward(history, cfg)
    assert model is not None, "应成功训练模型"
    cur = history[-1][1].copy()
    proba = ml_engine.predict_ml(model, cur, cfg)
    assert proba is not None
    assert len(proba) == len(cur)
    assert proba.min() >= 0.0 and proba.max() <= 1.0


def test_run_ml_layer_learns_signal():
    history = _make_history()
    cfg = ScreenerConfig()
    cur = history[-1][1].copy()
    store = _FakeStore(history)
    mlp, diag, status = ml_engine.run_ml_layer(
        cfg, store=store, current_df=cur, history=history)
    assert status == "trained"
    assert mlp is not None
    assert diag.get("backend") in ("numpy_logistic", "lightgbm")
    # 学到的信号应使 OOS 排名 IC / AUC 优于随机
    oos = diag.get("ml_oos")
    if oos == "ok":
        auc = diag.get("ml_oos_auc")
        assert auc is not None and auc > 0.5, f"ML 应学到增量信号，AUC={auc}"


def test_run_ml_layer_insufficient_history():
    # 仅 10 天历史，远低于 ml_min_history_days(60)
    history = _make_history(n_dates=10)
    cfg = ScreenerConfig()
    cur = history[-1][1].copy()
    store = _FakeStore(history)
    mlp, diag, status = ml_engine.run_ml_layer(
        cfg, store=store, current_df=cur, history=history)
    assert mlp is None
    assert status == "insufficient_history"


def test_score_frame_ml_mode_fills_prob():
    history = _make_history()
    cfg = ScreenerConfig.from_dict({"engine": {"mode": "ml"}})
    store = _FakeStore(history)
    cur = history[-1][1].copy()
    meta: dict = {}
    scores = scoring.score_frame(cur, cfg, store=store, meta=meta)
    assert len(scores) > 0
    # 至少部分标的应被 ML 层赋予概率
    probs = [s.ml_prob for s in scores if s.ml_prob is not None]
    assert len(probs) == len(scores), "ml 模式下每只标的都应有 ml_prob"
    assert all(0.0 <= p <= 1.0 for p in probs)
    assert meta.get("engine_mode") == "ml"
    assert meta.get("model_status") == "trained"
    # ml 模式下综合分应落在 0~100
    assert all(0.0 <= s.total_score <= 100.0 for s in scores)


def test_score_frame_blend_mode_runs():
    history = _make_history()
    cfg = ScreenerConfig.from_dict({"engine": {"mode": "blend", "blend_alpha": 0.5}})
    store = _FakeStore(history)
    cur = history[-1][1].copy()
    meta: dict = {}
    scores = scoring.score_frame(cur, cfg, store=store, meta=meta)
    assert len(scores) > 0
    assert meta.get("engine_mode") == "blend"
    assert meta.get("model_status") == "trained"
    assert all(s.ml_prob is not None for s in scores)
