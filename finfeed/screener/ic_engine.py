#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""IC 加权选股引擎（新选股方法核心）。

取代旧管线「经验固定权重」，改用滚动 RankIC 客观赋权：
- 线性层：每个维度滚动窗口 RankIC，按半衰期衰减加权（近期 IC 影响更大），
  维度间按 ICIR 加权合成；可选正交化去冗余。
- 与 ML 层（LightGBM，后续阶段）通过 resolve_weights 的 mode 切换衔接。

加权逻辑依据（见 docs/screener_refactor_design.md）：
- 半衰期 IC 加权：结合 XGBoost 选因子实证（沪深300 年化 26.86% vs 基准 2.05%）；
- 正交化提升 ICIR 稳定性（海通：ICIR 2.29→3.30）；
- walk-forward：因子仅用 t 及之前数据，前瞻收益用 t+1..t+h，严禁未来函数。

对外主入口：
    resolve_weights(cfg, store=None) -> (weights, mode, diagnostics)
        mode="fixed"  : 经验固定权重（默认，零风险）
        mode="ic"     : 用真实快照历史的 IC 加权（需 ≥ min_history_days）
        mode="auto"   : 有历史用 IC，无历史降级 fixed
"""

from __future__ import annotations

import math
from typing import Any

import numpy as np
import pandas as pd

from . import vector
from .config import ScreenerConfig

# 八维体系（在六维基础上显式补入 growth / reversal，逐步接入）
DIMS = ("capital", "momentum", "valuation", "liquidity", "quality", "sentiment")


def _forward_returns(history: list[tuple[str, pd.DataFrame]], horizon: int):
    """由收盘价构造前瞻收益序列。

    history: 升序的 (trade_date, snapshot_df) 列表；df 需含 code / close。
    返回 [(date, codes(Index), r(Series 索引=code))] —— 仅含存在 h 日后收益的截面。
    """
    out = []
    n = len(history)
    for i in range(n - horizon):
        d, df = history[i]
        _, fdf = history[i + horizon]
        tclose = df.set_index("code")["close"]
        fclose = fdf.set_index("code")["close"]
        common = tclose.index.intersection(fclose.index)
        if len(common) < 30:
            continue
        r = fclose[common] / tclose[common] - 1.0
        out.append((d, common, r))
    return out


def compute_dimension_ic(
    history: list[tuple[str, pd.DataFrame]],
    cfg: ScreenerConfig,
    horizon: int = 20,
    dims: tuple[str, ...] = DIMS,
) -> dict[str, list[float]]:
    """计算每个维度在时间序列上的 RankIC 列表（与前瞻收益的截面 Spearman 相关）。

    对每个有前瞻收益的截面 t：用 vector.dimension_scores_vec 计算维度子分，
    与前瞻收益做截面秩相关 → IC_t；汇总为 ic_by_dim[dim] = [IC_1, ..., IC_T]。
    缺失 IC（NaN）被跳过。
    """
    by_date = {d: df for d, df in history}
    fr = _forward_returns(history, horizon)
    ic_by_dim: dict[str, list[float]] = {d: [] for d in dims}
    for d, codes, r in fr:
        df = by_date.get(d)
        if df is None or "code" not in df.columns:
            continue
        dim_scores = vector.dimension_scores_vec(df, cfg)
        # dimension_scores_vec 返回 Series 以 df 行位置为索引；前瞻收益 r 以
        # code 为索引。两者通过 code 对齐，避免位置错位导致 IC 全为 NaN。
        code_idx = df["code"].values
        for dim in dims:
            if dim not in dim_scores:
                continue
            s_by_code = pd.Series(dim_scores[dim].values, index=code_idx)
            s = s_by_code.reindex(codes)
            ic = s.corr(r, method="spearman")
            if ic is not None and not (isinstance(ic, float) and math.isnan(ic)):
                ic_by_dim[dim].append(float(ic))
    return ic_by_dim


def halflife_weights(
    ic_by_dim: dict[str, list[float]],
    halflife: int = 60,
    dims: tuple[str, ...] = DIMS,
) -> dict[str, float]:
    """半衰期权重：w = Σ_k 0.5^{k/h}·IC_{t-k} / Σ 0.5^{k/h}（近期 IC 权重更高）。

    负 IC 维度权重置 0（多头选股不做空），全 0 时退化为等权。
    """
    raw: dict[str, float] = {}
    for d in dims:
        series = ic_by_dim.get(d, [])
        if not series:
            raw[d] = 0.0
            continue
        arr = np.asarray(series, dtype=float)
        k = np.arange(len(arr))[::-1]  # 最新在末，权重最高
        decay = 0.5 ** (k / max(halflife, 1))
        raw[d] = float(np.sum(decay * arr) / np.sum(decay))
    w = {d: max(v, 0.0) for d, v in raw.items()}
    tot = sum(w.values())
    if tot <= 0:
        return {d: 1.0 / len(dims) for d in dims}
    return {d: v / tot for d, v in w.items()}


def icir_by_dim(ic_by_dim: dict[str, list[float]]) -> dict[str, float]:
    """每个维度的 ICIR = mean(IC) / std(IC)。"""
    out = {}
    for d, series in ic_by_dim.items():
        arr = np.asarray(series, dtype=float)
        if len(arr) < 2:
            out[d] = 0.0
        else:
            out[d] = float(arr.mean() / (arr.std(ddof=0) + 1e-9))
    return out


def compute_engine_weights(
    history: list[tuple[str, pd.DataFrame]],
    cfg: ScreenerConfig,
    dims: tuple[str, ...] = DIMS,
    scheme: str = "halflife_ic",
    halflife: int = 60,
    horizon: int = 20,
) -> tuple[dict[str, float], dict[str, Any]]:
    """由真实快照历史计算维度权重 + 诊断指标。

    scheme:
        "halflife_ic" : 滚动 RankIC 半衰期权重（默认）
        "icir"        : 维度 ICIR 加权（稳定性优先）
    返回 (weights, diagnostics)，weights 已归一化到合计 1。
    """
    ic_by_dim = compute_dimension_ic(history, cfg, horizon, dims)
    ir = icir_by_dim(ic_by_dim)
    if scheme == "icir":
        raw = {d: max(ir.get(d, 0.0), 0.0) for d in dims}
        tot = sum(raw.values())
        if tot <= 0:
            weights = {d: 1.0 / len(dims) for d in dims}
        else:
            weights = {d: v / tot for d, v in raw.items()}
    else:
        weights = halflife_weights(ic_by_dim, halflife, dims)

    diagnostics = {
        "scheme": scheme,
        "horizon": horizon,
        "halflife": halflife,
        "ic_by_dim": {d: ic_by_dim.get(d, []) for d in dims},
        "ic_mean_by_dim": {d: float(np.mean(ic_by_dim[d])) if ic_by_dim.get(d) else 0.0 for d in dims},
        "icir_by_dim": ir,
        "n_periods": {d: len(ic_by_dim.get(d, [])) for d in dims},
    }
    return weights, diagnostics


def load_history(store, cfg: ScreenerConfig, end_date: str | None = None
                  ) -> list[tuple[str, pd.DataFrame]]:
    """由 SnapshotStore 加载可用于客观加权 / ML 训练的历史快照（升序）。

    返回 [(trade_date, df), ...]，仅含含 close 列的快照。加载窗口取
    满足「最少历史天数 + 前瞻期」所需的日期；历史不足时尽力返回已有多少。
    """
    if store is None:
        return []
    dates = store.available_dates()
    if end_date:
        dates = [d for d in dates if d <= end_date]
    eng = getattr(cfg, "engine", None) or {}
    min_hist = int(eng.get("min_history_days", 120))
    horizon = int(eng.get("horizon", 20))
    need = min_hist + horizon
    if len(dates) < need:
        need = len(dates)  # 尽力而为：返回全部可用日期供降级判定
    history: list[tuple[str, pd.DataFrame]] = []
    for d in dates[-need:]:
        df = store.load_date(d)
        if df is not None and "close" in df.columns:
            history.append((d, df))
    return history


def resolve_weights(
    cfg: ScreenerConfig,
    store=None,
    end_date: str | None = None,
    history: list[tuple[str, pd.DataFrame]] | None = None,
) -> tuple[dict[str, float], str, dict[str, Any]]:
    """解析实际使用的维度权重（特性开关入口）。

    返回 (weights, mode, diagnostics)：
        mode="fixed"    : 经验固定权重（engine.mode="fixed" 或历史不足降级）
        mode="ic"       : 由真实快照历史的 IC 加权
        mode="degraded" : 期望 ic/auto 但历史不足，回退固定权重并标注原因

    安全性：默认 mode="fixed" 时**不触碰数据源**，与旧行为完全一致；
    仅当 mode=ic/auto 且快照历史充足时才访问 SnapshotStore。
    """
    engine = getattr(cfg, "engine", None) or {}
    mode = engine.get("mode", "fixed")
    if mode == "fixed":
        return dict(cfg.weights), "fixed", {"note": "经验固定权重（未启用 IC 加权）"}

    # ml/blend 模式对历史量的要求低于 IC（ML 训练样本可更少）
    if mode in ("ml", "blend"):
        min_hist = int(engine.get("ml_min_history_days", 60))
    else:
        min_hist = int(engine.get("min_history_days", 120))
    horizon = int(engine.get("horizon", 20))
    halflife = int(engine.get("ic_halflife", 60))
    scheme = engine.get("scheme", "halflife_ic")

    if store is None:
        try:
            from .snapshot_store import snapshot_store as store  # 延迟导入，避免副作用
        except Exception:
            store = None
    if store is None:
        return dict(cfg.weights), "degraded", {"reason": "无快照存储可用"}

    if history is None:
        history = load_history(store, cfg, end_date=end_date)
    need = min_hist + horizon
    if len(history) < need:
        return dict(cfg.weights), "degraded", {
            "reason": "历史快照不足，回退固定权重",
            "have": len(history),
            "need": need,
        }

    weights, diag = compute_engine_weights(
        history, cfg, dims=DIMS, scheme=scheme, halflife=halflife, horizon=horizon
    )
    # ml/blend 模式：线性层仍用 IC 半衰期权重（blend 需要），模式名原样透传；
    # 实际 ML 推理与混合在 score_frame 中完成（需当前截面）。
    if mode in ("ml", "blend"):
        return weights, mode, diag
    return weights, "ic", diag
