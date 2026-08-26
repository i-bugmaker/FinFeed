#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""ML 选股层（P5）：walk-forward 分类器，预测「未来强势」概率。

设计原则（见 docs/screener_refactor_design.md §3 混合框架）：
- 线性层（IC 半衰期权重）提供可解释、稳定的基础排序；
- ML 层在线性层之上学习「六维信号 → 未来收益」的非线性映射，捕捉维度间
  交互与择时，输出 P(未来处于强势分位)；
- 混合层 Score = α·Score_linear + (1-α)·ML_prob·100，α 默认 0.5。

后端（零外部依赖优先，自动升级）：
- 若已安装 lightgbm  -> 使用 LightGBM 二分类（梯度提升，捕捉非线性）；
- 否则              -> 使用依赖免费的 NumPy 逻辑回归（带 L2 正则，Newton/IRLS 求解）。
  本环境（lightgbm/sklearn 未安装）下默认走 NumPy 路径，保证可运行、可测试。

严谨性（杜绝未来函数）：
- 训练只用历史快照截面 t 的六维度子分作特征，标签用 t+horizon 的前瞻收益分位；
- 当前截面不参与训练，仅作推理，故对「今日」预测无任何泄漏；
- walk-forward 切分（按时间保留最后 20% 日期作验证集）产出 OOS 的 IC / AUC 诊断，
  用于评估 ML 层是否真正带来增量，而非过拟合噪声。

特征：六维度子分（0~100，已由 vector.dimension_scores_vec 产出，横截面可比）。
标签：前瞻收益在截面前 top_quantile（默认 0.3）分位为 1，否则 0。
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any

import numpy as np
import pandas as pd

from . import vector
from .ic_engine import DIMS, _forward_returns

# ---------------------------------------------------------------------------
# 后端可用性探测（模块级，仅探测一次）
# ---------------------------------------------------------------------------
try:  # noqa: BLE001
    import lightgbm as _lgb  # type: ignore
    _LGBM_AVAILABLE = True
except Exception:  # noqa: BLE001
    _lgb = None
    _LGBM_AVAILABLE = False


# ---------------------------------------------------------------------------
# 依赖免费 NumPy 逻辑回归（带 L2 正则，Newton/IRLS 求解）
# ---------------------------------------------------------------------------
class _NumpyLogistic:
    """逻辑回归：标准化特征 + 截距（不惩罚）+ L2 惩罚权重。

    求解用牛顿法（IRLS）；Hessian 奇异时回退最小二乘增量。对小特征维度（6~10）
    极快且数值稳定，作为无 LightGBM 环境下的工作后端。
    """

    def __init__(self, C: float = 1.0, max_iter: int = 60, tol: float = 1e-7) -> None:
        self.C = float(C)              # 逆正则强度（越大越不惩罚）
        self.max_iter = int(max_iter)
        self.tol = float(tol)
        self.mean_: np.ndarray | None = None
        self.std_: np.ndarray | None = None
        self.coef_: np.ndarray | None = None
        self.intercept_: float = 0.0
        self.backend = "numpy_logistic"

    def fit(self, X: np.ndarray, y: np.ndarray) -> "_NumpyLogistic":
        X = np.asarray(X, dtype=float)
        y = np.asarray(y, dtype=float).ravel()
        self.mean_ = X.mean(axis=0)
        self.std_ = X.std(axis=0)
        self.std_[self.std_ == 0] = 1.0
        Xs = (X - self.mean_) / self.std_
        n, d = Xs.shape
        Xd = np.hstack([np.ones((n, 1)), Xs])
        lam = 1.0 / max(self.C, 1e-8)
        w = np.zeros(d + 1)
        for _ in range(self.max_iter):
            eta = Xd @ w
            p = 1.0 / (1.0 + np.exp(-eta))
            g = Xd.T @ (p - y) + lam * w
            g[0] -= lam * w[0]                 # 截距不惩罚
            R = p * (1.0 - p)
            H = (Xd * R[:, None]).T @ Xd
            H[np.diag_indices_from(H)] += lam
            H[0, 0] -= lam
            try:
                delta = np.linalg.solve(H, g)
            except np.linalg.LinAlgError:
                delta = np.linalg.lstsq(H, g, rcond=None)[0]
            w = w - delta
            if np.max(np.abs(delta)) < self.tol:
                break
        self.coef_ = w[1:]
        self.intercept_ = float(w[0])
        return self

    def predict_proba(self, X: np.ndarray) -> np.ndarray:
        X = np.asarray(X, dtype=float)
        Xs = (X - self.mean_) / self.std_
        eta = Xs @ self.coef_ + self.intercept_
        p = 1.0 / (1.0 + np.exp(-eta))
        return np.vstack([1.0 - p, p]).T


class _LGBMWrapper:
    """LightGBM 二分类封装（仅在 lightgbm 可用时使用）。"""

    def __init__(self, booster: Any) -> None:
        self.booster = booster
        self.backend = "lightgbm"

    def predict_proba(self, X: np.ndarray) -> np.ndarray:
        X = np.asarray(X, dtype=float)
        # 二分类 objective=binary 时 bst.predict 返回正类概率
        p = np.asarray(self.booster.predict(X), dtype=float).ravel()
        return np.vstack([1.0 - p, p]).T


@dataclass
class MLModel:
    """训练好的 ML 模型（含元信息）。"""

    predictor: Any                       # 具 predict_proba(X) 的对象
    backend: str
    feature_dims: tuple[str, ...]
    n_train: int = 0
    oos_ic: float | None = None
    oos_auc: float | None = None


# ---------------------------------------------------------------------------
# 训练集构造
# ---------------------------------------------------------------------------
def _build_training_set(history: list[tuple[str, pd.DataFrame]], cfg,
                        dims: tuple[str, ...], horizon: int, top_quantile: float):
    """由历史快照构造 (X, y, dates_array)。

    X: (n_samples, len(dims))，每行=某历史日某只股票的六维度子分；
    y: 0/1，该股票在该历史日 h 日后的前瞻收益是否进入截面前 top_quantile；
    dates_array: 每个样本对应的历史交易日（用于 walk-forward 时间切分）。
    """
    fr = _forward_returns(history, horizon)
    by_date = {d: df for d, df in history}
    Xrows: list[np.ndarray] = []
    yrows: list[np.ndarray] = []
    drows: list[str] = []
    for d, codes, r in fr:
        df = by_date.get(d)
        if df is None or "code" not in df.columns:
            continue
        dim_scores = vector.dimension_scores_vec(df, cfg)
        code_idx = df["code"].values
        feat = pd.DataFrame(
            {dim: pd.Series(dim_scores[dim].values, index=code_idx) for dim in dims}
        )
        feat = feat.reindex(r.index)
        thr = r.quantile(1.0 - top_quantile)
        yvec = (r >= thr).astype(int).values
        Xmat = feat.values
        mask = ~np.isnan(Xmat).any(axis=1)
        if mask.sum() == 0:
            continue
        Xrows.append(Xmat[mask])
        yrows.append(yvec[mask])
        drows.extend([d] * int(mask.sum()))
    if not Xrows:
        return np.empty((0, len(dims))), np.empty((0,)), np.empty((0,), dtype=object)
    return np.vstack(Xrows), np.concatenate(yrows), np.array(drows)


def _current_features(current_df: pd.DataFrame, cfg, dims: tuple[str, ...]) -> pd.DataFrame:
    """当前截面（已过滤）的六维度特征矩阵，索引与 current_df 对齐。"""
    dim_scores = vector.dimension_scores_vec(current_df, cfg)
    feat = pd.DataFrame(
        {dim: pd.Series(dim_scores[dim].values, index=current_df.index) for dim in dims}
    )
    return feat


# ---------------------------------------------------------------------------
# 模型拟合
# ---------------------------------------------------------------------------
def _fit_final(X: np.ndarray, y: np.ndarray, cfg) -> MLModel:
    """用全部样本拟合最终模型（自动选择后端）。"""
    engine = getattr(cfg, "engine", None) or {}
    params = engine.get("ml_params", {}) or {}
    if _LGBM_AVAILABLE and _lgb is not None:
        try:
            n_pos = int(y.sum())
            scale = max((len(y) - n_pos) / max(n_pos, 1), 0.1)
            lgb_params = {
                "objective": "binary",
                "metric": "binary_logloss",
                "learning_rate": float(params.get("learning_rate", 0.05)),
                "num_leaves": int(params.get("num_leaves", 31)),
                "min_child_samples": int(params.get("min_child_samples", 100)),
                "feature_fraction": float(params.get("feature_fraction", 0.9)),
                "bagging_fraction": float(params.get("bagging_fraction", 0.8)),
                "bagging_freq": int(params.get("bagging_freq", 1)),
                "lambda_l2": float(params.get("lambda_l2", 1.0)),
                "verbose": -1,
                "seed": 42,
                "is_unbalance": False,
                "scale_pos_weight": scale,
            }
            n_round = int(params.get("num_boost_round", 200))
            dtrain = _lgb.Dataset(X, label=y)
            bst = _lgb.train(lgb_params, dtrain, num_boost_round=n_round)
            return MLModel(_LGBMWrapper(bst), "lightgbm", DIMS, n_train=len(y))
        except Exception:  # noqa: BLE001
            pass  # 回退 NumPy 后端
    model = _NumpyLogistic(
        C=float(params.get("C", 1.0)),
        max_iter=int(params.get("max_iter", 60)),
    ).fit(X, y)
    return MLModel(model, "numpy_logistic", DIMS, n_train=len(y))


# ---------------------------------------------------------------------------
# walk-forward 评估（OOS 诊断，杜绝乐观偏差）
# ---------------------------------------------------------------------------
def _auc(y: np.ndarray, p: np.ndarray) -> float:
    """二分类 AUC（Mann-Whitney U / 秩均值，无 sklearn 依赖）。"""
    y = np.asarray(y).ravel()
    p = np.asarray(p).ravel()
    pos = y == 1
    n_pos = int(pos.sum())
    n_neg = int((~pos).sum())
    if n_pos == 0 or n_neg == 0:
        return float("nan")
    from scipy.stats import rankdata
    r = rankdata(p)
    return float((r[pos].sum() - n_pos * (n_pos + 1) / 2) / (n_pos * n_neg))


def _walkforward_eval(X: np.ndarray, y: np.ndarray, dates: np.ndarray,
                      cfg, top_quantile: float) -> dict[str, Any]:
    """按时间切分：前 80% 日期训练，后 20% 验证，产出 OOS 的 IC / AUC。"""
    ud = np.unique(dates)
    if len(ud) < 5:
        return {"ml_oos": "skipped_too_few_dates"}
    n_hold = max(1, int(len(ud) * 0.2))
    hold = set(ud[-n_hold:])
    tr = ~np.isin(dates, hold)
    if tr.sum() < 100 or (len(dates) - tr.sum()) < 30:
        return {"ml_oos": "skipped_small_split"}
    model = _fit_final(X[tr], y[tr], cfg)
    p = model.predict_proba(X[~tr])[:, 1]
    yv = y[~tr]
    from scipy.stats import spearmanr
    try:
        ic, _ = spearmanr(p, yv)
    except Exception:  # noqa: BLE001
        ic = float("nan")
    return {
        "ml_oos": "ok",
        "ml_oos_ic": (float(ic) if (ic == ic and ic is not None) else None),
        "ml_oos_auc": _auc(yv, p),
        "ml_oos_n_train": int(tr.sum()),
        "ml_oos_n_valid": int((~tr).sum()),
    }


# ---------------------------------------------------------------------------
# 主入口：一次完整 ML 层推理（训练 + 预测当前截面）
# ---------------------------------------------------------------------------
def run_ml_layer(cfg, store=None, current_df: pd.DataFrame | None = None,
                 end_date: str | None = None,
                 history: list[tuple[str, pd.DataFrame]] | None = None
                 ) -> tuple[pd.Series | None, dict[str, Any], str]:
    """对当前截面执行 ML 层，返回 (ml_prob, 诊断, 状态)。

    ml_prob: 以 current_df 索引为索引的 Series（0~1，P(未来强势)）；不可用时为 None。
    状态: "trained" | "insufficient_history" | "degraded"。
    """
    engine = getattr(cfg, "engine", None) or {}
    horizon = int(engine.get("horizon", 20))
    top_quantile = float(engine.get("top_quantile", 0.3))

    if store is None:
        return None, {"ml_note": "无快照存储，ML 层不可用"}, "degraded"

    if history is None:
        history = _load_history_shared(store, cfg, end_date)
    ml_min = int(engine.get("ml_min_history_days", 60))
    if len(history) < ml_min:
        return (None,
                {"ml_note": "历史快照不足", "have": len(history), "need": ml_min},
                "insufficient_history")

    try:
        X, y, dates = _build_training_set(history, cfg, DIMS, horizon, top_quantile)
    except Exception as exc:  # noqa: BLE001
        return None, {"ml_error": str(exc)}, "degraded"

    # 特征退化检测：维度子分方差趋零（历史快照缺因子列）则 ML 无效
    feat_std = float(np.nanstd(X, axis=0).mean()) if X.shape[0] else 0.0
    if X.shape[0] < 200 or len(np.unique(y)) < 2 or feat_std < 1e-6:
        return (None,
                {"ml_note": "标注样本不足或特征退化",
                 "n_samples": int(X.shape[0]),
                 "n_classes": int(len(np.unique(y))),
                 "feat_std": feat_std},
                "insufficient_history")

    wf = _walkforward_eval(X, y, dates, cfg, top_quantile)
    model = _fit_final(X, y, cfg)

    if current_df is None:
        return None, {**wf, "backend": model.backend, "ml_note": "未提供当前截面"}, "trained"

    try:
        feat = _current_features(current_df, cfg, DIMS)
    except Exception as exc:  # noqa: BLE001
        return None, {**wf, "ml_error": str(exc)}, "degraded"
    proba = model.predictor.predict_proba(feat.values)[:, 1]
    ml_prob = pd.Series(proba, index=current_df.index, name="ml_prob")
    diag = {
        **wf,
        "backend": model.backend,
        "n_train": int(X.shape[0]),
        "ml_label_quantile": top_quantile,
        "ml_horizon": horizon,
    }
    return ml_prob, diag, "trained"


# ---------------------------------------------------------------------------
# 便捷包装（供测试 / 显式调用）
# ---------------------------------------------------------------------------
def train_walkforward(history: list[tuple[str, pd.DataFrame]], cfg,
                      dims: tuple[str, ...] = DIMS,
                      horizon: int | None = None,
                      top_quantile: float | None = None,
                      store=None) -> MLModel | None:
    """由历史快照训练最终模型（不返回诊断）。"""
    engine = getattr(cfg, "engine", None) or {}
    horizon = int(horizon if horizon is not None else engine.get("horizon", 20))
    top_quantile = float(top_quantile if top_quantile is not None else engine.get("top_quantile", 0.3))
    X, y, _ = _build_training_set(history, cfg, dims, horizon, top_quantile)
    if X.shape[0] < 200 or len(np.unique(y)) < 2:
        return None
    return _fit_final(X, y, cfg)


def predict_ml(model: MLModel, current_df: pd.DataFrame, cfg,
               dims: tuple[str, ...] = DIMS) -> pd.Series | None:
    """用已训练模型对当前截面预测 ml_prob（索引与 current_df 对齐）。"""
    if model is None:
        return None
    try:
        feat = _current_features(current_df, cfg, dims)
    except Exception:  # noqa: BLE001
        return None
    proba = model.predictor.predict_proba(feat.values)[:, 1]
    return pd.Series(proba, index=current_df.index, name="ml_prob")


# ---------------------------------------------------------------------------
# 历史加载（与 ic_engine.load_history 同源，避免重复实现 / 双重 IO）
# ---------------------------------------------------------------------------
def _load_history_shared(store, cfg, end_date: str | None = None):
    """延迟导入 ic_engine.load_history，避免模块循环依赖。"""
    from .ic_engine import load_history
    return load_history(store, cfg, end_date=end_date)
