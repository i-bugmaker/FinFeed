#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""内置离线样例数据（真实字段结构，数值为虚构示例）。

用途：
- 无网络环境下演示 / 验证评分引擎（`--demo`）。
- 单元测试（tests/test_screener.py）的确定性输入，覆盖各边界情形：
  ST、停牌、亏损、小市值、高估值、低换手、入选候选、护栏降级等。
"""

from __future__ import annotations

import pandas as pd

# 列顺序无关；scoring.build_factor_row 会按需读取并计算派生字段。
_ROWS = [
    # 1) 入选候选：资金+动量+估值+量价俱佳
    dict(market=1, code="600001", name="齐鲁优选", pre_close=24.50, open=24.60, high=25.40, low=24.30,
         close=25.00, vol=3.2e6, vol_ratio=1.1, amount=8.0e9, total_shares=1.2e6, float_shares=1.0e5,
         eps=1.50, total_market_cap=3.0e10, dividend_yield=1.2, turnover=3.2,
         circulating_capital_z=2.5e10, pe_ttm=16.0, main_net_amount=2.0e8, main_net_ratio=3.0,
         main_net_5d_amount=3.75e8, change_5d_pct=10.0, change_20d_pct=28.0, change_60d_pct=40.0,
         change_1y_pct=15.0, realized_vol_ann=35.0, ma_align=True, drawdown_from_high=-8.0),
    # 2) 关注：综合分高但估值偏高（触发护栏降级）
    dict(market=1, code="600002", name="长江科技", pre_close=58.0, open=58.5, high=60.0, low=57.5,
         close=59.0, vol=2.0e6, vol_ratio=1.0, amount=1.2e10, total_shares=1.0e6, float_shares=9.0e4,
         eps=1.05, total_market_cap=5.9e10, dividend_yield=0.3, turnover=3.5,
         circulating_capital_z=5.3e10, pe_ttm=55.0, main_net_amount=4.0e8, main_net_ratio=4.0,
         main_net_5d_amount=8.0e8, change_5d_pct=8.0, change_20d_pct=30.0, change_60d_pct=45.0,
         change_1y_pct=60.0, realized_vol_ann=55.0, ma_align=True, drawdown_from_high=-5.0),
    # 3) 观察：中规中矩
    dict(market=0, code="000003", name="华夏制造", pre_close=12.0, open=12.1, high=12.4, low=11.9,
         close=12.2, vol=1.5e6, vol_ratio=0.9, amount=1.8e9, total_shares=2.0e6, float_shares=1.8e5,
         eps=0.60, total_market_cap=2.4e10, dividend_yield=0.8, turnover=1.0,
         circulating_capital_z=2.2e10, pe_ttm=20.3, main_net_amount=2.0e7, main_net_ratio=0.8,
         main_net_5d_amount=5.0e7, change_5d_pct=2.0, change_20d_pct=8.0, change_60d_pct=12.0,
         change_1y_pct=5.0, realized_vol_ann=30.0, ma_align=True, drawdown_from_high=-12.0),
    # 4) 入选候选：稳健绩优，估值低但动量一般
    dict(market=1, code="600004", name="滨海能源", pre_close=9.80, open=9.85, high=10.0, low=9.70,
         close=9.95, vol=2.5e6, vol_ratio=1.0, amount=2.5e9, total_shares=3.0e6, float_shares=2.8e5,
         eps=0.85, total_market_cap=2.98e10, dividend_yield=3.5, turnover=1.2,
         circulating_capital_z=2.8e10, pe_ttm=11.7, main_net_amount=1.2e8, main_net_ratio=2.4,
         main_net_5d_amount=3.0e8, change_5d_pct=3.0, change_20d_pct=12.0, change_60d_pct=18.0,
         change_1y_pct=8.0, realized_vol_ann=22.0, ma_align=True, drawdown_from_high=-15.0),
    # 5) 排除：ST
    dict(market=0, code="000005", name="ST金星", pre_close=3.50, open=3.50, high=3.60, low=3.40,
         close=3.45, vol=1.0e6, vol_ratio=1.0, amount=3.5e8, total_shares=5.0e5, float_shares=4.5e5,
         eps=-0.30, total_market_cap=1.7e9, dividend_yield=0.0, turnover=1.5,
         circulating_capital_z=1.5e9, pe_ttm=-11.0, main_net_amount=-2.0e7, main_net_ratio=-1.0,
         main_net_5d_amount=-5.0e7, change_5d_pct=-2.0, change_20d_pct=-10.0, change_60d_pct=-20.0,
         change_1y_pct=-40.0),
    # 6) 排除：停牌（无成交）
    dict(market=1, code="000006", name="沉默股份", pre_close=20.0, open=20.0, high=20.0, low=20.0,
         close=20.0, vol=0.0, vol_ratio=0.0, amount=0.0, total_shares=1.0e6, float_shares=9.0e5,
         eps=0.40, total_market_cap=2.0e10, dividend_yield=1.0, turnover=0.0,
         circulating_capital_z=1.8e10, pe_ttm=50.0, main_net_amount=0.0, main_net_ratio=0.0,
         main_net_5d_amount=0.0, change_5d_pct=0.0, change_20d_pct=0.0, change_60d_pct=0.0,
         change_1y_pct=0.0),
    # 7) 排除：亏损
    dict(market=0, code="000007", name="微利科技", pre_close=15.0, open=15.1, high=15.4, low=14.8,
         close=15.2, vol=1.2e6, vol_ratio=1.0, amount=1.8e9, total_shares=8.0e5, float_shares=7.0e5,
         eps=-0.50, total_market_cap=1.2e10, dividend_yield=0.0, turnover=2.0,
         circulating_capital_z=1.06e10, pe_ttm=-30.0, main_net_amount=5.0e7, main_net_ratio=1.0,
         main_net_5d_amount=1.0e8, change_5d_pct=3.0, change_20d_pct=10.0, change_60d_pct=15.0,
         change_1y_pct=10.0),
    # 8) 排除：小市值壳
    dict(market=0, code="000008", name="壳资源A", pre_close=6.0, open=6.05, high=6.1, low=5.95,
         close=6.1, vol=8.0e5, vol_ratio=1.2, amount=4.9e8, total_shares=6.0e4, float_shares=5.0e3,
         eps=0.10, total_market_cap=3.6e8, dividend_yield=0.0, turnover=2.5,
         circulating_capital_z=3.0e8, pe_ttm=60.0, main_net_amount=2.0e7, main_net_ratio=2.0,
         main_net_5d_amount=4.0e7, change_5d_pct=4.0, change_20d_pct=15.0, change_60d_pct=20.0,
         change_1y_pct=12.0),
    # 9) 排除：高估值
    dict(market=1, code="000009", name="高估股份", pre_close=80.0, open=80.5, high=82.0, low=79.0,
         close=81.0, vol=9.0e5, vol_ratio=1.0, amount=7.3e9, total_shares=2.0e5, float_shares=1.8e5,
         eps=0.50, total_market_cap=1.6e10, dividend_yield=0.0, turnover=4.0,
         circulating_capital_z=1.45e10, pe_ttm=162.0, main_net_amount=1.0e8, main_net_ratio=1.5,
         main_net_5d_amount=2.0e8, change_5d_pct=5.0, change_20d_pct=20.0, change_60d_pct=30.0,
         change_1y_pct=50.0),
    # 10) 排除：低换手
    dict(market=0, code="000010", name="冷门传媒", pre_close=9.0, open=9.05, high=9.1, low=8.95,
         close=9.05, vol=2.0e5, vol_ratio=0.5, amount=1.8e8, total_shares=2.0e6, float_shares=1.8e6,
         eps=0.30, total_market_cap=1.8e10, dividend_yield=0.5, turnover=0.1,
         circulating_capital_z=1.6e10, pe_ttm=30.0, main_net_amount=1.0e7, main_net_ratio=0.5,
         main_net_5d_amount=2.0e7, change_5d_pct=1.0, change_20d_pct=5.0, change_60d_pct=8.0,
         change_1y_pct=3.0),
    # 11) 关注：综合强但当日涨停（接近涨跌停触发护栏降级）
    dict(market=1, code="600012", name="涨停追高", pre_close=20.0, open=20.5, high=22.0, low=20.3,
         close=22.0, vol=4.0e6, vol_ratio=2.0, amount=8.8e9, total_shares=1.0e6, float_shares=9.0e5,
         eps=1.20, total_market_cap=2.2e10, dividend_yield=1.0, turnover=4.5,
         circulating_capital_z=1.98e10, pe_ttm=18.3, main_net_amount=5.0e8, main_net_ratio=5.0,
         main_net_5d_amount=9.0e8, change_5d_pct=15.0, change_20d_pct=35.0, change_60d_pct=50.0,
         change_1y_pct=40.0, realized_vol_ann=48.0, ma_align=True, drawdown_from_high=-2.0),
    # 12) 观察：优质银行，估值极低但动量弱
    dict(market=1, code="600013", name="稳健银行", pre_close=7.0, open=7.02, high=7.1, low=6.95,
         close=7.05, vol=5.0e6, vol_ratio=0.8, amount=3.5e9, total_shares=2.0e7, float_shares=1.5e7,
         eps=1.10, total_market_cap=1.4e11, dividend_yield=5.5, turnover=0.4,
         circulating_capital_z=1.05e11, pe_ttm=6.4, main_net_amount=-3.0e7, main_net_ratio=-0.3,
         main_net_5d_amount=-5.0e7, change_5d_pct=-0.5, change_20d_pct=2.0, change_60d_pct=4.0,
         change_1y_pct=-3.0, realized_vol_ann=18.0, ma_align=False, drawdown_from_high=-20.0),
]


def load_sample_dataframe() -> pd.DataFrame:
    """返回内置样例 DataFrame（规范列）。"""
    return pd.DataFrame(_ROWS)
