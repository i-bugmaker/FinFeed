#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""P6 评估闭环：walk-forward 评估 + 因子失效监控 + 权重重算触发。

设计目标（见 docs/screener_refactor_design.md §3 评估闭环）：
- 用真实积累的历史快照做**无未来函数**的 walk-forward 评估：
  每个截面 t 仅用 t 及之前的数据评分（score_frame 传 end_date=t），
  前瞻收益用 t+horizon 的真实快照 close，杜绝未来函数。
- 产出复合与分维度的 RankIC / ICIR、五分位分层收益、多空（Top-Bottom）价差与
  信息比率（IR，年化），作为方法论有效性的客观证据。
- 因子失效监控：滚动窗口内分维度 ICIR 跌破阈值即标记「失效维度」；
- 重算触发：失效维度过多或复合 ICIR 偏低时，给出「切 IC 客观重赋权 / 启 ML 混合」
  的可执行建议（recommend_recalibration），形成「评估 → 预警 → 重赋权」闭环。

本模块纯函数、零副作用；不修改任何全局配置，仅产出评估结果与建议。
"""

from __future__ import annotations

import math
from typing import Any

import numpy as np
import pandas as pd
from scipy.stats import spearmanr

from .config import ScreenerConfig
from .ic_engine import DIMS
from .scoring import score_frame

_ANNUAL_TRADING_DAYS = 242


def _agg_ic(series: list[float]) -> dict[str, float] | None:
    """由逐期 IC 序列聚合出 IC mean / std / ICIR / 命中率。"""
    arr = np.array([v for v in series if v == v and v is not None], dtype=float)
    if arr.size == 0:
        return None
    std = float(arr.std(ddof=0))
    icir = float(arr.mean() / (std + 1e-9))
    return {
        "ic_mean": round(float(arr.mean()), 4),
        "ic_std": round(std, 4),
        "icir": round(icir, 4),
        "hit_rate": round(float((arr > 0).mean()), 4),
        "n_periods": int(arr.size),
    }


def evaluate_engine(cfg: ScreenerConfig, store, end_date: str | None = None,
                    horizon: int | None = None, step: int = 1,
                    min_periods: int = 20) -> dict[str, Any]:
    """walk-forward 评估当前引擎配置，返回 RankIC/ICIR/分层收益/IR 等指标。

    Args:
        cfg:          评分配置（engine.mode 决定线性/IC/ML/混合）。
        store:        SnapshotStore 实例（需已积累历史快照）。
        end_date:     评估截止日（含）；默认用最新快照。
        horizon:      前瞻收益期限（交易日）；默认取 engine.horizon。
        step:         截面间隔（交易日），1=每个交易日一个截面。
        min_periods:  最少所需有效截面数，不足返回 error。

    返回 dict 含：composite(复合 RankIC/ICIR)、per_dimension(分维度)、
        layers(五分位分层收益)、spread(多空价差与 IR)、factor_health(失效标记)、
        n_periods、engine_mode 等。
    """
    engine = getattr(cfg, "engine", None) or {}
    horizon = int(horizon if horizon is not None else engine.get("horizon", 20))

    dates = store.available_dates()
    if end_date:
        dates = [d for d in dates if d <= end_date]
    if len(dates) < horizon + 1:
        return {"error": f"历史快照不足：当前 {len(dates)} 日，需 ≥{horizon + 1}",
                "n_periods": 0}

    records: list[dict[str, Any]] = []
    for i in range(0, len(dates) - horizon, max(step, 1)):
        t = dates[i]
        tf = dates[i + horizon]
        day = store.load_date(t)
        fday = store.load_date(tf)
        if day is None or fday is None or len(day) < 30:
            continue
        close_map = day.set_index("code")["close"].to_dict()
        fwd_map = fday.set_index("code")["close"].to_dict()
        meta: dict = {}
        # 关键：end_date=t 保证评分只用 t 及之前数据（IC 权重/ML 训练无未来函数）
        scores = score_frame(day, cfg, store=store, meta=meta, end_date=t)
        if len(scores) < 30:
            continue
        tot = {s.code: float(s.total_score) for s in scores}
        dims = {d: {s.code: float(getattr(s, f"{d}_score")) for s in scores} for d in DIMS}
        fwd = {}
        for c in tot:
            c0 = close_map.get(c)
            cf = fwd_map.get(c)
            fwd[c] = (cf / c0 - 1.0) if (c0 and cf and c0 > 0) else float("nan")
        records.append({
            "date": t,
            "engine_mode": meta.get("engine_mode", engine.get("mode", "fixed")),
            "codes": list(tot.keys()),
            "total": tot,
            "dims": dims,
            "fwd": fwd,
        })

    if len(records) < min_periods:
        return {"error": f"有效评估截面不足：{len(records)} < {min_periods}",
                "n_periods": len(records)}

    # 逐期复合 RankIC 与分维度 RankIC
    period_total: list[float] = []
    period_dim: dict[str, list[float]] = {d: [] for d in DIMS}
    layer_q: dict[int, list[float]] = {q: [] for q in range(5)}
    spreads: list[float] = []

    for rec in records:
        codes = rec["codes"]
        tot = np.array([rec["total"][c] for c in codes], dtype=float)
        fwd = np.array([rec["fwd"][c] for c in codes], dtype=float)
        mask = ~np.isnan(fwd)
        if mask.sum() < 20:
            continue
        tm, fm = tot[mask], fwd[mask]
        if np.std(tm) > 0:
            r = spearmanr(tm, fm).statistic
            if r == r:
                period_total.append(float(r))
        for d in DIMS:
            dv = np.array([rec["dims"][d][c] for c in codes], dtype=float)[mask]
            if np.std(dv) > 0:
                rd = spearmanr(dv, fm).statistic
                if rd == rd:
                    period_dim[d].append(float(rd))
        # 五分位分层（按综合分）
        if np.std(tm) <= 0:
            continue
        try:
            q = pd.qcut(tm, 5, labels=False, duplicates="drop")
        except ValueError:
            continue
        for qq in range(5):
            sel = fm[q == qq]
            if len(sel) >= 3:
                layer_q[qq].append(float(sel.mean()))
        if 0 in q and 4 in q:
            spreads.append(float(fm[q == 4].mean()) - float(fm[q == 0].mean()))

    composite = _agg_ic(period_total)
    per_dim = {d: _agg_ic(period_dim[d]) for d in DIMS}
    per_dim = {d: v for d, v in per_dim.items() if v is not None}

    layers = {f"Q{q + 1}": round(float(np.mean(layer_q[q])) * 100.0, 3)
              for q in range(5) if layer_q[q]}
    spread_arr = np.array(spreads, dtype=float)
    ann = math.sqrt(_ANNUAL_TRADING_DAYS / max(horizon, 1))
    spread_mean = float(spread_arr.mean()) * 100.0
    spread_std = float(spread_arr.std(ddof=0)) * 100.0
    ir = float(spread_mean / (spread_std + 1e-9) * ann) if spread_std > 0 else None

    return {
        "engine_mode": records[0]["engine_mode"],
        "horizon": horizon,
        "n_periods": len(records),
        "min_periods": min_periods,
        "composite": composite,
        "per_dimension": per_dim,
        "layers": layers,
        "spread": {
            "top_minus_bottom_mean_pct": round(spread_mean, 3),
            "std_pct": round(spread_std, 3),
            "information_ratio": round(ir, 4) if ir is not None else None,
            "annualization_factor": round(ann, 3),
        },
        "factor_health": monitor_factor_health(per_dim, recent_window=min(20, len(records))),
        "recommendation": recommend_recalibration(composite, per_dim),
    }


def monitor_factor_health(per_dim: dict[str, dict[str, float]],
                          recent_window: int = 20,
                          fail_icir: float = 0.5) -> list[dict[str, Any]]:
    """因子失效监控：滚动窗口（最近 recent_window 期）内分维度 ICIR 跌破阈值即标记。

    per_dim: evaluate_engine 产出的分维度聚合（含 ic_mean/ic_std/icir/n_periods）。
    注意：本函数无逐期序列，仅用全样本 ICIR 与样本量近似判断（轻量监控）。
    若需更严谨的滚动窗口，请传入逐期序列（见 evaluation._roll_icir）。
    """
    flags: list[dict[str, Any]] = []
    for d, agg in per_dim.items():
        n = agg.get("n_periods", 0)
        full_icir = agg.get("icir", 0.0)
        # 样本不足或全样本 ICIR 偏弱 → 标记「观察」
        status = "ok"
        if full_icir < fail_icir:
            status = "weak"
        elif full_icir < fail_icir * 2:
            status = "watch"
        if status != "ok":
            flags.append({
                "dim": d,
                "status": status,
                "icir": full_icir,
                "ic_mean": agg.get("ic_mean"),
                "n_periods": n,
            })
    return flags


def _roll_icir(period_series: list[float], window: int = 20) -> float | None:
    """由逐期 IC 序列计算滚动窗口（最近 window 期）ICIR。"""
    arr = np.array([v for v in period_series if v == v and v is not None], dtype=float)
    if arr.size < window:
        return None
    w = arr[-window:]
    std = float(w.std(ddof=0))
    return float(w.mean() / (std + 1e-9))


def recommend_recalibration(composite: dict[str, float] | None,
                             per_dim: dict[str, dict[str, float]]) -> dict[str, Any]:
    """重算触发建议（闭环核心）：评估指标偏弱时给出可执行动作。

    返回 {flags, actions, suggested_engine_mode}：
    - 分维度失效（ICIR<0.5）维度较多 → 建议 engine.mode=ic（RankIC 客观重赋权，
      自动把权重从失效维度移开）；
    - 复合 ICIR < 1.0（单因子信息系数偏低）→ 建议启用 ml/blend 引入非线性增量；
    - 否则维持现状。
    """
    weak = [d for d, agg in per_dim.items() if agg.get("icir", 0.0) < 0.5]
    actions: list[dict[str, str]] = []
    suggested = "fixed"
    composite_icir = (composite or {}).get("icir", 0.0)
    if weak:
        actions.append({
            "action": "recompute_weights",
            "target_mode": "ic",
            "reason": f"{len(weak)} 个维度 ICIR<0.5（{', '.join(weak)}），"
                      f"建议 engine.mode=ic 用滚动 RankIC 客观重赋权，自动降低失效维度权重",
        })
        suggested = "ic"
    if composite_icir < 1.0:
        actions.append({
            "action": "enable_ml_blend",
            "target_mode": "blend",
            "reason": f"复合 ICIR={composite_icir:.2f}<1.0，线性层信息系数偏低，"
                      f"建议启用 ml/blend 引入非线性 ML 信号",
        })
        if not weak:
            suggested = "blend"
    if not actions:
        actions.append({"action": "keep", "target_mode": "current",
                         "reason": "各维度与复合 ICIR 健康，维持当前引擎配置"})
    return {
        "flags": [{"dim": d} for d in weak],
        "actions": actions,
        "suggested_engine_mode": suggested,
    }


def render_evaluation_markdown(result: dict[str, Any]) -> str:
    """渲染评估闭环报告（Markdown）。"""
    if "error" in result:
        return f"# 选股引擎评估\n\n**失败**：{result['error']}\n"
    L = ["# 选股引擎评估闭环报告", ""]
    L.append(f"- 引擎模式：`{result['engine_mode']}`｜前瞻期：{result['horizon']} 日｜"
             f"有效截面：{result['n_periods']} 个")
    comp = result.get("composite") or {}
    L.append(f"- **复合 RankIC(T+{result['horizon']})**：均值 {comp.get('ic_mean')} ± {comp.get('ic_std')}"
             f"，ICIR={comp.get('icir')}，正截面占比 {comp.get('hit_rate')}")
    spread = result.get("spread") or {}
    L.append(f"- **多空价差（Top-Bottom）**：均值 {spread.get('top_minus_bottom_mean_pct')}%"
             f"，IR={spread.get('information_ratio')}（年化因子 {spread.get('annualization_factor')}）")
    L.append("")
    pd_ = result.get("per_dimension") or {}
    if pd_:
        L.append("### 分维度 RankIC / ICIR")
        L.append("")
        L.append("| 维度 | IC均值 | ICIR | 正截面 |")
        L.append("|------|--------|------|--------|")
        for d, v in pd_.items():
            L.append(f"| {d} | {v.get('ic_mean')} | {v.get('icir')} | {v.get('hit_rate')} |")
        L.append("")
    layers = result.get("layers") or {}
    if layers:
        L.append("### 五分位分层收益（前瞻收益均值 %）")
        L.append("")
        L.append("| 分层 | T+" + str(result['horizon']) + " 收益 |")
        L.append("|------|------|")
        for q, v in layers.items():
            L.append(f"| {q} | {v} |")
        L.append("")
    fh = result.get("factor_health") or []
    if fh:
        L.append("### 因子失效监控")
        L.append("")
        for f in fh:
            L.append(f"- ⚠️ `{f['dim']}`：状态 {f['status']}，ICIR={f.get('icir')}")
        L.append("")
    rec = result.get("recommendation") or {}
    if rec.get("actions"):
        L.append("### 重算触发建议")
        L.append("")
        for a in rec["actions"]:
            L.append(f"- **{a['action']}** → {a.get('target_mode')}：{a.get('reason')}")
        L.append("")
    L.append("> 评估严格无未来函数（每个截面仅用其之前数据评分）；本结果为样本内/外混合验证，"
             "不构成投资建议。")
    return "\n".join(L)
