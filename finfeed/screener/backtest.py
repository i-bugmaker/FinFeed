#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""最小回测器：K 线重建因子 → 评分 → 前瞻收益 → IC / 分层收益。

用途：为「权重与阈值校准」提供数据化入口，验证评分框架端到端可用，
并给出动量/质量维度的初步预测力信号。

数据可得性约束（如实声明）：
- 可重建因子（来自日线 K 线）：
    5/20/60 日动量、年化已实现波动、均线多头排列、距高点回撤、量能；
- 不可重建因子（需真实历史资金流/财务数据，本项目暂缺历史源）：
    资金面（主力净流入）、估值（PE/股息率）→ 评分时按缺失语义给中性分，
    故 IC 主要由动量/量价/质量维度贡献，解读时须注意。

截面构造（尾部对齐）：每只股票保留尾部 max_horizon 根 K 线用于未来收益，
向前每 step 根取一个截面，共 n_cross 个截面；各股截面日期近似对齐。
"""

from __future__ import annotations

import logging
import math
import time
from typing import Any

import numpy as np
import pandas as pd
from scipy.stats import spearmanr

from .boards import classify_board
from .config import ScreenerConfig, load_config
from .datasource import _kline_pool
from .scoring import score_frame

logger = logging.getLogger("finfeed.screener.backtest")

# 回测可执行性与成本参数
TOP_N = 10                 # TopN 组合规模（每截面综合分前 N 名）
COST_ROUND_TRIP_PCT = 0.2  # 单次双边交易成本（%，佣金+滑点），从前瞻收益中扣除

# 回测股票池生成规则（混合板块抽样，代码前缀 + 序号区间）
_POOL_RULES: list[tuple[str, int, int]] = [
    ("600", 0, 50),   # 沪主板 600000~600049
    ("000", 0, 50),   # 深主板 000001~000050
    ("300", 0, 50),   # 创业板 300001~300050
    ("688", 0, 50),   # 科创板 688001~688050
]


def _code_pool(size: int) -> list[tuple[int, str]]:
    """生成混合板块股票池 [(market, code), ...]。"""
    out: list[tuple[int, str]] = []
    for prefix, start, _n in _POOL_RULES:
        market = 1 if prefix in ("600", "688") else 0
        for i in range(start, start + _n):
            code = f"{prefix}{i:03d}"
            out.append((market, code))
    return out[:size]


def _fetch_history(market: int, code: str, days: int) -> pd.DataFrame | None:
    """用连接池抓取日线 K 线（date/close/high/low/vol），失败返回 None。"""
    from easy_tdx import Adjust, Period

    client = _kline_pool.borrow()
    try:
        raw = client.get_stock_kline(market, code, Period.DAILY, count=days, adjust=Adjust.QFQ)
    except Exception as exc:  # noqa: BLE001
        logger.debug("回测抓取 K 线失败 %s: %s", code, exc)
        return None
    finally:
        _kline_pool.giveback(client)
    if raw is None or len(raw) < 60:
        return None
    cols = {str(c).lower(): c for c in raw.columns}
    date_col = next((c for c in ("date", "datetime", "time", "day") if c in cols), None)
    df = pd.DataFrame({
        "date": pd.to_datetime(raw[cols[date_col]] if date_col else range(len(raw))),
        "open": pd.to_numeric(raw[cols.get("open", "open")], errors="coerce"),
        "close": pd.to_numeric(raw[cols.get("close", "close")], errors="coerce"),
        "high": pd.to_numeric(raw[cols.get("high", "high")], errors="coerce"),
        "low": pd.to_numeric(raw[cols.get("low", "low")], errors="coerce"),
        "vol": pd.to_numeric(raw[cols.get("vol", "vol")], errors="coerce"),
    }).dropna().sort_values("date").reset_index(drop=True)
    return df if len(df) >= 60 else None


def _build_snapshot_row(hist: pd.DataFrame, asof_pos: int, market: int, code: str) -> dict[str, Any]:
    """由截至 asof_pos 的 K 线构造评分因子行（缺失字段置 NaN，缺失语义见 scoring）。"""
    sub = hist.iloc[: asof_pos + 1]
    close = sub["close"].astype(float)
    c = float(close.iloc[-1])
    prev = float(close.iloc[-2]) if len(close) >= 2 else float("nan")
    high = sub["high"].astype(float)
    low = sub["low"].astype(float)
    vol = sub["vol"].astype(float)

    def ret_days(n: int) -> float:
        if len(close) > n:
            base = float(close.iloc[-1 - n])
            return (c / base - 1.0) * 100.0 if base > 0 else float("nan")
        return float("nan")

    rets = close.pct_change().dropna()
    rv = float(rets.std() * math.sqrt(242.0) * 100.0) if len(rets) >= 5 else float("nan")

    ma_align = False
    if len(close) >= 60:
        ma20 = float(close.tail(20).mean())
        ma60 = float(close.tail(60).mean())
        ma_align = bool(c > ma20 > ma60)

    dd = float("nan")
    if len(high) >= 20 and high.max() > 0:
        dd = (c - float(high.max())) / float(high.max()) * 100.0

    vol_ratio = float("nan")
    if len(vol) >= 10 and vol.iloc[-11:-1].mean() > 0:
        vol_ratio = float(vol.iloc[-1] / vol.iloc[-11:-1].mean())

    return {
        "market": market,
        "code": code,
        "name": code,
        "pre_close": prev,
        "open": float(sub["open"].iloc[-1]) if "open" in sub else float("nan"),
        "high": float(high.iloc[-1]),
        "low": float(low.iloc[-1]),
        "close": c,
        "vol": float(vol.iloc[-1]),
        "vol_ratio": vol_ratio,
        "amount": c * float(vol.iloc[-1]) * 100.0,   # 量(手)×价×100 估算成交额
        "total_shares": float("nan"),
        "float_shares": float("nan"),
        "eps": float("nan"),
        "total_market_cap": float("nan"),
        "dividend_yield": float("nan"),
        "turnover": float("nan"),
        "circulating_capital_z": float("nan"),
        "pe_ttm": float("nan"),
        "main_net_amount": float("nan"),
        "main_net_ratio": float("nan"),
        "main_net_5d_amount": float("nan"),
        "change_5d_pct": ret_days(5),
        "change_10d_pct": ret_days(10),
        "change_20d_pct": ret_days(20),
        "change_60d_pct": ret_days(60),
        "change_1y_pct": float("nan"),
        "realized_vol_ann": rv,
        "ma_align": ma_align,
        "drawdown_from_high": dd,
    }


def run_backtest(pool_size: int = 200, n_cross: int = 8, step: int = 5,
                 max_horizon: int = 20, days: int = 240,
                 cfg: "ScreenerConfig | None" = None) -> dict[str, Any]:
    """执行回测，返回结果字典（含 IC / 分层 / TopN 统计与逐截面明细）。

    Args:
        pool_size:      股票池规模（混合板块抽样）。
        n_cross:        截面数量。
        step:           截面间隔（交易日）。
        max_horizon:    最长前瞻收益天数（T+20），K 线尾部保留。
        days:           每只股票抓取的 K 线根数。
        cfg:            自定义评分配置（权重敏感性扫描用）；默认 load_config()。
    """
    if cfg is None:
        cfg = load_config()
    cfg.filters["turnover_missing_tolerant"] = True  # 回测验证因子预测力，放行换手缺失

    rows: list[dict] = []
    pool = _code_pool(pool_size)
    t0 = time.time()
    for market, code in pool:
        hist = _fetch_history(market, code, days)
        if hist is None:
            continue
        n = len(hist)
        for k in range(n_cross):
            asof_pos = n - 1 - (k + 1) * step - max_horizon
            if asof_pos < 60:
                break
            row = _build_snapshot_row(hist, asof_pos, market, code)
            close = hist["close"].astype(float)
            c0 = float(close.iloc[asof_pos])
            if c0 <= 0:
                continue
            row["asof_date"] = hist["date"].iloc[asof_pos].strftime("%Y-%m-%d")
            row["cross"] = k
            row["fwd_5"] = float(close.iloc[asof_pos + 5] / c0 - 1.0) * 100.0
            row["fwd_20"] = float(close.iloc[asof_pos + 20] / c0 - 1.0) * 100.0
            # 可执行性：次日开盘即涨停（≥ 板块涨停×99.5%）时 T+1 无法买入，
            # 该样本从分层收益 / TopN 等交易类统计中剔除（IC 为秩统计，保留）。
            buyable = True
            if asof_pos + 1 < n:
                next_open = float(hist["open"].iloc[asof_pos + 1])
                board = classify_board(code, market)
                limit = {"kcb": 20.0, "cyb": 20.0, "bj": 30.0}.get(board, 10.0)
                buyable = not (next_open > 0 and next_open >= c0 * (1.0 + limit * 0.995 / 100.0))
            row["buyable"] = buyable
            rows.append(row)
    if not rows:
        return {"error": "回测样本为空（K 线抓取失败或股票池无有效标的）", "pool_size": pool_size}
    frame = pd.DataFrame(rows)
    # 逐截面评分（向量路径），写入 total_score 与维度分（供因子 IC 分析）
    for k in range(n_cross):
        sub = frame[frame["cross"] == k]
        if len(sub) < 30:
            continue
        scores = score_frame(sub, cfg, technical_enabled=True)
        sc_map = {s.code: s.total_score for s in scores}
        frame.loc[sub.index, "total_score"] = sub["code"].map(sc_map)
        for col in ("capital_score", "momentum_score", "valuation_score",
                    "liquidity_score", "quality_score"):
            frame.loc[sub.index, col] = sub["code"].map(
                {s.code: getattr(s, col) for s in scores})
    frame = frame.dropna(subset=["total_score"])
    if len(frame) < 30:
        return {"error": "回测评分样本不足（过滤后 <30）", "pool_size": pool_size}
    return _aggregate_metrics(
        frame, cfg, pool_size, n_cross, step, time.time() - t0,
        full_factors=False,
    )


def run_backtest_from_snapshots(pool_size: int = 200, n_cross: int = 8,
                                step: int = 5, max_horizon: int = 20) -> dict[str, Any]:
    """基于快照库的真实资金/估值因子回测（消除 K 线重建的因子盲区）。

    每个截面 = 一个已积累的交易日快照（资金面/估值因子为真实数据），
    未来收益 = 后续交易日快照 close 变化。快照历史不足时返回 error。
    """
    from .snapshot_store import snapshot_store

    dates = snapshot_store.available_dates()
    need = (n_cross - 1) * step + max_horizon + 1
    if len(dates) < need:
        return {
            "error": (f"快照库历史不足：当前 {len(dates)} 个交易日，需 ≥{need}。"
                      f"每天运行选股自动积累，{need} 个交易日后即可启用真实因子回测；"
                      f"当前可用 --screener backtest（K 线重建路径）。"),
            "pool_size": pool_size,
        }

    cfg = load_config()
    cfg.filters["turnover_missing_tolerant"] = True
    rows: list[dict] = []
    topn_by_cross: dict[int, set] = {}
    t0 = time.time()
    for k in range(n_cross):
        asof_idx = k * step
        asof_date = dates[asof_idx]
        day = snapshot_store.load_date(asof_date)
        if day is None or len(day) < 30:
            continue
        day = day.head(pool_size).copy()
        scores = score_frame(day, cfg, technical_enabled=False)
        if len(scores) < 30:
            continue
        sc = {s.code: s.total_score for s in scores}
        # 记录每截面 TopN 名单（用于相邻截面换手率统计）
        topn_by_cross[k] = {c for c, _ in sorted(sc.items(), key=lambda kv: -kv[1])[:TOP_N]}
        # 未来收益（后续交易日快照 close）
        fwd = {}
        for h in (5, 20):
            idx = asof_idx + h
            if idx < len(dates):
                fd = snapshot_store.load_date(dates[idx])
                if fd is not None:
                    fwd[h] = fd.set_index("code")["close"].to_dict()
        for code, total in sc.items():
            c0 = day.loc[day["code"] == code, "close"]
            if c0.empty or float(c0.iloc[0]) <= 0:
                continue
            rows.append({
                "code": code,
                "name": code,
                "cross": k,
                "asof_date": asof_date,
                "total_score": total,
                "fwd_5": (fwd.get(5, {}).get(code, float("nan")) / float(c0.iloc[0]) - 1.0) * 100.0,
                "fwd_20": (fwd.get(20, {}).get(code, float("nan")) / float(c0.iloc[0]) - 1.0) * 100.0,
            })
    if not rows:
        return {"error": "快照回测样本为空", "pool_size": pool_size}
    # 相邻截面 TopN 名单重合度 → 每期换手率（1 - 重合比例；截面间隔 step 日）
    topn_turnover: list[float] = []
    for k in sorted(topn_by_cross):
        if k - 1 in topn_by_cross:
            a, b = topn_by_cross[k - 1], topn_by_cross[k]
            if a:
                topn_turnover.append(1.0 - len(a & b) / len(a))
    return _aggregate_metrics(
        pd.DataFrame(rows), cfg, pool_size, n_cross, step, time.time() - t0,
        full_factors=True, topn_turnover=topn_turnover,
    )


def _aggregate_metrics(frame: pd.DataFrame, cfg, pool_size: int, n_cross: int,
                       step: int, elapsed: float, full_factors: bool,
                       topn_turnover: list[float] | None = None) -> dict[str, Any]:
    """公共聚合：逐截面 IC、分层收益、TopN 统计。

    可执行性约束：若 frame 含 buyable 列（K 线重建路径计算「次日开盘涨停不可买」），
    IC 为秩统计保留全样本；分层收益与 TopN 等**交易类**统计仅用可执行样本，
    并扣除双边交易成本（COST_ROUND_TRIP_PCT%）。
    """
    ic_5: list[float] = []
    ic_20: list[float] = []
    layer_stats: dict[str, dict[str, float]] = {}
    topn_ret5: list[float] = []
    topn_ret20: list[float] = []
    n_unbuyable = 0
    cost = COST_ROUND_TRIP_PCT / 100.0
    has_buyable = "buyable" in frame.columns
    if has_buyable:
        n_unbuyable = int((~frame["buyable"].astype(bool)).sum())

    for k in range(n_cross):
        sub = frame[frame["cross"] == k]
        if len(sub) < 30:
            continue
        # 交易类统计只用可执行样本
        trade = sub[sub["buyable"].astype(bool)] if has_buyable else sub
        sc = sub.set_index("code")["total_score"]
        joined = sub.set_index("code")
        joined = joined.assign(total_score=sc)
        joined = joined.dropna(subset=["fwd_5", "fwd_20"])
        if len(joined) < 20:
            continue
        if joined["total_score"].nunique() > 1:
            r5 = spearmanr(joined["total_score"], joined["fwd_5"]).statistic
            r20 = spearmanr(joined["total_score"], joined["fwd_20"]).statistic
            if r5 == r5:  # not NaN
                ic_5.append(float(r5))
                ic_20.append(float(r20))
        # 分层：按总分五分位（仅可执行样本，净收益）
        trade_j = trade.set_index("code").dropna(subset=["fwd_5", "fwd_20"])
        if len(trade_j) >= 20 and trade_j["total_score"].nunique() > 1:
            q_ok = True
            try:
                trade_j["q"] = pd.qcut(trade_j["total_score"], 5, labels=False, duplicates="drop")
            except ValueError:
                q_ok = False
            if q_ok:
                for q in sorted(trade_j["q"].dropna().unique()):
                    grp = trade_j[trade_j["q"] == q]
                    if len(grp) >= 3:
                        s = layer_stats.setdefault(f"Q{int(q) + 1}", {"fwd_5": [], "fwd_20": []})
                        s["fwd_5"].append(float(grp["fwd_5"].mean()) - cost)
                        s["fwd_20"].append(float(grp["fwd_20"].mean()) - cost)
                # TopN：综合分前 N 名的净前瞻收益
                if len(trade_j) >= TOP_N:
                    top = trade_j.nlargest(TOP_N, "total_score")
                    topn_ret5.append(float(top["fwd_5"].mean()) - cost)
                    topn_ret20.append(float(top["fwd_20"].mean()) - cost)

    # 市场状态分组：按截面全样本平均 fwd_20 正负分「强/弱市」，分别统计 IC
    state_ic: dict[str, dict[str, float]] = {"bull": {"ic_5": [], "ic_20": []},
                                             "bear": {"ic_5": [], "ic_20": []}}
    for k in range(n_cross):
        sub = frame[frame["cross"] == k]
        if len(sub) < 30:
            continue
        joined = sub.set_index("code")
        joined = joined.assign(total_score=pd.to_numeric(joined.get("total_score"), errors="coerce"))
        joined = joined.dropna(subset=["fwd_5", "fwd_20", "total_score"])
        if len(joined) < 20 or joined["total_score"].nunique() <= 1:
            continue
        state = "bull" if float(joined["fwd_20"].mean()) > 0 else "bear"
        r5 = spearmanr(joined["total_score"], joined["fwd_5"]).statistic
        r20 = spearmanr(joined["total_score"], joined["fwd_20"]).statistic
        if r5 == r5:
            state_ic[state]["ic_5"].append(float(r5))
            state_ic[state]["ic_20"].append(float(r20))

    # 因子 IC 相关矩阵（可得维度分与未来收益的相关，识别共线性/预测力）
    factor_cols = [c for c in ("momentum_score", "quality_score", "valuation_score",
                               "capital_score", "liquidity_score", "total_score")
                   if c in frame.columns]
    factor_corr: dict[str, float] = {}
    if len(factor_cols) >= 2 and "fwd_20" in frame.columns:
        corr_sub = frame.dropna(subset=factor_cols + ["fwd_20"])
        if len(corr_sub) >= 30:
            for c in factor_cols:
                r = spearmanr(corr_sub[c], corr_sub["fwd_20"]).statistic
                factor_corr[c] = round(float(r), 4) if r == r else None

    return {
        "pool_size": pool_size,
        "n_cross": n_cross,
        "step": step,
        "samples": int(len(frame)),
        "stocks_ok": int(frame["code"].nunique()),
        "duration_s": round(elapsed, 1),
        "ic_5_mean": round(float(np.mean(ic_5)), 4) if ic_5 else None,
        "ic_5_std": round(float(np.std(ic_5)), 4) if ic_5 else None,
        "ic_20_mean": round(float(np.mean(ic_20)), 4) if ic_20 else None,
        "ic_20_std": round(float(np.std(ic_20)), 4) if ic_20 else None,
        "ic_5_hits": sum(1 for v in ic_5 if v > 0),
        "ic_5_total": len(ic_5),
        "state_ic": {
            k: {"ic_5_mean": round(float(np.mean(v["ic_5"])), 4) if v["ic_5"] else None,
                "ic_20_mean": round(float(np.mean(v["ic_20"])), 4) if v["ic_20"] else None,
                "sections": len(v["ic_5"])}
            for k, v in state_ic.items()
        },
        "factor_ic_20": factor_corr,
        "topn": {
            "n": TOP_N,
            "cost_round_trip_pct": COST_ROUND_TRIP_PCT,
            "fwd_5_mean": round(float(np.mean(topn_ret5)), 3) if topn_ret5 else None,
            "fwd_20_mean": round(float(np.mean(topn_ret20)), 3) if topn_ret20 else None,
            "n_cross": len(topn_ret20),
            "turnover_per_step": (round(float(np.mean(topn_turnover)), 3)
                                  if topn_turnover else None),
            "turnover_periods": len(topn_turnover),
        },
        "excluded_unbuyable": n_unbuyable,
        "layers": {k: {kk: round(float(np.mean(vv)), 3) for kk, vv in v.items()}
                   for k, v in sorted(layer_stats.items())},
        "disclaimer": ("" if full_factors else
                       "仅动量/量价/质量维度有效：资金面与估值因子需真实历史资金流与财务数据，"
                       "本项目暂缺历史源，评分时按缺失语义给中性分；已启用每日快照持久化，"
                       "积累足够交易日后可用 --screener backtest-snapshots 走真实因子路径。"),
    }


def weight_sensitivity(pool_size: int = 120, n_cross: int = 6, step: int = 5,
                       max_horizon: int = 20, delta: float = 0.20) -> dict[str, Any]:
    """权重敏感性扫描：对五维权重逐一 ±delta 扰动，观察 IC(T+20) 变化。

    用于识别「权重对结果的影响方向与强度」，为权重校准提供数据依据。
    每个扰动组合独立跑一次小规模回测（约 6 组，耗时可控）。
    """
    from .config import ScreenerConfig
    from .ic_engine import DIMS

    dims = DIMS  # 八维全量扫描（capital/momentum/valuation/liquidity/quality/sentiment/growth/reversal）
    base_cfg = load_config()
    results: dict[str, Any] = {"delta": delta, "variants": {}}

    # 基准
    base = run_backtest(pool_size=pool_size, n_cross=n_cross, step=step, max_horizon=max_horizon)
    results["baseline"] = {"ic_5": base.get("ic_5_mean"), "ic_20": base.get("ic_20_mean")}

    for d in dims:
        for sign, tag in ((1.0, f"{d}+"), (-1.0, f"{d}-")):
            cfg = ScreenerConfig()
            cfg.weights.update(base_cfg.weights)
            others = [x for x in dims if x != d]
            w0 = cfg.weights[d]
            cfg.weights[d] = max(0.05, w0 * (1.0 + sign * delta))
            # 等比例缩放其余维度权重保持合计 1.0
            rest = sum(cfg.weights[x] for x in others)
            if rest > 0:
                scale = (1.0 - cfg.weights[d]) / rest
                for x in others:
                    cfg.weights[x] *= scale
            # 用扰动配置跑回测（直接传入 cfg，避免全局配置污染）
            r = run_backtest(pool_size=pool_size, n_cross=n_cross,
                             step=step, max_horizon=max_horizon, cfg=cfg)
            results["variants"][tag] = {
                "w": round(cfg.weights[d], 2),
                "ic_5": r.get("ic_5_mean"),
                "ic_20": r.get("ic_20_mean"),
                "delta_ic20": (round(r.get("ic_20_mean") - (base.get("ic_20_mean") or 0.0), 4)
                               if r.get("ic_20_mean") is not None and base.get("ic_20_mean") is not None else None),
            }
    return results


def render_markdown(result: dict[str, Any]) -> str:
    """渲染回测报告（Markdown）。"""
    if "error" in result:
        return f"# 选股回测\n\n**失败**：{result['error']}\n"
    L = ["# 选股因子回测报告", ""]
    L.append(f"- 股票池：{result['pool_size']} 只（混合板块抽样）｜截面：{result['n_cross']} 个（步长 {result['step']} 日）")
    L.append(f"- 有效样本：{result['samples']} 行（{result['stocks_ok']} 只）｜耗时 {result['duration_s']}s")
    L.append(f"- **IC(T+5)**：均值 {result['ic_5_mean']} ± {result['ic_5_std']}（正截面 {result['ic_5_hits']}/{result['ic_5_total']}）")
    L.append(f"- **IC(T+20)**：均值 {result['ic_20_mean']} ± {result['ic_20_std']}")
    L.append("")
    # 市场状态分组
    st = result.get("state_ic") or {}
    if st.get("bull") or st.get("bear"):
        L.append("### 市场状态分组 IC（按截面全样本 T+20 平均收益正负）")
        L.append("")
        L.append("| 状态 | 截面数 | IC(T+5) | IC(T+20) |")
        L.append("|------|--------|---------|----------|")
        for label, key in (("强市（平均正收益）", "bull"), ("弱市（平均负收益）", "bear")):
            v = st.get(key)
            if v:
                L.append(f"| {label} | {v.get('sections', 0)} | {v.get('ic_5_mean', '—')} | {v.get('ic_20_mean', '—')} |")
        L.append("")
    # 因子 IC
    fic = result.get("factor_ic_20") or {}
    if fic:
        L.append("### 因子 IC(T+20)（单因子与未来 20 日收益的 Spearman 相关）")
        L.append("")
        for k, v in fic.items():
            L.append(f"- {k}：{v}")
        L.append("")
    L.append("### 分层收益（按综合分五分位，各层前瞻收益均值 %，扣双边成本后）")
    L.append("")
    L.append("| 分层 | T+5 | T+20 |")
    L.append("|------|-----|------|")
    for q, v in result["layers"].items():
        L.append(f"| {q} | {v.get('fwd_5', '—')} | {v.get('fwd_20', '—')} |")
    L.append("")
    topn = result.get("topn") or {}
    if topn.get("fwd_20_mean") is not None:
        L.append(f"### TopN 组合（前 {topn['n']} 名，扣双边成本 {topn.get('cost_round_trip_pct')}%）")
        L.append("")
        L.append(f"- 净前瞻收益：T+5 {topn.get('fwd_5_mean')}%｜T+20 {topn.get('fwd_20_mean')}%（{topn.get('n_cross')} 个截面）")
        if topn.get("turnover_per_step") is not None:
            L.append(f"- TopN 换手率：每 {result.get('step', 1)} 日 {topn['turnover_per_step']:.0%}"
                     f"（{topn.get('turnover_periods')} 期，快照路径）")
        L.append("")
    if result.get("excluded_unbuyable"):
        L.append(f"> ⚠️ 可执行性：已从交易类统计中剔除 {result['excluded_unbuyable']} 个"
                 "「次日开盘涨停无法买入」样本（IC 为秩统计不受影响）。")
        L.append("")
    if result.get("disclaimer"):
        L.append(f"> ⚠️ {result['disclaimer']}")
        L.append("")
    L.append("> 回测用于权重/阈值校准参考，不构成投资建议；历史规律不代表未来收益。")
    return "\n".join(L)


def render_sensitivity(res: dict[str, Any]) -> str:
    """渲染权重敏感性扫描报告。"""
    L = ["# 权重敏感性扫描", ""]
    L.append(f"- 基准权重回测：IC(T+5)={res['baseline'].get('ic_5')}，IC(T+20)={res['baseline'].get('ic_20')}")
    L.append(f"- 扰动幅度：±{res['delta']:.0%}（其余维度等比例缩放保持合计 1.0）")
    L.append("")
    L.append("| 变体 | 权重 | IC(T+5) | IC(T+20) | ΔIC(T+20) |")
    L.append("|------|------|---------|----------|-----------|")
    for tag, v in res["variants"].items():
        L.append(f"| {tag} | {v.get('w', '—')} | {v.get('ic_5', '—')} | {v.get('ic_20', '—')} | {v.get('delta_ic20', '—')} |")
    L.append("")
    L.append("> ΔIC(T+20)>0 表示该维度权重上调对预测力有正向贡献；反之应下调。")
    return "\n".join(L)
