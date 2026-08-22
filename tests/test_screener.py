#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""选股模块单元测试（离线、确定性，基于内置样例数据）。"""

from __future__ import annotations

import math

from finfeed.screener import config as cfg_mod
from finfeed.screener import sample_data, scoring
from finfeed.screener.config import ScreenerConfig
from finfeed.screener.models import StockScore


def _scores():
    cfg = ScreenerConfig()
    df = sample_data.load_sample_dataframe()
    return cfg, scoring.score_frame(df, cfg, technical_enabled=True)


def test_excluded_by_filters():
    """ST / 停牌 / 亏损 / 小市值 / 高估值 / 低换手 应被硬性过滤剔除。"""
    cfg, scores = _scores()
    codes = {s.code for s in scores}
    for excluded in ("000005", "000006", "000007", "000008", "000009", "000010"):
        assert excluded not in codes, f"{excluded} 应被过滤，但出现在评分结果中"


def test_strong_candidate():
    """齐鲁优选(600001) 应为入选候选(strong)且各维度分在 0~100。"""
    cfg, scores = _scores()
    by_code = {s.code: s for s in scores}
    s = by_code["600001"]
    assert isinstance(s, StockScore)
    assert s.tier == "strong", f"600001 评级应为 strong，实际 {s.tier}"
    assert 0.0 <= s.total_score <= 100.0
    for dim in (s.capital_score, s.momentum_score, s.valuation_score,
                s.liquidity_score, s.quality_score):
        assert 0.0 <= dim <= 100.0, f"维度分越界: {dim}"


def test_guardrail_downgrade():
    """高估值(600002)与当日涨停(600012)触发护栏，不应入选 strong。"""
    cfg, scores = _scores()
    by_code = {s.code: s for s in scores}
    assert by_code["600002"].tier != "strong"
    assert by_code["600012"].tier != "strong"
    # 护栏失败原因应被记录
    assert by_code["600002"].guardrail_failures, "600002 应记录估值护栏失败"
    assert by_code["600012"].guardrail_failures, "600012 应记录接近涨跌停护栏失败"


def test_sorted_descending():
    """结果按综合分降序。"""
    cfg, scores = _scores()
    totals = [s.total_score for s in scores]
    assert totals == sorted(totals, reverse=True)


def test_deterministic():
    """同输入两次评分结果一致。"""
    cfg = ScreenerConfig()
    df = sample_data.load_sample_dataframe()
    a = scoring.score_frame(df, cfg, technical_enabled=True)
    b = scoring.score_frame(df, cfg, technical_enabled=True)
    assert [s.code for s in a] == [s.code for s in b]
    assert [round(s.total_score, 6) for s in a] == [round(s.total_score, 6) for s in b]


def test_is_eligible_unit():
    """直接验证硬性过滤逻辑。"""
    cfg = ScreenerConfig()
    st_row = scoring.build_factor_row({"name": "ST测试", "market": 1, "close": 10,
                                        "pe_ttm": 20, "vol": 1e6, "amount": 1e9,
                                        "turnover": 2.0, "float_shares": 1e5})
    ok, reason = scoring.is_eligible(st_row, cfg)
    assert not ok and "ST" in reason

    normal = scoring.build_factor_row({"name": "正常股", "market": 1, "close": 10,
                                        "pre_close": 9.8, "high": 10.2, "low": 9.7,
                                        "pe_ttm": 18, "vol": 1e6, "amount": 1e9,
                                        "turnover": 2.0, "float_shares": 1e5,
                                        "main_net_5d_amount": 1e8})
    ok2, _ = scoring.is_eligible(normal, cfg)
    assert ok2


def test_explain_nonempty():
    """方法论说明应非空且包含维度表。"""
    text = ScreenerConfig().explain()
    assert "资金面" in text and "动量趋势" in text and "评级" in text


def test_config_roundtrip(tmp_path):
    """配置 JSON 序列化往返一致。"""
    cfg = ScreenerConfig()
    p = tmp_path / "cfg.json"
    cfg.save(str(p))
    cfg2 = ScreenerConfig.load(str(p))
    assert math.isclose(cfg.weights["capital"], cfg2.weights["capital"])
    assert cfg.tiers["strong"] == cfg2.tiers["strong"]
