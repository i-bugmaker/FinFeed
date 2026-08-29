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


def _is_missing(x: Any) -> bool:
    """判断是否为缺失值（None / NaN），用于区分「缺失」与「真实 0/负值」。"""
    try:
        return x is None or math.isnan(float(x))
    except (TypeError, ValueError):
        return True


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
    """动量趋势：20日动量(含过热衰减) + 60日动量 + 动量有序 + 动量加速度。

    加速度 = 20日动量 - 10日动量（趋势加速>0 更优），衡量时序动能；
    缺失（无 10 日数据源）时给中性分（sigmoid(0)=50）。
    """
    mp = p["momentum"]
    c5 = _f(row.get("change_5d_pct"))
    c10 = _f(row.get("change_10d_pct"))
    c20 = _f(row.get("change_20d_pct"))
    c60 = _f(row.get("change_60d_pct"))

    s20 = score_sigmoid(c20, mp["mom20_mid"], mp["mom20_scale"])
    if c20 > mp["mom20_overheat"]:
        denom = mp.get("mom20_decay_denom", 80.0)
        floor = mp.get("mom20_overheat_floor", 0.6)
        decay = max(floor, 1.0 - (c20 - mp["mom20_overheat"]) / denom)
        s20 = clamp(s20 * decay)
    s60 = score_sigmoid(c60, mp["mom60_mid"], mp["mom60_scale"])

    # 多周期动量有序：5日≥20日≥60日≥0 每满足一项 +1/3
    ordered = ((c5 >= c20) + (c20 >= c60) + (c60 >= 0)) / 3.0 * 100.0

    # 动量加速度：20日动量 - 10日动量（缺失给中性 50）
    if _is_missing(row.get("change_10d_pct")):
        s_accel = 50.0
        accel_label = "缺失→中性"
    else:
        accel = c20 - c10
        s_accel = score_sigmoid(accel, mp["accel_mid"], mp["accel_scale"])
        accel_label = f"{accel:+.1f}%"

    score = (
        mp["w_mom20"] * s20 + mp["w_mom60"] * s60
        + mp["w_align"] * ordered + mp["w_accel"] * s_accel
    )
    contrib = {
        "20日动量": f"{c20:+.1f}% → {s20:.0f}",
        "60日动量": f"{c60:+.1f}% → {s60:.0f}",
        "动量有序度": f"{ordered:.0f}",
        "动量加速度": f"{accel_label} → {s_accel:.0f}",
    }
    return clamp(score), contrib


def score_valuation(row: dict, p: dict) -> tuple[float, dict[str, str]]:
    """估值（双价值因子）：PE_TTM 钟形 + 股息率钟形。

    PE_TTM 衡量相对估值（越低越便宜，钟形峰值在合理区）；
    股息率衡量收入型价值与现金流稳定性（持续高分红≈经营稳健）。
    两者按 w_pe / w_dy 加权融合。

    缺失语义：PE 缺失（NaN）给中性分，**绝不误判为亏损**。
    """
    vp = p["valuation"]
    pe = _f(row.get("pe_ttm"))
    if _is_missing(row.get("pe_ttm")):
        contrib = {"PE_TTM": "缺失 → 中性"}
        return clamp(vp.get("missing_score", 50.0)), contrib
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


def score_sentiment(row: dict, p: dict) -> tuple[float, dict[str, str]]:
    """情绪/事件（四因子，easy-tdx 快照源）：

    - 涨停基因：年内涨停天数（钟形，峰值约 6 次；过高=妖股风险衰减）
    - 连涨动能：连涨天数（钟形，峰值 3 天；连跌自然低分）
    - 大单动向：DDX 大单净量比（sigmoid，>0 净流入更好）
    - 量能变化：量速（钟形，适度放量最优，爆量警惕）
    缺失（回退源/非交易时段）按中性处理。
    """
    sp = p["sentiment"]

    lup = _f(row.get("annual_limit_up_days"))
    s_lup = score_bell(lup, sp["limitup_mid"], sp["limitup_width"])

    streak = _f(row.get("consecutive_up_days"))
    s_streak = score_bell(streak, sp["streak_mid"], sp["streak_width"])

    ddx = _f(row.get("ddx"))
    s_ddx = score_sigmoid(ddx, sp["ddx_mid"], sp["ddx_scale"])

    vs = _f(row.get("vol_speed_pct"))
    s_vs = score_bell(vs, sp["volspeed_mid"], sp["volspeed_width"])

    score = (
        sp["w_limitup"] * s_lup + sp["w_streak"] * s_streak
        + sp["w_ddx"] * s_ddx + sp["w_volspeed"] * s_vs
    )
    contrib = {
        "年内涨停": f"{lup:.0f}次 → {s_lup:.0f}",
        "连涨": f"{streak:.0f}天 → {s_streak:.0f}",
        "DDX": f"{ddx:+.3f} → {s_ddx:.0f}",
        "量速": f"{vs:.2f} → {s_vs:.0f}",
    }
    return clamp(score), contrib


def score_growth(row: dict, p: dict) -> tuple[float, dict[str, str]]:
    """成长性（两因子，数据源：东财业绩预告 earnings_forecast）：

    - 预告增幅：最新一期业绩预告的净利润同比增幅（sigmoid，增幅 30% 得 50 分）
    - 预告类型：预增/扭亏/略增加分，预减/首亏/略减/续亏减分，未知给中性
    缺失（无业绩预告覆盖）按中性 50 处理——不因信息缺失惩罚标的。
    """
    gp = p["growth"]
    g = row.get("earnings_growth_pct")
    if _is_missing(g):
        s_growth = 50.0
        g_label = "缺失→中性"
    else:
        s_growth = score_sigmoid(_f(g), gp["growth_mid"], gp["growth_scale"])
        g_label = f"{_f(g):+.1f}%"

    ftype = str(row.get("forecast_type") or "").strip()
    if ftype in gp.get("bonus_types", ()):
        s_type = 100.0
    elif ftype in gp.get("penalty_types", ()):
        s_type = 0.0
    else:
        s_type = 50.0

    score = gp["w_growth"] * s_growth + gp["w_type"] * s_type
    contrib = {
        "预告增幅": f"{g_label} → {s_growth:.0f}",
        "预告类型": f"{ftype or '无'} → {s_type:.0f}",
    }
    return clamp(score), contrib


def score_reversal(row: dict, p: dict) -> tuple[float, dict[str, str]]:
    """反转/超跌修复（两因子，easy-tdx 快照源）：

    - 20 日跌幅反转：跌得越深反弹弹性越高（higher_better=False）；
      跌势过深（> 阈值）视为趋势性下跌，分数衰减防接飞刀
    - 当日企稳：止跌（≥0）给高分，继续大跌给低分
    缺失（无 K 线派生数据）按中性处理。
    """
    rp = p["reversal"]
    c20 = row.get("change_20d_pct")
    if _is_missing(c20):
        s_drop = 50.0
        drop_label = "缺失→中性"
    else:
        c20 = _f(c20)
        s_drop = score_sigmoid(c20, rp["drop_mid"], rp["drop_scale"], higher_better=False)
        if c20 < -rp["cliff_threshold"]:
            s_drop = clamp(s_drop * rp["cliff_floor"])
        drop_label = f"{c20:+.1f}%"

    chg = row.get("chg_today")
    if _is_missing(chg):
        s_stab = 50.0
        stab_label = "缺失→中性"
    else:
        s_stab = score_sigmoid(_f(chg), rp["stabilize_mid"], rp["stabilize_scale"])
        stab_label = f"{_f(chg):+.2f}%"

    score = rp["w_drop"] * s_drop + rp["w_stabilize"] * s_stab
    contrib = {
        "20日跌幅": f"{drop_label} → {s_drop:.0f}",
        "当日企稳": f"{stab_label} → {s_stab:.0f}",
    }
    return clamp(score), contrib


def dimension_scores(row: dict, cfg) -> dict[str, tuple[float, dict[str, str]]]:
    """返回八个维度的 (子分, 贡献说明)。"""
    p = cfg.params
    return {
        "capital": score_capital(row, p),
        "momentum": score_momentum(row, p),
        "valuation": score_valuation(row, p),
        "liquidity": score_liquidity(row, p),
        "quality": score_quality(row, p),
        "sentiment": score_sentiment(row, p),
        "growth": score_growth(row, p),
        "reversal": score_reversal(row, p),
    }
