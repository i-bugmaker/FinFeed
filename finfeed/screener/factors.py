#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""因子计算与归一化（纯函数，可单测）。

本模块把「原始行情/基本面字段」映射为「0~100 的维度子分」，并通过
可解释的归一化函数（sigmoid / 钟形 / 分段线性）完成。
所有锚点参数来自 config.ScreenerConfig，便于复现与调参。
"""

from __future__ import annotations

import math
from typing import Any


# ---------------------------------------------------------------------------
# 归一化基元
# ---------------------------------------------------------------------------

def clamp(x: float, lo: float = 0.0, hi: float = 100.0) -> float:
    """将数值截断到 [lo, hi]。"""
    if x < lo:
        return lo
    if x > hi:
        return hi
    return x


def _sigmoid(x: float, mid: float, scale: float) -> float:
    """Logistic：x=mid 时为 0.5；scale 控制陡峭度。"""
    try:
        return 1.0 / (1.0 + math.exp(-(x - mid) / scale))
    except OverflowError:
        return 0.0 if x < mid else 1.0


def score_sigmoid(x: float, mid: float, scale: float, higher_better: bool = True) -> float:
    """sigmoid 映射到 0~100。higher_better=False 时取反（越低越好）。"""
    s = _sigmoid(x, mid, scale)
    if not higher_better:
        s = 1.0 - s
    return clamp(s * 100.0)


def score_bell(x: float, mid: float, width: float) -> float:
    """高斯钟形：x=mid 时 100，离 mid 越远越低。"""
    if width <= 0:
        return 100.0 if x == mid else 0.0
    return clamp(100.0 * math.exp(-(((x - mid) / width) ** 2)))


def score_band(x: float, lo: float, hi: float) -> float:
    """分段线性：x<=lo→0，x>=hi→100，之间线性。"""
    if x <= lo:
        return 0.0
    if x >= hi:
        return 100.0
    return clamp((x - lo) / (hi - lo) * 100.0)


def _f(x: Any) -> float:
    """安全转 float：None / NaN → 0.0。"""
    try:
        v = float(x)
        return v if math.isfinite(v) else 0.0
    except (TypeError, ValueError):
        return 0.0


# ---------------------------------------------------------------------------
# 维度子分
# ---------------------------------------------------------------------------

def score_capital(row: dict, p: dict) -> tuple[float, dict[str, str]]:
    """资金面：今日主力净比 + 5日主力净流入占流通市值比。"""
    cp = p["capital"]
    ratio = _f(row.get("main_net_ratio"))
    s_today = score_sigmoid(ratio, cp["today_ratio_mid"], cp["today_ratio_scale"])

    net5d_pct = _f(row.get("main_net_5d_pct"))
    s_5d = score_sigmoid(net5d_pct, cp["net5d_pct_mid"], cp["net5d_pct_scale"])

    score = cp["w_today"] * s_today + cp["w_5d"] * s_5d
    contrib = {
        "主力净比": f"{ratio:+.2f}% → {s_today:.0f}",
        "5日净流入占流通": f"{net5d_pct:+.2f}% → {s_5d:.0f}",
    }
    return clamp(score), contrib


def score_momentum(row: dict, p: dict) -> tuple[float, dict[str, str]]:
    """动量趋势：20日动量(含过热衰减) + 60日动量 + 多周期动量有序性。"""
    mp = p["momentum"]
    c5 = _f(row.get("change_5d_pct"))
    c20 = _f(row.get("change_20d_pct"))
    c60 = _f(row.get("change_60d_pct"))

    s20 = score_sigmoid(c20, mp["mom20_mid"], mp["mom20_scale"])
    if c20 > mp["mom20_overheat"]:
        decay = max(mp["mom20_overheat_floor"], 1.0 - (c20 - mp["mom20_overheat"]) / 80.0)
        s20 = clamp(s20 * decay)
    s60 = score_sigmoid(c60, mp["mom60_mid"], mp["mom60_scale"])

    # 多周期动量有序：5日≥20日≥60日≥0 每满足一项 +1/3
    ordered = ((c5 >= c20) + (c20 >= c60) + (c60 >= 0)) / 3.0 * 100.0

    score = mp["w_mom20"] * s20 + mp["w_mom60"] * s60 + mp["w_align"] * ordered
    contrib = {
        "20日动量": f"{c20:+.1f}% → {s20:.0f}",
        "60日动量": f"{c60:+.1f}% → {s60:.0f}",
        "动量有序度": f"{ordered:.0f}",
    }
    return clamp(score), contrib


def score_valuation(row: dict, p: dict) -> tuple[float, dict[str, str]]:
    """估值（双价值因子）：PE_TTM 钟形 + 股息率钟形。

    PE_TTM 衡量相对估值（越低越便宜，钟形峰值在合理区）；
    股息率衡量收入型价值与现金流稳定性（持续高分红≈经营稳健）。
    两者按 w_pe / w_dy 加权融合。
    """
    vp = p["valuation"]
    pe = _f(row.get("pe_ttm"))
    if pe <= 0:
        contrib = {"PE_TTM": f"亏损 → {vp['loss_penalty']:.0f}"}
        return clamp(vp["loss_penalty"]), contrib
    s_pe = score_bell(pe, vp["pe_mid"], vp["pe_width"])

    dy = _f(row.get("dividend_yield"))
    s_dy = score_bell(dy, vp["dy_mid"], vp["dy_width"]) if dy > 0 else 0.0

    score = vp["w_pe"] * s_pe + vp["w_dy"] * s_dy
    contrib = {
        "PE_TTM": f"{pe:.1f} → {s_pe:.0f}",
        "股息率": f"{dy:.2f}% → {s_dy:.0f}",
    }
    return clamp(score), contrib


def score_liquidity(row: dict, p: dict) -> tuple[float, dict[str, str]]:
    """量价活跃：成交额(log) + 换手率(钟形)。"""
    lp = p["liquidity"]
    amt = _f(row.get("amount"))
    if amt > 0:
        la = math.log10(amt)
        s_amt = score_band(la, lp["amount_log_lo"], lp["amount_log_hi"])
    else:
        s_amt = 0.0
    to = _f(row.get("turnover"))
    s_to = score_bell(to, lp["turnover_mid"], lp["turnover_width"])

    score = lp["w_amount"] * s_amt + lp["w_turnover"] * s_to
    contrib = {
        "成交额(亿)": f"{amt / 1e8:.2f} → {s_amt:.0f}",
        "换手率": f"{to:.2f}% → {s_to:.0f}",
    }
    return clamp(score), contrib


def score_quality(row: dict, p: dict) -> tuple[float, dict[str, str]]:
    """质量稳定（四因子）：

    - 波动率适中（振幅或已实现年化波动）
    - 盈利为正（EPS>0）
    - 市值规模稳健（log10 总市值钟形，避免壳/妖股与超大盘极端）
    - 持续分红（股息率钟形，经营稳健信号）
    """
    qp = p["quality"]
    eps = _f(row.get("eps"))
    s_profit = 100.0 if eps > 0 else 0.0

    rv = row.get("realized_vol_ann")
    if rv is not None and math.isfinite(float(rv)):
        v = float(rv)
        s_vol = score_bell(v, qp["vol_ann_mid"], qp["vol_ann_width"])
        vol_label = f"年化波动{v:.0f}%"
    else:
        amp = _f(row.get("amplitude"))
        s_vol = score_bell(amp, qp["amp_mid"], qp["amp_width"])
        vol_label = f"振幅{amp:.2f}%"

    mcap = _f(row.get("total_market_cap"))
    if mcap > 0:
        lm = math.log10(mcap)
        s_size = score_bell(lm, qp["size_log_mid"], qp["size_log_width"])
        size_label = f"市值{lm:.1f}(log)"
    else:
        s_size = 0.0
        size_label = "市值缺失"

    dy = _f(row.get("dividend_yield"))
    s_dy = score_bell(dy, qp["dy_mid"], qp["dy_width"]) if dy > 0 else 0.0

    score = (
        qp["w_vol"] * s_vol
        + qp["w_profit"] * s_profit
        + qp["w_size"] * s_size
        + qp["w_dy"] * s_dy
    )
    contrib = {
        vol_label: f"→ {s_vol:.0f}",
        "盈利EPS": f"{eps:.2f} → {s_profit:.0f}",
        size_label: f"→ {s_size:.0f}",
        "股息率": f"{dy:.2f}% → {s_dy:.0f}",
    }
    return clamp(score), contrib


def dimension_scores(row: dict, cfg) -> dict[str, tuple[float, dict[str, str]]]:
    """返回五个维度的 (子分, 贡献说明)。"""
    p = cfg.params
    return {
        "capital": score_capital(row, p),
        "momentum": score_momentum(row, p),
        "valuation": score_valuation(row, p),
        "liquidity": score_liquidity(row, p),
        "quality": score_quality(row, p),
    }
