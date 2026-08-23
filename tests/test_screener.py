#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""选股模块单元测试（离线、确定性）。

测试输入为「固定真实代码 + 固定数值」构造的 DataFrame（仅存在于本测试文件，
用于验证评分逻辑的确定性，绝不进入生产数据链路；生产数据唯一来源为 easy-tdx
实时行情 / 项目内真实数据源，选股模块不包含任何演示或模拟数据）。

fixture 覆盖的边界情形：
    ST、停牌、亏损、小市值、高估值、低换手、入选候选、护栏降级（高估值/接近涨停）。
"""

from __future__ import annotations

import math

import pandas as pd
from finfeed.screener import factors, scoring
from finfeed.screener.config import ScreenerConfig
from finfeed.screener.models import StockScore

# 固定测试输入（真实代码 + 固定数值）。列契约与 datasource.fetch_universe 的
# 规范列一致（market: 1=沪 0=深；float_shares 单位万股；金额单位元）。
_FIXTURE_ROWS = [
    # 1) 入选候选：资金+动量+估值+量价俱佳（真实代码 600036 招商银行，数值为固定快照）
    dict(market=1, code="600036", name="招商银行", pre_close=24.50, open=24.60, high=25.40, low=24.30,
         close=25.00, vol=3.2e6, vol_ratio=1.1, amount=8.0e9, total_shares=1.2e6, float_shares=1.0e5,
         eps=1.50, total_market_cap=3.0e10, dividend_yield=1.2, turnover=3.2,
         circulating_capital_z=2.5e10, pe_ttm=16.0, main_net_amount=2.0e8, main_net_ratio=3.0,
         main_net_5d_amount=3.75e8, change_5d_pct=10.0, change_20d_pct=28.0, change_60d_pct=40.0,
         change_1y_pct=15.0, realized_vol_ann=35.0, ma_align=True, drawdown_from_high=-8.0),
    # 2) 关注：综合分高但估值偏高（触发护栏降级）
    dict(market=1, code="603288", name="海天味业", pre_close=58.0, open=58.5, high=60.0, low=57.5,
         close=59.0, vol=2.0e6, vol_ratio=1.0, amount=1.2e10, total_shares=1.0e6, float_shares=9.0e4,
         eps=1.05, total_market_cap=5.9e10, dividend_yield=0.3, turnover=3.5,
         circulating_capital_z=5.3e10, pe_ttm=55.0, main_net_amount=4.0e8, main_net_ratio=4.0,
         main_net_5d_amount=8.0e8, change_5d_pct=8.0, change_20d_pct=30.0, change_60d_pct=45.0,
         change_1y_pct=60.0, realized_vol_ann=55.0, ma_align=True, drawdown_from_high=-5.0),
    # 3) 观察：中规中矩
    dict(market=0, code="000858", name="五粮液", pre_close=12.0, open=12.1, high=12.4, low=11.9,
         close=12.2, vol=1.5e6, vol_ratio=0.9, amount=1.8e9, total_shares=2.0e6, float_shares=1.8e5,
         eps=0.60, total_market_cap=2.4e10, dividend_yield=0.8, turnover=1.0,
         circulating_capital_z=2.2e10, pe_ttm=20.3, main_net_amount=2.0e7, main_net_ratio=0.8,
         main_net_5d_amount=5.0e7, change_5d_pct=2.0, change_20d_pct=8.0, change_60d_pct=12.0,
         change_1y_pct=5.0, realized_vol_ann=30.0, ma_align=True, drawdown_from_high=-12.0),
    # 4) 排除：ST
    dict(market=0, code="000005", name="ST星源", pre_close=3.50, open=3.50, high=3.60, low=3.40,
         close=3.45, vol=1.0e6, vol_ratio=1.0, amount=3.5e8, total_shares=5.0e5, float_shares=4.5e5,
         eps=-0.30, total_market_cap=1.7e9, dividend_yield=0.0, turnover=1.5,
         circulating_capital_z=1.5e9, pe_ttm=-11.0, main_net_amount=-2.0e7, main_net_ratio=-1.0,
         main_net_5d_amount=-5.0e7, change_5d_pct=-2.0, change_20d_pct=-10.0, change_60d_pct=-20.0,
         change_1y_pct=-40.0),
    # 5) 排除：停牌（无成交）
    dict(market=1, code="600519", name="贵州茅台", pre_close=20.0, open=20.0, high=20.0, low=20.0,
         close=20.0, vol=0.0, vol_ratio=0.0, amount=0.0, total_shares=1.0e6, float_shares=9.0e5,
         eps=0.40, total_market_cap=2.0e10, dividend_yield=1.0, turnover=0.0,
         circulating_capital_z=1.8e10, pe_ttm=50.0, main_net_amount=0.0, main_net_ratio=0.0,
         main_net_5d_amount=0.0, change_5d_pct=0.0, change_20d_pct=0.0, change_60d_pct=0.0,
         change_1y_pct=0.0),
    # 6) 排除：亏损
    dict(market=0, code="000008", name="神州高铁", pre_close=15.0, open=15.1, high=15.4, low=14.8,
         close=15.2, vol=1.2e6, vol_ratio=1.0, amount=1.8e9, total_shares=8.0e5, float_shares=7.0e5,
         eps=-0.50, total_market_cap=1.2e10, dividend_yield=0.0, turnover=2.0,
         circulating_capital_z=1.06e10, pe_ttm=-30.0, main_net_amount=5.0e7, main_net_ratio=1.0,
         main_net_5d_amount=1.0e8, change_5d_pct=3.0, change_20d_pct=10.0, change_60d_pct=15.0,
         change_1y_pct=10.0),
    # 7) 排除：小市值壳
    dict(market=0, code="000009", name="中国宝安", pre_close=6.0, open=6.05, high=6.1, low=5.95,
         close=6.1, vol=8.0e5, vol_ratio=1.2, amount=4.9e8, total_shares=6.0e4, float_shares=5.0e3,
         eps=0.10, total_market_cap=3.6e8, dividend_yield=0.0, turnover=2.5,
         circulating_capital_z=3.0e8, pe_ttm=60.0, main_net_amount=2.0e7, main_net_ratio=2.0,
         main_net_5d_amount=4.0e7, change_5d_pct=4.0, change_20d_pct=15.0, change_60d_pct=20.0,
         change_1y_pct=12.0),
    # 8) 排除：高估值
    dict(market=1, code="600012", name="皖通高速", pre_close=80.0, open=80.5, high=82.0, low=79.0,
         close=81.0, vol=9.0e5, vol_ratio=1.0, amount=7.3e9, total_shares=2.0e5, float_shares=1.8e5,
         eps=0.50, total_market_cap=1.6e10, dividend_yield=0.0, turnover=4.0,
         circulating_capital_z=1.45e10, pe_ttm=162.0, main_net_amount=1.0e8, main_net_ratio=1.5,
         main_net_5d_amount=2.0e8, change_5d_pct=5.0, change_20d_pct=20.0, change_60d_pct=30.0,
         change_1y_pct=50.0),
    # 9) 排除：低换手
    dict(market=0, code="000010", name="美丽生态", pre_close=9.0, open=9.05, high=9.1, low=8.95,
         close=9.05, vol=2.0e5, vol_ratio=0.5, amount=1.8e8, total_shares=2.0e6, float_shares=1.8e6,
         eps=0.30, total_market_cap=1.8e10, dividend_yield=0.5, turnover=0.1,
         circulating_capital_z=1.6e10, pe_ttm=30.0, main_net_amount=1.0e7, main_net_ratio=0.5,
         main_net_5d_amount=2.0e7, change_5d_pct=1.0, change_20d_pct=5.0, change_60d_pct=8.0,
         change_1y_pct=3.0),
    # 10) 关注：综合强但当日涨停（接近涨跌停触发护栏降级）
    dict(market=1, code="601318", name="中国平安", pre_close=20.0, open=20.5, high=22.0, low=20.3,
         close=22.0, vol=4.0e6, vol_ratio=2.0, amount=8.8e9, total_shares=1.0e6, float_shares=9.0e5,
         eps=1.20, total_market_cap=2.2e10, dividend_yield=1.0, turnover=4.5,
         circulating_capital_z=1.98e10, pe_ttm=18.3, main_net_amount=5.0e8, main_net_ratio=5.0,
         main_net_5d_amount=9.0e8, change_5d_pct=15.0, change_20d_pct=35.0, change_60d_pct=50.0,
         change_1y_pct=40.0, realized_vol_ann=48.0, ma_align=True, drawdown_from_high=-2.0),
    # 11) 入选候选：创业板 15% 涨幅（< 20%×0.95），动态涨跌停护栏不应降级
    dict(market=0, code="300001", name="特锐德", pre_close=20.0, open=20.5, high=23.0, low=20.3,
         close=23.0, vol=4.0e6, vol_ratio=2.0, amount=8.8e9, total_shares=1.0e6, float_shares=9.0e5,
         eps=1.20, total_market_cap=2.2e10, dividend_yield=1.0, turnover=4.5,
         circulating_capital_z=1.98e10, pe_ttm=18.3, main_net_amount=5.0e8, main_net_ratio=5.0,
         main_net_5d_amount=9.0e8, change_5d_pct=15.0, change_20d_pct=35.0, change_60d_pct=50.0,
         change_1y_pct=40.0, realized_vol_ann=48.0, ma_align=True, drawdown_from_high=-2.0),
]


def _make_df() -> pd.DataFrame:
    """构造测试固定输入的 DataFrame（规范列，与真实数据链路列契约一致）。"""
    return pd.DataFrame(_FIXTURE_ROWS)


def _scores():
    cfg = ScreenerConfig()
    df = _make_df()
    return cfg, scoring.score_frame(df, cfg, technical_enabled=True)


def test_excluded_by_filters():
    """ST / 停牌 / 亏损 / 小市值 / 高估值 / 低换手 应被硬性过滤剔除。"""
    cfg, scores = _scores()
    codes = {s.code for s in scores}
    for excluded in ("000005", "600519", "000008", "000009", "600012", "000010"):
        assert excluded not in codes, f"{excluded} 应被过滤，但出现在评分结果中"


def test_strong_candidate():
    """招商银行(600036) 应为入选候选(strong)且各维度分在 0~100。"""
    cfg, scores = _scores()
    by_code = {s.code: s for s in scores}
    s = by_code["600036"]
    assert isinstance(s, StockScore)
    assert s.tier == "strong", f"600036 评级应为 strong，实际 {s.tier}"
    assert 0.0 <= s.total_score <= 100.0
    for dim in (s.capital_score, s.momentum_score, s.valuation_score,
                s.liquidity_score, s.quality_score):
        assert 0.0 <= dim <= 100.0, f"维度分越界: {dim}"


def test_guardrail_downgrade():
    """高估值(603288)与当日涨停(601318)触发护栏，不应入选 strong。"""
    cfg, scores = _scores()
    by_code = {s.code: s for s in scores}
    assert by_code["603288"].tier != "strong"
    assert by_code["601318"].tier != "strong"
    # 护栏失败原因应被记录
    assert by_code["603288"].guardrail_failures, "603288 应记录估值护栏失败"
    assert "当日接近涨跌停" in by_code["601318"].guardrail_failures, \
        "601318（主板 +10%）应触发动态涨跌停护栏"


def test_cyb_limit_not_downgraded():
    """板块动态涨跌停：创业板 15% 涨幅（<20%×0.95）不应触发涨跌停护栏。"""
    cfg, scores = _scores()
    by_code = {s.code: s for s in scores}
    s = by_code["300001"]
    assert "当日接近涨跌停" not in s.guardrail_failures, "创业板 15% 不应被误判接近涨跌停"
    assert s.tier == "strong", "创业板强动量标的应入选 strong"


def test_pe_missing_not_excluded():
    """缺失语义：PE 缺失不应被误判为亏损/高估值而剔除。"""
    cfg = ScreenerConfig()
    df = pd.DataFrame([
        dict(market=1, code="600999", name="招商证券", close=12.0, pre_close=11.8,
             high=12.2, low=11.7, vol=2.0e6, amount=2.0e9, turnover=2.0,
             float_shares=5.0e5, pe_ttm=float("nan"), main_net_5d_amount=1.0e8),
    ])
    row = scoring.build_factor_row(df.iloc[0].to_dict())
    ok, reason = scoring.is_eligible(row, cfg)
    assert ok, f"PE 缺失不应被剔除（实际原因：{reason}）"
    # 估值维度应给中性分而非亏损惩罚分
    dims = scoring.factors.dimension_scores(row, cfg)
    val_score, contrib = dims["valuation"]
    assert val_score >= 40, f"PE 缺失应给中性估值分，实际 {val_score}"


def test_mcap_missing_not_excluded():
    """缺失语义：流通市值缺失（回退源场景）不应被误判为小市值剔除。"""
    cfg = ScreenerConfig()
    df = pd.DataFrame([
        dict(market=1, code="600998", name="九州通", close=12.0, pre_close=11.8,
             high=12.2, low=11.7, vol=2.0e6, amount=2.0e9, turnover=2.0,
             float_shares=float("nan"), pe_ttm=18.0, main_net_5d_amount=1.0e8),
    ])
    row = scoring.build_factor_row(df.iloc[0].to_dict())
    ok, reason = scoring.is_eligible(row, cfg)
    assert ok, f"市值缺失不应按小市值剔除（实际原因：{reason}）"


def test_price_missing_excluded():
    """缺失语义：价格缺失应被剔除（无法交易/评分）。"""
    cfg = ScreenerConfig()
    df = pd.DataFrame([
        dict(market=1, code="600997", name="开滦股份", close=float("nan"), pre_close=11.8,
             vol=2.0e6, amount=2.0e9, turnover=2.0, float_shares=5.0e5, pe_ttm=18.0),
    ])
    row = scoring.build_factor_row(df.iloc[0].to_dict())
    ok, reason = scoring.is_eligible(row, cfg)
    assert not ok and "价格缺失" in reason


def test_sorted_descending():
    """结果按综合分降序。"""
    cfg, scores = _scores()
    totals = [s.total_score for s in scores]
    assert totals == sorted(totals, reverse=True)


def test_deterministic():
    """同输入两次评分结果一致。"""
    cfg = ScreenerConfig()
    df = _make_df()
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


def test_vector_scalar_consistency():
    """向量化评分（score_frame）与标量因子路径（factors.dimension_scores）数值一致。"""
    from finfeed.screener import vector
    from finfeed.screener.datasource import _add_derived

    cfg = ScreenerConfig()
    df = _add_derived(_make_df())
    dims_v = vector.dimension_scores_vec(df, cfg)
    for pos, rec in enumerate(df.to_dict("records")):
        row = scoring.build_factor_row(rec)
        dims_s = factors.dimension_scores(row, cfg)
        for d in ("capital", "momentum", "valuation", "liquidity", "quality", "sentiment"):
            v = float(dims_v[d].iloc[pos])
            s = dims_s[d][0]
            assert abs(v - s) < 1e-6, f"pos {pos} 维度 {d} 不一致: vec={v} scalar={s}"


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
