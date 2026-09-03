#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""短线市场环境上下文（大盘 / 涨跌停 / ETF / 大资金 / 龙虎榜）。

背景
----
短线选股（T+1~T+5 持有）的胜率高度依赖「市场环境」：强市中动量与题材
容错率高，弱市与情绪退潮期追高易被闷杀。本模块为选股引擎补充一层独立的
**市场环境上下文**（market context），把五类盘面信号统一为可解释的
「短线风险偏好分」，并输出 TOP 榜单供结果页展示：

1. 近期大盘整体走势 —— 上证/深成/创业板/科创50/沪深300 当日涨跌（push2 ulist）
2. 涨跌停板分布       —— 涨停/跌停/炸板池 + 炸板率 + 最高连板（push2ex 三池）
3. ETF 资金流向       —— 场内 ETF 主力净流入/流出 TOP（push2 clist，b:MK0021）
4. 大资金与大基金动向 —— 全 A 主力净流入/流出 TOP（push2 clist）
5. 龙虎榜数据         —— 当日龙虎榜个股净买入汇总（datacenter）

设计约束
--------
- 全部走 finfeed.market.client（统一限速/冷却/降级/熔断），任何一路失败仅
  标记该信号不可用，**绝不阻塞**选股主流程；全部不可用时返回 None（不做调整）。
- 结果带 TTL 缓存（默认 240s），同一时段多次运行只拉一次，避免打爆 push2。
- 风险偏好分 0~100 → 线性映射为总分的「情绪系数」，在 scoring.py 的
  market overlay 中应用；无数据或关闭时系数恒为 1.0（行为与旧版一致）。
- 仅消费公开行情接口，无未来函数；盘中为实时截面，盘后为当日定格。
"""

from __future__ import annotations

import asyncio
import math
import logging
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Optional

logger = logging.getLogger("finfeed.screener.market_context")

_YI = 1e8

# push2 clist 行情列表基础参数
_CLIST_COMMON = {"pn": 1, "np": 1, "fltt": 2, "invt": 2}
# 场内基金大类：ETF 等（实测 total≈1313）
_ETF_FS = "b:MK0021"
# 全 A（沪深主板 + 双创 + 北交？北交数据口径不同，不含）
_BIGMONEY_FS = "m:0+t:6,m:0+t:80,m:1+t:2,m:1+t:23,m:0+t:81+s:2048"
# 指数 ulist：上证 / 深成 / 创业板 / 科创50 / 沪深300
_INDEX_SECIDS = "1.000001,0.399001,0.399006,1.000688,1.000300"
# ETF/个股资金字段：价/涨跌幅/主力净流入/主力净占比 + 代码/名称
_MONEY_FIELDS = "f2,f3,f12,f14,f62,f184"


@dataclass
class MarketContext:
    """一次市场环境快照（线程安全只读，变更请整体替换）。"""

    ts: float = 0.0                      # 采集时刻（epoch）
    trade_date: str = ""                 # 交易日 YYYY-MM-DD
    as_of: str = ""                      # 展示用时间
    # 1) 大盘走势
    indices: list[dict] = field(default_factory=list)      # [{code,name,price,pct}]
    index_available: bool = False
    # 2) 涨跌停板分布
    limit_stats: dict[str, Any] = field(default_factory=dict)  # up/down/broken/炸板率/最高连板
    limit_available: bool = False
    # 3) ETF 资金流向
    etf_in: list[dict] = field(default_factory=list)       # 主力净流入 TOP（降序）
    etf_out: list[dict] = field(default_factory=list)      # 主力净流出 TOP（降序）
    etf_available: bool = False
    # 4) 大资金动向
    big_in: list[dict] = field(default_factory=list)
    big_out: list[dict] = field(default_factory=list)
    big_available: bool = False
    # 5) 龙虎榜
    lhb_net_buy: list[dict] = field(default_factory=list)  # 净买入 TOP（降序）
    lhb_net_sell: list[dict] = field(default_factory=list)  # 净卖出 TOP
    lhb_available: bool = False
    # 信号级可用性（供 UI 展示哪一路缺数据）
    unavailable: list[str] = field(default_factory=list)

    # 综合结论
    regime_score: float = 50.0           # 短线风险偏好 0~100
    appetite: float = 1.0                # 情绪系数（scoring 使用；无数据=1.0）
    regime_label: str = "均衡"
    gauge_detail: dict[str, Any] = field(default_factory=dict)  # 各分量分

    def to_dict(self) -> dict[str, Any]:
        return {
            "ts": self.ts,
            "trade_date": self.trade_date,
            "as_of": self.as_of,
            "indices": self.indices,
            "index_available": self.index_available,
            "limit_stats": self.limit_stats,
            "limit_available": self.limit_available,
            "etf_in": self.etf_in,
            "etf_out": self.etf_out,
            "etf_available": self.etf_available,
            "big_in": self.big_in,
            "big_out": self.big_out,
            "big_available": self.big_available,
            "lhb_net_buy": self.lhb_net_buy,
            "lhb_net_sell": self.lhb_net_sell,
            "lhb_available": self.lhb_available,
            "unavailable": self.unavailable,
            "regime_score": round(self.regime_score, 1),
            "appetite": round(self.appetite, 4),
            "regime_label": self.regime_label,
            "gauge_detail": self.gauge_detail,
        }

    def summary(self) -> str:
        """一行日志摘要。"""
        ls = self.limit_stats
        return (
            f"regime={self.regime_label}({self.regime_score:.0f}) "
            f"涨停{ls.get('up', '-')}/跌停{ls.get('down', '-')}/炸板{ls.get('broken', '-')} "
            f"最高{ls.get('max_streak', '-')}连板 缺口{[*self.unavailable] or '无'}"
        )


# ──────────────────────────────────────────────────────────────────────────
# 异步采集（走 finfeed.market.client 统一限速/冷却/熔断）
# ──────────────────────────────────────────────────────────────────────────

async def _fetch_indexes() -> Optional[list[dict]]:
    from finfeed.market.client import RateLimited, get_json
    from finfeed.market.endpoints import PUSH2, UT

    try:
        data = await get_json(
            f"{PUSH2}/ulist.np/get",
            params={"secids": _INDEX_SECIDS, "fields": "f2,f3,f12,f14", "fltt": 2, "ut": UT},
            group="em_push2",
        )
    except (RateLimited, RuntimeError) as exc:
        logger.info("大盘指数获取跳过（%s）", exc)
        return None
    diff = (data.get("data") or {}).get("diff") or []
    out = []
    for it in diff:
        code = str(it.get("f12") or "").strip()
        if not code:
            continue
        out.append({
            "code": code,
            "name": (it.get("f14") or "").strip(),
            "price": _f(it.get("f2")),
            "pct": _f(it.get("f3")),
        })
    return out or None


async def _fetch_limit_stats(trade_date: str) -> Optional[dict]:
    from finfeed.market import quote

    try:
        zt = await quote.fetch_limit_pool(trade_date, "up")
        dt = await quote.fetch_limit_pool(trade_date, "down")
        zb = await quote.fetch_limit_pool(trade_date, "broken")
    except Exception as exc:  # noqa: BLE001
        logger.warning("涨跌停池获取失败: %s", exc)
        return None
    zt_n, dt_n, zb_n = len(zt), len(dt), len(zb)
    denom = zt_n + zb_n
    return {
        "up": zt_n, "down": dt_n, "broken": zb_n,
        "broken_rate": round(zb_n / denom * 100, 2) if denom else 0.0,
        "max_streak": max((int(r.get("limit_streak") or 0) for r in zt), default=0),
    }


async def _fetch_money_ranking(fs: str, top: int = 12,
                               out_dir: bool = False) -> Optional[list[dict]]:
    """push2 clist 资金净流入/流出排行（fs 决定标的池）。"""
    from finfeed.market.client import RateLimited, get_json
    from finfeed.market.endpoints import PUSH2, UT

    try:
        data = await get_json(
            f"{PUSH2}/clist/get",
            params={
                **_CLIST_COMMON, "fid": "f62", "po": 1 if not out_dir else 0,
                "pz": top, "fs": fs, "fields": _MONEY_FIELDS, "ut": UT,
            },
            group="em_push2",
        )
    except (RateLimited, RuntimeError) as exc:
        logger.info("资金排行获取跳过（%s）", exc)
        return None
    diff = (data.get("data") or {}).get("diff") or []
    out = []
    for it in diff:
        code = str(it.get("f12") or "").strip()
        if not code:
            continue
        out.append({
            "code": code,
            "name": (it.get("f14") or "").strip(),
            "price": _f(it.get("f2")),
            "pct": _f(it.get("f3")),
            "net_yi": round(_f(it.get("f62")) / _YI, 2),      # 主力净额（亿元）
            "net_ratio": _f(it.get("f184")),                  # 主力净占比 %
        })
    return out or None


async def _fetch_lhb(trade_date: str) -> Optional[tuple[list[dict], list[dict]]]:
    """当日龙虎榜：按代码汇总净额，返回 (净买入TOP, 净卖出TOP)。"""
    from finfeed.market import board

    try:
        rows = await board.fetch_billboard(trade_date)
    except Exception as exc:  # noqa: BLE001
        logger.warning("龙虎榜获取失败: %s", exc)
        return None
    if not rows:
        return [], []
    agg: dict[str, dict] = {}
    for r in rows:
        code = str(r.get("code") or "").strip()
        if not code:
            continue
        a = agg.setdefault(code, {"code": code, "name": str(r.get("name") or ""),
                                  "net_yi": 0.0, "reason": ""})
        a["net_yi"] += _f(r.get("net_amount")) / _YI
        if r.get("reason"):
            a["reason"] = a["reason"] or str(r.get("reason"))
    items = sorted(agg.values(), key=lambda x: x["net_yi"], reverse=True)
    buy = [x for x in items if x["net_yi"] > 0][:10]
    sell = sorted([x for x in items if x["net_yi"] < 0], key=lambda x: x["net_yi"])[:10]
    for s in sell:
        s["net_yi"] = round(abs(s["net_yi"]), 2)
    for b in buy:
        b["net_yi"] = round(b["net_yi"], 2)
    return buy, sell


# ──────────────────────────────────────────────────────────────────────────
# 综合风险偏好评估
# ──────────────────────────────────────────────────────────────────────────

def _sigmoid(x: float, mid: float = 0.0, scale: float = 1.0) -> float:
    try:
        return 1.0 / (1.0 + math.exp(-(x - mid) / scale))
    except OverflowError:
        return 1.0 if x > mid else 0.0


def _clip(x: float, lo: float = 0.0, hi: float = 100.0) -> float:
    return max(lo, min(hi, x))


def _band(x: float, lo: float, hi: float) -> float:
    """[lo,hi] 线性映射到 0~100，x 落在区间外时钳制。"""
    if hi <= lo:
        return 50.0
    return _clip((x - lo) / (hi - lo) * 100.0)


def _gauge(ctx: MarketContext) -> None:
    """由各信号计算 regime_score（0~100）与情绪系数。

    各分量的分（0~100）与权重：
      大盘走势 0.30 | 涨跌停分布 0.30 | ETF 流向 0.15 | 大资金 0.10 | 龙虎榜 0.15
    某分量不可用/缺数据时其权重均摊给其余可用分量；全部不可用保持 50（中性）。
    """
    parts: list[tuple[str, float, float]] = []  # (名称, 分, 权重)

    # 1) 大盘：主要指数当日平均涨跌幅
    if ctx.index_available and ctx.indices:
        pcts = [x["pct"] for x in ctx.indices if _f(x.get("pct")) is not None]
        if pcts:
            mean_pct = sum(pcts) / len(pcts)
            parts.append(("index", _sigmoid(mean_pct, mid=0.1, scale=0.9) * 100.0, 0.30))

    # 2) 涨跌停：多空比 + 炸板率惩罚 + 连板高度奖励
    if ctx.limit_available:
        up = int(ctx.limit_stats.get("up") or 0)
        down = int(ctx.limit_stats.get("down") or 0)
        broken_rate = float(ctx.limit_stats.get("broken_rate") or 0.0)
        max_streak = int(ctx.limit_stats.get("max_streak") or 0)
        base = _band(up / (up + down) * 100.0 if (up + down) else 50.0, 20.0, 85.0) \
            if (up + down) else 50.0
        pen = min(broken_rate * 0.6, 45.0)      # 炸板率越高越差
        bonus = min(max_streak * 12.0, 36.0)    # 连板高度代表情绪温度
        parts.append(("limit", _clip(base - pen + bonus), 0.30))

    # 3) ETF 资金：净流入总和（亿元）决定方向与强度
    if ctx.etf_available and (ctx.etf_in or ctx.etf_out):
        net = sum(x["net_yi"] for x in ctx.etf_in) + sum(x["net_yi"] for x in ctx.etf_out)
        parts.append(("etf", _sigmoid(net, mid=0.0, scale=25.0) * 100.0, 0.15))

    # 4) 大资金：全 A 主力净流入/流出 TOP 净额
    if ctx.big_available and (ctx.big_in or ctx.big_out):
        net = sum(x["net_yi"] for x in ctx.big_in) + sum(x["net_yi"] for x in ctx.big_out)
        parts.append(("big", _sigmoid(net, mid=0.0, scale=40.0) * 100.0, 0.10))

    # 5) 龙虎榜：净买入总额（亿元），代表游资/机构活跃度
    if ctx.lhb_available and ctx.lhb_net_buy:
        net = sum(x["net_yi"] for x in ctx.lhb_net_buy)
        parts.append(("lhb", _sigmoid(net, mid=0.0, scale=12.0) * 100.0, 0.15))

    if not parts:
        ctx.regime_score, ctx.appetite, ctx.regime_label = 50.0, 1.0, "数据缺失"
        ctx.gauge_detail = {"weighted": 0.0, "parts": {}}
        return

    total_w = sum(w for _, _, w in parts)
    score = sum(s * w for _, s, w in parts) / total_w
    ctx.regime_score = _clip(score)
    # 情绪系数由 _collect 统一按 config.params（appetite_lo/hi）映射，此处不设值
    if ctx.regime_score >= 62:
        ctx.regime_label = "强势"
    elif ctx.regime_score >= 40:
        ctx.regime_label = "均衡"
    else:
        ctx.regime_label = "谨慎"
    ctx.gauge_detail = {
        "weighted": round(score, 1),
        "parts": {name: round(s, 1) for name, s, _ in parts},
    }


# ──────────────────────────────────────────────────────────────────────────
# 同步入口（worker 线程） + TTL 缓存
# ──────────────────────────────────────────────────────────────────────────

_build_lock = threading.Lock()
_cache: dict[str, Any] = {"ctx": None, "built_at": 0.0, "params": None}


def _default_appetite(score: float, params: dict | None) -> float:
    """regime_score → 情绪系数（可在 config.params.market 中配置上下限）。"""
    mp = params or {}
    lo = float(mp.get("appetite_lo", 0.88))
    hi = float(mp.get("appetite_hi", 1.08))
    return round(lo + (hi - lo) * (_clip(score) / 100.0), 4)


async def _collect(trade_date: str, params: dict | None) -> MarketContext:
    """异步采集 + 组装 + 打分（单次，不缓存）。"""
    ctx = MarketContext(ts=time.time(), trade_date=trade_date,
                        as_of=time.strftime("%Y-%m-%d %H:%M:%S"))

    # 并发出五路（限速在 client 内部，各请求自然排队）
    idx_task = asyncio.create_task(_fetch_indexes())
    lim_task = asyncio.create_task(_fetch_limit_stats(trade_date))
    etf_in_t = asyncio.create_task(_fetch_money_ranking(_ETF_FS, top=12))
    etf_out_t = asyncio.create_task(_fetch_money_ranking(_ETF_FS, top=12, out_dir=True))
    big_in_t = asyncio.create_task(_fetch_money_ranking(_BIGMONEY_FS, top=10))
    big_out_t = asyncio.create_task(_fetch_money_ranking(_BIGMONEY_FS, top=10, out_dir=True))
    lhb_t = asyncio.create_task(_fetch_lhb(trade_date))

    idx = await idx_task
    if idx is None:
        ctx.unavailable.append("大盘")
    else:
        ctx.indices = idx
        ctx.index_available = True

    lim = await lim_task
    if lim is None:
        ctx.unavailable.append("涨跌停")
    else:
        ctx.limit_stats = lim
        ctx.limit_available = True

    etf_in = await etf_in_t
    etf_out = await etf_out_t
    if etf_in is None and etf_out is None:
        ctx.unavailable.append("ETF资金")
    else:
        ctx.etf_in = etf_in or []
        ctx.etf_out = etf_out or []
        ctx.etf_available = True

    big_in = await big_in_t
    big_out = await big_out_t
    if big_in is None and big_out is None:
        ctx.unavailable.append("大资金")
    else:
        ctx.big_in = big_in or []
        ctx.big_out = big_out or []
        ctx.big_available = True

    lhb = await lhb_t
    if lhb is None:
        ctx.unavailable.append("龙虎榜")
    else:
        ctx.lhb_net_buy, ctx.lhb_net_sell = lhb
        ctx.lhb_available = True

    _gauge(ctx)
    ctx.appetite = _default_appetite(ctx.regime_score, params)
    return ctx


def fetch_market_context(force: bool = False,
                         ttl_seconds: float = 240.0,
                         params: dict | None = None) -> Optional[MarketContext]:
    """同步拉取（带 TTL 缓存）。全部数据源失败返回 None（调用方不做调整）。

    Args:
        force: 强制刷新缓存。
        ttl_seconds: 缓存有效期（秒）；config.params.market.ttl_seconds 覆盖。
        params: config.params.market 参数（appetite 上下限等）。
    """
    from finfeed.utils.time_utils import now_bj

    with _build_lock:
        if not force and _cache["ctx"] is not None:
            age = time.time() - _cache["built_at"]
            if age < ttl_seconds and _cache["params"] == params:
                return _cache["ctx"]
        # 缓存未命中 → 释放锁采集（避免长采集阻塞其它调用方读旧缓存）
    try:
        trade_date = now_bj().strftime("%Y-%m-%d")
        ctx = asyncio.run(_collect(trade_date, params))
    except Exception as exc:  # noqa: BLE001
        logger.warning("市场环境上下文采集失败（本次不做环境调整）: %s", exc)
        return None

    if not ctx.index_available and not ctx.limit_available and not ctx.etf_available \
            and not ctx.big_available and not ctx.lhb_available:
        logger.warning("市场环境五路信号全部不可用，本次不做环境调整")
        return None
    with _build_lock:
        _cache["ctx"] = ctx
        _cache["built_at"] = time.time()
        _cache["params"] = params
    return ctx


def get_cached() -> Optional[MarketContext]:
    """读取最近一次缓存（供 UI 展示，无数据返回 None）。"""
    with _build_lock:
        return _cache["ctx"]


def lhb_net_buy_codes(ctx: MarketContext) -> dict[str, float]:
    """龙虎榜净买入代码 → 净额（元级已转亿元，仅正数）。"""
    if not ctx or not ctx.lhb_available:
        return {}
    return {x["code"]: float(x["net_yi"]) for x in ctx.lhb_net_buy}


# ──────────────────────────────────────────────────────────────────────────
# Overlay：情绪系数 → 维度权重调整（供 scoring 调用；纯函数，不触网）
# ──────────────────────────────────────────────────────────────────────────

def apply_market_weights(weights: dict, cfg, appetite: float) -> tuple[dict, dict]:
    """按情绪系数调整维度权重（进攻维上调 / 防御维下调，乘子后整体归一化）。

    Args:
        weights: 当前使用的维度权重（fixed 经验值或 IC 客观值）。
        cfg:     ScreenerConfig（读取 market 段）。
        appetite: 情绪系数（1.0=中性不变）。

    Returns:
        (调整后权重, 调整诊断 dict)。appetite 缺失/为 1.0/配置关闭时原样返回。
    """
    mk = cfg.market if cfg is not None else None
    mcfg = mk if isinstance(mk, dict) else {}
    off = set(mcfg.get("offense_dims") or ["momentum", "sentiment"])
    deff = set(mcfg.get("defense_dims") or ["valuation", "quality"])
    strength = _clip(float(mcfg.get("overlay_strength", 0.6)), 0.0, 1.0)
    diag: dict = {"appetite": appetite, "applied": False, "delta": {}, "note": ""}

    try:
        ap = float(appetite)
    except (TypeError, ValueError):
        diag["note"] = "情绪系数缺失，跳过权重调整"
        return dict(weights), diag
    if not math.isfinite(ap) or abs(ap - 1.0) < 1e-9 or strength <= 0:
        diag["note"] = "情绪系数中性或 overlay 强度为 0，跳过权重调整"
        return dict(weights), diag

    # 乘子：强市进攻维放大、防御维收缩（2-ap 与放大对称）；再整体归一化保持合计 1.0
    # 系数限制在 [0.7, 1.3]，防止极端情绪下权重畸变（弱市防防御维被削到失效）
    base = {d: float(w) for d, w in weights.items()}
    adj = {}
    for d, w in base.items():
        if d in off:
            m = 1.0 + (ap - 1.0) * strength
        elif d in deff:
            m = 1.0 - (ap - 1.0) * strength
        else:
            m = 1.0
        m = _clip(m, 0.7, 1.3)
        adj[d] = m
    scaled = {d: w * adj[d] for d, w in base.items()}
    tot = sum(scaled.values())
    out = {d: (v / tot if tot > 0 else 0.0) for d, v in scaled.items()}
    diag["applied"] = True
    diag["multipliers"] = {d: round(m, 4) for d, m in adj.items() if abs(m - 1.0) > 1e-9}
    diag["delta"] = {d: round(out[d] - base[d], 4) for d in out if abs(out[d] - base[d]) > 1e-4}
    diag["note"] = f"情绪系数 {ap:.3f}：{'、'.join(off)} 上调 / {'、'.join(deff)} 下调"
    return out, diag


def rank_flags(ctx: Optional[MarketContext], code: str) -> list[str]:
    """个股是否命中当日资金/龙虎榜榜单（结果页标注，纯文本增强不改分）。

    命中大资金主力净流入 TOP 或龙虎榜净买入 TOP 的标的，在 rationale 中显著标注，
    让「综合考量大资金动向/龙虎榜数据」落到个股层面。榜单位为亿元。
    """
    if ctx is None:
        return []
    code = str(code or "").zfill(6)
    out: list[str] = []
    if ctx.big_available:
        for it in ctx.big_in:
            if str(it.get("code", "")).zfill(6) == code:
                out.append(f"主力净流入榜{it.get('net_yi', 0):.1f}亿")
                break
    if ctx.lhb_available:
        for it in ctx.lhb_net_buy:
            if str(it.get("code", "")).zfill(6) == code:
                out.append(f"龙虎榜净买{it.get('net_yi', 0):.1f}亿")
                break
    return out


def _f(v: Any) -> float:
    try:
        f = float(v)
        return f
    except (TypeError, ValueError):
        return float("nan")
