# -*- coding: utf-8 -*-
"""板块分时 —— FastAPI 服务入口。

提供板块列表 / 分时图 / 订阅管理 / 个股池搜索等 API，并以独立后台线程
周期刷新行情写入内存仓库（对齐需求文档「后台自动刷新与时效控制」）。

挂载到 FinFeed 主应用时使用前缀 ``/api/sector-minute``。
"""

from __future__ import annotations

import logging
import threading
import time
from datetime import date, datetime
from typing import Any, Optional

from fastapi import APIRouter, Body, HTTPException, Query

from . import config
from .collector import INDEX_LIST, fetch_tick_chart
from .store import RefreshWorker, SectorStore

logger = logging.getLogger("finfeed.sector_minute")

# 进程级单例
store = SectorStore()
worker: Optional[RefreshWorker] = None
_worker_lock = threading.Lock()


# --------------------------------------------------------------------------- #
# 刷新线程生命周期（幂等，供主应用挂载共用）
# --------------------------------------------------------------------------- #

def start_refresh_worker() -> None:
    """启动后台刷新线程（幂等：已在运行则跳过）。"""
    global worker
    with _worker_lock:
        if worker is not None and worker.is_alive():
            return
        worker = RefreshWorker(store)
        worker.start()
        logger.info("板块分时后台刷新线程已启动 interval=%ss", config.REFRESH_INTERVAL)


def stop_refresh_worker() -> None:
    """停止后台刷新线程（幂等）。"""
    global worker
    with _worker_lock:
        if worker is not None:
            worker.stop()
            worker.join(timeout=3)
            worker = None
            logger.info("板块分时后台刷新线程已停止")


# --------------------------------------------------------------------------- #
# 序列化辅助
# --------------------------------------------------------------------------- #

def _chart_dict(chart) -> dict[str, Any]:
    """TickChart → JSON 字典（points 直接透传，前端折线图使用）。"""
    return {
        "kind": chart.kind,
        "market": chart.market,
        "code": chart.code,
        "name": chart.name,
        "board_type": chart.board_type,
        "trade_date": chart.trade_date,
        "pre_close": chart.pre_close,
        "open": chart.open,
        "high": chart.high,
        "low": chart.low,
        "close": chart.close,
        "change_pct": chart.change_pct,
        "change_amt": chart.change_amt,
        "points": [
            {"time": p.time, "price": p.price, "avg": p.avg, "vol": p.vol}
            for p in chart.points
        ],
        "ts": chart.ts,
    }


def _immediate_fetch_new(subs) -> None:
    """对新增且尚无缓存分时的标的，立即抓取首帧并写入仓库。

    用于勾选后快速出图：这些标的无需排在后台整轮串行采集队列末尾等待，
    独立线程立即采集；已缓存标的仍由 RefreshWorker 按周期刷新。
    """
    for i, s in enumerate(subs):
        chart = fetch_tick_chart(s.market, s.code)
        store.update_tick(s, chart)
        if i < len(subs) - 1:
            time.sleep(config.SLEEP_BETWEEN_REQUESTS)


# --------------------------------------------------------------------------- #
# 历史日期分时（日期切换组件）
# --------------------------------------------------------------------------- #

def _today_str() -> str:
    """服务器本地自然日（YYYY-MM-DD），作为「今天」的判定基准。"""
    return datetime.now().strftime("%Y-%m-%d")


def _parse_date(date_str: str) -> Optional[date]:
    """解析 YYYY-MM-DD；非法返回 None。"""
    try:
        return date.fromisoformat(date_str.strip())
    except (TypeError, ValueError):
        return None


def _fetch_hist_date(date_str: str) -> None:
    """后台线程：按当前订阅整批抓取某历史日期的分时并写入历史缓存。

    用户在日期组件中切换历史日期时由 ``/charts?date=`` 触发；
    完成后前端轮询 ``/charts?date=`` 即可取到全部数据。
    """
    try:
        d = _parse_date(date_str)
        if d is None:
            return
        subs = store.subscriptions()
        for i, sub in enumerate(subs):
            chart = fetch_tick_chart(sub.market, sub.code, query_date=d)
            store.hist_set(date_str, sub, chart)
            if i < len(subs) - 1:
                time.sleep(config.HIST_FETCH_SLEEP)
        logger.info("历史分时抓取完成 date=%s 标的=%d", date_str, len(subs))
    except Exception as exc:  # noqa: BLE001
        logger.warning("历史分时抓取失败[%s]: %s", date_str, exc)
    finally:
        store.hist_fetch_end(date_str)


def _ensure_hist_fetch(date_str: str) -> None:
    """若该历史日期尚未抓全，则启动后台线程补齐（并发去重，幂等）。"""
    if store.hist_all_ready(date_str):
        return
    if not store.hist_fetch_start(date_str):
        return  # 该日期已有抓取线程在跑
    threading.Thread(
        target=_fetch_hist_date, args=(date_str,), daemon=True
    ).start()


# --------------------------------------------------------------------------- #
# 路由工厂：独立运行使用前缀 /api，挂载到 FinFeed 主应用时使用 /api/sector-minute
# --------------------------------------------------------------------------- #

def create_router(prefix: str = "/api/sector-minute") -> APIRouter:
    router = APIRouter(prefix=prefix, tags=["sector-minute"])

    @router.get("/health")
    def health() -> dict[str, Any]:
        """模块运行状态：最近刷新时间 / 订阅数 / 分时缓存数 / 错误信息。"""
        h = store.health()
        h["board_types"] = {bt: len(store.get_board_list(bt)) for bt in ("hy", "hy2", "gn", "fg", "dq")}
        return h

    @router.post("/refresh")
    def manual_refresh() -> dict[str, Any]:
        """手动触发一轮行情刷新。

        仅唤醒后台线程异步抓取（不阻塞请求）；前端通过轮询取数。
        """
        with _worker_lock:
            if worker is None or not worker.is_alive():
                raise HTTPException(status_code=503, detail="刷新线程未运行")
            worker.refresh_now()
            return {"ok": True, "msg": "已触发刷新"}

    @router.get("/boards")
    def boards(board_type: str = Query("hy", pattern="^(hy|hy2|gn|fg|dq)$")) -> dict[str, Any]:
        """指定类型板块列表（含实时涨跌幅）。"""
        items = store.get_board_list(board_type)
        if not items:
            # 冷启动无缓存时立即触网补一次
            from .collector import fetch_board_list
            items = fetch_board_list(board_type)
            if items:
                store.set_board_list(board_type, items)
        return {
            "board_type": board_type,
            "total": len(items),
            "items": [
                {
                    "market": b.market,
                    "code": b.code,
                    "name": b.name,
                    "board_type": b.board_type,
                    "price": b.price,
                    "pre_close": b.pre_close,
                    "rise_pct": b.rise_pct,
                }
                for b in items
            ],
        }

    @router.get("/subscriptions")
    def get_subscriptions() -> dict[str, Any]:
        """当前对比标的列表。"""
        return {"items": [{"kind": s.kind, "market": s.market, "code": s.code,
                           "name": s.name, "board_type": s.board_type} for s in store.subscriptions()]}

    @router.post("/subscriptions")
    def set_subscriptions(payload: dict = Body(default={})) -> dict[str, Any]:
        """整体替换对比标的列表（前端多选后一次性提交）。

        仅登记订阅并唤醒后台线程异步抓取（不阻塞请求）；
        后台线程按周期自动刷新所有订阅的分时数据，前端轮询取数。

        优化：对「新勾选且尚无缓存分时」的标的，立即在独立线程抓取首帧，
        使其无需排在整轮串行采集队列末尾，勾选后能快速出图。
        """
        items = payload.get("items", [])
        subs = store.set_subscriptions(items)

        # 新勾选且尚无缓存分时的标的 → 独立线程立即首抓，尽快出图
        new_subs = [s for s in subs if not store.has_tick(s)]
        if new_subs:
            threading.Thread(
                target=_immediate_fetch_new, args=(new_subs,), daemon=True
            ).start()

        with _worker_lock:
            if worker is not None and worker.is_alive():
                worker.refresh_now()
        return {"ok": True, "count": len(subs),
                "items": [{"kind": s.kind, "market": s.market, "code": s.code,
                           "name": s.name, "board_type": s.board_type} for s in subs]}

    @router.get("/charts")
    def charts(date: str = Query("", max_length=10)) -> dict[str, Any]:
        """当前订阅标的分时图集合（涨跌幅已按昨收归一化）。

        支持 ``date=YYYY-MM-DD`` 查询历史交易日分时：
        - 空日期或等于「今天」：走实时缓存（RefreshWorker 持续刷新）；
        - 历史日期：走按日期的静态快照缓存；未抓全时自动启动后台线程补齐，
          返回当前已缓存部分（``done`` 标记是否已抓全），前端轮询本接口取全。
        """
        date_str = date.strip()
        today = _today_str()
        # 空日期 / 今天 / 非法日期 / 未来日期 → 一律走实时路径（防御旧前端或脏参数）
        if not date_str or date_str == today or _parse_date(date_str) is None or date_str > today:
            ticks = store.get_ticks()
            return {
                "date": today,
                "is_hist": False,
                "done": True,
                "ts": store.health().get("last_refresh_ts", 0),
                "total": len(ticks),
                "items": [_chart_dict(t) for t in ticks],
            }

        # 历史日期：未抓全 → 后台线程补齐；返回当前快照 + 完成标记
        _ensure_hist_fetch(date_str)
        ticks = store.hist_ticks(date_str)
        return {
            "date": date_str,
            "is_hist": True,
            "done": store.hist_all_ready(date_str),
            "has_data": store.hist_any_points(date_str),
            "ts": store.health().get("last_refresh_ts", 0),
            "total": len(ticks),
            "items": [_chart_dict(t) for t in ticks],
        }

    @router.get("/sparklines")
    def sparklines(codes: str = Query(""), lazy: int = Query(1), date: str = Query("", max_length=10)) -> dict[str, Any]:
        """列表项迷你分时简图：按 key 批量返回分时点序列。

        ``date=YYYY-MM-DD`` 时返回该历史交易日对应的分时形状（命中按日期的
        历史缓存，未命中且 ``lazy=1`` 时按需抓取一次并写回，供后续复用）；
        空日期则保持实时语义（今天）。返回未命中的 key 供前端决定是否继续处理。
        """
        from .models import Subscription

        date_str = date.strip()
        hist = bool(date_str) and date_str != _today_str()
        keys = [k.strip() for k in codes.split(",") if k.strip()]

        def to_sub(key: str) -> Optional[Subscription]:
            parts = key.split(":")
            if parts[0] == "board" and len(parts) >= 4:
                try:
                    return Subscription(kind="board", market=int(parts[2]), code=parts[3], board_type=parts[1])
                except ValueError:
                    return None
            if parts[0] in ("stock", "index") and len(parts) >= 3:
                try:
                    return Subscription(kind=parts[0], market=int(parts[1]), code=parts[2])
                except ValueError:
                    return None
            return None

        def snapshot(ch) -> dict[str, Any]:
            return {
                "kind": ch.kind, "market": ch.market, "code": ch.code,
                "name": ch.name, "pre_close": ch.pre_close, "change_pct": ch.change_pct,
                "points": [{"price": p.price, "avg": p.avg, "vol": p.vol} for p in ch.points],
            }

        out: dict[str, Any] = {}
        missing: list[str] = []
        for k in keys:
            ch = (store.hist_get(date_str, k) if hist else store.get_tick(k))
            if ch is not None and ch.points:
                out[k] = snapshot(ch)
            elif not (hist and store.hist_has(date_str, k)):
                missing.append(k)

        if lazy and missing:
            qd = _parse_date(date_str)
            for k in missing[: config.MAX_LAZY_SPARKS]:
                sub = to_sub(k)
                if sub is None:
                    continue
                try:
                    chart = fetch_tick_chart(sub.market, sub.code, query_date=qd)
                except Exception:  # noqa: BLE001
                    chart = None
                if hist:
                    store.hist_set(date_str, sub, chart)
                else:
                    store.update_tick(sub, chart)
                if chart is not None and chart.points:
                    out[k] = snapshot(chart)

        return {"items": out, "missing": [m for m in missing if m not in out]}

    @router.get("/indices")
    def indices() -> dict[str, Any]:
        """常见指数池（宽基/风格，含实时涨跌幅，缓存命中时提供）。"""
        items: list[dict[str, Any]] = []
        for it in INDEX_LIST:
            ch = store.get_tick(f"index:{it['market']}:{it['code']}")
            items.append({
                "market": it["market"],
                "code": it["code"],
                "name": it["name"],
                "price": round(ch.close, 2) if ch is not None else None,
                "change_pct": ch.change_pct if ch is not None else None,
                "cached": ch is not None,
            })
        return {"total": len(items), "items": items}

    @router.get("/stocks")
    def stocks(kw: str = Query("", max_length=32)) -> dict[str, Any]:
        """个股池搜索（按代码/名称模糊匹配，用于个股对比添加）。"""
        from .collector import stock_market

        with _worker_lock:
            if worker is not None and worker.is_alive():
                worker.ensure_stock_pool()
        pool = store.get_stock_pool()
        kw = kw.strip()
        if kw:
            pool = [s for s in pool if kw in s.code or kw in s.name]
        return {
            "total": len(pool),
            "items": [
                {"market": s.market, "code": s.code, "name": s.name,
                 "price": s.price, "change_pct": s.change_pct}
                for s in pool
            ],
        }

    return router


app = None  # 模块仅提供路由工厂，不建立独立 FastAPI 实例
