#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""评分引擎向量化实现（numpy / pandas 批量计算）。

与 factors.py 的标量路径共用同一份 config 参数，数值行为保持一致
（差异仅来自浮点运算顺序，容差 < 1e-6 量级）。

职责：
- dimension_scores_vec：对全市场 DataFrame 一次性计算五个维度子分；
- assemble_vec：板块中性化（groupby percentile）+ 加权总分 + 动态涨跌停护栏 + 评级，
  输出数值字段 DataFrame（rationale 等解释性文本由调用方在逐行阶段生成）。

缺失语义：各维度计算前对缺失列 fillna(0)，与标量路径 _f(NaN)->0 行为一致；
估值维度按 PE 缺失 -> 中性分处理（与 factors.score_valuation 对齐）。
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from .boards import classify_board
from .normalize import orthogonalize_dimensions


def _vec_sigmoid(x: pd.Series, mid: float, scale: float) -> pd.Series:
    return 1.0 / (1.0 + np.exp(-(x - mid) / scale))


def _vec_bell(x: pd.Series, mid: float, width: float) -> pd.Series:
    if width <= 0:
        return (x == mid).astype(float) * 100.0
    return 100.0 * np.exp(-(((x - mid) / width) ** 2))


def _vec_band(x: pd.Series, lo: float, hi: float) -> pd.Series:
    return ((x - lo) / (hi - lo)).clip(0.0, 1.0) * 100.0


def _col(df: pd.DataFrame, name: str) -> pd.Series:
    """取列；列不存在时返回全 NaN Series（保持行对齐）。"""
    if name in df.columns:
        return df[name]
    return pd.Series(float("nan"), index=df.index)


def _num(s: pd.Series) -> pd.Series:
    """转数值并填充缺失为 0（与标量 _f 行为一致）。"""
    return pd.to_numeric(s, errors="coerce").fillna(0.0).astype(float)


def dimension_scores_vec(df: pd.DataFrame, cfg) -> dict[str, pd.Series]:
    """批量计算五维度子分。返回 dict[dim] -> Series（0~100）。"""
    p = cfg.params
    out: dict[str, pd.Series] = {}

    # ---- 资金面 ----
    cp = p["capital"]
    ratio = _num(_col(df, "main_net_ratio"))
    net5d_pct = _num(_col(df, "main_net_5d_pct"))
    s_today = _vec_sigmoid(ratio, cp["today_ratio_mid"], cp["today_ratio_scale"]) * 100.0
    s_5d = _vec_sigmoid(net5d_pct, cp["net5d_pct_mid"], cp["net5d_pct_scale"]) * 100.0
    out["capital"] = (cp["w_today"] * s_today + cp["w_5d"] * s_5d).clip(0.0, 100.0)

    # ---- 动量趋势 ----
    mp = p["momentum"]
    c5 = _num(_col(df, "change_5d_pct"))
    c10 = _num(_col(df, "change_10d_pct"))
    c20 = _num(_col(df, "change_20d_pct"))
    c60 = _num(_col(df, "change_60d_pct"))
    s20 = _vec_sigmoid(c20, mp["mom20_mid"], mp["mom20_scale"]) * 100.0
    overheat = c20 > mp["mom20_overheat"]
    denom = mp.get("mom20_decay_denom", 80.0)
    decay = (1.0 - (c20 - mp["mom20_overheat"]) / denom).clip(mp.get("mom20_overheat_floor", 0.6), 1.0)
    s20 = s20.where(~overheat, s20 * decay)
    s60 = _vec_sigmoid(c60, mp["mom60_mid"], mp["mom60_scale"]) * 100.0
    ordered = ((c5 >= c20).astype(float) + (c20 >= c60).astype(float) + (c60 >= 0).astype(float)) / 3.0 * 100.0
    # 动量加速度：20日动量 - 10日动量（10日缺失 -> 输入 0 得 sigmoid 中性 50，与标量一致）
    c10_raw = pd.to_numeric(_col(df, "change_10d_pct"), errors="coerce")
    accel_in = (c20 - c10).where(c10_raw.notna(), 0.0)
    s_accel = _vec_sigmoid(accel_in, mp["accel_mid"], mp["accel_scale"]) * 100.0
    out["momentum"] = (
        mp["w_mom20"] * s20 + mp["w_mom60"] * s60
        + mp["w_align"] * ordered + mp["w_accel"] * s_accel
    ).clip(0.0, 100.0)

    # ---- 估值（PE 缺失 -> 中性分；PE<=0 -> 亏损惩罚）----
    vp = p["valuation"]
    pe_raw = pd.to_numeric(_col(df, "pe_ttm"), errors="coerce")
    pe = pe_raw.fillna(0.0).astype(float)
    missing = pe_raw.isna()
    loss = pe <= 0
    s_pe = _vec_bell(pe, vp["pe_mid"], vp["pe_width"])
    s_pe = s_pe.where(~loss, vp["loss_penalty"])
    s_pe = s_pe.where(~missing, vp.get("missing_score", 50.0))
    dy = _num(_col(df, "dividend_yield"))
    s_dy = _vec_bell(dy, vp["dy_mid"], vp["dy_width"]).where(dy > 0, 0.0)
    out["valuation"] = (vp["w_pe"] * s_pe + vp["w_dy"] * s_dy).clip(0.0, 100.0)
    # 与标量一致：亏损行直接取 loss_penalty（不含股息率加权），缺失行取中性分
    out["valuation"] = out["valuation"].where(~loss, vp["loss_penalty"])
    out["valuation"] = out["valuation"].where(~missing, vp.get("missing_score", 50.0))

    # ---- 量价活跃 ----
    lp = p["liquidity"]
    amt = _num(_col(df, "amount"))
    la = np.log10(amt.replace(0.0, np.nan)).fillna(0.0)
    s_amt = _vec_band(la, lp["amount_log_lo"], lp["amount_log_hi"]).where(amt > 0, 0.0)
    to = _num(_col(df, "turnover"))
    s_to = _vec_bell(to, lp["turnover_mid"], lp["turnover_width"])
    out["liquidity"] = (lp["w_amount"] * s_amt + lp["w_turnover"] * s_to).clip(0.0, 100.0)

    # ---- 质量稳定（四因子）----
    qp = p["quality"]
    eps = _num(_col(df, "eps"))
    s_profit = (eps > 0).astype(float) * 100.0
    rv = pd.to_numeric(_col(df, "realized_vol_ann"), errors="coerce")
    amp = _num(_col(df, "amplitude"))
    s_vol_rv = _vec_bell(rv, qp["vol_ann_mid"], qp["vol_ann_width"])
    s_vol_amp = _vec_bell(amp, qp["amp_mid"], qp["amp_width"])
    s_vol = s_vol_rv.where(rv.notna(), s_vol_amp).fillna(0.0)
    mcap = _num(_col(df, "total_market_cap"))
    lm = np.log10(mcap.replace(0.0, np.nan)).fillna(0.0)
    s_size = _vec_bell(lm, qp["size_log_mid"], qp["size_log_width"]).where(mcap > 0, 0.0)
    s_dy_q = _vec_bell(dy, qp["dy_mid"], qp["dy_width"]).where(dy > 0, 0.0)
    out["quality"] = (
        qp["w_vol"] * s_vol + qp["w_profit"] * s_profit
        + qp["w_size"] * s_size + qp["w_dy"] * s_dy_q
    ).clip(0.0, 100.0)

    # ---- 情绪/事件（四因子，easy-tdx 快照源）----
    sp = p["sentiment"]
    lup = _num(_col(df, "annual_limit_up_days"))
    s_lup = _vec_bell(lup, sp["limitup_mid"], sp["limitup_width"])
    streak = _num(_col(df, "consecutive_up_days"))
    s_streak = _vec_bell(streak, sp["streak_mid"], sp["streak_width"])
    ddx = _num(_col(df, "ddx"))
    s_ddx = _vec_sigmoid(ddx, sp["ddx_mid"], sp["ddx_scale"]) * 100.0
    vs = _num(_col(df, "vol_speed_pct"))
    s_vs = _vec_bell(vs, sp["volspeed_mid"], sp["volspeed_width"])
    out["sentiment"] = (
        sp["w_limitup"] * s_lup + sp["w_streak"] * s_streak
        + sp["w_ddx"] * s_ddx + sp["w_volspeed"] * s_vs
    ).clip(0.0, 100.0)

    return out


def _limit_pct_series(board: pd.Series, name: pd.Series) -> pd.Series:
    """按行计算板块动态涨跌停幅度（%）。"""
    s = pd.Series(10.0, index=board.index)
    s = s.where(~name.str.contains("ST|退", case=False, regex=True), 5.0)
    s = s.where(~board.isin(["kcb", "cyb"]), 20.0)
    s = s.where(~board.eq("bj"), 30.0)
    return s


def _neutralize_groups(df: pd.DataFrame, boards: pd.Series, cfg) -> pd.Series:
    """构造中性化分组键：板块 + 行业 + 市值分层（配置驱动，逐级回退）。

    返回与 df 同索引的分组标签 Series。
    """
    nz = cfg.neutralize or {}
    group = boards.astype(str)
    if nz.get("by_industry", True):
        ind = df.get("industry")
        if ind is not None:
            # 行业缺失("")回退板块分组
            g2 = group + "|" + ind.astype(str).where(ind.astype(str) != "", group)
            group = g2
    if nz.get("by_size", True):
        mcap = pd.to_numeric(df.get("total_market_cap"), errors="coerce")
        if mcap is not None and mcap.notna().sum() > 10:
            q = nz.get("size_quantiles", 3)
            try:
                size_band = pd.qcut(mcap, q, labels=False, duplicates="drop")
                size_band = size_band.astype(str).where(size_band.notna(), "")
                group = group + "|sz" + size_band.where(size_band != "", group)
            except ValueError:
                pass  # 分位数不足时回退
    return group


def assign_tier(total: pd.Series, fail_mask: pd.Series, cfg) -> pd.Series:
    """由综合分 + 护栏掩码计算评级（strong/watch/observe/none）。

    与 assemble_vec 内的评级逻辑完全一致：绝对阈值优先；动态评级启用时，
    「绝对达标者少于下限」才用截面分位兜底放宽（弱市防入选=0、强市不过度泛滥）。
    抽出为独立函数，便于混合层（ML/blend）在复算综合分后复用同一套评级。
    """
    t = cfg.tiers
    g = t["guardrails"]
    dyn_cfg = t.get("dynamic") or {}
    dyn = bool(dyn_cfg.get("enabled", False))
    idx = total.index
    rank_frac = total.rank(method="max", pct=True) if dyn else None
    tier = pd.Series("none", index=idx)

    def _dynamic_ok(rank_ge: float, floor: int, abs_ok: pd.Series) -> pd.Series:
        n_abs = int(abs_ok.sum())
        if n_abs >= floor:
            return abs_ok
        return abs_ok | (rank_frac >= rank_ge)

    if dyn:
        strong_abs = (total >= t["strong"]) & ~fail_mask
        watch_abs = (((total >= t["watch"]) | ((total >= t["strong"]) & fail_mask)))
        observe_abs = total >= t["observe"]
        strong_ok = _dynamic_ok(
            1.0 - float(dyn_cfg.get("rank_top_strong", 0.08)),
            int(dyn_cfg.get("min_strong_floor", 10)), strong_abs)
        watch_ok = _dynamic_ok(
            1.0 - float(dyn_cfg.get("rank_top_watch", 0.25)),
            int(dyn_cfg.get("min_strong_floor", 10)) * 2, watch_abs) & ~strong_ok
        observe_ok = _dynamic_ok(
            1.0 - float(dyn_cfg.get("rank_top_observe", 0.50)),
            int(dyn_cfg.get("min_strong_floor", 10)) * 4, observe_abs) & ~strong_ok & ~watch_ok
        tier[strong_ok] = "strong"
        tier[watch_ok] = "watch"
        tier[observe_ok] = "observe"
    else:
        strong_ok = (total >= t["strong"]) & ~fail_mask
        watch_ok = ((total >= t["watch"]) | ((total >= t["strong"]) & fail_mask)) & ~strong_ok
        tier[strong_ok] = "strong"   # strong 优先于 watch
        tier[watch_ok] = "watch"
        tier[total < t["observe"]] = "none"
    return tier


def assemble_vec(df: pd.DataFrame, dims: dict[str, pd.Series], cfg,
                 weights: dict | None = None, orthogonalize: bool = False) -> pd.DataFrame:
    """中性化 + 加权总分 + 动态护栏 + 评级，输出数值字段 DataFrame。

    返回列：code/name/market/board/price/change_pct/pe_ttm/amplitude/amount/
    capital_score/momentum_score/valuation_score/liquidity_score/quality_score/
    total_score/tier/eligible/guardrail_failures(空列表占位)。

    weights: 维度权重覆盖（默认用 cfg.weights）。IC 加权引擎通过 resolve_weights
             产出后传入，实现「客观赋权」而不改动默认经验权重路径。
    orthogonalize: 是否对维度子分做横截面正交化（去冗余，提升 ICIR 稳定性）。
    """
    w = weights if weights is not None else cfg.weights
    t = cfg.tiers
    g = t["guardrails"]
    nb = float((cfg.neutralize or {}).get("blend", 0.0))

    idx = df.index
    dim_df = pd.DataFrame({k: v.reindex(idx) for k, v in dims.items()})

    # 板块归类（行级，纯前缀映射）
    codes = _col(df, "code").astype(str).str.zfill(6)
    markets = pd.to_numeric(_col(df, "market"), errors="coerce").fillna(0).astype(int)
    boards = pd.Series(
        [classify_board(c, m) for c, m in zip(codes, markets)],
        index=idx,
    )

    # 组内百分位中性化（板块+行业+市值分层；method="max" 与标量 bisect_right/n 语义一致）
    blended = dim_df.copy()
    if nb > 0:
        groups = _neutralize_groups(df, boards, cfg)
        pct = dim_df.groupby(groups).rank(method="max", pct=True) * 100.0
        blended = ((1.0 - nb) * dim_df + nb * pct).clip(0.0, 100.0)

    # 维度正交化（可选）：剔除维度间冗余信息，提升合成 ICIR 稳定性
    # （engine.orthogonalize=True 时启用；残差重缩放回 0~100，不改变量纲）
    if orthogonalize:
        blended = orthogonalize_dimensions(blended)

    _DIMS = ("capital", "momentum", "valuation", "liquidity", "quality", "sentiment")
    total = sum(w[d] * blended[d] for d in _DIMS if d in blended)
    total = total.clip(0.0, 100.0)

    chg = pd.to_numeric(_col(df, "chg_today"), errors="coerce").fillna(0.0)
    names = _col(df, "name").astype(str)
    limit = _limit_pct_series(boards, names)

    failures: dict[str, pd.Series] = {
        "资金面不足": blended["capital"] < g["capital_min"],
        "动量不足": blended["momentum"] < g["momentum_min"],
        "估值偏高": blended["valuation"] < g["valuation_min"],
        "质量/波动欠佳": blended["quality"] < g["quality_min"],
        "当日接近涨跌停": chg.abs() >= limit * 0.95,
    }
    fail_mask = pd.concat(list(failures.values()), axis=1).any(axis=1)

    # 动态评级：绝对阈值优先；仅当绝对达标者低于下限（弱市）时，
    # 用截面分位作为兜底放宽（assign_tier 内实现，混合层复用同一逻辑）。
    tier = assign_tier(total, fail_mask, cfg)

    out = pd.DataFrame({
        "code": codes,
        "name": names,
        "market": markets,
        "board": boards,
        "price": pd.to_numeric(_col(df, "close"), errors="coerce").fillna(0.0),
        "change_pct": chg,
        "pe_ttm": pd.to_numeric(_col(df, "pe_ttm"), errors="coerce").fillna(0.0),
        "amplitude": pd.to_numeric(_col(df, "amplitude"), errors="coerce").fillna(0.0),
        "amount": pd.to_numeric(_col(df, "amount"), errors="coerce").fillna(0.0),
        "capital_score": blended["capital"],
        "momentum_score": blended["momentum"],
        "valuation_score": blended["valuation"],
        "liquidity_score": blended["liquidity"],
        "quality_score": blended["quality"],
        "sentiment_score": blended["sentiment"] if "sentiment" in blended else pd.Series(0.0, index=idx),
        "total_score": total,
        "tier": tier,
        "eligible": pd.Series(True, index=idx),
        "guardrail_mask": fail_mask,
        "fail_capital": failures["资金面不足"],
        "fail_momentum": failures["动量不足"],
        "fail_valuation": failures["估值偏高"],
        "fail_quality": failures["质量/波动欠佳"],
        "fail_limit": failures["当日接近涨跌停"],
    }, index=idx)
    return out
