#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""FinFeed FastAPI 应用（方案 D 新后端）。

设计要点
--------
1. **复用而非重写**：业务函数与 SSE 广播通道直接复用 ``finfeed.ui.web.server``
   （下文 ``legacy``）的模块级实现，仅替换 HTTP 传输层为 FastAPI。
2. **SSE 桥接**：FastAPI 的 ``StreamingResponse`` 通过 threading.Queue 注册进
   ``legacy._sse_clients``，复用同一条广播通道；monitor 触发的 ``broadcast_new_news``
   会自动送达本端 SSE 客户端，双水位线/幂等/降级语义不变。
3. **导出 / 健康检查 / 熔断状态**：与旧实现逐字段对齐。
"""

import asyncio
import csv
import io
import json
import logging
import os
import queue as _queue
import threading as _threading
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional
from urllib.parse import parse_qs

import uvicorn
from fastapi import Body, FastAPI, HTTPException, Query, Request, WebSocket

from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, JSONResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.gzip import GZipMiddleware

from finfeed.config.settings import DEFAULT_WEB_PORT, get_display_name
from finfeed.config.sources import get_enabled_sources
from finfeed.core.health import get_health_monitor
from finfeed.ecal import api as calendar_api
from finfeed.ecal import fetcher as calendar_fetcher
from finfeed.llm import api as llm_api
from finfeed.market import scheduler as market_scheduler
from finfeed.market import alerting as market_alerting
from finfeed.market import ws_feed as market_ws
from finfeed.storage.database import (
    db_get_all_for_export,
    db_get_all_stock_names,
    db_get_date_range,
    db_get_news_by_id,
    db_get_statistics,
    db_mark_read,
    db_query_news,
    db_search_news,
    db_toggle_favorite,
    get_db,
)

# ----------------------------------------------------------------------
# 复用旧实现的模块级对象（SSE 客户端集合 / 广播 / 缓存 / 解析辅助）
# ----------------------------------------------------------------------
from finfeed.ui.web import server as legacy
from finfeed.utils.time_utils import bj_str_from_ts, now_bj

# easy-tdx 集成模块（FinFeed × 通达信行情）：分组导航 / 参数表单 / 任务执行与进度
from finfeed.integrations.easytdx.router import router as easytdx_router

# 智能选股模块（五维加权评分）
from finfeed.integrations.screener.router import router as screener_router

logger = logging.getLogger("news_monitor")

SSE_CLIENT_QUEUE_MAXSIZE = legacy.SSE_CLIENT_QUEUE_MAXSIZE

# SSE 增量推送的触发策略（亚秒级 + 兜底）：
# - SSE_TICK_POLL_INTERVAL：高频检查 monitor 主进程写入的 tick 哨兵文件
#   （finfeed/.finfeed_sse_tick）mtime。主进程每轮抓取完成即触碰该文件，
#   本进程随即立即触发 broadcast_new_news()，推送延迟降到亚秒级，与 TUI 同级。
# - SSE_SAFETY_POLL_INTERVAL：兜底全量轮询。即便 tick 文件机制因极端时序
#   （如同一秒内两次抓取导致 1s 精度 mtime 未变）漏触发，也能在 15s 内补上，
#   避免 Web 端静默停更。
# 设计依据：monitor 在主进程，浏览器 SSE 连接在本（FastAPI）子进程的
# _sse_clients；主进程直接 broadcast_new_news() 只能推到自己进程的空集合，
# 对浏览器无效。故仅由本进程负责推送，主进程改为触碰 tick 文件来「唤醒」本进程。
SSE_TICK_POLL_INTERVAL = 0.5
SSE_SAFETY_POLL_INTERVAL = 15.0

app = FastAPI(
    title="FinFeed API",
    version="2.1.0",
    description="FinFeed 实时财经新闻监控 — FastAPI 后端（双轨并行，兼容旧 SSE 通道）",
)

# 注册 easy-tdx 集成路由（/api/easytdx/*）
app.include_router(easytdx_router)

# 注册智能选股路由（/api/screener/*）
app.include_router(screener_router)

# ----------------------------------------------------------------------
# 全市场资金流与板块轮动监控大屏集成（可选，依赖 easy-tdx）
#  - API 前缀：/api/capital/*
#  - 大屏页面：/capital
#  - 独立运行：python -m finfeed.capital_dashboard（端口 8090）
# 依赖缺失或导入失败时优雅降级，不影响 FinFeed 主服务。
# ----------------------------------------------------------------------
try:
    from finfeed.capital_dashboard.server import (
        create_router as _cap_create_router,
        start_refresh_worker as _cap_start_worker,
        stop_refresh_worker as _cap_stop_worker,
    )
    from finfeed.capital_dashboard import config as _cap_config

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
    unread_only = gv("unread", "0") == "1"
    min_importance = gv("min_importance", "0")

    start_ts = legacy._ts_from_date_str(start_date, end_of_day=False) if start_date else None
    end_ts = legacy._ts_from_date_str(end_date, end_of_day=True) if end_date else None

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
    with legacy._web_state_lock:
        stats["cycle"] = legacy._web_state.get("cycle", 0)
        stats["status"] = legacy._web_state.get("status", "运行中")
        stats["new_count"] = legacy._web_state.get("new_count", 0)

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


# ----------------------------------------------------------------------
# 快讯 / 财经文章 / 舆情 / 收藏 / 搜索 / 详情
# ----------------------------------------------------------------------
def _api_category_news(request: Request, category: str, display_names: list):
    """快讯(category=flash)与财经文章(category=article)共用的分类新闻端点。

    原「新闻流」(/api/news) 已拆分为本函数支撑的两个独立模块：
      - /api/flash   ：快讯（7×24 实时短消息）
      - /api/articles：财经文章（长文/深度内容）
    """
    try:
        params = parse_query_params(qdict(request))
        if params["source"] and params["source"] not in display_names and params["source"] != "all":
            params["source"] = None
        cache_key = f"{category}:{json.dumps(params, sort_keys=True, default=str)}"
        cached = legacy._cache_get(cache_key)
        if cached is not None:
            return json_resp(cached, max_age=1)
        db_kwargs = {
            "limit": params["page_size"],
            "offset": params["offset"],
            "keyword": params["keyword"],
            "start_ts": params["start_ts"],
            "end_ts": params["end_ts"],
            "sentiment": params["sentiment"],
            "is_favorite": params["is_favorite"],
            "stock_name": params["stock"],
            "min_importance": params["min_importance"],
            # 分类隔离：快讯/文章/舆情互不混流
            "category": category,
        }
        if params["source"]:
            db_kwargs["source"] = params["source"]
        news_items, db_total = db_query_news(**db_kwargs)
        result = legacy._build_news_response(news_items, db_total, params["offset"], params["page_size"], display_names)
        legacy._cache_set(cache_key, result)
        return json_resp(result, max_age=1)
    except Exception as e:
        logger.error(f"{category}API错误: {e}")
        return json_resp({"error": str(e)}, status=500)


@app.get("/api/flash")
def api_flash(request: Request):
    flash_names, _ = legacy._get_flash_article_display_names()
    return _api_category_news(request, "flash", flash_names)


@app.get("/api/articles")
def api_articles(request: Request):
    _, article_names = legacy._get_flash_article_display_names()
    return _api_category_news(request, "article", article_names)


@app.get("/api/sentiment")
def api_sentiment(request: Request):
    try:
        params = parse_query_params(qdict(request))
        forum_raw_names, forum_raw_set, forum_display_names, forum_display_set, finance_display_names = legacy._get_cached_sources()
        cache_key = f"sentiment:{json.dumps(params, sort_keys=True, default=str)}"
        cached = legacy._cache_get(cache_key)
        if cached is not None:
            return json_resp(cached, max_age=1)
        db_kwargs = {
            "limit": params["page_size"],
            "offset": params["offset"],
            "keyword": params["keyword"],
            "start_ts": params["start_ts"],
            "end_ts": params["end_ts"],
            "sentiment": params["sentiment"],
            "is_favorite": params["is_favorite"],
            "stock_name": params["stock"],
            "min_importance": params["min_importance"],
            "category": "forum",
            "source": params["source"],
        }
        news_items, db_total = db_query_news(**db_kwargs)
        result = legacy._build_news_response(news_items, db_total, params["offset"], params["page_size"], forum_display_names)
        legacy._cache_set(cache_key, result)
        return json_resp(result, max_age=1)
    except Exception as e:
        logger.error(f"舆情API错误: {e}")
        return json_resp({"error": str(e)}, status=500)


@app.get("/api/favorites")
def api_favorites(request: Request):
    try:
        params = parse_query_params(qdict(request))
        news_items, total = db_query_news(limit=params["page_size"], offset=params["offset"], keyword=params["keyword"], is_favorite=True)
        result = legacy._build_news_response(news_items, total, params["offset"], params["page_size"], [])
        return json_resp(result)
    except Exception as e:
        return json_resp({"error": str(e)}, status=500)


@app.get("/api/search")
def api_search(q: str = Query("", alias="q"), limit: int = Query(100)):
    if q:
        news = db_search_news(q, limit=limit)
    else:
        news = []
    return {"keyword": q, "count": len(news), "news": [n.to_dict() for n in news]}


@app.get("/api/detail")
def api_detail(id: int = Query(0)):
    news = db_get_news_by_id(id)
    if news:
        db_mark_read(id, True)
        return {"success": True, "news": news.to_dict()}
    return {"success": False, "error": "News not found"}


@app.get("/api/stock_names")
def api_stock_names():
    cache_key = "stock_names_map"
    cached = legacy._cache_get(cache_key)
    if cached is not None:
        return json_resp(cached, max_age=300)
    try:
        stock_map = db_get_all_stock_names()
        if not stock_map:
            from finfeed.analysis.stock_names import STOCK_NAMES
            stock_map = dict(STOCK_NAMES)
        result = {"stock_names": stock_map}
        legacy._cache_set(cache_key, result)
        return json_resp(result, max_age=300)
    except Exception as e:
        logger.error(f"获取股票名称映射失败: {e}")
        return json_resp({"stock_names": {}}, status=500)


@app.get("/api/daterange")
def api_daterange():
    min_date, max_date, dates = db_get_date_range()
    return {"min": min_date, "max": max_date, "dates": dates}


# ----------------------------------------------------------------------
# 收藏 / 已读（POST）
# ----------------------------------------------------------------------
@app.post("/api/favorite")
def api_toggle_favorite(data: dict = Body(default={})):
    try:
        news_id = int(data.get("id", 0))
        if news_id <= 0:
            return json_resp({"success": False, "error": "Invalid id"}, status=400)
        new_state = db_toggle_favorite(news_id)
        legacy.invalidate_api_cache()
        return {"success": True, "is_favorite": new_state}
    except Exception as e:
        return json_resp({"success": False, "error": str(e)}, status=500)


@app.post("/api/read")
def api_mark_read(data: dict = Body(default={})):
    try:
        news_id = int(data.get("id", 0))
        is_read = bool(data.get("read", True))
        if news_id <= 0:
            return json_resp({"success": False, "error": "Invalid id"}, status=400)
        db_mark_read(news_id, is_read)
        legacy.invalidate_api_cache()
        return {"success": True}
    except Exception as e:
        return json_resp({"success": False, "error": str(e)}, status=500)


# ----------------------------------------------------------------------
# 导出（CSV / JSON / Markdown）
# ----------------------------------------------------------------------
@app.get("/api/export")
def api_export(format: str = Query("json"), start: Optional[str] = None, end: Optional[str] = None, favorites: int = Query(0)):
    fav_only = favorites == 1
    if fav_only:
        news, _ = db_query_news(limit=10000, is_favorite=True)
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
# LLM / 日历 适配器（与旧 server 透传语义一致）
# ----------------------------------------------------------------------
@app.get("/api/llm/report/export")
def api_llm_export(id: int = Query(0), fmt: str = Query("md")):
    out = llm_api.export_report(id, fmt)
    if not out:
        raise HTTPException(status_code=404, detail="not found")
    filename, body, content_type = out
    return Response(content=body, media_type=content_type,
                    headers={"Content-Disposition": f'attachment; filename="{filename}"'})


@app.api_route("/api/llm/{rest:path}", methods=["GET", "POST"])
async def api_llm(request: Request, rest: str):
    path = request.url.path
    if request.method == "GET":
        result = llm_api.handle_get(path, parse_qs(request.url.query))
    else:
        body = await request.body()
        data = json.loads(body.decode("utf-8")) if body else {}
        result = llm_api.handle_post(path, data)
    if result is not None:
        return json_resp(result[1], status=result[0])
    raise HTTPException(status_code=404, detail="not found")


@app.get("/api/calendar/export")
def api_calendar_export(request: Request):
    qs = parse_qs(request.url.query)
    try:
        payload, content_type, filename = calendar_api.export_events(qs)
    except Exception as e:
        logger.error(f"日历导出失败: {e}")
        return json_resp({"error": str(e)}, status=500)
    return Response(content=payload, media_type=content_type,
                    headers={"Content-Disposition": f'attachment; filename="{filename}"'})


@app.api_route("/api/calendar/{rest:path}", methods=["GET", "POST"])
async def api_calendar(request: Request, rest: str):
    path = request.url.path
    if request.method == "GET":
        result = calendar_api.handle_get(path, parse_qs(request.url.query))
    else:
        body = await request.body()
        data = json.loads(body.decode("utf-8")) if body else {}
        result = calendar_api.handle_post(path, data)
    if result is not None:
        return json_resp(result[1], status=result[0])
    raise HTTPException(status_code=404, detail="not found")


# ----------------------------------------------------------------------
# 市场行情（移植自 legacy._serve_market_api / _market_dates / _serve_market_action）
# ----------------------------------------------------------------------
_market_tasks: Dict[str, Dict] = {}


def _market_dates(fallback_date: str) -> dict:
    from finfeed.storage.database import get_db
    out: Dict[str, Any] = {"billboard": None, "limit_pool": None, "sentiment": None}
    with get_db() as c:
        for tbl, key, cond in (
            ("billboard", "billboard", ""),
            ("limit_pool", "limit_pool", ""),
            ("market_sentiment_daily", "sentiment", "WHERE (breadth > 0 OR up_limit > 0 OR down_limit > 0)"),
            ("money_flow", "money_flow", ""),
            ("margin_detail", "margin_detail", ""),
            ("daily_bar", "daily_bar", ""),
        ):
            try:
                c.execute(f"SELECT MAX(trade_date) AS d FROM {tbl} {cond}")
                row = c.fetchone()
                out[key] = row["d"] if row and row["d"] else None
            except Exception:
                out[key] = None
        for tbl, key, col in (
            ("earnings_forecast", "forecast", "notice_date"),
            ("ipo_calendar", "ipo", "apply_date"),
        ):
            try:
                c.execute(f"SELECT MAX({col}) AS d FROM {tbl}")
                row = c.fetchone()
                out[key] = row["d"] if row and row["d"] else None
            except Exception:
                out[key] = None
    table_dates = [d for d in (out["billboard"], out["limit_pool"]) if d]
    if table_dates:
        out["default_date"] = max(table_dates)
    else:
        sent = out.get("sentiment")
        out["default_date"] = sent or fallback_date
    out["has_billboard"] = out["billboard"] is not None
    out["has_limit_pool"] = out["limit_pool"] is not None
    return out


def _market_action(q: Dict[str, List[str]]):
    def gv(key, default):
        v = q.get(key)
        return v[0] if v else default
    action = (gv("action", "") or "").strip().lower()
    date = gv("date", None)

    if action == "status":
        tasks = {k: {"status": v["status"], "message": v.get("message", ""), "started": v.get("started", ""), "result": v.get("result")}
                 for k, v in _market_tasks.items()}
        return {"success": True, "data": tasks}

    if action == "autocollect":
        enable = gv("enable", "1") not in ("0", "false", "no")
        if enable:
            market_scheduler.start()
        else:
            market_scheduler.stop()
        return {"success": True, "data": market_scheduler.get_state()}

    svc = legacy._get_mk_service()
    ACTION_MAP = {
        "snapshot": ("采集行情快照", lambda: legacy._run_in_thread(lambda d=date: svc.run_daily_snapshot_sync(d))),
        "bars": ("采集K线数据", lambda: legacy._run_in_thread(lambda d=date: svc.collect_bars_sync(d))),
        "universe": ("初始化股票池", lambda: legacy._run_in_thread(lambda: svc.run_universe_sync())),
        "calibrate": ("校准情绪模型", lambda: legacy._run_in_thread(lambda: legacy._mk_calibrate())),
    }
    if action not in ACTION_MAP:
        return {"success": False, "error": f"未知操作: {action}，可选: {', '.join(ACTION_MAP)}"}
    existing = _market_tasks.get(action)
    if existing and existing["status"] == "running":
        return {"success": False, "error": f"「{ACTION_MAP[action][0]}」正在执行中，请等待完成"}
    label = ACTION_MAP[action][0]
    task_id = f"{action}_{int(time.time())}"
    _market_tasks[action] = {"status": "running", "message": f"⏳ {label} 执行中…", "started": datetime.now().strftime("%H:%M:%S"), "result": None}

    def _worker():
        try:
            result = ACTION_MAP[action][1]()
            _market_tasks[action]["status"] = "done"
            _market_tasks[action]["message"] = f"✅ {label} 完成"
            _market_tasks[action]["result"] = result
        except Exception as exc:
            _market_tasks[action]["status"] = "error"
            _market_tasks[action]["message"] = f"❌ {label} 失败: {exc}"
            _market_tasks[action]["result"] = str(exc)
            logger.error("Market action '%s' failed: %s", action, exc, exc_info=True)
    t = _threading.Thread(target=_worker, daemon=True, name=f"mk-{action}")
    t.start()
    return {"success": True, "data": {"task_id": task_id, "action": action, "label": label, "status": "running", "message": f"已启动「{label}，后台执行中"}}


# ---------------------------------------------------------------------------
# 指数 K 线 / 分时
# 分时（trends）：内存 TTL 缓存（300s），日内瞬态数据不入库。
# K 线（101 日 / 102 周 / 103 月 / 104 季 / 105 年）：本地 SQLite kline_cache
#   优先 + TTL 定期刷新。每个 (code, klt) 在 TTL 窗口内至多触发一次东财
#   push2his 请求，其余请求全部命中本地库，规避 600s 冷却限流。
# ---------------------------------------------------------------------------
_KLINE_CACHE: Dict[tuple, tuple] = {}
_KLINE_CACHE_TTL = 300.0
# K 线周期 -> 缓存 TTL（秒）：日K 30min / 周K 1h / 月K 3h / 季K 6h / 年K 12h
_KLINE_TTL = {101: 1800, 102: 3600, 103: 10800, 104: 21600, 105: 43200}
# K 线周期 -> 单次拉取窗口（根数，与前端「全部」lmt 对齐）
_KLINE_WINDOW = {101: 1500, 102: 520, 103: 240, 104: 80, 105: 30}


def _strip_fetched(rows_list):
    """去掉内部字段 fetched_at，仅返回前端需要的行情字段。"""
    return [{k: v for k, v in r.items() if k != "fetched_at"} for r in rows_list]


def _ok(rows_list):
    return {"rows": rows_list or [], "reason": "ok" if rows_list else "empty"}


def _last_n(rows_list, limit):
    """取最近 limit 根（保持升序）；limit 为空则原样返回。"""
    if not rows_list or not limit:
        return rows_list or []
    return rows_list[-int(limit):]


async def _get_chart_data(code, chart_type, klt, ndays, lmt, start, end):
    """返回 {rows: [...], reason: 'ok'|'empty'|'rate_limited'|'error', error?: str}。

    分时走内存 TTL 缓存；K 线走本地 SQLite kline_cache：
    - TTL 内新鲜 → 直接读库返回（不触网）；
    - 过期/无缓存 → 若处于限流冷却则不触网，回退旧缓存；
    - 否则发一次东财请求（取「全部」窗口）写入缓存后返回。
    """
    from finfeed.market import kline as _mk_kline
    from finfeed.market import store as _mk_store
    from finfeed.market.client import RateLimited, cooldown_remaining

    now = time.time()

    # ---- 分时：内存 TTL 缓存（与旧行为一致）----
    if chart_type == "trends":
        key = (code, chart_type, klt, ndays, lmt, start, end)
        cached = _KLINE_CACHE.get(key)
        if cached and (now - cached[0]) < _KLINE_CACHE_TTL:
            return cached[1]
        try:
            result = _ok(await _mk_kline.fetch_trends(code, ndays=ndays))
        except RateLimited:
            logger.warning("分时获取被限流：%s", code)
            return {"rows": [], "reason": "rate_limited"}
        except Exception as e:  # noqa: BLE001
            logger.warning("分时获取失败 %s: %s", code, e)
            return {"rows": [], "reason": "error", "error": str(e)[:200]}
        if result["reason"] == "ok":
            _KLINE_CACHE[key] = (now, result)
        return result

    # ---- K 线：本地优先 + TTL 刷新 ----
    # 日线且有起止区间时优先读 daily_bar（盘后快照已入库的标的）
    if klt == 101 and start and end:
        db_rows = _mk_store.get_daily_bar(code, start, end)
        if db_rows:
            return _ok(db_rows)

    cached_rows = _mk_store.get_cached_kline(code, klt, start, end)
    if cached_rows:
        newest_fetched = max(r["fetched_at"] for r in cached_rows)
        try:
            fetched_dt = datetime.strptime(newest_fetched, "%Y-%m-%d %H:%M:%S")
        except (ValueError, TypeError):
            fetched_dt = None
        ttl = _KLINE_TTL.get(klt, 1800)
        if fetched_dt is not None and (now_bj() - fetched_dt).total_seconds() < ttl:
            return _ok(_strip_fetched(_last_n(cached_rows, lmt)))

    # 过期 / 无缓存：限流冷却期内不触网，回退旧缓存（旧数据优于空/限流提示）
    if cooldown_remaining("em_push2his") > 0:
        if cached_rows:
            return _ok(_strip_fetched(_last_n(cached_rows, lmt)))
        return {"rows": [], "reason": "rate_limited"}

    try:
        first_date = cached_rows[0]["trade_date"] if cached_rows else None
        if start and first_date and start < first_date:
            # 自定义历史区间早于缓存最早日期：区间模式补拉并合并进缓存
            bars = await _mk_kline.fetch_daily_bar(
                code, end_date=end or "20500101", beg=start, klt=klt
            )
        else:
            # 常规刷新：一次取「全部」窗口，覆盖所有快捷区间
            bars = await _mk_kline.fetch_daily_bar(
                code, end_date=end, limit=_KLINE_WINDOW.get(klt, 1500), klt=klt
            )
        if bars:
            _mk_store.upsert_kline_cache([dict(b, code=code) for b in bars], klt)
        rows = _mk_store.get_cached_kline(code, klt, start, end)
        return _ok(_strip_fetched(_last_n(rows, lmt)))
    except RateLimited:
        logger.warning("K线获取被限流：%s", code)
        if cached_rows:
            return _ok(_strip_fetched(_last_n(cached_rows, lmt)))
        return {"rows": [], "reason": "rate_limited"}
    except Exception as e:  # noqa: BLE001
        logger.warning("K线获取失败 %s: %s", code, e)
        rows = _last_n(cached_rows, lmt) if cached_rows else []
        return {"rows": _strip_fetched(rows), "reason": "error", "error": str(e)[:200]}


@app.api_route("/api/market/{rest:path}", methods=["GET", "POST"])
async def api_market(rest: str, request: Request):
    q = qdict(request)
    date = (q.get("date", [None])[0]) or now_bj().strftime("%Y-%m-%d")
    sub = rest.strip("/") or "sentiment"

    if sub == "action":
        return _market_action(q)

    def _int(key: str, default: int, cap: int = 500) -> int:
        try:
            return max(1, min(int(q.get(key, [default])[0]), cap))
        except (TypeError, ValueError):
            return default

    try:
        from finfeed.market import alerts as mk_alerts
        from finfeed.market import store as mk_store
        from finfeed.storage import sentiment_store as ss

        if sub == "sentiment":
            data = ss.get_market_sentiment(date) or {}
        elif sub == "dates":
            data = _market_dates(date)
        elif sub == "limitup":
            data = mk_store.get_limit_pool(date, "up")
        elif sub == "limitdown":
            data = mk_store.get_limit_pool(date, "down")
        elif sub == "limitbroken":
            data = mk_store.get_limit_pool(date, "broken")
        elif sub == "billboard":
            data = mk_store.get_billboard(date)
        elif sub == "alerts":
            data = mk_alerts.regime_summary(date)
        elif sub == "moneyflow":
            d = mk_store.latest_date("money_flow") or date
            data = {
                "trade_date": d,
                "summary": mk_store.get_money_flow_summary(d),
                "inflow": mk_store.get_money_flow(d, "in", q.get("order", ["main_net"])[0], _int("limit", 40)),
                "outflow": mk_store.get_money_flow(d, "out", q.get("order", ["main_net"])[0], _int("limit", 40)),
            }
        elif sub == "margin":
            d = mk_store.latest_date("margin_detail") or date
            order = q.get("order", ["fin_net"])[0]
            data = {
                "trade_date": d,
                "summary": mk_store.get_margin_summary(d),
                "top": mk_store.get_margin_rank(d, order, True, _int("limit", 40)),
                "bottom": mk_store.get_margin_rank(d, order, False, _int("limit", 40)),
            }
        elif sub == "forecast":
            ftype = (q.get("type", [""])[0] or "").strip() or None
            data = {
                "stats": mk_store.get_forecast_type_stats(),
                "rows": mk_store.get_earnings_forecast(ftype=ftype, order_by=q.get("order", ["increase_high"])[0], limit=_int("limit", 80)),
            }
        elif sub == "ipo":
            data = mk_store.get_ipo_calendar(q.get("start", [None])[0], q.get("end", [None])[0], _int("limit", 80))
        elif sub == "sectors":
            d = mk_store.latest_date("money_flow") or date
            stype = q.get("stype", ["concept"])[0]
            data = {
                "trade_date": d,
                "sector_type": stype,
                "rows": mk_store.get_sector_heat(d, stype, min_members=_int("min_members", 5, 100), order_by=q.get("order", ["avg_pct"])[0], limit=_int("limit", 40)),
            }
        elif sub == "sectorstocks":
            d = mk_store.latest_date("money_flow") or date
            data = mk_store.get_sector_stocks(q.get("sector", [""])[0], d, _int("limit", 60))
        elif sub == "profile":
            code = q.get("code", [""])[0]
            data = mk_store.get_stock_profile(code, _int("bars", 120))
        elif sub == "search":
            data = mk_store.search_stock(q.get("kw", [""])[0], _int("limit", 20, 50))
        elif sub == "autostatus":
            data = market_scheduler.get_state()
        elif sub == "alertlog":
            data = {
                "recent": market_alerting.get_recent(limit=_int("limit", 50)),
                "stats": market_alerting.get_stats(),
            }
        elif sub == "hotrank":
            from finfeed.market.ths_hotrank import fetch_hotrank
            category = (q.get("category", ["stock"])[0] or "stock").strip()
            list_type = (q.get("list", ["normal"])[0] or "normal").strip()
            period = (q.get("period", ["hour"])[0] or "hour").strip()
            date = (q.get("date", [None])[0]) or None
            data = await fetch_hotrank(
                list_type, period, _int("limit", 100, 200), date, category=category
            )
        elif sub == "hotrank_dates":
            from finfeed.market import store as mk_store
            data = mk_store.get_ths_hotrank_dates()
        elif sub == "thslimitup":
            from finfeed.market import ths_limitup
            section = (q.get("section", ["all"])[0] or "all").strip()
            date = (q.get("date", [None])[0]) or None
            if section == "all":
                data = await ths_limitup.fetch_limitup_focus(date, sections="all")
            elif section == "intensity":
                data = await ths_limitup.fetch_limit_up_intensity(date)
            elif section == "ladder":
                data = await ths_limitup.fetch_board_ladder(date)
            elif section == "wind":
                data = await ths_limitup.fetch_strong_wind(date)
            elif section == "sentiment":
                data = await ths_limitup.fetch_market_sentiment(date)
            else:
                data = {"error": f"unknown limitup section: {section}"}
        elif sub == "thslimitup_dates":
            from finfeed.market import store as mk_store
            data = mk_store.get_ths_limitup_dates()
        elif sub == "overview":
            data = mk_store.get_fact_overview()
        elif sub == "kline":
            code = q.get("code", [""])[0]
            if not code:
                data = []
            else:
                chart_type = (q.get("type", ["kline"])[0] or "kline").strip()
                klt = _int("klt", 101, 105)
                ndays = _int("ndays", 1, 10)
                lmt = _int("lmt", 250, 2000)
                start = q.get("start", [None])[0]
                end = q.get("end", [None])[0]
                data = await _get_chart_data(code, chart_type, klt, ndays, lmt, start, end)
        else:
            data = {"error": f"unknown market action: {sub}"}
        return {"success": True, "data": data}
    except Exception as e:
        return json_resp({"success": False, "error": str(e)[:200]}, status=500)


# ----------------------------------------------------------------------
# SSE 增量推送（桥接 legacy._sse_clients 广播通道）
# ----------------------------------------------------------------------
@app.get("/api/events")
async def sse_events(request: Request):
    q = _queue.Queue(maxsize=SSE_CLIENT_QUEUE_MAXSIZE)
    with legacy._sse_clients_lock:
        legacy._sse_clients.add(q)
    loop = asyncio.get_event_loop()
    aq: "asyncio.Queue" = asyncio.Queue()
    stop = {"v": False}

    def pump():
        while not stop["v"]:
            try:
                item = q.get(timeout=15)
            except _queue.Empty:
                asyncio.run_coroutine_threadsafe(aq.put(("ping", None)), loop)
                continue
            if item.get("type") == "shutdown":
                break
            asyncio.run_coroutine_threadsafe(aq.put(("data", item)), loop)

    t = _threading.Thread(target=pump, daemon=True)
    t.start()

    async def gen():
        yield "event: connected\ndata: {\"type\":\"connected\"}\n\n"
        try:
            while True:
                kind, item = await aq.get()
                if kind == "ping":
                    yield ": ping\n\n"
                else:
                    payload = json.dumps(item, ensure_ascii=False)
                    yield f"event: news\ndata: {payload}\n\n"
        finally:
            stop["v"] = True
            with legacy._sse_clients_lock:
                legacy._sse_clients.discard(q)

    return StreamingResponse(
        gen(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "Connection": "keep-alive", "X-Accel-Buffering": "no"},
    )


async def _sse_poll_loop() -> None:
    """SSE 增量推送循环：tick 即时触发 + 定时兜底轮询。

    主进程 monitor 每轮抓取完成会触碰 tick 哨兵文件（finfeed/.finfeed_sse_tick）；
    本循环高频（SSE_TICK_POLL_INTERVAL）检查其 mtime，一旦变化立即调用
    broadcast_new_news() 把增量推给本进程的 SSE 客户端（即浏览器连接）。
    同时保留 SSE_SAFETY_POLL_INTERVAL 的兜底全量轮询，防止 tick 机制在
    极短时序下漏触发导致 Web 端静默停更。broadcast_new_news() 基于 DB 自增
    id 水位线且严格幂等，重复/兜底触发不会重复推送、也不会遗漏。
    """
    logger.info(
        f"SSE 增量推送循环已启动（tick 轮询 {SSE_TICK_POLL_INTERVAL}s / 兜底 {SSE_SAFETY_POLL_INTERVAL}s）"
    )
    last_tick = legacy.get_sse_tick_mtime()
    acc = 0.0
    while True:
        try:
            await asyncio.sleep(SSE_TICK_POLL_INTERVAL)
            acc += SSE_TICK_POLL_INTERVAL
            tick = legacy.get_sse_tick_mtime()
            triggered = bool(tick) and tick != last_tick
            if triggered:
                last_tick = tick
            if triggered or acc >= SSE_SAFETY_POLL_INTERVAL:
                acc = 0.0
                await asyncio.to_thread(legacy.broadcast_new_news)
        except asyncio.CancelledError:
            break
        except Exception as e:  # noqa: BLE001
            logger.error(f"SSE 增量推送循环异常: {e}")
            try:
                await asyncio.sleep(SSE_TICK_POLL_INTERVAL)
            except asyncio.CancelledError:
                break


@app.on_event("startup")
async def _startup():
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

    legacy.init_broadcast_watermark()
    # 创建 tick 哨兵文件并置为当前时间，使 _sse_poll_loop 的 last_tick 基准有效；
    # 之后主进程每次抓取完成都会更新其 mtime 以「唤醒」本进程的即时推送。
    legacy.touch_sse_tick()
    try:
        calendar_fetcher.warmup()
    except Exception as e:
        logger.warning(f"日历连接池预热失败（可忽略）: {e}")
    # 启动 SSE 增量推送循环（tick 即时触发 + 定时兜底），修复子进程跨进程
    # 广播失效导致的 Web 端不实时更新。
    app.state.sse_poll_task = asyncio.create_task(_sse_poll_loop())

    # 行情后台自动采集调度器（按交易日时点定时自我完成采集任务）
    try:
        market_scheduler.maybe_autostart()
    except Exception as e:  # noqa: BLE001
        logger.warning(f"行情自动采集调度器启动失败（可忽略）: {e}")

    # WebSocket 行情推送服务：把采集失败告警实时推送给在线客户端
    # （回调接线同时内置于 ws_feed.start()，避免依赖启动顺序）
    try:
        market_alerting.manager.on_alert_callback = market_ws.push_alert
        market_ws.start()
    except Exception as e:  # noqa: BLE001
        logger.warning(f"行情 WebSocket 推送服务启动失败（可忽略）: {e}")


@app.on_event("shutdown")
async def _shutdown():
    task = getattr(app.state, "sse_poll_task", None)
    if task is not None:
        task.cancel()
        try:
            await task
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


@app.get("/api/ping")
def ping():
    return {"service": "FinFeed API", "version": "2.1.0", "docs": "/docs"}


@app.get("/api/sse/health")
def sse_health():
    """SSE 推送桥接健康度：供前端/运维判断 Web 实时通道是否存活。

    - clients: 当前本进程 SSE 客户端数（即已连浏览器数）
    - last_broadcast_ts: 最近一次「实际广播出数据」的时间戳（0 表示从未）
    - watermark: 各分类增量推送水位线（自增 id）
    - watermark_initialized: 水位线是否已初始化
    """
    with legacy._sse_clients_lock:
        n = len(legacy._sse_clients)
    return {
        "clients": n,
        "last_broadcast_ts": legacy._last_broadcast_ts,
        "watermark": dict(legacy._broadcast_watermarks),
        "watermark_initialized": legacy._watermark_initialized,
    }


# ----------------------------------------------------------------------
# WebSocket 行情推送（独立于 SSE 的实时行情通道）
# ----------------------------------------------------------------------
@app.websocket("/ws/market")
async def ws_market(websocket: WebSocket):
    await market_ws.handle_connection(websocket)


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
