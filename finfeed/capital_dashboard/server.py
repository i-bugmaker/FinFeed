# -*- coding: utf-8 -*-
"""全市场资金流与板块轮动监控大屏 —— FastAPI 服务入口。

启动方式：
    python -m finfeed.capital_dashboard.server
    # 或
    uvicorn finfeed.capital_dashboard.server:app --host 0.0.0.0 --port 8090

浏览器访问 http://localhost:8090 查看大屏。
"""

from __future__ import annotations

import logging
import threading
from contextlib import asynccontextmanager
from dataclasses import asdict
from pathlib import Path
from typing import Any, Optional

from fastapi import APIRouter, FastAPI, HTTPException, Query
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from . import config, tdx
from .collector import fetch_stock_detail
from .rotation import STATUS_LABEL
from .snapshot import RefreshWorker, SnapshotStore

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
)
logger = logging.getLogger("finfeed.capital_dashboard")

_WEB_DIR = Path(__file__).resolve().parent / "web"

# 进程级单例
store = SnapshotStore()
worker: Optional[RefreshWorker] = None
_worker_lock = threading.Lock()


# --------------------------------------------------------------------------- #
# 刷新线程生命周期（幂等，供独立运行与主应用挂载共用）
# --------------------------------------------------------------------------- #

def start_refresh_worker() -> None:
    """启动后台刷新线程（幂等：已在运行则跳过）。"""
    global worker
    with _worker_lock:
        if worker is not None and worker.is_alive():
            return
        worker = RefreshWorker(store)
        worker.start()
        logger.info("资金流大屏后台刷新线程已启动 interval=%ss", config.REFRESH_INTERVAL)


def stop_refresh_worker() -> None:
    """停止后台刷新线程并断开 TDX 连接（幂等）。"""
    global worker
    with _worker_lock:
        if worker is not None:
            worker.stop()
            worker.join(timeout=3)
            worker = None
        tdx.close()
        logger.info("资金流大屏后台刷新线程已停止")


@asynccontextmanager
async def lifespan(_: FastAPI):
    logger.info("启动资本流监控大屏服务 (端口 %s)", config.PORT)
    start_refresh_worker()
    try:
        yield
    finally:
        stop_refresh_worker()


# --------------------------------------------------------------------------- #
# 路由工厂：独立运行使用前缀 /api，挂载到 FinFeed 主应用时使用 /api/capital
# --------------------------------------------------------------------------- #

def create_router(prefix: str = "/api") -> APIRouter:
    router = APIRouter(prefix=prefix, tags=["capital-dashboard"])


# --------------------------------------------------------------------------- #
# 工具函数
# --------------------------------------------------------------------------- #

def _now() -> dict[str, Any]:
    snap = store.get_snapshot()
    if snap is None:
        return {"ts": "", "ts_label": "--:--:--", "trading": False}
    return {
        "ts": snap.ts,
        "ts_label": snap.ts_label,
        "last_refresh": store.health()["last_refresh_ts"],
        "trading": bool(snap.stocks),
    }


def _stock_listing(stocks: list, limit: int) -> list[dict]:
    """个股 → JSON 字典（截断小数位，保留资金流字段）。"""
    out: list[dict] = []
    for s in stocks[:limit]:
        out.append(
            {
                "market": s.market,
                "code": s.code,
                "name": s.name,
                "price": s.price,
                "change_pct": s.change_pct,
                "amount": s.amount,
                "turnover": s.turnover,
                "main_net": s.main_net,
                "main_net_ratio": s.main_net_ratio,
                "main_net_5m": s.main_net_5m,
                "main_net_3d": s.main_net_3d,
                "main_net_5d": s.main_net_5d,
                "main_in": s.main_in,
                "main_out": s.main_out,
                "retail_in": s.retail_in,
                "retail_out": s.retail_out,
                "large_net_5d": s.large_net_5d,
                "mid_net_5d": s.mid_net_5d,
            }
        )
    return out


def _board_listing(boards: list, limit: int) -> list[dict]:
    out: list[dict] = []
    for b in boards[:limit]:
        out.append(
            {
                "code": b.code,
                "name": b.name,
                "board_type": b.board_type,
                "change_pct": b.change_pct,
                "amount": b.amount,
                "main_net": b.main_net,
                "up_count": b.up_count,
                "down_count": b.down_count,
                "member_count": b.member_count,
                "status": b.status,
                "status_label": STATUS_LABEL.get(b.status, ""),
                "rank_delta": b.rank_delta,
                "trend": b.trend,
            }
        )
    return out


# --------------------------------------------------------------------------- #
# API（可挂载路由）
# --------------------------------------------------------------------------- #

def create_router(prefix: str = "/api") -> APIRouter:
    """构建资金流大屏 API 路由。

    - 独立运行：``create_router("/api")`` → /api/overview 等
    - 挂载到 FinFeed 主应用：``create_router("/api/capital")`` → /api/capital/overview 等
    """
    router = APIRouter(prefix=prefix, tags=["capital-dashboard"])

    @router.get("/health")
    def health() -> dict[str, Any]:
        h = store.health()
        h.update(_now())
        return h

    @router.post("/refresh")
    def manual_refresh() -> dict[str, Any]:
        """手动触发一轮数据刷新。"""
        with _worker_lock:
            if worker is not None:
                worker.refresh_now()
                return {"ok": True, "msg": "已触发刷新"}
        raise HTTPException(status_code=503, detail="刷新线程未运行")

    @router.get("/overview")
    def overview() -> dict[str, Any]:
        """市场总览：指数、涨跌家数、成交额、主力资金流合计。"""
        snap = store.get_snapshot()
        if snap is None:
            raise HTTPException(status_code=503, detail="数据未就绪，请稍后重试")
        return {
            **_now(),
            "indices": [asdict(i) for i in snap.indices],
            "breadth": asdict(snap.breadth),
            "stats": asdict(snap.stats),
            "unusual_count": len(snap.unusual),
        }

    @router.get("/ranking/stocks")
    def stock_ranking(
        direction: str = Query("in", pattern="^(in|out)$"),
        limit: int = Query(config.STOCK_TOP_N, ge=1, le=100),
    ) -> dict[str, Any]:
        """个股资金流榜单。direction=in 净流入榜 / out 净流出榜。"""
        snap = store.get_snapshot()
        if snap is None:
            raise HTTPException(status_code=503, detail="数据未就绪")
        stocks = sorted(
            snap.stocks, key=lambda s: s.main_net, reverse=(direction == "in")
        )
        return {
            "direction": direction,
            "limit": limit,
            "total": len(snap.stocks),
            "items": _stock_listing(stocks, limit),
        }

    @router.get("/ranking/boards")
    def board_ranking(
        board_type: str = Query("hy", pattern="^(hy|gn)$"),
        sort: str = Query("main_net", pattern="^(main_net|change|amount)$"),
        limit: int = Query(config.BOARD_TOP_N, ge=1, le=100),
    ) -> dict[str, Any]:
        """板块资金流榜单。board_type=hy 行业 / gn 概念。"""
        snap = store.get_snapshot()
        if snap is None:
            raise HTTPException(status_code=503, detail="数据未就绪")
        bt = "HY" if board_type == "hy" else "GN"
        boards = [b for b in snap.boards if b.board_type == bt]
        key = {"main_net": lambda b: b.main_net, "change": lambda b: b.change_pct,
               "amount": lambda b: b.amount}[sort]
        boards = sorted(boards, key=key, reverse=True)
        return {"board_type": bt, "sort": sort, "limit": limit,
                "total": len(boards), "items": _board_listing(boards, limit)}

    @router.get("/rotation")
    def rotation() -> dict[str, Any]:
        """板块轮动分析：资金状态、切换信号、热力图、趋势序列。"""
        rep = store.get_rotation()
        if rep is None:
            raise HTTPException(status_code=503, detail="轮动分析未就绪")
        return asdict(rep)

    @router.get("/unusual")
    def unusual() -> dict[str, Any]:
        """市场异动（涨停/跌停/异动拉升等）。"""
        snap = store.get_snapshot()
        if snap is None:
            raise HTTPException(status_code=503, detail="数据未就绪")
        return {"items": [asdict(u) for u in snap.unusual]}

    @router.get("/stock/{code}")
    def stock_detail(code: str) -> dict[str, Any]:
        """单只个股资金流详情（实时查询 0x1218 接口）。"""
        snap = store.get_snapshot()
        market = 0
        name = code
        if snap is not None:
            for s in snap.stocks:
                if s.code == code:
                    market = s.market
                    name = s.name
                    break
        detail = fetch_stock_detail(market, code)
        if not detail:
            raise HTTPException(status_code=404, detail=f"未获取到 {code} 资金流数据")
        return {"code": code, "name": name, **detail}

    return router


# 独立运行模式的应用对象（也可作为 FastAPI 子应用被挂载）
app = FastAPI(
    title="全市场资金流与板块轮动监控大屏",
    version="1.0.0",
    description="基于 easy-tdx (通达信 MAC 协议) 的全市场资金流与板块轮动实时监控",
    lifespan=lifespan,
)
app.include_router(create_router("/api"))


@app.get("/")
def index() -> FileResponse:
    """大屏首页（独立运行模式）。"""
    return FileResponse(_WEB_DIR / "index.html")


# 静态资源（大屏单文件，无额外资源）
app.mount("/web", StaticFiles(directory=str(_WEB_DIR)), name="web")


def main() -> None:
    import uvicorn

    uvicorn.run(app, host=config.HOST, port=config.PORT, log_level="info")


if __name__ == "__main__":
    main()
