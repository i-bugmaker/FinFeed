#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Web 仪表盘服务

提供 HTTP API 和前端页面，支持：
- 实时新闻列表
- 来源筛选
- 日期范围选择
- JSON/CSV 导出
- FTS5 全文搜索
- 健康检查端点
"""

import os
import csv
import json
import time
import logging
import threading
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs

from config.settings import get_display_name, DEFAULT_WEB_PORT
from config.sources import get_enabled_sources
from utils.time_utils import now_bj
from storage.database import (
    db_get_all_for_export, db_get_date_range, db_search_news,
    db_get_news_by_id, db_get_recent_news,
)
from storage.models import NewsItem

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
}
_web_state_lock = threading.Lock()

_template_cache: str | None = None
_template_mtime: float = 0
_dashboard_cache: str | None = None
_dashboard_mtime: float = 0
_about_cache: str | None = None
_about_mtime: float = 0
_template_lock = threading.Lock()


def _get_template() -> str:
    """获取 HTML 模板（带文件修改时间检测，支持开发热重载）"""
    global _template_cache, _template_mtime
    template_path = os.path.join(
        os.path.dirname(os.path.abspath(__file__)),
        "templates", "index.html"
    )
    try:
        current_mtime = os.path.getmtime(template_path)
    except OSError:
        current_mtime = 0
    
    with _template_lock:
        if _template_cache is not None and current_mtime <= _template_mtime:
            return _template_cache
    
    try:
        with open(template_path, "r", encoding="utf-8") as f:
            content = f.read()
        with _template_lock:
            _template_cache = content
            _template_mtime = current_mtime
            return _template_cache
    except Exception as e:
        logger.warning(f"加载模板失败: {e}")
        with _template_lock:
            if _template_cache is None:
                _template_cache = "<h1>Template not found</h1>"
            return _template_cache


_dashboard_mtime: float = 0

def _get_dashboard_html() -> str:
    """获取可视化大屏 HTML（带文件修改时间检测）"""
    global _dashboard_cache, _dashboard_mtime
    dashboard_path = os.path.join(
        os.path.dirname(os.path.abspath(__file__)),
        "templates", "dashboard.html"
    )
    try:
        current_mtime = os.path.getmtime(dashboard_path)
    except OSError:
        current_mtime = 0
    
    with _template_lock:
        if _dashboard_cache is not None and current_mtime <= _dashboard_mtime:
            return _dashboard_cache
    
    try:
        with open(dashboard_path, "r", encoding="utf-8") as f:
            content = f.read()
        with _template_lock:
            _dashboard_cache = content
            _dashboard_mtime = current_mtime
            return _dashboard_cache
    except Exception as e:
        logger.warning(f"加载大屏模板失败: {e}")
        with _template_lock:
            if _dashboard_cache is None:
                _dashboard_cache = "<h1>Dashboard template not found</h1>"
            return _dashboard_cache


def _get_about_html() -> str:
    """获取关于页面 HTML（带文件修改时间检测）"""
    global _about_cache, _about_mtime
    about_path = os.path.join(
        os.path.dirname(os.path.abspath(__file__)),
        "templates", "about.html"
    )
    try:
        current_mtime = os.path.getmtime(about_path)
    except OSError:
        current_mtime = 0
    
    with _template_lock:
        if _about_cache is not None and current_mtime <= _about_mtime:
            return _about_cache
    
    try:
        with open(about_path, "r", encoding="utf-8") as f:
            content = f.read()
        with _template_lock:
            _about_cache = content
            _about_mtime = current_mtime
            return _about_cache
    except Exception as e:
        logger.warning(f"加载关于页面模板失败: {e}")
        with _template_lock:
            if _about_cache is None:
                _about_cache = "<h1>About template not found</h1>"
            return _about_cache


class _WebHandler(BaseHTTPRequestHandler):
    """Web 仪表盘 HTTP 请求处理器"""

    def do_GET(self):
        parsed = urlparse(self.path)

        if parsed.path == "/" or parsed.path.startswith("/index"):
            self._serve_html()
        elif parsed.path.startswith("/api/news"):
            self._serve_news()
        elif parsed.path.startswith("/api/search"):
            self._serve_search()
        elif parsed.path.startswith("/api/export"):
            self._serve_export(parsed.query)
        elif parsed.path.startswith("/api/daterange"):
            self._serve_daterange()
        elif parsed.path.startswith("/api/detail"):
            self._serve_detail()
        elif parsed.path.startswith("/api/health"):
            self._serve_health()
        elif parsed.path.startswith("/api/stats"):
            self._serve_stats()
        elif parsed.path.startswith("/dashboard"):
            self._serve_dashboard()
        elif parsed.path.startswith("/about"):
            self._serve_about()
        else:
            self.send_error(404)

    def do_POST(self):
        parsed = urlparse(self.path)
        self.send_error(404)

    def _serve_html(self):
        data = _get_template().encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _serve_news(self):
        qs = parse_qs(urlparse(self.path).query)
        limit = int(qs.get("limit", ["2000"])[0])
        source = qs.get("source", ["all"])[0]
        if limit > 10000:
            limit = 10000
        news = db_get_recent_news(limit=limit, source=source if source != "all" else None)
        news_dicts = [n.to_dict() for n in news]
        with _web_state_lock:
            stats = dict(_web_state.get("stats", {}))
            cycle = _web_state.get("cycle", 0)
            total = _web_state.get("total", 0)
            new_count = _web_state.get("new_count", 0)
            status = _web_state.get("status", "运行中")
            last_update = _web_state.get("last_update", "")
        configured_sources = list(dict.fromkeys(get_display_name(s.name) for s in get_enabled_sources()))
        result = {
            "news": news_dicts,
            "stats": stats,
            "cycle": cycle,
            "total": total,
            "new_count": new_count,
            "status": status,
            "sources": configured_sources,
            "last_update": last_update,
            "server_ts": time.time(),
        }
        data = json.dumps(result, ensure_ascii=False).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

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
        data = json.dumps(result, ensure_ascii=False).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _serve_export(self, query: str):
        qs = parse_qs(query)
        fmt = qs.get("format", ["json"])[0]
        start = qs.get("start", [None])[0]
        end = qs.get("end", [None])[0]
        news = db_get_all_for_export(start, end)
        ts_str = now_bj().strftime("%Y%m%d_%H%M%S")

        if fmt == "csv":
            import io
            buf = io.StringIO()
            w = csv.writer(buf)
            w.writerow(["标题", "链接", "来源", "发布时间", "时间戳", "简介"])
            for n in news:
                w.writerow([n.title, n.url, n.source, n.publish_time, n.publish_ts, n.intro])
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
        data = json.dumps(d, ensure_ascii=False).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _serve_detail(self):
        qs = parse_qs(urlparse(self.path).query)
        news_id = int(qs.get("id", ["0"])[0])
        news = db_get_news_by_id(news_id)
        if news:
            result = {"success": True, "news": news.to_dict()}
        else:
            result = {"success": False, "error": "News not found"}
        data = json.dumps(result, ensure_ascii=False).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _serve_health(self):
        from core.health import get_health_monitor
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
        result = {
            "status": "ok",
            "server_ts": time.time(),
            "total_news": _web_state.get("total", 0),
            "cycle": _web_state.get("cycle", 0),
            "sources": health_data,
        }
        data = json.dumps(result, ensure_ascii=False).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _serve_stats(self):
        from analysis.stats import get_dashboard_stats
        qs = parse_qs(urlparse(self.path).query)
        range_type = qs.get("range", ["24h"])[0]
        stats = get_dashboard_stats(range_type)
        data = json.dumps(stats, ensure_ascii=False).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

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

    def log_message(self, fmt, *args):
        pass


def start_web_server(port: int = DEFAULT_WEB_PORT) -> HTTPServer:
    """在后台线程启动 Web 仪表盘服务"""
    server = HTTPServer(("0.0.0.0", port), _WebHandler)
    server.daemon_threads = True
    t = threading.Thread(
        target=server.serve_forever, daemon=True, name="web-dashboard"
    )
    t.start()
    return server


def update_web_state(news, stats, cycle, total, new_count, status):
    """更新 Web 仪表盘共享状态（线程安全）"""
    news_dicts = [n.to_dict() if isinstance(n, NewsItem) else n for n in news[:500]]
    sources_list = list(dict.fromkeys(get_display_name(k) for k in stats.keys()))
    last_update = now_bj().strftime("%Y-%m-%d %H:%M:%S")
    with _web_state_lock:
        _web_state["news"] = news_dicts
        _web_state["stats"] = stats
        _web_state["cycle"] = cycle
        _web_state["total"] = total
        _web_state["new_count"] = new_count
        _web_state["status"] = status
        _web_state["sources"] = sources_list
        _web_state["last_update"] = last_update
        _web_state["server_ts"] = time.time()
