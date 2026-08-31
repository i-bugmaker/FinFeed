#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""FinFeed FastAPI 应用（方案 D 新后端）。

设计要点
--------
1. **复用而非重写**：业务函数与 SSE 广播通道复用 ``finfeed.ui.web.shared``
   共享运行时（SSE 通道 / 缓存 / Web 状态），仅替换 HTTP 传输层为 FastAPI。
2. **SSE 桥接**：FastAPI 的 ``StreamingResponse`` 通过 threading.Queue 注册进
   ``shared._sse_clients``，复用同一条广播通道；monitor 触发的 ``broadcast_new_news``
   会自动送达本端 SSE 客户端，双水位线/幂等/降级语义不变。
3. **导出 / 健康检查 / 熔断状态**：与旧实现逐字段对齐。
"""

import asyncio
import csv
import io
import json
import logging
import os
import time
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Dict, List, Optional

import uvicorn
from fastapi import FastAPI, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from starlette.middleware.gzip import GZipMiddleware

from finfeed.application.market_service import MarketService, first_query_value
from finfeed.config.settings import DEFAULT_WEB_PORT, get_display_name
from finfeed.config.sources import get_enabled_sources
from finfeed.core.health import get_health_monitor
from finfeed.ecal import fetcher as calendar_fetcher

# easy-tdx 盘面复盘仪表盘快捷数据接口（同步 + 缓存）
from finfeed.integrations.easytdx.dashboard import router as easytdx_dashboard_router

# easy-tdx 集成模块（FinFeed × 通达信行情）：分组导航 / 参数表单 / 任务执行与进度
from finfeed.integrations.easytdx.router import router as easytdx_router

# 智能选股模块（五维加权评分）
from finfeed.integrations.screener.router import router as screener_router

# 股票监控模块（导入管理 / 舆情聚合 / AI 分析）
from finfeed.stock_monitor import service as stock_monitor_service
from finfeed.stock_monitor.router import router as stock_monitor_router

# 告警推送模块（webhook 渠道 / 主题订阅 / 推送日志 / 情感校准）
from finfeed.alerts.router import router as alerts_router
from finfeed.market import alerting as market_alerting
from finfeed.market import scheduler as market_scheduler
from finfeed.market import ws_feed as market_ws
from finfeed.storage.database import (
    db_get_all_for_export,
    db_get_statistics,
    db_query_news,
    get_db,
)

# ----------------------------------------------------------------------
# 共享运行时：SSE 广播通道 / Web 状态 / 时间解析（由 finfeed.ui.web.shared 收敛）
# ----------------------------------------------------------------------
from finfeed.ui.web.shared import _ts_from_date_str, _web_state, _web_state_lock
from finfeed.ui.web_fastapi.core.errors import install_exception_handlers
from finfeed.ui.web_fastapi.routers.calendar import create_router as create_calendar_router
from finfeed.ui.web_fastapi.routers.llm import create_router as create_llm_router
from finfeed.ui.web_fastapi.routers.market import create_router as create_market_router
from finfeed.ui.web_fastapi.routers.news import create_router as create_news_router
from finfeed.ui.web_fastapi.routers.realtime import (
    LegacyNewsEventPublisher,
    poll_events,
)
from finfeed.ui.web_fastapi.routers.realtime import (
    create_router as create_realtime_router,
)
from finfeed.ui.web_fastapi.routers.system import create_router as create_system_router
from finfeed.utils.time_utils import bj_str_from_ts, now_bj

logger = logging.getLogger("news_monitor")



app = FastAPI(
    title="FinFeed API",
    version="2.1.0",
    description="FinFeed 实时财经新闻监控 — FastAPI 后端（双轨并行，兼容旧 SSE 通道）",
)
install_exception_handlers(app)

# Transport adapters receive their dependencies explicitly. The temporary
# legacy publisher keeps SSE behaviour intact while isolating its globals here.
news_events = LegacyNewsEventPublisher()
app.include_router(create_realtime_router(news_events, market_ws.handle_connection))
app.include_router(create_system_router("2.1.0"))
app.include_router(create_llm_router())

# LLM 任务事件桥接：领域层 AnalysisService 通过注入的回调发布 stage/delta/done，
# SSE 订阅注册表位于 llm 路由模块（领域包不感知 UI，依赖方向保持向内）。
from finfeed.llm.service import get_service as _get_llm_service  # noqa: E402
from finfeed.ui.web_fastapi.routers.llm import (  # noqa: E402
    publish_llm_task_event as _publish_llm_task_event,
)

_get_llm_service().set_event_publisher(_publish_llm_task_event)

app.include_router(create_calendar_router())

# 注册 easy-tdx 集成路由（/api/easytdx/*）
app.include_router(easytdx_router)

# 注册 easy-tdx 盘面复盘仪表盘路由（/api/easytdx/dashboard/*）
app.include_router(easytdx_dashboard_router)

# 注册智能选股路由（/api/screener/*）
app.include_router(screener_router)

# 注册股票监控路由（/api/stock-monitor/*）
app.include_router(stock_monitor_router)
app.include_router(alerts_router)

# ----------------------------------------------------------------------
# 全市场资金流与板块轮动监控大屏集成（可选，依赖 easy-tdx）
#  - API 前缀：/api/capital/*
#  - 大屏页面：/capital
#  - 独立运行：python -m finfeed.capital_dashboard（端口 8090）
# 依赖缺失或导入失败时优雅降级，不影响 FinFeed 主服务。
# ----------------------------------------------------------------------
try:
    from finfeed.capital_dashboard import config as _cap_config
    from finfeed.capital_dashboard.server import (
        create_router as _cap_create_router,
    )
    from finfeed.capital_dashboard.server import (
        start_refresh_worker as _cap_start_worker,
    )
    from finfeed.capital_dashboard.server import (
        stop_refresh_worker as _cap_stop_worker,
    )

    app.include_router(_cap_create_router("/api/capital"))

    @app.get("/capital", include_in_schema=False)
    async def capital_dashboard_page():
        """资金流大屏页面（注入 /api/capital 前缀供前端消费）。"""
        idx = Path(_cap_config.__file__).resolve().parent / "web" / "index.html"
        html = idx.read_text(encoding="utf-8")
        inject = '<script>window.CAPITAL_API_BASE="/api/capital";</script>'
        html = html.replace("</head>", inject + "</head>", 1)
        return HTMLResponse(html)

    logger.info("已集成全市场资金流大屏模块（/capital, /api/capital/*）")
except Exception as _cap_exc:  # noqa: BLE001
    logger.warning("全市场资金流大屏模块未加载（可忽略；安装依赖后重启生效）: %s", _cap_exc)

# ----------------------------------------------------------------------
# 板块分时模块（web 左侧导航 独立页 /sector-minute）
#  - API 前缀：/api/sector-minute/*
#  - 独立页面：/sector-minute（浅色简洁专业风）
#  - 后台刷新线程随主应用启动/停止
# ----------------------------------------------------------------------
try:
    from finfeed.sector_minute import config as _sm_config
    from finfeed.sector_minute.server import (
        create_router as _sm_create_router,
    )
    from finfeed.sector_minute.server import (
        start_refresh_worker as _sm_start_worker,
    )
    from finfeed.sector_minute.server import (
        stop_refresh_worker as _sm_stop_worker,
    )

    app.include_router(_sm_create_router("/api/sector-minute"))

    @app.get("/sector-minute", include_in_schema=False)
    async def sector_minute_page():
        """板块分时独立页面（注入 /api/sector-minute 前缀供前端消费）。"""
        idx = Path(_sm_config.__file__).resolve().parent / "web" / "index.html"
        html = idx.read_text(encoding="utf-8")
        inject = '<script>window.SECTOR_MINUTE_API_BASE="/api/sector-minute";</script>'
        html = html.replace("</head>", inject + "</head>", 1)
        return HTMLResponse(html)

    logger.info("已集成板块分时独立页（/sector-minute, /api/sector-minute/*）")
except Exception as _sm_exc:  # noqa: BLE001
    _sm_start_worker = _sm_stop_worker = None
    logger.warning("板块分时模块未加载（可忽略；安装依赖后重启生效）: %s", _sm_exc)

# ----------------------------------------------------------------------
# 同花顺 F10 个股资料模块（f10-Web 移植）
#  - API 前缀：/api/f10/*
#  - 独立页面：/f10（服务端静态托管模块自带的手写前端）
#  - 依赖缺失（fastapi/bs4/requests）时优雅降级，不影响 FinFeed 主服务。
#  注意：/f10 的 StaticFiles 挂载必须先于底部根路由 "/" 的 SPA 挂载，
#  否则会被 catch-all 吞掉；因此本模块的静态托管也在此统一完成。
# ----------------------------------------------------------------------
try:
    from fastapi.staticfiles import StaticFiles as _f10StaticFiles

    from finfeed.f10 import WEB_DIR as _f10_WEB_DIR
    from finfeed.f10.server import create_router as _f10_create_router

    app.include_router(_f10_create_router("/api/f10"))

    # LazyImporter 下引入 redirect（避免与主流依赖耦合）
    from fastapi.responses import RedirectResponse as _f10Redirect

    @app.get("/f10", include_in_schema=False)
    async def _f10_redirect():
        """StaticFiles 挂载不带尾部斜杠时被 SPA catch-all 截断，故补一条斜杠跳转。"""
        return _f10Redirect("/f10/")

    _f10_DIST = Path(_f10_WEB_DIR)
    if _f10_DIST.exists():
        app.mount("/f10", _f10StaticFiles(directory=str(_f10_DIST), html=True),
                  name="f10")
        logger.info(
            "已集成同花顺 F10 个股资料模块（/f10, /api/f10/*）")
except Exception as _f10_exc:  # noqa: BLE001
    logger.warning("同花顺 F10 模块未加载（可忽略；安装依赖后重启生效）: %s", _f10_exc)

app.add_middleware(GZipMiddleware, minimum_size=500)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def no_cache_static(request: Request, call_next):
    """禁用前端资源（HTML/JS/CSS）的浏览器缓存，避免更新后加载旧文件。"""
    response = await call_next(request)
    path = request.url.path
    if path.endswith((".html", ".js", ".css", ".mjs")) or path in ("/", "/index.html"):
        response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
        response.headers["Pragma"] = "no-cache"
        response.headers["Expires"] = "0"
    return response


# ----------------------------------------------------------------------
# 通用工具
# ----------------------------------------------------------------------
def parse_query_params(q: Dict[str, List[str]]) -> dict:
    """与旧 server._parse_query_params 逐字段对齐。"""
    def gv(key, default):
        v = q.get(key)
        return v[0] if v else default

    if "offset" in q or "limit" in q:
        offset = int(gv("offset", "0"))
        page_size = int(gv("limit", "50"))
        page_size = min(max(page_size, 10), 200)
        page = (offset // page_size) + 1
    else:
        page = int(gv("page", "1"))
        page_size = int(gv("page_size", "50"))
        page_size = min(max(page_size, 10), 200)
        offset = (page - 1) * page_size

    source = gv("source", "all")
    keyword = gv("keyword", "") or gv("q", "")
    sentiment = gv("sentiment", "all")
    stock = gv("stock", "")
    start_date = gv("start", "")
    end_date = gv("end", "")
    fav_only = gv("favorites", "0") == "1"
    min_importance = gv("min_importance", "0")

    start_ts = _ts_from_date_str(start_date, end_of_day=False) if start_date else None
    end_ts = _ts_from_date_str(end_date, end_of_day=True) if end_date else None

    return {
        "page": page,
        "page_size": page_size,
        "offset": offset,
        "source": source if source != "all" else None,
        "keyword": keyword if keyword else None,
        "sentiment": sentiment if sentiment != "all" else None,
        "stock": stock if stock else None,
        "start_ts": start_ts,
        "end_ts": end_ts,
        "is_favorite": True if fav_only else None,
        "min_importance": float(min_importance) if min_importance else None,
    }


def json_resp(data, status: int = 200, max_age: int = 0):
    headers = {"Cache-Control": f"private, max-age={max_age}" if max_age > 0 else "no-cache"}
    return JSONResponse(content=data, status_code=status, headers=headers)


def qdict(request: Request) -> Dict[str, List[str]]:
    """把 FastAPI 的 query_params 规整为 {key: [values]} 形式，便于复用旧解析逻辑。"""
    out: Dict[str, List[str]] = {}
    for k, v in request.query_params.multi_items():
        out.setdefault(k, []).append(v)
    return out


# News routes depend on the shared query normalization helpers above.
app.include_router(create_news_router(parse_query_params, qdict))


# ----------------------------------------------------------------------
# 健康检查 / 统计
# ----------------------------------------------------------------------
@app.get("/api/health")
def api_health():
    health_monitor = get_health_monitor()
    all_health = health_monitor.get_all_health()
    health_data = {}
    for name, h in all_health.items():
        health_data[name] = {
            "total_requests": h.total_requests,
            "success_count": h.success_count,
            "failure_count": h.failure_count,
            "consecutive_failures": h.consecutive_failures,
            "success_rate": round(h.success_rate * 100, 2),
            "avg_latency": round(h.avg_latency * 1000, 1),
            "is_circuit_open": h.is_circuit_open,
            "last_error": h.last_error,
        }
    stats = db_get_statistics()
    return {
        "status": "ok",
        "server_ts": time.time(),
        "total_news": stats["total_news"],
        "total_24h": stats["total_24h"],
        "favorite_count": stats["favorite_count"],
        "unread_count": stats["unread_count"],
        "sources": health_data,
    }


@app.get("/api/stats")
def api_stats():
    stats = db_get_statistics()
    with _web_state_lock:
        stats["cycle"] = _web_state.get("cycle", 0)
        stats["status"] = _web_state.get("status", "运行中")
        stats["new_count"] = _web_state.get("new_count", 0)

    source_list = []
    try:
        health_monitor = get_health_monitor()
        all_health = health_monitor.get_all_health()
        enabled_sources = get_enabled_sources()
        now_ts = int(time.time())
        day_ago = now_ts - 86400
        with get_db() as c:
            for s in enabled_sources:
                raw_name = s.name
                display_name = get_display_name(raw_name)
                h = all_health.get(raw_name)
                c.execute(
                    "SELECT COUNT(*) as today_count FROM news WHERE source = ? AND publish_ts >= ?",
                    (display_name, day_ago),
                )
                row = c.fetchone()
                today_count = row["today_count"] if row else 0
                c.execute(
                    "SELECT publish_ts FROM news WHERE source = ? ORDER BY publish_ts DESC LIMIT 1",
                    (display_name,),
                )
                r2 = c.fetchone()
                last_news_ts = r2["publish_ts"] if r2 else 0
                status = "normal"
                if h:
                    if h.is_circuit_open:
                        status = "fused"
                    elif h.consecutive_failures >= 2:
                        status = "warning"
                    elif h.total_requests > 0 and h.success_rate < 0.7:
                        status = "warning"
                    elif last_news_ts > 0 and (now_ts - last_news_ts) > 3600 * 6:
                        status = "idle"
                else:
                    if last_news_ts > 0 and (now_ts - last_news_ts) > 3600 * 12:
                        status = "idle"
                last_success_str = ""
                if h and h.last_success_ts > 0:
                    last_success_str = bj_str_from_ts(h.last_success_ts)
                elif last_news_ts > 0:
                    last_success_str = bj_str_from_ts(last_news_ts)
                last_error_str = h.last_error if h and h.last_error else ""
                success_rate = round(h.success_rate * 100, 1) if h and h.total_requests > 0 else (100.0 if last_news_ts > 0 else 0)
                avg_latency = round(h.avg_latency * 1000, 0) if h else 0
                source_list.append({
                    "name": display_name,
                    "status": status,
                    "success_rate": success_rate,
                    "avg_latency": avg_latency,
                    "today_count": today_count,
                    "last_update": last_success_str,
                    "last_error": last_error_str,
                    "consecutive_failures": h.consecutive_failures if h else 0,
                    "is_circuit_open": h.is_circuit_open if h else False,
                })
            # web-only 回退：monitor 未运行（_web_state 为 0）时，从 DB 派生真实指标
            if stats["cycle"] == 0:
                c.execute(
                    "SELECT COUNT(DISTINCT date(publish_ts, 'unixepoch', '+8 hours')) FROM news"
                )
                row = c.fetchone()
                stats["cycle"] = int(row[0]) if row and row[0] else 0
            if stats["new_count"] == 0:
                nb = now_bj()
                today_start = int(time.time()) - (
                    nb.hour * 3600 + nb.minute * 60 + nb.second
                )
                c.execute("SELECT COUNT(*) FROM news WHERE publish_ts >= ?", (today_start,))
                row = c.fetchone()
                stats["new_count"] = int(row[0]) if row and row[0] else 0
    except Exception as e:
        logger.error(f"获取数据源状态失败: {e}")
    stats["source_health"] = source_list
    return stats


# 离线告警阈值：连续 N 秒无任何数据源成功抓取，即判定系统处于离线/卡死状态。
# 可通过环境变量 FINFEED_OFFLINE_ALERT_SEC 覆盖（默认 15 分钟）。
OFFLINE_ALERT_SECONDS = int(os.environ.get("FINFEED_OFFLINE_ALERT_SEC", "900"))


@app.get("/api/monitor/status")
def api_monitor_status():
    """轻量全局运行态：最近一次成功抓取时间 + 离线告警判定。

    前端状态栏高频轮询使用，独立于 /api/stats 的重查询。
    last_success_ts 取自各源健康度记录中的最大「最近成功时间」，
    进程崩溃/卡死时该值冻结，offline_seconds 持续增大并触发告警。
    web-only（监控器未运行）模式下所有源 last_success_ts 为 0，
    此时 offline_seconds=-1 且不会误报。
    """
    health_monitor = get_health_monitor()
    all_health = health_monitor.get_all_health()
    now_ts = int(time.time())
    last_success_ts = 0
    ok_count = 0
    for h in all_health.values():
        if h.last_success_ts > last_success_ts:
            last_success_ts = h.last_success_ts
        if h.total_requests > 0 and h.consecutive_failures == 0 and not h.is_circuit_open:
            ok_count += 1
    offline_seconds = (now_ts - last_success_ts) if last_success_ts > 0 else -1
    offline_alert = offline_seconds >= OFFLINE_ALERT_SECONDS
    return {
        "server_ts": now_ts,
        "last_success_ts": last_success_ts,
        "last_success_str": bj_str_from_ts(last_success_ts) if last_success_ts > 0 else "",
        "offline_seconds": offline_seconds,
        "offline_alert": offline_alert,
        "alert_threshold": OFFLINE_ALERT_SECONDS,
        "source_total": len(all_health),
        "source_ok": ok_count,
    }


def api_export(
    format: str = Query("json"),
    start: Optional[str] = None,
    end: Optional[str] = None,
    favorites: int = Query(0),
    keyword: Optional[str] = None,
    source: Optional[str] = None,
    sentiment: Optional[str] = None,
):
    """导出新闻。携带任一筛选条件时走 db_query_news，保证导出结果与列表所见一致。"""
    fav_only = favorites == 1
    has_filters = bool(keyword) or (source and source != "all") or (sentiment and sentiment != "all")
    if fav_only or has_filters:
        news, _ = db_query_news(
            limit=10000,
            source=source if source and source != "all" else None,
            keyword=keyword or None,
            sentiment=sentiment if sentiment and sentiment != "all" else None,
            start_ts=_ts_from_date_str(start, end_of_day=False) if start else None,
            end_ts=_ts_from_date_str(end, end_of_day=True) if end else None,
            is_favorite=True if fav_only else None,
        )
    else:
        news = db_get_all_for_export(start, end)
    ts_str = now_bj().strftime("%Y%m%d_%H%M%S")

    if format == "csv":
        buf = io.StringIO()
        w = csv.writer(buf)
        w.writerow(["标题", "链接", "来源", "分类", "发布时间", "时间戳", "简介", "情绪", "重要性", "关键词", "关联股票", "已收藏"])
        for n in news:
            w.writerow([
                n.title, n.url, n.source, n.category, n.publish_time, n.publish_ts,
                n.intro, n.sentiment, n.importance,
                ",".join(n.keywords) if n.keywords else "",
                ",".join(n.stocks) if n.stocks else "",
                "是" if n.is_favorite else "否",
            ])
        data = buf.getvalue().encode("utf-8-sig")
        return Response(content=data, media_type="text/csv; charset=utf-8",
                        headers={"Content-Disposition": f'attachment; filename="finfeed_news_{ts_str}.csv"'})
    elif format in ("markdown", "md"):
        lines = ["# FinFeed 财经新闻导出", "", f"导出时间: {now_bj().strftime('%Y-%m-%d %H:%M:%S')}", f"共 {len(news)} 条新闻", ""]
        for n in news:
            time_str = n.publish_time or ""
            lines.append(f"### [{n.title}]({n.url})")
            lines.append(f"**来源**: {n.source} | **时间**: {time_str}")
            if n.intro:
                lines.append(f"> {n.intro}")
            lines.append("")
        content = "\n".join(lines).encode("utf-8")
        return Response(content=content, media_type="text/markdown; charset=utf-8",
                        headers={"Content-Disposition": f'attachment; filename="finfeed_news_{ts_str}.md"'})
    else:
        news_dicts = [n.to_dict() for n in news]
        data = json.dumps(news_dicts, ensure_ascii=False, indent=2).encode("utf-8")
        return Response(content=data, media_type="application/json; charset=utf-8",
                        headers={"Content-Disposition": f'attachment; filename="finfeed_news_{ts_str}.json"'})


# ----------------------------------------------------------------------
# 市场行情（业务用例已下沉至 finfeed.application.market_service.MarketService）
# ----------------------------------------------------------------------
market_service = MarketService()


async def api_market(rest: str, request: Request):
    """市场行情传输层薄壳：仅做参数规整与响应包装，业务全部委托应用层。"""
    q = qdict(request)
    date = first_query_value(q, "date") or now_bj().strftime("%Y-%m-%d")
    sub = rest.strip("/") or "sentiment"

    if sub == "action":
        return market_service.run_action(q)
    try:
        data = await market_service.dispatch(sub, q, date)
        return {"success": True, "data": data}
    except Exception as e:
        return json_resp({"success": False, "error": str(e)[:200]}, status=500)


app.include_router(create_market_router(api_market))



async def _startup(app: FastAPI) -> None:
    # 确保行情相关表（含涨停聚焦四模块）存在，支撑历史快照回看
    try:
        from finfeed.market import store as _mk_store
        _mk_store.ensure_market_tables()
    except Exception as e:  # noqa: BLE001
        logger.warning(f"行情数据表初始化失败（可忽略）: {e}")

    # 资金流大屏后台刷新线程（若模块已集成则启动；TDX 连接失败不阻断主服务）
    try:
        _cap_start_worker()
    except Exception as e:  # noqa: BLE001
        logger.warning(f"资金流大屏刷新线程启动失败（可忽略）: {e}")

    # 板块分时后台刷新线程（若模块已集成则启动；TDX 连接失败不阻断主服务）
    try:
        if _sm_start_worker is not None:
            _sm_start_worker()
    except Exception as e:  # noqa: BLE001
        logger.warning(f"板块分时刷新线程启动失败（可忽略）: {e}")

    # 股票监控外部舆情刷新线程（东财资讯/公告周期入库；失败不阻断主服务）
    try:
        stock_monitor_service.worker.start()
    except Exception as e:  # noqa: BLE001
        logger.warning(f"股票监控刷新线程启动失败（可忽略）: {e}")

    news_events.initialize()
    # 创建 tick 哨兵文件并置为当前时间，使 _sse_poll_loop 的 last_tick 基准有效；
    # 之后主进程每次抓取完成都会更新其 mtime 以「唤醒」本进程的即时推送。
    news_events.touch()
    try:
        calendar_fetcher.warmup()
    except Exception as e:
        logger.warning(f"日历连接池预热失败（可忽略）: {e}")
    # 启动 SSE 增量推送循环（tick 即时触发 + 定时兜底），修复子进程跨进程
    # 广播失效导致的 Web 端不实时更新。
    app.state.sse_poll_task = asyncio.create_task(poll_events(news_events))

    # 原文正文后台批量补齐（随查随补 + 周期扫描缺正文的记录；失败不阻断主服务）
    try:
        from finfeed.content_fetch import content_backfill_loop
        app.state.content_backfill_task = asyncio.create_task(content_backfill_loop())
    except Exception as e:  # noqa: BLE001
        logger.warning(f"正文后台补齐任务启动失败（可忽略）: {e}")

    # 行情后台自动采集调度器（按交易日时点定时自我完成采集任务）
    try:
        market_scheduler.maybe_autostart()
    except Exception as e:  # noqa: BLE001
        logger.warning(f"行情自动采集调度器启动失败（可忽略）: {e}")

    # 告警推送模块数据表（webhooks/topics/settings/push_log，幂等建表）
    try:
        from finfeed.alerts import store as alerts_store
        alerts_store.ensure_tables()
    except Exception as e:  # noqa: BLE001
        logger.warning(f"告警模块数据表初始化失败（可忽略）: {e}")

    # WebSocket 行情推送服务：把采集失败告警实时推送给在线客户端
    # （回调接线同时内置于 ws_feed.start()，避免依赖启动顺序）
    try:
        market_alerting.manager.on_alert_callback = market_ws.push_alert
        market_ws.start()
    except Exception as e:  # noqa: BLE001
        logger.warning(f"行情 WebSocket 推送服务启动失败（可忽略）: {e}")


async def _shutdown(app: FastAPI) -> None:
    task = getattr(app.state, "sse_poll_task", None)
    if task is not None:
        task.cancel()
        try:
            await task
        except (asyncio.CancelledError, Exception):  # noqa: BLE001
            pass

    backfill = getattr(app.state, "content_backfill_task", None)
    if backfill is not None:
        backfill.cancel()
        try:
            await backfill
        except (asyncio.CancelledError, Exception):  # noqa: BLE001
            pass

    # 关闭行情 WebSocket 推送服务
    try:
        await market_ws.stop()
    except Exception:  # noqa: BLE001
        pass


    # 关闭行情自动采集调度器
    try:
        market_scheduler.stop()
    except Exception:  # noqa: BLE001
        pass
    # 停止资金流大屏刷新线程并断开 TDX 连接
    try:
        _cap_stop_worker()
    except Exception:  # noqa: BLE001
        pass
    # 停止板块分时刷新线程
    try:
        if _sm_stop_worker is not None:
            _sm_stop_worker()
    except Exception:  # noqa: BLE001
        pass
    # 停止股票监控外部舆情刷新线程
    try:
        stock_monitor_service.worker.stop()
    except Exception:  # noqa: BLE001
        pass


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Own application resources in one modern FastAPI lifecycle boundary."""
    await _startup(app)
    try:
        yield
    finally:
        await _shutdown(app)


app.router.lifespan_context = lifespan


# ----------------------------------------------------------------------
# 托管前端构建产物（Phase 3：FastAPI 静态托管 SPA）
# 注意：必须注册在所有 /api 路由之后，且不再保留返回 JSON 的 "/" 端点，
# 以免覆盖 SPA 首页。前端使用 hash 路由，深链直接命中 "/"。
# ----------------------------------------------------------------------
_DIST_DIR = Path(__file__).resolve().parent.parent.parent.parent / "web" / "dist"
if _DIST_DIR.exists():
    app.mount("/", StaticFiles(directory=str(_DIST_DIR), html=True), name="spa")


def run(port: int = DEFAULT_WEB_PORT):
    """启动 FastAPI 服务（双轨：旧 server.py 在 8867 作 fallback）。

    绑定 0.0.0.0（IPv4）以保证 127.0.0.1/localhost 可达；
    Windows 下 :: 默认 IPV6_V6ONLY=1，会导致 IPv4 客户端连接超时。
    """
    uvicorn.run(app, host="0.0.0.0", port=port, loop="asyncio")


if __name__ == "__main__":
    run()
