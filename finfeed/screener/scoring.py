#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""评分编排：硬性过滤 + 加权总分 + 评级分层 + 入选护栏 + 选股逻辑说明。

对外主入口：
    score_frame(df, cfg, technical_enabled) -> list[StockScore]   （按综合分降序）
    score_one(row, cfg, technical_enabled) -> StockScore          （单只，便于测试）
"""

from __future__ import annotations

import bisect
import math
import re
from typing import Any

import pandas as pd

from . import factors, ic_engine, ml_engine
from .boards import classify_board
from .config import ScreenerConfig
from .ic_engine import resolve_weights
from .models import StockScore

_ST_RE = re.compile(r"(ST|\*ST|退)", re.IGNORECASE)


def _f(x: Any) -> float:
    try:
        v = float(x)
        return v if math.isfinite(v) else 0.0
    except (TypeError, ValueError):
        return 0.0


def _is_missing(x: Any) -> bool:
    """判断是否为缺失值（None / NaN），用于缺失三态判定（见 is_eligible）。"""
    try:
        return x is None or math.isnan(float(x))
    except (TypeError, ValueError):
        return True


def _limit_pct(board: str, name: str) -> float:
    """板块动态涨跌停幅度（%）。

    主板 10%、科创板/创业板 20%、北交所 30%；ST/*ST/退市 5%。
    用于入选护栏的「接近涨跌停」判定，避免统一阈值误伤双创正常涨幅标的。
    """
    if _ST_RE.search(name or ""):
        return 5.0
    if board in ("kcb", "cyb"):
        return 20.0
    if board == "bj":
        return 30.0
    return 10.0


def build_factor_row(rec: dict) -> dict:
    """把原始记录（dict 或 DataFrame 行）规范化为含派生字段的因子行。

    派生字段：
        chg_today          当日涨跌幅 %
        amplitude          当日振幅 %
        circ_cap           流通市值(元) = float_shares(万股) × 1e4 × close
        main_net_5d_pct    5日主力净流入占流通市值 %
        realized_vol_ann / ma_align / drawdown_from_high 由技术面阶段填充（可选）
    """
    row: dict[str, Any] = {}
    for k, v in rec.items():
        row[str(k)] = v
    close_raw = row.get("close")
    pre_raw = row.get("pre_close")
    high_raw = row.get("high")
    low_raw = row.get("low")
    fs_raw = row.get("float_shares")  # 万股

    close = _f(close_raw)
    pre = _f(pre_raw)
    high = _f(high_raw)
    low = _f(low_raw)
    float_shares = _f(fs_raw)

    # 派生字段保持缺失语义：pre 缺失时 chg/振幅为 NaN（不冒充 0/平盘）
    valid = not _is_missing(pre_raw) and pre > 0
    row["chg_today"] = (close - pre) / pre * 100.0 if valid else float("nan")
    row["amplitude"] = (high - low) / pre * 100.0 if valid else float("nan")
    circ_cap = float_shares * 1e4 * close
    row["circ_cap"] = circ_cap if not (_is_missing(fs_raw) or _is_missing(close_raw)) else float("nan")
    net5d = _f(row.get("main_net_5d_amount"))
    row["main_net_5d_pct"] = (net5d / circ_cap * 100.0) if circ_cap > 0 else float("nan")

    # 技术面字段缺省
    row.setdefault("realized_vol_ann", None)
    row.setdefault("ma_align", False)
    row.setdefault("drawdown_from_high", None)
    # 板块归类（主板/科创板/创业板/北交所）
    row["board"] = classify_board(row.get("code"), int(_f(row.get("market"))))
    return row


def is_eligible(row: dict, cfg: ScreenerConfig) -> tuple[bool, str]:
    """硬性过滤（缺失三态语义）：返回 (是否通过, 未通过原因)。

    缺失处理原则：
    - 价格缺失（close NaN）→ 剔除「价格缺失」（无法交易/评分）；
    - PE 缺失 → **不**按亏损/高估值剔除（数据缺失 ≠ 亏损），估值维度按缺失给中性分；
    - 流通市值缺失 → 不按「过小」剔除（回退源场景避免全灭），靠质量维度低分自然排序；
    - vol/amount 缺失 → 不判停牌；明确为 0 才判停牌（无成交）。
    """
    f = cfg.filters
    name = str(row.get("name", "") or "")
    market = int(_f(row.get("market")))
    price_raw = row.get("close")
    price = _f(price_raw)
    pe_raw = row.get("pe_ttm")
    pe = _f(pe_raw)
    turnover = _f(row.get("turnover"))
    vol_raw = row.get("vol")
    amount_raw = row.get("amount")
    circ_raw = row.get("circ_cap")
    circ_cap = _f(circ_raw)

    if f.get("exclude_st") and _ST_RE.search(name):
        return False, "ST/退市"
    # 停牌：仅当 vol/amount 明确为 0（非缺失）时判定
    vol_zero = not _is_missing(vol_raw) and _f(vol_raw) <= 0
    amount_zero = not _is_missing(amount_raw) and _f(amount_raw) <= 0
    if f.get("exclude_suspended") and (vol_zero or amount_zero):
        return False, "停牌"
    # 板块过滤：优先用 boards 白名单；无 boards 时退回 exclude_bj 兼容逻辑
    boards = f.get("boards")
    if isinstance(boards, dict):
        board = row.get("board") or classify_board(row.get("code"), market)
        if not boards.get(board, False):
            return False, "板块剔除"
    elif f.get("exclude_bj") and market == 2:
        return False, "北交所"
    if _is_missing(price_raw):
        return False, "价格缺失"
    if price < _f(f.get("min_price")) or price > _f(f.get("max_price")):
        return False, "价格越界"
    # 亏损/高估值：PE 缺失不误杀（缺失 ≠ 亏损）
    if f.get("exclude_loss") and not _is_missing(pe_raw) and pe <= 0:
        return False, "亏损"
    if not _is_missing(pe_raw) and pe > _f(f.get("pe_max")):
        return False, "PE过高"
    # 流通市值：缺失不判「过小」
    if not _is_missing(circ_raw) and circ_cap < _f(f.get("min_circ_cap")):
        return False, "流通市值过小"
    # 换手率：缺失默认剔除（流动性无法评估）；回测等场景可设
    # filters.turnover_missing_tolerant=True 放行缺失（验证因子预测力而非可交易性）
    if not f.get("turnover_missing_tolerant") and _is_missing(row.get("turnover")):
        return False, "换手率过低"
    if not _is_missing(row.get("turnover")) and turnover < _f(f.get("min_turnover")):
        return False, "换手率过低"
    # 可交易性护栏：成交额下限（缺失放行，回退源场景避免全灭）
    if f.get("min_amount") and not _is_missing(amount_raw) and _f(amount_raw) < _f(f.get("min_amount")):
        return False, "成交额过低"
    return True, ""


def _highlight_capital(row: dict, contrib: dict) -> list[str]:
    out = []
    ratio = _f(row.get("main_net_ratio"))
    net5d_pct = _f(row.get("main_net_5d_pct"))
    if ratio >= 1.0:
        out.append(f"主力净比{ratio:+.2f}%")
    if net5d_pct >= 0.4:
        out.append(f"5日主力净流入占流通{net5d_pct:+.2f}%")
    return out


def _highlight_momentum(row: dict) -> list[str]:
    out = []
    c20 = _f(row.get("change_20d_pct"))
    c60 = _f(row.get("change_60d_pct"))
    c5 = _f(row.get("change_5d_pct"))
    if c20 >= 8:
        out.append(f"20日动量{c20:+.1f}%")
    if c60 >= 15:
        out.append(f"60日动量{c60:+.1f}%")
    if c5 >= c20 >= c60 >= 0:
        out.append("多周期动量多头排列")
    c10 = _f(row.get("change_10d_pct"))
    if not _is_missing(row.get("change_10d_pct")) and (c20 - c10) >= 5:
        out.append(f"动量加速{(c20 - c10):+.1f}pp")
    return out


def _highlight_valuation(row: dict) -> list[str]:
    pe = _f(row.get("pe_ttm"))
    if 8 <= pe <= 36:
        return [f"PE={pe:.1f}合理"]
    return []


def _highlight_liquidity(row: dict) -> list[str]:
    amt = _f(row.get("amount"))
    to = _f(row.get("turnover"))
    if amt >= 1e9 and 1.0 <= to <= 8.0:
        return [f"量价活跃(成交{amt/1e8:.1f}亿/换手{to:.1f}%)"]
    return []


def _highlight_quality(row: dict) -> list[str]:
    rv = row.get("realized_vol_ann")
    if rv is not None and math.isfinite(float(rv)):
        v = float(rv)
        if 20 <= v <= 70:
            return [f"年化波动{v:.0f}%适中"]
    amp = _f(row.get("amplitude"))
    if 1.0 <= amp <= 5.0:
        return [f"日振幅{amp:.1f}%平稳"]
    return []


def _highlight_sentiment(row: dict) -> list[str]:
    """情绪/事件亮点：涨停基因、连涨动能、大单净流入。"""
    out = []
    lup = _f(row.get("annual_limit_up_days"))
    if 2 <= lup <= 12:
        out.append(f"年内涨停{lup:.0f}次")
    streak = _f(row.get("consecutive_up_days"))
    if streak >= 2:
        out.append(f"连涨{streak:.0f}天")
    ddx = _f(row.get("ddx"))
    if ddx >= 0.3:
        out.append(f"大单净流入DDX={ddx:+.2f}")
    return out


def _make_percentile(values: list[float]):
    """构造「值 → 同组内百分位(0~100)」的函数（越高越好方向）。"""
    s = sorted(values)
    n = len(s)

    def fn(v: float) -> float:
        if n == 0:
            return 50.0
        i = bisect.bisect_right(s, v)
        return factors.clamp(i / n * 100.0)

    return fn


def _assemble(row: dict, dims: dict, pct_map: dict, cfg: ScreenerConfig,
              technical_enabled: bool = False) -> StockScore:
    """由维度子分组装 StockScore：板块中性化混合 → 加权总分 → 护栏 → 评级 → 说明。

    dims:     factors.dimension_scores 返回的绝对子分（含贡献说明）
    pct_map:  各维度的板块内百分位函数（为空则不做中性化，纯绝对分）
    """
    w = cfg.weights
    t = cfg.tiers
    g = t["guardrails"]
    nb = _f((cfg.neutralize or {}).get("blend", 0.0))

    def blended(d: str) -> float:
        av = factors.clamp(dims[d][0])
        if nb > 0 and pct_map and d in pct_map:
            pr = factors.clamp(pct_map[d](av))
            return factors.clamp((1.0 - nb) * av + nb * pr)
        return av

    capital = blended("capital")
    momentum = blended("momentum")
    valuation = blended("valuation")
    liquidity = blended("liquidity")
    quality = blended("quality")
    sentiment = blended("sentiment") if "sentiment" in dims else 0.0

    total = (
        w["capital"] * capital
        + w["momentum"] * momentum
        + w["valuation"] * valuation
        + w["liquidity"] * liquidity
        + w["quality"] * quality
        + w.get("sentiment", 0.0) * sentiment
    )
    total = factors.clamp(total)

    chg = _f(row.get("chg_today"))

    # 入选护栏
    failures: list[str] = []
    if capital < _f(g.get("capital_min")):
        failures.append("资金面不足")
    if momentum < _f(g.get("momentum_min")):
        failures.append("动量不足")
    if valuation < _f(g.get("valuation_min")):
        failures.append("估值偏高")
    if quality < _f(g.get("quality_min")):
        failures.append("质量/波动欠佳")
    # 板块动态涨跌停护栏：接近涨跌停（≥95% 幅度）即降级，避免追高/无法成交；
    # 按板块（主板 10% / 双创 20% / 北交所 30% / ST 5%）动态判定，替代统一阈值
    limit = _limit_pct(str(row.get("board", "")), str(row.get("name", "")))
    if abs(chg) >= limit * 0.95:
        failures.append("当日接近涨跌停")

    # 评级
    if total >= _f(t.get("strong")) and not failures:
        tier = "strong"
    elif total >= _f(t.get("watch")) or (total >= _f(t.get("strong")) and failures):
        tier = "watch"
    elif total >= _f(t.get("observe")):
        tier = "observe"
    else:
        tier = "none"

    # 选股逻辑说明
    highlights = (
        _highlight_capital(row, dims["capital"][1])
        + _highlight_momentum(row)
        + _highlight_valuation(row)
        + _highlight_liquidity(row)
        + _highlight_quality(row)
    )
    rationale = "；".join(highlights) if highlights else "无显著亮点"
    if failures:
        rationale += " ｜【降级】" + "、".join(failures)

    return StockScore(
        code=str(row.get("code", "")).zfill(6),
        name=str(row.get("name", "")),
        market=int(_f(row.get("market"))),
        board=str(row.get("board", "")),
        price=_f(row.get("close")),
        change_pct=chg,
        pe_ttm=_f(row.get("pe_ttm")),
        amplitude=_f(row.get("amplitude")),
        amount=_f(row.get("amount")),
        capital_score=capital,
        momentum_score=momentum,
        valuation_score=valuation,
        liquidity_score=liquidity,
        quality_score=quality,
        sentiment_score=sentiment,
        total_score=total,
        tier=tier,
        eligible=True,
        rationale=rationale,
        highlights=highlights,
        guardrail_failures=failures,
        realized_vol_ann=(float(row["realized_vol_ann"])
                          if row.get("realized_vol_ann") is not None
                          and math.isfinite(float(row["realized_vol_ann"])) else None),
        ma_align=bool(row.get("ma_align", False)),
        drawdown_from_high=(float(row["drawdown_from_high"])
                            if row.get("drawdown_from_high") is not None
                            and math.isfinite(float(row["drawdown_from_high"])) else None),
    )


def score_one(row: dict, cfg: ScreenerConfig, technical_enabled: bool = False) -> StockScore:
    """对单只因子行评分（单行无板块中性化，等价于 blend=0 的绝对分）。"""
    dims = factors.dimension_scores(row, cfg)
    return _assemble(row, dims, {}, cfg, technical_enabled)


def score_frame(df, cfg: ScreenerConfig, technical_enabled: bool = False,
               store=None, meta: dict | None = None, end_date: str | None = None
               ) -> list[StockScore]:
    """对 DataFrame（含原始列）做过滤+评分，返回按综合分降序的 StockScore 列表。

    向量化流程（numpy/pandas 批量，见 vector.py）：
        Pass 0  补派生列（chg_today/amplitude/circ_cap/main_net_5d_pct），
                与标量 build_factor_row 派生逻辑一致（缺失保持 NaN）
        Pass 1  逐行 build_factor_row + is_eligible（硬性过滤，缺失三态语义）
        Pass 2  向量计算五维度子分 + 板块内百分位中性化 + 动态护栏 + 评级
        Pass 3  逐行构造 StockScore；解释性文本（rationale/highlights）仅对
                Top RATIONALE_TOP 生成，其余留空（字符串开销集中收敛）。
    与 factors 标量路径共用同一 config，数值行为一致。

    引擎开关：
        store  — 快照存储（SnapshotStore 实例）；engine.mode=ic/auto 时用于
                 读取真实历史计算 RankIC 客观权重；默认 None（fixed 模式不触碰）。
        meta   — 可选 dict，回填引擎诊断信息（engine_mode / engine_weights /
                 engine_diagnostics），供调用方写入 ScreenerResult 报告。
    """
    from . import vector
    from .datasource import _add_derived

    # 解析实际维度权重：默认 fixed=经验权重（与重构前完全一致）；
    # engine.mode=ic/auto/ml/blend 时由真实历史客观赋权（特性开关，向后兼容）。
    # ml/blend 模式需历史训练 ML，提前加载一次历史（resolve_weights 复用，避免双重 IO）。
    intended_mode = (cfg.engine or {}).get("mode", "fixed")
    history = None
    if intended_mode in ("ml", "blend") and store is not None:
        history = ic_engine.load_history(store, cfg, end_date=end_date)
    weights, engine_mode, engine_diag = resolve_weights(
        cfg, store=store, history=history, end_date=end_date)
    # 防御：保证权重键集与配置一致（IC 引擎缺失维度时回退经验权重）
    weights = {d: float(weights.get(d, cfg.weights.get(d, 0.0))) for d in cfg.weights}
    ortho = bool((cfg.engine or {}).get("orthogonalize", False))
    if isinstance(meta, dict):
        meta["engine_mode"] = engine_mode
        meta["engine_weights"] = weights
        meta["engine_diagnostics"] = engine_diag
        meta["model_status"] = "linear"

    df = _add_derived(df)

    keep_recs: list[dict] = []
    for rec in df.to_dict("records"):
        row = build_factor_row(rec)
        ok, _reason = is_eligible(row, cfg)
        if not ok:
            continue
        keep_recs.append(rec)
    if not keep_recs:
        return []

    sub = pd.DataFrame(keep_recs)
    dims = vector.dimension_scores_vec(sub, cfg)
    assembled = vector.assemble_vec(sub, dims, cfg, weights=weights, orthogonalize=ortho)
    assembled = assembled.sort_values("total_score", ascending=False)

    # ---- ML 层（P5）：engine.mode=ml/blend 时叠加非线性预测 ----
    # ml   : 综合分直接取 P(未来强势)×100
    # blend: Score = α·线性分 + (1-α)·P(未来强势)×100，α 默认 0.5
    # 复算后重新排序与评级，保证 tier 与最终综合分一致。无未来函数：
    # 训练只用历史截面，当前截面仅作推理。
    if engine_mode in ("ml", "blend"):
        mlp, ml_diag, ml_status = ml_engine.run_ml_layer(
            cfg, store=store, current_df=sub, end_date=None, history=history)
        if mlp is not None and len(mlp) == len(assembled):
            alpha = float((cfg.engine or {}).get("blend_alpha", 0.5))
            if engine_mode == "ml":
                assembled["total_score"] = (100.0 * mlp).clip(0.0, 100.0)
            else:
                assembled["total_score"] = (
                    alpha * assembled["total_score"] + (1.0 - alpha) * 100.0 * mlp
                ).clip(0.0, 100.0)
            assembled["tier"] = vector.assign_tier(
                assembled["total_score"], assembled["guardrail_mask"], cfg)
            assembled = assembled.sort_values("total_score", ascending=False)
            assembled["ml_prob"] = mlp
            if isinstance(meta, dict):
                engine_diag.update(ml_diag)
                meta["engine_diagnostics"] = engine_diag
                meta["model_status"] = ml_status
        elif isinstance(meta, dict):
            meta["model_status"] = ml_status

    rationale_top = 200
    top_idx = set(assembled.index[:rationale_top])

    scores: list[StockScore] = []
    raw_records = sub.to_dict("records")
    raw_by_pos = {i: rec for i, rec in zip(sub.index, raw_records)}
    _DIMS_SCORES = ("capital", "momentum", "valuation", "liquidity", "quality", "sentiment")
    for i, rec in assembled.iterrows():
        raw = raw_by_pos.get(i, {})
        failures: list[str] = []
        if rec["fail_capital"]:
            failures.append("资金面不足")
        if rec["fail_momentum"]:
            failures.append("动量不足")
        if rec["fail_valuation"]:
            failures.append("估值偏高")
        if rec["fail_quality"]:
            failures.append("质量/波动欠佳")
        if rec["fail_limit"]:
            failures.append("当日接近涨跌停")

        if i in top_idx:
            row = build_factor_row(raw)
            dims_scalar = factors.dimension_scores(row, cfg)
            highlights = (
                _highlight_capital(row, dims_scalar["capital"][1])
                + _highlight_momentum(row)
                + _highlight_valuation(row)
                + _highlight_liquidity(row)
                + _highlight_quality(row)
                + _highlight_sentiment(row)
            )
            rationale = "；".join(highlights) if highlights else "无显著亮点"
            if failures:
                rationale += " ｜【降级】" + "、".join(failures)
        else:
            highlights = []
            rationale = ""

        # ML 概率与因子暴露（ml/blend 模式下由 ML 层填充）
        mlpv = rec.get("ml_prob", None)
        ml_prob = (
            float(mlpv)
            if (mlpv is not None and not (isinstance(mlpv, float) and math.isnan(mlpv)))
            else None
        )
        factor_exposure = {
            d: float(rec[f"{d}_score"]) for d in _DIMS_SCORES if f"{d}_score" in rec
        }

        rv = raw.get("realized_vol_ann")
        dd = raw.get("drawdown_from_high")
        scores.append(StockScore(
            code=str(rec["code"]).zfill(6),
            name=str(rec["name"]),
            market=int(rec["market"]),
            board=str(rec["board"]),
            price=float(rec["price"]),
            change_pct=float(rec["change_pct"]),
            pe_ttm=float(rec["pe_ttm"]),
            amplitude=float(rec["amplitude"]),
            amount=float(rec["amount"]),
            capital_score=float(rec["capital_score"]),
            momentum_score=float(rec["momentum_score"]),
            valuation_score=float(rec["valuation_score"]),
            liquidity_score=float(rec["liquidity_score"]),
            quality_score=float(rec["quality_score"]),
            sentiment_score=float(rec["sentiment_score"]),
            total_score=float(rec["total_score"]),
            tier=str(rec["tier"]),
            eligible=bool(rec["eligible"]),
            rationale=rationale,
            highlights=highlights,
            guardrail_failures=failures,
            ml_prob=ml_prob,
            factor_exposure=factor_exposure,
            realized_vol_ann=(float(rv)
                              if rv is not None and math.isfinite(float(rv)) else None),
            ma_align=bool(raw.get("ma_align", False)),
            drawdown_from_high=(float(dd)
                                if dd is not None and math.isfinite(float(dd)) else None),
        ))
    return scores
