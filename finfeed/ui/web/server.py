#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Web 仪表盘服务

提供 HTTP API 和前端页面，支持：
- 实时新闻列表（分页）
- 来源筛选、日期筛选、情绪筛选、股票筛选
- 收藏/已读功能
- JSON/CSV/Excel/Markdown 导出
- FTS5 全文搜索
- SSE 实时推送
- 健康检查端点
"""

import os
import csv
import io
import json
import gzip
import time
import socket
import logging
import threading
import queue
import traceback
from typing import Optional, Dict, List, Any, Tuple, Set
from functools import lru_cache
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs
from datetime import datetime


class DualStackThreadingHTTPServer(ThreadingHTTPServer):
    """支持IPv4/IPv6双栈的线程HTTP服务器"""
    address_family = socket.AF_INET6
    allow_reuse_address = True
    daemon_threads = True

    def server_bind(self):
        self.socket.setsockopt(socket.IPPROTO_IPV6, socket.IPV6_V6ONLY, 0)
        super().server_bind()

from finfeed.config.settings import get_display_name, DEFAULT_WEB_PORT, API_CACHE_TTL
from finfeed.config.sources import get_enabled_sources, get_forum_sources
from finfeed.utils.time_utils import now_bj, bj_str_from_ts, ts_from_bj_str
from finfeed.storage.database import (
    db_get_all_for_export, db_get_date_range, db_search_news,
    db_get_news_by_id, db_get_recent_news, db_mark_read, db_toggle_favorite,
    db_query_news, db_get_statistics, db_get_favorites, get_db,
    db_get_all_stock_names,
)
from finfeed.storage.models import NewsItem
from finfeed.core.health import get_health_monitor
from finfeed.llm import api as llm_api

logger = logging.getLogger("news_monitor")

_web_state = {
    "news": [],
    "stats": {},
    "cycle": 0,
    "total": 0,
    "new_count": 0,
    "status": "启动中",
    "sources": [],
    "last_update": "",
    "server_ts": time.time(),
    "latest_id": 0,
}
_web_state_lock = threading.Lock()

_sse_clients: set = set()
_sse_clients_lock = threading.Lock()
_notification_queue: queue.Queue = queue.Queue()

_template_lock = threading.Lock()

_forum_source_raw_names: list | None = None
_forum_source_raw_set: set | None = None
_forum_source_display_names: list | None = None
_forum_source_display_set: set | None = None
_finance_source_display_names: list | None = None
_sources_cache_lock = threading.Lock()

_api_cache = {}
_api_cache_lock = threading.Lock()


def _cache_get(key: str):
    with _api_cache_lock:
        entry = _api_cache.get(key)
        if entry and time.time() - entry[0] < API_CACHE_TTL:
            return entry[1]
        if key in _api_cache:
            del _api_cache[key]
        return None


def _cache_set(key: str, value):
    with _api_cache_lock:
        _api_cache[key] = (time.time(), value)


def invalidate_api_cache():
    with _api_cache_lock:
        _api_cache.clear()


def invalidate_sources_cache():
    """重置来源列表缓存"""
    global _forum_source_raw_names, _forum_source_raw_set, _forum_source_display_names, _forum_source_display_set, _finance_source_display_names
    with _sources_cache_lock:
        _forum_source_raw_names = None
        _forum_source_raw_set = None
        _forum_source_display_names = None
        _forum_source_display_set = None
        _finance_source_display_names = None


def _get_cached_sources():
    global _forum_source_raw_names, _forum_source_raw_set, _forum_source_display_names, _forum_source_display_set, _finance_source_display_names
    with _sources_cache_lock:
        if _forum_source_raw_names is None:
            forum_sources = get_forum_sources()
            _forum_source_raw_names = [s.name for s in forum_sources]
            _forum_source_raw_set = set(_forum_source_raw_names)
            _forum_source_display_names = list(dict.fromkeys(
                get_display_name(s.name) for s in forum_sources
            ))
            _forum_source_display_set = set(_forum_source_display_names)
            _finance_source_display_names = list(dict.fromkeys(
                get_display_name(s.name) for s in get_enabled_sources()
                if s.name not in _forum_source_raw_set
            ))
        return _forum_source_raw_names, _forum_source_raw_set, _forum_source_display_names, _forum_source_display_set, _finance_source_display_names


_template_cache_map = {
    "index": {"cache": None, "mtime": 0, "filename": "index.html"},
    "dashboard": {"cache": None, "mtime": 0, "filename": "dashboard.html"},
    "about": {"cache": None, "mtime": 0, "filename": "about.html"},
    "sentiment": {"cache": None, "mtime": 0, "filename": "sentiment.html"},
    "favorites": {"cache": None, "mtime": 0, "filename": "favorites.html"},
    "ai_analysis": {"cache": None, "mtime": 0, "filename": "ai_analysis.html"},
}


def _load_template(template_name: str) -> str:
    info = _template_cache_map.get(template_name)
    if not info:
        return f"<h1>Template {template_name} not found</h1>"

    template_path = os.path.join(
        os.path.dirname(os.path.abspath(__file__)),
        "templates", info["filename"]
    )
    try:
        current_mtime = os.path.getmtime(template_path)
    except OSError:
        current_mtime = 0

    with _template_lock:
        if info["cache"] is not None and current_mtime <= info["mtime"]:
            return info["cache"]

    try:
        with open(template_path, "r", encoding="utf-8") as f:
            content = f.read()
        with _template_lock:
            info["cache"] = content
            info["mtime"] = current_mtime
            return content
    except Exception as e:
        logger.warning(f"加载模板 {info['filename']} 失败: {e}")
        with _template_lock:
            if info["cache"] is None:
                info["cache"] = f"<h1>{info['filename']} not found</h1>"
            return info["cache"]


def _get_template() -> str:
    return _load_template("index")

def _get_dashboard_html() -> str:
    return _load_template("dashboard")

def _get_about_html() -> str:
    return _load_template("about")

def _get_sentiment_html() -> str:
    return _load_template("sentiment")

def _get_favorites_html() -> str:
    return _load_template("favorites")

def _get_ai_analysis_html() -> str:
    return _load_template("ai_analysis")


def _ts_from_date_str(date_str: str, end_of_day: bool = False) -> int | None:
    if not date_str:
        return None
    try:
        if len(date_str) == 10:
            return ts_from_bj_str(date_str + (" 23:59:59" if end_of_day else " 00:00:00"))
        return ts_from_bj_str(date_str)
    except Exception as e:
        logger.debug(f"日期解析失败 '{date_str}': {e}")
        return None


def _build_news_response(news_items: list, total: int, offset: int, limit: int, sources: list) -> dict:
    news_dicts = [n.to_dict() for n in news_items]
    stats = db_get_statistics()
    has_more = len(news_items) >= limit
    next_offset = offset + len(news_items) if has_more else None

    return {
        "news": news_dicts,
        "total": total,
        "offset": offset,
        "next_offset": next_offset,
        "limit": limit,
        "returned_count": len(news_items),
        "has_more": has_more,
        "stats": stats,
        "sources": sources,
        "server_ts": time.time(),
    }


class _WebHandler(BaseHTTPRequestHandler):
    """Web 仪表盘 HTTP 请求处理器"""

    def do_GET(self):
        parsed = urlparse(self.path)
        path = parsed.path

        if path == "/" or path.startswith("/index"):
            self._serve_html()
        elif path.startswith("/api/news"):
            self._serve_news()
        elif path.startswith("/api/sentiment"):
            self._serve_sentiment_api()
        elif path.startswith("/api/favorites"):
            self._serve_favorites_api()
        elif path.startswith("/api/search"):
            self._serve_search()
        elif path.startswith("/api/detail"):
            self._serve_detail()
        elif path.startswith("/api/health"):
            self._serve_health()
        elif path.startswith("/api/stats"):
            self._serve_stats()
        elif path.startswith("/api/stock_names"):
            self._serve_stock_names()
        elif path.startswith("/api/daterange"):
            self._serve_daterange()
        elif path.startswith("/api/llm/report/export"):
            self._serve_llm_export(parsed)
        elif path.startswith("/api/llm"):
            result = llm_api.handle_get(path, parse_qs(parsed.query))
            if result is not None:
                self._send_json(result[1], result[0])
            else:
                self.send_error(404)
        elif path.startswith("/ai/analysis"):
            self._serve_ai_analysis()
        elif path.startswith("/api/export"):
            self._serve_export(parsed.query)
        elif path.startswith("/api/events"):
            self._serve_sse()
        elif path.startswith("/dashboard"):
            self._serve_dashboard()
        elif path.startswith("/about"):
            self._serve_about()
        elif path.startswith("/sentiment"):
            self._serve_sentiment()
        elif path.startswith("/favorites"):
            self._serve_favorites()
        else:
            self.send_error(404)

    def do_POST(self):
        parsed = urlparse(self.path)
        path = parsed.path
        content_length = int(self.headers.get('Content-Length', 0))
        body = self.rfile.read(content_length) if content_length > 0 else b''

        try:
            data = json.loads(body.decode('utf-8')) if body else {}
        except json.JSONDecodeError:
            data = {}

        if path.startswith("/api/favorite"):
            self._handle_toggle_favorite(data)
        elif path.startswith("/api/read"):
            self._handle_mark_read(data)
        elif path.startswith("/api/llm"):
            result = llm_api.handle_post(path, data)
            if result is not None:
                self._send_json(result[1], result[0])
            else:
                self.send_error(404)
        else:
            self.send_error(404)

    def _serve_html(self):
        data = _get_template().encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _serve_favorites(self):
        html = _get_favorites_html().encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(html)))
        self.end_headers()
        self.wfile.write(html)

    def _parse_query_params(self, query: str) -> dict:
        qs = parse_qs(query)

        if "offset" in qs or "limit" in qs:
            offset = int(qs.get("offset", ["0"])[0])
            page_size = int(qs.get("limit", ["50"])[0])
            page_size = min(max(page_size, 10), 200)
            page = (offset // page_size) + 1
        else:
            page = int(qs.get("page", ["1"])[0])
            page_size = int(qs.get("page_size", ["50"])[0])
            page_size = min(max(page_size, 10), 200)
            offset = (page - 1) * page_size

        source = qs.get("source", ["all"])[0]
        keyword = qs.get("keyword", [""])[0] or qs.get("q", [""])[0]
        sentiment = qs.get("sentiment", ["all"])[0]
        stock = qs.get("stock", [""])[0]
        start_date = qs.get("start", [""])[0]
        end_date = qs.get("end", [""])[0]
        fav_only = qs.get("favorites", ["0"])[0] == "1"
        unread_only = qs.get("unread", ["0"])[0] == "1"
        min_importance = qs.get("min_importance", ["0"])[0]

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

    def _serve_news(self):
        try:
            params = self._parse_query_params(urlparse(self.path).query)
            forum_raw_names, forum_raw_set, forum_display_names, forum_display_set, finance_display_names = _get_cached_sources()

            if params["source"] and params["source"] not in finance_display_names and params["source"] != "all":
                params["source"] = None

            cache_key = f"news:{json.dumps(params, sort_keys=True, default=str)}"
            cached = _cache_get(cache_key)
            if cached is not None:
                self._send_json(cached, max_age=1)
                return

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
            }
            
            if params["source"]:
                db_kwargs["source"] = params["source"]
            else:
                db_kwargs["category"] = "finance"
            
            news_items, db_total = db_query_news(**db_kwargs)
            result = _build_news_response(
                news_items, db_total, params["offset"], params["page_size"], finance_display_names
            )
            _cache_set(cache_key, result)
            self._send_json(result, max_age=1)
        except Exception as e:
            logger.error(f"新闻API错误: {e}")
            logger.error(traceback.format_exc())
            self._send_json({"error": str(e)}, status=500)

    def _serve_sentiment_api(self):
        try:
            params = self._parse_query_params(urlparse(self.path).query)
            forum_raw_names, forum_raw_set, forum_display_names, forum_display_set, finance_display_names = _get_cached_sources()

            cache_key = f"sentiment:{json.dumps(params, sort_keys=True, default=str)}"
            cached = _cache_get(cache_key)
            if cached is not None:
                self._send_json(cached, max_age=1)
                return

            if params["source"] and params["source"] in forum_display_names:
                db_kwargs = {
                    "limit": params["page_size"],
                    "offset": params["offset"],
                    "source": params["source"],
                    "keyword": params["keyword"],
                    "start_ts": params["start_ts"],
                    "end_ts": params["end_ts"],
                    "sentiment": params["sentiment"],
                    "is_favorite": params["is_favorite"],
                    "stock_name": params["stock"],
                    "min_importance": params["min_importance"],
                    "category": "forum",
                }
            else:
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
                }

            news_items, db_total = db_query_news(**db_kwargs)
            result = _build_news_response(
                news_items, db_total, params["offset"], params["page_size"], forum_display_names
            )
            _cache_set(cache_key, result)
            self._send_json(result, max_age=1)
        except Exception as e:
            logger.error(f"舆情API错误: {e}")
            logger.error(traceback.format_exc())
            self._send_json({"error": str(e)}, status=500)

    def _serve_favorites_api(self):
        try:
            params = self._parse_query_params(urlparse(self.path).query)
            news_items, total = db_query_news(
                limit=params["page_size"],
                offset=params["offset"],
                keyword=params["keyword"],
                is_favorite=True,
            )
            result = _build_news_response(
                news_items, total, params["offset"], params["page_size"], []
            )
            self._send_json(result)
        except Exception as e:
            self._send_json({"error": str(e)}, status=500)

    def _serve_search(self):
        qs = parse_qs(urlparse(self.path).query)
        keyword = qs.get("q", [""])[0]
        limit = int(qs.get("limit", ["100"])[0])
        if keyword:
            news = db_search_news(keyword, limit=limit)
        else:
            news = []
        result = {
            "keyword": keyword,
            "count": len(news),
            "news": [n.to_dict() for n in news],
        }
        self._send_json(result)

    def _serve_export(self, query: str):
        qs = parse_qs(query)
        fmt = qs.get("format", ["json"])[0]
        start = qs.get("start", [None])[0]
        end = qs.get("end", [None])[0]
        fav_only = qs.get("favorites", ["0"])[0] == "1"
        if fav_only:
            news, _ = db_query_news(limit=10000, is_favorite=True)
        else:
            news = db_get_all_for_export(start, end)
        ts_str = now_bj().strftime("%Y%m%d_%H%M%S")

        if fmt == "csv":
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
            self.send_response(200)
            self.send_header("Content-Type", "text/csv; charset=utf-8")
            self.send_header(
                "Content-Disposition",
                f'attachment; filename="finfeed_news_{ts_str}.csv"'
            )
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)
        elif fmt == "markdown" or fmt == "md":
            lines = [f"# FinFeed 财经新闻导出", f"", f"导出时间: {now_bj().strftime('%Y-%m-%d %H:%M:%S')}", f"共 {len(news)} 条新闻", f""]
            for n in news:
                time_str = n.publish_time or ""
                lines.append(f"### [{n.title}]({n.url})")
                lines.append(f"**来源**: {n.source} | **时间**: {time_str}")
                if n.intro:
                    lines.append(f"> {n.intro}")
                lines.append("")
            content = "\n".join(lines)
            data = content.encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/markdown; charset=utf-8")
            self.send_header(
                "Content-Disposition",
                f'attachment; filename="finfeed_news_{ts_str}.md"'
            )
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)
        else:
            news_dicts = [n.to_dict() for n in news]
            data = json.dumps(news_dicts, ensure_ascii=False, indent=2).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header(
                "Content-Disposition",
                f'attachment; filename="finfeed_news_{ts_str}.json"'
            )
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

    def _serve_daterange(self):
        min_date, max_date, dates = db_get_date_range()
        d = {"min": min_date, "max": max_date, "dates": dates}
        self._send_json(d)

    def _serve_detail(self):
        qs = parse_qs(urlparse(self.path).query)
        news_id = int(qs.get("id", ["0"])[0])
        news = db_get_news_by_id(news_id)
        if news:
            db_mark_read(news_id, True)
            result = {"success": True, "news": news.to_dict()}
        else:
            result = {"success": False, "error": "News not found"}
        self._send_json(result)

    def _handle_toggle_favorite(self, data: dict):
        try:
            news_id = int(data.get("id", 0))
            if news_id <= 0:
                self._send_json({"success": False, "error": "Invalid id"}, status=400)
                return
            new_state = db_toggle_favorite(news_id)
            invalidate_api_cache()
            self._send_json({"success": True, "is_favorite": new_state})
        except Exception as e:
            self._send_json({"success": False, "error": str(e)}, status=500)

    def _handle_mark_read(self, data: dict):
        try:
            news_id = int(data.get("id", 0))
            is_read = bool(data.get("read", True))
            if news_id <= 0:
                self._send_json({"success": False, "error": "Invalid id"}, status=400)
                return
            db_mark_read(news_id, is_read)
            invalidate_api_cache()
            self._send_json({"success": True})
        except Exception as e:
            self._send_json({"success": False, "error": str(e)}, status=500)

    def _serve_health(self):
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
        result = {
            "status": "ok",
            "server_ts": time.time(),
            "total_news": stats["total_news"],
            "total_24h": stats["total_24h"],
            "favorite_count": stats["favorite_count"],
            "unread_count": stats["unread_count"],
            "sources": health_data,
        }
        self._send_json(result)

    def _serve_stock_names(self):
        """返回股票代码->名称映射，供前端展示使用"""
        cache_key = "stock_names_map"
        cached = _cache_get(cache_key)
        if cached is not None:
            self._send_json(cached, max_age=300)
            return
        try:
            stock_map = db_get_all_stock_names()
            if not stock_map:
                from finfeed.analysis.stock_names import STOCK_NAMES
                stock_map = dict(STOCK_NAMES)
            result = {"stock_names": stock_map}
            _cache_set(cache_key, result)
            self._send_json(result, max_age=300)
        except Exception as e:
            logger.error(f"获取股票名称映射失败: {e}")
            self._send_json({"stock_names": {}}, status=500)

    def _serve_stats(self):
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
        except Exception as e:
            logger.error(f"获取数据源状态失败: {e}")
            logger.error(traceback.format_exc())

        stats["source_health"] = source_list
        self._send_json(stats)

    def _serve_sse(self):
        logger.info(f"SSE连接请求: {self.client_address}")
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Connection", "keep-alive")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()

        client_queue: queue.Queue = queue.Queue()
        with _sse_clients_lock:
            _sse_clients.add(client_queue)
            logger.info(f"SSE客户端已连接, 当前客户端数: {len(_sse_clients)}")

        try:
            self.wfile.write(b"event: connected\ndata: {\"type\":\"connected\"}\n\n")
            self.wfile.flush()

            while True:
                try:
                    msg = client_queue.get(timeout=15)
                    data_str = json.dumps(msg, ensure_ascii=False)
                    self.wfile.write(f"event: news\ndata: {data_str}\n\n".encode("utf-8"))
                    self.wfile.flush()
                    logger.debug(f"SSE消息发送: {msg.get('type')}, count={msg.get('count',0)}")
                except queue.Empty:
                    self.wfile.write(b": ping\n\n")
                    self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError):
            logger.info(f"SSE连接断开: {self.client_address}")
        except Exception as e:
            logger.error(f"SSE异常: {e}")
        finally:
            with _sse_clients_lock:
                _sse_clients.discard(client_queue)
                logger.info(f"SSE客户端已断开, 当前客户端数: {len(_sse_clients)}")

    def _serve_dashboard(self):
        dashboard_html = _get_dashboard_html()
        data = dashboard_html.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _serve_about(self):
        about_html = _get_about_html()
        data = about_html.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _serve_sentiment(self):
        sentiment_html = _get_sentiment_html()
        data = sentiment_html.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _serve_ai_analysis(self):
        ai_html = _get_ai_analysis_html()
        data = ai_html.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _serve_llm_export(self, parsed):
        qs = parse_qs(parsed.query)
        rid = int(qs.get("id", ["0"])[0] or 0)
        fmt = qs.get("fmt", ["md"])[0] or "md"
        out = llm_api.export_report(rid, fmt)
        if not out:
            self.send_error(404)
            return
        filename, body, content_type = out
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header(
            "Content-Disposition",
            f'attachment; filename="{filename}"'
        )
        self.end_headers()
        self.wfile.write(body)

    def _send_json(self, data: dict, status: int = 200, max_age: int = 0):
        resp = json.dumps(data, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        accept_encoding = self.headers.get("Accept-Encoding", "")
        use_gzip = "gzip" in accept_encoding and len(resp) > 500

        if use_gzip:
            resp = gzip.compress(resp, compresslevel=1)

        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Access-Control-Allow-Origin", "*")
        if max_age > 0:
            self.send_header("Cache-Control", f"private, max-age={max_age}")
        else:
            self.send_header("Cache-Control", "no-cache")
        if use_gzip:
            self.send_header("Content-Encoding", "gzip")
        self.send_header("Content-Length", str(len(resp)))
        self.end_headers()
        self.wfile.write(resp)

    def log_message(self, fmt, *args):
        pass


def _sse_broadcast(message: dict):
    with _sse_clients_lock:
        client_count = len(_sse_clients)
        dead_clients = set()
        for q in _sse_clients:
            try:
                q.put_nowait(message)
            except queue.Full:
                dead_clients.add(q)
        for q in dead_clients:
            _sse_clients.discard(q)
        if client_count > 0:
            logger.info(f"SSE广播: {len(_sse_clients)} 客户端, 消息类型: {message.get('type')}, 数量: {message.get('count', 0)}")


def start_web_server(port: int = DEFAULT_WEB_PORT) -> DualStackThreadingHTTPServer:
    """在后台线程启动 Web 仪表盘服务（支持IPv4/IPv6双栈）"""
    global _global_server
    try:
        server = DualStackThreadingHTTPServer(("::", port), _WebHandler)
    except OSError:
        server = ThreadingHTTPServer(("0.0.0.0", port), _WebHandler)
        server.daemon_threads = True
    _global_server = server
    t = threading.Thread(
        target=server.serve_forever, daemon=True, name="web-dashboard"
    )
    t.start()
    logger.info(f"Web 服务已启动: http://localhost:{port}")
    return server


def update_web_state(news, stats, cycle, total, new_count, status, force_broadcast=False):
    """更新 Web 仪表盘共享状态（线程安全）
    
    force_broadcast: 强制广播 SSE 消息，不依赖时间戳比较
    """
    news_dicts = [n.to_dict() if isinstance(n, NewsItem) else n for n in news[:500]]
    sources_list = list(dict.fromkeys(get_display_name(k) for k in stats.keys()))
    last_update = now_bj().strftime("%Y-%m-%d %H:%M:%S")

    latest_id = 0
    if news_dicts:
        for n in news_dicts:
            nid = n.get("id", 0)
            if nid > latest_id:
                latest_id = nid

    new_items = []
    new_finance_items = []
    new_forum_items = []
    with _web_state_lock:
        old_latest_id = _web_state.get("latest_id", 0)
        
        if force_broadcast and news_dicts:
            for n in news_dicts:
                new_items.append(n)
                cat = n.get("category", "")
                if cat == "forum":
                    new_forum_items.append(n)
                else:
                    new_finance_items.append(n)
        elif latest_id > old_latest_id and news_dicts:
            for n in news_dicts:
                if n.get("id", 0) > old_latest_id:
                    new_items.append(n)
                    cat = n.get("category", "")
                    if cat == "forum":
                        new_forum_items.append(n)
                    else:
                        new_finance_items.append(n)
        
        _web_state["news"] = news_dicts
        _web_state["stats"] = stats
        _web_state["cycle"] = cycle
        _web_state["total"] = total
        _web_state["new_count"] = new_count
        _web_state["status"] = status
        _web_state["sources"] = sources_list
        _web_state["last_update"] = last_update
        _web_state["server_ts"] = time.time()
        if new_items:
            _web_state["latest_id"] = max(latest_id, old_latest_id)

    logger.info(f"update_web_state: force_broadcast={force_broadcast}, news_count={len(news_dicts)}, new_items={len(new_items)}, finance={len(new_finance_items)}, forum={len(new_forum_items)}, old_latest_id={old_latest_id}, latest_id={latest_id}")

    if new_items:
        invalidate_api_cache()
        if new_finance_items:
            logger.info(f"SSE广播finance: {len(new_finance_items)}条, 客户端数: {len(_sse_clients)}")
            _sse_broadcast({
                "type": "new_news",
                "category": "finance",
                "items": new_finance_items[:20],
                "count": len(new_finance_items),
                "ts": time.time(),
            })
        if new_forum_items:
            logger.info(f"SSE广播forum: {len(new_forum_items)}条, 客户端数: {len(_sse_clients)}")
            _sse_broadcast({
                "type": "new_news",
                "category": "forum",
                "items": new_forum_items[:20],
                "count": len(new_forum_items),
                "ts": time.time(),
            })
    else:
        logger.info(f"update_web_state: 无新新闻可广播, force_broadcast={force_broadcast}, news_dicts_len={len(news_dicts)}")


_global_server: Optional[DualStackThreadingHTTPServer] = None


def stop_web_server(timeout: float = 5.0) -> None:
    """优雅停止Web服务器
    
    关闭所有SSE连接，停止接受新请求，等待现有请求完成
    """
    global _global_server
    
    with _sse_clients_lock:
        for q in _sse_clients:
            try:
                q.put_nowait({"type": "shutdown"})
            except Exception as e:
                logger.debug(f"SSE 关闭通知失败: {e}")
        _sse_clients.clear()
    
    if _global_server:
        threading.Thread(target=_global_server.shutdown, daemon=True).start()
        _global_server = None
        logger.info("Web服务器已发送关闭信号")
