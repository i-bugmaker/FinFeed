#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""P6 评估闭环单元测试。

覆盖：
- evaluate_engine 在合成历史上无未来函数地产出 RankIC/ICIR/分层收益/IR；
- 因子失效监控能识别 ICIR 偏弱的维度；
- 重算触发建议能给出可执行动作（recompute_weights / enable_ml_blend）；
- 历史不足时优雅返回 error。
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from finfeed.screener.config import ScreenerConfig
from finfeed.screener import evaluation
from test_ml_engine import _make_history, _FakeStore


def test_evaluate_engine_produces_metrics():
    hist = _make_history(n_dates=120)
    store = _FakeStore(hist)
    cfg = ScreenerConfig.from_dict({"engine": {"mode": "fixed"}})
    res = evaluation.evaluate_engine(cfg, store, horizon=20, step=2, min_periods=10)
    assert "error" not in res, res.get("error")
    assert res["n_periods"] >= 10
    assert res["composite"] is not None
    # 复合 RankIC 应显著（动量信号在合成数据中有效）
    assert res["composite"]["ic_mean"] > 0.0
    assert res["composite"]["icir"] > 0.0
    # 五分位分层应单调（高分位前瞻收益 > 低分位）
    layers = res["layers"]
    assert "Q1" in layers and "Q5" in layers
    assert layers["Q5"] >= layers["Q1"]
    # 多空价差 IR 字段存在
    assert "information_ratio" in res["spread"]


def test_evaluate_engine_insufficient_history():
    hist = _make_history(n_dates=15)  # 远不足 horizon+1
    store = _FakeStore(hist)
    cfg = ScreenerConfig.from_dict({"engine": {"mode": "fixed"}})
    res = evaluation.evaluate_engine(cfg, store, horizon=20, min_periods=10)
    assert "error" in res


def test_monitor_factor_health_flags_weak():
    per_dim = {
        "momentum": {"ic_mean": 0.08, "icir": 2.5, "n_periods": 50},
        "capital": {"ic_mean": 0.01, "icir": 0.3, "n_periods": 50},   # 偏弱
        "valuation": {"ic_mean": 0.02, "icir": 0.8, "n_periods": 50},
    }
    flags = evaluation.monitor_factor_health(per_dim, fail_icir=0.5)
    weak_dims = {f["dim"] for f in flags}
    assert "capital" in weak_dims
    assert "momentum" not in weak_dims


def test_recommend_recalibration():
    composite = {"ic_mean": 0.05, "icir": 0.8}  # 复合 ICIR 偏低
    per_dim = {
        "momentum": {"icir": 2.5},
        "capital": {"icir": 0.3},     # 失效维度
    }
    rec = evaluation.recommend_recalibration(composite, per_dim)
    actions = {a["action"] for a in rec["actions"]}
    assert "recompute_weights" in actions        # 失效维度 → IC 客观重赋权
    assert "enable_ml_blend" in actions          # 复合 ICIR 低 → 启 ML 混合
    assert rec["suggested_engine_mode"] in ("ic", "blend")


def test_recommend_recalibration_healthy():
    composite = {"ic_mean": 0.10, "icir": 3.0}
    per_dim = {"momentum": {"icir": 3.0}, "capital": {"icir": 2.0}}
    rec = evaluation.recommend_recalibration(composite, per_dim)
    assert rec["actions"][0]["action"] == "keep"


def test_render_evaluation_markdown():
    hist = _make_history(n_dates=120)
    store = _FakeStore(hist)
    cfg = ScreenerConfig.from_dict({"engine": {"mode": "fixed"}})
    res = evaluation.evaluate_engine(cfg, store, horizon=20, step=2, min_periods=10)
    md = evaluation.render_evaluation_markdown(res)
    assert "# 选股引擎评估闭环报告" in md
    assert "RankIC" in md
