#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""热门板块 / 热门概念贴合数据（题材热度维度 heat）。

背景
----
短线选股的核心前提是「站在当下资金与情绪的公共主线上」。本模块拉取
概念(GN)与行业(HY)板块的**综合热度**，并把每个热门板块映射回其成分股，
供 score_heat 给「命中热门题材的个股」加分——让选股结果聚焦最近的主攻方向。

热度口径（综合，用户选定）：
    板块热度 = 0.5 × 当日热度 + 0.5 × 近 N 日动能
    当日热度 = 0.40 × 板块涨幅 + 0.35 × 主力净流入 + 0.25 × 涨停普涨度
    近 N 日动能 = 板块成分股在行情快照中的近 5 日涨幅均值
                （放眼最近两三个交易日，而非只看当日）

数据源（复用 easy-tdx 进程级单例，统一限速锁）：
    get_board_ranking(BoardType.GN/HY)  板块排行（涨幅/资金/涨停家数）
    get_board_members(板块代码)          板块成分股 → 构建 股票→热门板块 映射

设计约束
--------
- 走 finfeed.capital_dashboard.tdx 的 call_lock，与资金流大屏/行情共享单连接，
  串行化保证安全；任何一路失败仅标记不可用，**绝不阻塞选股主流程**。
- 结果带 TTL 缓存（按交易日），同一天多次运行时无需重复拉取板块与成分股。
- 返回统一热映射（dict: code -> {hits, best_heat, boards}）供 merge 进快照 df；
  全部不可用时 heat 列置缺失，评分层按中性 50 处理，与旧版行为一致。
"""

from __future__ import annotations

import math
import threading
import time
from typing import Any

import pandas as pd

from easy_tdx import BoardType

from finfeed.capital_dashboard.tdx import call_lock, ensure_alive, get_client
from finfeed.utils.time_utils import now_bj

logger = __import__("logging").getLogger("finfeed.screener.hot_boards")

_YI = 1e8


def _f(v: Any) -> float:
    try:
        f = float(v)
        return f if math.isfinite(f) else float("nan")
    except (TypeError, ValueError):
        return float("nan")


def _norm(series: pd.Series) -> pd.Series:
    """min-max 归一化到 0~100（全相同或空 -> 中性 50）。"""
    s = pd.to_numeric(series, errors="coerce")
    if s.notna().sum() == 0:
        return pd.Series(50.0, index=s.index)
    lo = float(s.min())
    hi = float(s.max())
    if hi <= lo:
        return pd.Series(50.0, index=s.index)
    return (s - lo) / (hi - lo) * 100.0


def _int_code(v: Any) -> str:
    """转 6 位整型代码（兼容 '600519' / 600519 / '600519.0'）。"""
    try:
        return str(int(float(v))).zfill(6)
    except (TypeError, ValueError):
        return str(v)


class HotBoardContext:
    """一次热门板块贴合快照（线程安全只读）。"""

    available: bool = False
    trade_date: str = ""
    top_boards: list[dict] = []     # [{type,name,code,heat}]
    by_code: dict[str, dict] = {}   # code -> {hits, best_heat, boards: [name,...]}
    n_hot_members: int = 0          # 命中热门板块的个股数

    def __init__(self) -> None:
        self.top_boards = []
        self.by_code = {}

    def to_dict(self) -> dict[str, Any]:
        return {
            "available": self.available,
            "trade_date": self.trade_date,
            "top_boards": self.top_boards,
            "n_hot_members": self.n_hot_members,
        }


# ──────────────────────────────────────────────────────────────────────────
# 采集（TDX 串行）
# ──────────────────────────────────────────────────────────────────────────

def _fetch_board_rankings(top_n: int) -> dict[str, pd.DataFrame]:
    """拉概念(GN) + 行业(HY) 板块排行（各自 top_n）。失败置 None。"""
    ensure_alive()
    client = get_client()
    out: dict[str, Any] = {"GN": None, "HY": None}
    for bt, key in ((BoardType.GN, "GN"), (BoardType.HY, "HY")):
        try:
            with call_lock():
                df = client.get_board_ranking(bt, top_n=top_n)
            out[key] = df if (df is not None and len(df)) else None
        except Exception as exc:  # noqa: BLE001
            logger.warning("热门板块排行获取失败[%s]: %s", key, exc)
    return out


def _fetch_board_members(board_code: str) -> set[str]:
    """取板块成分 6 位代码集合；失败返回空集。"""
    try:
        with call_lock():
            mem = get_client().get_board_members(board_code, count=100000)
        if mem is None or len(mem) == 0:
            return set()
        col = "code" if "code" in mem.columns else next(
            (c for c in mem.columns if str(c).lower() == "code"), None)
        if col is None:
            return {_int_code(c) for c in mem.iloc[:, 0]}
        return {_int_code(c) for c in mem[col]}
    except Exception as exc:  # noqa: BLE001
        logger.debug("板块成分股获取失败 %s: %s", board_code, exc)
        return set()


def _today_heat(frame: pd.DataFrame) -> pd.Series:
    """当日热度：0.40×涨幅 + 0.35×主力净流入 + 0.25×涨停普涨度（min-max）。"""
    chg = _norm(frame["change_pct"])
    fund = _norm(frame["main_net_amount"])
    frac = frame["up_count"] / frame["member_count"].replace(0, pd.NA)
    rally = _norm(frac.fillna(0.0))
    return (0.40 * chg + 0.35 * fund + 0.25 * rally).clip(0.0, 100.0)


def _build(ctx: HotBoardContext, df: pd.DataFrame, cfg) -> None:
    """采集 + 打分 + 建映射。cfg 提供热板块 top 数等参数（读 cfg.params.heat）。"""
    p = (getattr(cfg, "params", None) or {}).get("heat") or {}
    top_each = int(p.get("top_each", 30))        # 每榜拉取规模
    hot_total = int(p.get("hot_total", 24))      # 综合热度入选板块数
    today_w = float(p.get("today_w", 0.5))
    mom5d_w = 1.0 - today_w
    mom_col = str(p.get("momentum_col", "change_5d_pct"))

    rank = _fetch_board_rankings(top_each)
    rows: list[dict] = []
    for key, f in rank.items():
        if f is None:
            continue
        f = f.copy()
        for c in ("change_pct", "main_net_amount", "up_count", "member_count"):
            if c not in f.columns:
                f[c] = float("nan")
        f["type"] = key
        rows.extend(f.to_dict("records"))
    if not rows:
        ctx.available = False
        return

    frame = pd.DataFrame(rows)
    frame["code"] = frame["code"].astype(str).str.strip()
    frame["heat_today"] = _today_heat(frame)

    # 近 5 日动能：板块成分股在快照中的近 5 日涨幅均值（放眼近几个交易日）
    df_codes = {_int_code(c) for c in df["code"].dropna()}
    if mom_col in df.columns:
        df_mom = pd.to_numeric(df[mom_col], errors="coerce")
        mom_by_code = dict(zip(df["code"].map(_int_code), df_mom))
    else:
        mom_by_code = {}

    ranked = frame.sort_values("heat_today", ascending=False)
    top = ranked.head(hot_total)

    by_code: dict[str, dict] = {}
    top_list: list[dict] = []
    for _, b in top.iterrows():
        bcode = str(b["code"])
        bname = str(b["name"])
        btype = str(b["type"])
        members = _fetch_board_members(bcode) & df_codes
        # 板块近5日动能（缺失时回退当日热度，不放大当日口径误差）
        if mom_by_code:
            vals = [_f(mom_by_code.get(c)) for c in members]
            vals = [v for v in vals if v == v]  # 去 NaN
            b5d = float(sum(vals) / len(vals)) if vals else float("nan")
        else:
            b5d = float("nan")
        if not math.isnan(b5d):
            # 近5日动能 sigmoid 映射到 0~100：+5% 得 50 分
            b_mom_score = 100.0 / (1.0 + math.exp(-(b5d - 5.0) / 10.0))
        else:
            b_mom_score = float(b["heat_today"])  # 无近端数据按当日处理
        heat = max(0.0, min(100.0, today_w * float(b["heat_today"]) + mom5d_w * b_mom_score))
        top_list.append({"type": btype, "code": bcode, "name": bname,
                         "heat": round(heat, 1)})
        for m in members:
            rec = by_code.setdefault(m, {"hits": 0, "best_heat": 0.0, "boards": []})
            rec["hits"] += 1
            rec["boards"].append(bname)
            if heat > rec["best_heat"]:
                rec["best_heat"] = heat

    ctx.available = True
    ctx.trade_date = now_bj().strftime("%Y-%m-%d")
    ctx.top_boards = top_list
    ctx.by_code = by_code
    ctx.n_hot_members = len(by_code)


# 缓存（TTL，按运行轮次命中；交易日为粒度）
_lock = threading.Lock()
_cache: dict[str, Any] = {"ctx": None, "date": "", "built_at": 0.0, "ttl": 900.0}


def build_hot_heat(df: pd.DataFrame, cfg) -> tuple[pd.DataFrame, HotBoardContext]:
    """采集热门板块贴合数据并 merge 进 df（就地新增列），返回 (df, ctx)。

    全部不可用时 df 不新增列（评分层按缺失->中性处理），ctx.available=False。

    新增列：
        hot_hits       该股命中的热门板块数
        hot_best_heat  命中板块中的最高热度（0~100）
        hot_boards     命中热门板块名称（逗号分隔，用于标注展示）
    """
    ctx = HotBoardContext()
    p = (getattr(cfg, "params", None) or {}).get("heat") or {}

    with _lock:
        if _cache["ctx"] is not None \
                and _cache["date"] == now_bj().strftime("%Y-%m-%d") \
                and (time.time() - _cache["built_at"]) < float(p.get("ttl_seconds", 900)):
            ctx = _cache["ctx"]
            return _apply(df, ctx), ctx

    try:
        _build(ctx, df, cfg)
    except Exception as exc:  # noqa: BLE001
        logger.warning("热门板块贴合采集失败（本次不启用 heat 维度）: %s", exc)
        ctx = HotBoardContext()
    if ctx.available:
        with _lock:
            _cache["ctx"] = ctx
            _cache["date"] = ctx.trade_date
            _cache["built_at"] = time.time()
    return _apply(df, ctx), ctx


def _apply(df: pd.DataFrame, ctx: HotBoardContext) -> pd.DataFrame:
    """把热映射 merge 进快照 df（未能映射的 code 保持命中 0 / 最高热度 0）。"""
    if not ctx.available:
        return df
    out = df.copy()
    codes = out["code"].map(_int_code)
    rec = (
        codes.map(lambda c: ctx.by_code.get(c))
        if ctx.by_code else None
    )
    if rec is None:
        out["hot_hits"] = 0
        out["hot_best_heat"] = float("nan")
        out["hot_boards"] = ""
        return out
    hits = rec.map(lambda r: r["hits"] if r else 0).fillna(0).astype(int)
    # 未命中热门板块：热度给 0（真实零收益，区别于「数据不可用→缺失」），
    # 这样评分层才能把「没贴合主线」与「整模块不可用」区分开。
    best = rec.map(lambda r: r["best_heat"] if r else 0.0)
    boards = rec.map(lambda r: ",".join(r["boards"]) if r else "")
    out["hot_hits"] = hits
    out["hot_best_heat"] = best
    out["hot_boards"] = boards.fillna("")
    return out