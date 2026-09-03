# -*- coding: utf-8 -*-
"""ETF / 各类基金主力资金排行 —— 东方财富 push2 clist 采集层。

背景
----
资金流监控大屏原有的全市场个股/板块资金流全部来自通达信 MAC 协议（两档口径）。
为补齐「ETF 及各类基金」的资金排行（用户需求 2），本模块新增一路**独立的
东财数据源**：push2 clist 按主力净额(f62)排序的场内基金榜单，与 TDX 主链路
解耦 —— 东财限流/断连只影响本模块，不拖垮大屏主刷新。

实现要点
--------
- 走 ``finfeed.market.client`` 统一客户端（group=em_push2）：令牌桶限速、
  组级冷却熔断、业务拒绝降级语义全部复用；冷却期内请求即刻短路抛
  ``RateLimited``，采集线程静默降级，绝不打爆上游。
- 基金池注册表 ``FUND_POOLS``：每个池 = 东财行情市场代码(fs)。**已实测**：
  ``b:MK0021`` = 沪深场内 ETF（约 1300+ 只）。``b:MK0022`` 为候选的
  场内 LOF 池（编码沿用东财行情中心基金分类惯例，上线时以实际返回校验，
  无数据/返回空会自动隐藏该类别，不影响其余池）。
- 单飞顺序采集（每轮每池 净流入 + 净流出 两次请求），避免并发突发触发限流。
- 存储为进程内线程安全快照：某一池瞬时失败时**保留其上一轮数据**（仅记
  日志），避免面板内容抖动；从未成功过的池列入 ``unavailable`` 供前端提示。
"""

from __future__ import annotations

import asyncio
import logging
import threading
import time
from dataclasses import asdict
from typing import Any, Optional

from . import config
from .models import FundFlow

logger = logging.getLogger("finfeed.capital_dashboard.funds")

_YI = 1e8  # noqa: F841  # 保留常量便于后续改口径为亿元时使用

# push2 clist 行情列表基础参数（与 screener.market_context 同口径）
_CLIST_COMMON = {"pn": 1, "np": 1, "fltt": 2, "invt": 2}
_FIELDS = "f2,f3,f12,f14,f62,f184"

# 基金池注册表（顺序即前端展示顺序）。
# verified=True 表示池编码已实测可用；False 为候选池（运行时自动核验，
# 返回空/失败则不出现在 categories，不产生误导性空榜）。
FUND_POOLS: list[dict[str, Any]] = [
    {"key": "etf", "fs": "b:MK0021", "label": "ETF", "verified": True},
    {"key": "lof", "fs": "b:MK0022", "label": "LOF", "verified": False},
]


def _f(v: Any) -> float:
    """数值化；'-'/None/非法 → NaN（调用方自行过滤）。"""
    try:
        f = float(v)
        return f
    except (TypeError, ValueError):
        return float("nan")


# --------------------------------------------------------------------------- #
# 异步采集（单池单方向一次请求）
# --------------------------------------------------------------------------- #

async def _fetch_side(fs: str, top: int, out_dir: bool) -> Optional[tuple[int, list[dict]]]:
    """拉取某基金池按主力净额排序的榜单一侧。

    Returns:
        (池内标的总数 total, 条目 dict 列表)；网络失败或限流返回 None。
        条目字段：code/name/price/change_pct/main_net/main_net_ratio。
    """
    from finfeed.market.client import RateLimited, get_json
    from finfeed.market.endpoints import PUSH2, UT

    try:
        data = await get_json(
            f"{PUSH2}/clist/get",
            params={
                **_CLIST_COMMON, "fid": "f62", "po": 1 if not out_dir else 0,
                "pz": top, "fs": fs, "fields": _FIELDS, "ut": UT,
            },
            group="em_push2",
        )
    except (RateLimited, RuntimeError) as exc:
        logger.info("基金资金榜获取跳过 %s out=%s（%s）", fs, out_dir, exc)
        return None
    d = data.get("data") or {}
    diff = d.get("diff") or []
    total = int(d.get("total") or 0)
    rows: list[dict] = []
    for it in diff:
        code = str(it.get("f12") or "").strip()
        net = _f(it.get("f62"))
        if not code or net != net:  # 无代码或主力净额缺失('-')的行跳过
            continue
        rows.append(
            {
                "code": code,
                "name": (it.get("f14") or "").strip(),
                "price": _f(it.get("f2")),
                "change_pct": _f(it.get("f3")),
                "main_net": round(net, 2),              # 元
                "main_net_ratio": _f(it.get("f184")),   # %
            }
        )
    if not rows:
        return None
    return total, rows


async def _fetch_pool(pool: dict, top: int) -> Optional[tuple[int, list[dict], list[dict]]]:
    """拉取单个基金池（净流入 + 净流出）。失败返回 None。"""
    fs = pool["fs"]
    inc = await _fetch_side(fs, top, out_dir=False)
    out = await _fetch_side(fs, top, out_dir=True)
    if inc is None and out is None:
        return None
    total = max((inc[0] if inc else 0), (out[0] if out else 0))
    return (total, (inc[1] if inc else []), (out[1] if out else []))


# --------------------------------------------------------------------------- #
# 线程安全快照存储
# --------------------------------------------------------------------------- #

class FundRankStore:
    """进程内 ETF/基金资金排行快照（写者 = FundRankWorker，读任一线程）。"""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._meta: dict[str, dict] = {}      # key -> {key,label,fs,total,verified}
        self._rank: dict[str, dict] = {}      # key -> {"in": [...], "out": [...]}
        self._unavailable: list[dict] = []    # 从未成功过的池 + 失败原因
        self._last_attempt: float = 0.0
        self._ts: str = ""                    # 最近一次成功采集时间
        self._ts_label: str = ""
        self._error: str = ""

    # -- 写 ----------------------------------------------------------------
    def update_pool(self, pool: dict, total: int, inc: list[dict], out: list[dict]) -> None:
        key = pool["key"]
        now = time.strftime("%Y-%m-%d %H:%M:%S")
        with self._lock:
            self._meta[key] = {
                "key": key,
                "fs": pool["fs"],
                "label": pool["label"],
                "verified": bool(pool.get("verified", False)),
                "total": int(total),
            }
            self._rank[key] = {"in": inc, "out": out}
            self._ts = now
            self._ts_label = time.strftime("%H:%M:%S")
            self._error = ""

    def mark_unavailable(self, pool: dict, reason: str) -> None:
        with self._lock:
            key = pool["key"]
            if key in self._meta:
                return  # 曾成功过：瞬时失败保留旧数据，仅记日志
            entry = next((u for u in self._unavailable if u["key"] == key), None)
            if entry:
                entry["reason"] = reason
            else:
                self._unavailable.append(
                    {"key": key, "label": pool["label"], "reason": reason}
                )

    def mark_attempt(self, error: str = "") -> None:
        with self._lock:
            self._last_attempt = time.time()
            if error:
                self._error = error

    # -- 读 ----------------------------------------------------------------
    def get_snapshot(self) -> Optional[dict[str, Any]]:
        """组装对外 JSON 载荷（无任何成功数据时返回 None）。"""
        with self._lock:
            if not self._meta:
                return None
            cats: list[dict] = []
            rank: dict[str, dict] = {}
            for pool in FUND_POOLS:
                key = pool["key"]
                if key not in self._meta:
                    continue
                cats.append(self._meta[key])
                rank[key] = self._rank[key]
            return {
                "ts": self._ts,
                "ts_label": self._ts_label,
                "categories": cats,
                "unavailable": [dict(u) for u in self._unavailable],
                "rank": rank,
                "ok": True,
                "error": self._error,
            }

    def health(self) -> dict[str, Any]:
        with self._lock:
            return {
                "categories": [self._meta[k]["label"] for k in self._meta],
                "error": self._error,
                "age": round(time.time() - self._last_attempt, 1) if self._last_attempt else -1.0,
            }


fund_store = FundRankStore()


def get_snapshot() -> Optional[dict[str, Any]]:
    """读取最近一次基金资金排行快照（API / WS 共用入口）。"""
    return fund_store.get_snapshot()


def health() -> dict[str, Any]:
    return fund_store.health()


# --------------------------------------------------------------------------- #
# 后台刷新线程
# --------------------------------------------------------------------------- #

class FundRankWorker(threading.Thread):
    """ETF/基金资金排行后台采集线程。

    - 周期 = ``config.FUND_REFRESH_INTERVAL``（默认 20s）；
    - 每轮顺序拉取各基金池的 净流入/净流出 TOP（请求间由客户端限速自然排队）；
    - 任一步失败只降级该池，绝不影响其余池与 TDX 主链路。
    """

    def __init__(self) -> None:
        super().__init__(name="capital-fund-rank", daemon=True)
        self._stop_evt = threading.Event()

    def stop(self) -> None:
        self._stop_evt.set()

    def run(self) -> None:
        logger.info("ETF/基金资金排行线程启动，interval=%ss", config.FUND_REFRESH_INTERVAL)
        while not self._stop_evt.is_set():
            try:
                self._collect_once()
            except Exception as exc:  # noqa: BLE001
                logger.warning("基金资金排行采集异常（已忽略）: %s", exc)
                fund_store.mark_attempt(f"{type(exc).__name__}: {exc}")
            self._stop_evt.wait(timeout=config.FUND_REFRESH_INTERVAL)
        logger.info("ETF/基金资金排行线程已停止")

    @staticmethod
    def _collect_once() -> None:
        top = config.FUND_TOP_N
        any_ok = False
        for pool in FUND_POOLS:
            try:
                result = asyncio.run(_fetch_pool(pool, top))
            except Exception as exc:  # noqa: BLE001
                logger.warning("基金池[%s]采集失败: %s", pool["key"], exc)
                fund_store.mark_unavailable(pool, f"{type(exc).__name__}")
                continue
            if result is None:
                logger.info("基金池[%s]无可用数据（上游限流或编码失效）", pool["key"])
                fund_store.mark_unavailable(pool, "上游无数据或限流")
                continue
            total, inc, out = result
            fund_store.update_pool(pool, total, inc, out)
            any_ok = True
            logger.info(
                "基金池[%s %s] 净流入%d/净流出%d",
                pool["label"], pool["fs"], len(inc), len(out),
            )
        fund_store.mark_attempt("" if any_ok else "全部基金池不可用")
        if not any_ok:
            logger.warning("本轮基金资金排行全部不可用（东财数据源不可达），保留旧快照")
