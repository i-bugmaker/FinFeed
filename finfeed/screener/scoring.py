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

from . import factors
from .boards import classify_board
from .config import ScreenerConfig
from .models import StockScore

_ST_RE = re.compile(r"(ST|\*ST|退)", re.IGNORECASE)


def _f(x: Any) -> float:
    try:
        v = float(x)
        return v if math.isfinite(v) else 0.0
    except (TypeError, ValueError):
        return 0.0


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
    close = _f(row.get("close"))
    pre = _f(row.get("pre_close"))
    high = _f(row.get("high"))
    low = _f(row.get("low"))
    float_shares = _f(row.get("float_shares"))  # 万股

    row["chg_today"] = (close - pre) / pre * 100.0 if pre > 0 else 0.0
    row["amplitude"] = (high - low) / pre * 100.0 if pre > 0 else 0.0
    circ_cap = float_shares * 1e4 * close
    row["circ_cap"] = circ_cap
    net5d = _f(row.get("main_net_5d_amount"))
    row["main_net_5d_pct"] = (net5d / circ_cap * 100.0) if circ_cap > 0 else 0.0

    # 技术面字段缺省
    row.setdefault("realized_vol_ann", None)
    row.setdefault("ma_align", False)
    row.setdefault("drawdown_from_high", None)
    # 板块归类（主板/科创板/创业板/北交所）
    row["board"] = classify_board(row.get("code"), int(_f(row.get("market"))))
    return row


def is_eligible(row: dict, cfg: ScreenerConfig) -> tuple[bool, str]:
    """硬性过滤：返回 (是否通过, 未通过原因)。"""
    f = cfg.filters
    name = str(row.get("name", "") or "")
    market = int(_f(row.get("market")))
    price = _f(row.get("close"))
    pe = _f(row.get("pe_ttm"))
    turnover = _f(row.get("turnover"))
    vol = _f(row.get("vol"))
    amount = _f(row.get("amount"))
    circ_cap = _f(row.get("circ_cap"))

    if f.get("exclude_st") and _ST_RE.search(name):
        return False, "ST/退市"
    if f.get("exclude_suspended") and (vol <= 0 or amount <= 0):
        return False, "停牌"
    # 板块过滤：优先用 boards 白名单；无 boards 时退回 exclude_bj 兼容逻辑
    boards = f.get("boards")
    if isinstance(boards, dict):
        board = row.get("board") or classify_board(row.get("code"), market)
        if not boards.get(board, False):
            return False, "板块剔除"
    elif f.get("exclude_bj") and market == 2:
        return False, "北交所"
    if price < _f(f.get("min_price")) or price > _f(f.get("max_price")):
        return False, "价格越界"
    if f.get("exclude_loss") and pe <= 0:
        return False, "亏损"
    if pe > _f(f.get("pe_max")):
        return False, "PE过高"
    if circ_cap < _f(f.get("min_circ_cap")):
        return False, "流通市值过小"
    if turnover < _f(f.get("min_turnover")):
        return False, "换手率过低"
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

    total = (
        w["capital"] * capital
        + w["momentum"] * momentum
        + w["valuation"] * valuation
        + w["liquidity"] * liquidity
        + w["quality"] * quality
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
    if abs(chg) >= _f(g.get("max_abs_chg_today")):
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


def score_frame(df, cfg: ScreenerConfig, technical_enabled: bool = False) -> list[StockScore]:
    """对 DataFrame（含原始列）做过滤+评分，返回按综合分降序的 StockScore 列表。

    两遍流程：
        Pass 1  逐行 build_factor_row + is_eligible + 绝对子分
        Pass 2  按板块构造各维度百分位函数（截面中性化），混合后组装评级
    """
    rows: list[tuple[dict, dict]] = []
    for rec in df.to_dict("records"):
        row = build_factor_row(rec)
        ok, _reason = is_eligible(row, cfg)
        if not ok:
            continue
        dims = factors.dimension_scores(row, cfg)
        rows.append((row, dims))

    # 板块内百分位（中性化）：按板块分组计算每维度相对排名
    pct_maps: dict[str, dict[str, Any]] = {}
    nb = _f((cfg.neutralize or {}).get("blend", 0.0))
    if nb > 0 and rows:
        by_board: dict[str, list[dict]] = {}
        for row, dims in rows:
            by_board.setdefault(row["board"], []).append(dims)
        for board, dl in by_board.items():
            pm: dict[str, Any] = {}
            for d in ("capital", "momentum", "valuation", "liquidity", "quality"):
                pm[d] = _make_percentile([x[d][0] for x in dl])
            pct_maps[board] = pm

    scores = [
        _assemble(row, dims, pct_maps.get(row["board"], {}), cfg, technical_enabled)
        for row, dims in rows
    ]
    scores.sort(key=lambda s: s.total_score, reverse=True)
    return scores
