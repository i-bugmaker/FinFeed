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


def _get_dashboard_html() -> str:
    """获取可视化大屏 HTML（带缓存）"""
    global _dashboard_cache
    if _dashboard_cache is not None:
        return _dashboard_cache
    _dashboard_cache = _DASHBOARD_HTML
    return _dashboard_cache


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
            sources_list = list(dict.fromkeys(get_display_name(k) for k in stats.keys()))
            last_update = _web_state.get("last_update", "")
        result = {
            "news": news_dicts,
            "stats": stats,
            "cycle": cycle,
            "total": total,
            "new_count": new_count,
            "status": status,
            "sources": sources_list,
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
        stats = get_dashboard_stats()
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


_DASHBOARD_HTML = r"""<!DOCTYPE html>
<html lang="zh-CN" data-theme="dark">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>FinFeed 数据可视化大屏</title>
<script src="https://cdn.jsdelivr.net/npm/echarts@5.4.3/dist/echarts.min.js"></script>
<style>
:root,[data-theme="dark"]{
  --bg-grad-1:#0c1929;--bg-grad-2:#1a2a4a;--bg-grad-3:#0f1f35;
  --bg-card:rgba(0,30,60,0.5);--bg-card-grad-1:rgba(0,150,255,0.1);--bg-card-grad-2:rgba(0,200,255,0.05);
  --text:#ffffff;--text2:#8899aa;--text3:#556677;
  --border:rgba(0,200,255,0.2);--border-strong:rgba(0,200,255,0.3);
  --accent:#00d4ff;--accent-glow:rgba(0,200,255,0.5);--accent2:#00ff88;
  --green:#00ff88;--orange:#ffaa00;--red:#ff4466;--purple:#aa66ff;--pink:#ff66cc;
  --header-grad:linear-gradient(90deg,transparent,rgba(0,200,255,0.1),transparent);
  --title-grad:linear-gradient(90deg,#00d4ff,#00ff88);
  --shadow:0 0 20px rgba(0,200,255,0.3);
  --chart-axis:#8899aa;--chart-split:rgba(0,200,255,0.1);
}
[data-theme="light"]{
  --bg-grad-1:#e8eef5;--bg-grad-2:#f0f4f8;--bg-grad-3:#e2e8f0;
  --bg-card:rgba(255,255,255,0.85);--bg-card-grad-1:rgba(37,99,235,0.06);--bg-card-grad-2:rgba(37,99,235,0.03);
  --text:#1a1d23;--text2:#4a5060;--text3:#7a8298;
  --border:rgba(37,99,235,0.15);--border-strong:rgba(37,99,235,0.3);
  --accent:#2563eb;--accent-glow:rgba(37,99,235,0.3);--accent2:#16a34a;
  --green:#16a34a;--orange:#ea580c;--red:#dc2626;--purple:#9333ea;--pink:#db2777;
  --header-grad:linear-gradient(90deg,transparent,rgba(37,99,235,0.08),transparent);
  --title-grad:linear-gradient(90deg,#2563eb,#16a34a);
  --shadow:0 2px 12px rgba(0,0,0,0.08);
  --chart-axis:#7a8298;--chart-split:rgba(37,99,235,0.08);
}
* { margin: 0; padding: 0; box-sizing: border-box; }
body {
    background: linear-gradient(135deg, var(--bg-grad-1) 0%, var(--bg-grad-2) 50%, var(--bg-grad-3) 100%);
    color: var(--text);
    font-family: 'Microsoft YaHei', sans-serif;
    min-height: 100vh;
    overflow-x: hidden;
    transition: background .3s, color .3s;
}
.header {
    position: relative;
    text-align: center;
    padding: 20px 0;
    background: var(--header-grad);
    border-bottom: 1px solid var(--border);
}
.theme-toggle{
    position:absolute;
    right:30px;top:50%;transform:translateY(-50%);
    background:var(--bg-card);
    color:var(--text2);
    border:1px solid var(--border);
    width:36px;height:36px;
    border-radius:8px;cursor:pointer;
    font-size:18px;
    display:flex;align-items:center;justify-content:center;
    transition:all .2s;z-index:10;
}
.theme-toggle:hover{border-color:var(--accent);color:var(--accent);transform:translateY(-50%) rotate(15deg)}
.back-btn{
    position:absolute;
    left:30px;top:50%;transform:translateY(-50%);
    background:var(--bg-card);
    color:var(--text2);
    border:1px solid var(--border);
    padding:6px 14px;
    border-radius:8px;cursor:pointer;
    font-size:13px;font-family:inherit;
    display:flex;align-items:center;gap:6px;
    transition:all .2s;z-index:10;text-decoration:none;
}
.back-btn:hover{border-color:var(--accent);color:var(--accent)}
.header h1 {
    font-size: 32px;
    background: var(--title-grad);
    -webkit-background-clip: text;
    -webkit-text-fill-color: transparent;
    background-clip: text;
    letter-spacing: 4px;
}
.header .subtitle {
    color: var(--text2);
    margin-top: 5px;
    font-size: 14px;
}
.stats-row {
    display: flex;
    justify-content: center;
    gap: 30px;
    padding: 20px 40px;
    flex-wrap: wrap;
}
.stat-card {
    background: linear-gradient(135deg, var(--bg-card-grad-1), var(--bg-card-grad-2));
    background-color: var(--bg-card);
    border: 1px solid var(--border-strong);
    border-radius: 10px;
    padding: 15px 30px;
    text-align: center;
    min-width: 150px;
    backdrop-filter: blur(10px);
    transition: all .3s;
}
.stat-card:hover {
    transform: translateY(-2px);
    box-shadow: var(--shadow);
}
.stat-card .number {
    font-size: 36px;
    font-weight: bold;
    color: var(--accent);
    text-shadow: 0 0 20px var(--accent-glow);
    transition: color .3s, text-shadow .3s;
}
[data-theme="light"] .stat-card .number {
    text-shadow: none;
}
.stat-card .label {
    color: var(--text2);
    font-size: 14px;
    margin-top: 5px;
    transition: color .3s;
}
.charts-grid {
    display: grid;
    grid-template-columns: 1fr 1fr 1fr;
    grid-template-rows: auto auto;
    gap: 20px;
    padding: 20px 40px;
}
.chart-box {
    background: var(--bg-card);
    border: 1px solid var(--border);
    border-radius: 10px;
    padding: 15px;
    height: 320px;
    backdrop-filter: blur(10px);
    transition: background .3s, border-color .3s;
}
.chart-box h3 {
    color: var(--accent);
    font-size: 16px;
    margin-bottom: 10px;
    padding-bottom: 8px;
    border-bottom: 1px solid var(--border);
    transition: color .3s, border-color .3s;
}
.chart {
    width: 100%;
    height: calc(100% - 35px);
}
.footer {
    text-align: center;
    padding: 15px;
    color: var(--text3);
    font-size: 12px;
    transition: color .3s;
}
@media (max-width: 1200px) {
    .charts-grid { grid-template-columns: 1fr 1fr; }
}
@media (max-width: 768px) {
    .charts-grid { grid-template-columns: 1fr; }
    .stat-card { min-width: 120px; padding: 10px 15px; }
    .stat-card .number { font-size: 24px; }
    .back-btn,.theme-toggle{position:static;transform:none;margin:10px;display:inline-flex}
    .header{padding-bottom:10px}
    .header h1{font-size:24px}
}
</style>
</head>
<body>
<div class="header">
    <a href="/" class="back-btn" title="返回主页">&#8592; 返回</a>
    <h1>FinFeed 财经新闻数据大屏</h1>
    <div class="subtitle" id="updateTime">加载中...</div>
    <button class="theme-toggle" id="theme-btn" onclick="toggleTheme()" title="切换主题">&#9790;</button>
</div>

<div class="stats-row">
    <div class="stat-card">
        <div class="number" id="totalNews">0</div>
        <div class="label">新闻总数</div>
    </div>
    <div class="stat-card">
        <div class="number" id="total24h">0</div>
        <div class="label">24小时新增</div>
    </div>
    <div class="stat-card">
        <div class="number" id="sourceCount">0</div>
        <div class="label">信息来源</div>
    </div>
    <div class="stat-card">
        <div class="number" id="posRate">-</div>
        <div class="label">正面情绪占比</div>
    </div>
</div>

<div class="charts-grid">
    <div class="chart-box">
        <h3>📊 来源分布</h3>
        <div class="chart" id="sourceChart"></div>
    </div>
    <div class="chart-box">
        <h3>📈 24小时趋势</h3>
        <div class="chart" id="trendChart"></div>
    </div>
    <div class="chart-box">
        <h3>😊 情绪分布</h3>
        <div class="chart" id="sentimentChart"></div>
    </div>
    <div class="chart-box">
        <h3>📂 分类分布</h3>
        <div class="chart" id="categoryChart"></div>
    </div>
    <div class="chart-box">
        <h3>⭐ 重要性分布</h3>
        <div class="chart" id="importanceChart"></div>
    </div>
</div>

<div class="footer">FinFeed 实时财经新闻监控系统 | 数据每 30 秒自动刷新</div>

<script>
let sourceChart, trendChart, sentimentChart, categoryChart, importanceChart;
let lastData = null;

function getTheme() {
    try { return document.documentElement.getAttribute('data-theme') || 'dark'; }
    catch(e) { return 'dark'; }
}

function getThemeColors() {
    const t = getTheme();
    if (t === 'light') {
        return {
            axis: '#7a8298',
            split: 'rgba(37,99,235,0.08)',
            barGrad1: '#2563eb',
            barGrad2: '#1d4ed8',
            line: '#16a34a',
            lineArea1: 'rgba(22,163,74,0.25)',
            lineArea2: 'rgba(22,163,74,0)',
            pos: '#16a34a',
            neu: '#ea580c',
            neg: '#dc2626',
            pieColors: ['#2563eb','#16a34a','#ea580c','#db2777','#9333ea','#0891b2','#f97316','#3b82f6'],
            impColors: ['#dc2626','#ea580c','#ca8a04','#3b82f6','#94a3b8'],
            kwGrad1: '#db2777',
            kwGrad2: '#9333ea',
            labelEmphasis: '#1a1d23'
        };
    }
    return {
        axis: '#8899aa',
        split: 'rgba(0,200,255,0.1)',
        barGrad1: '#00d4ff',
        barGrad2: '#0066ff',
        line: '#00ff88',
        lineArea1: 'rgba(0,255,136,0.3)',
        lineArea2: 'rgba(0,255,136,0)',
        pos: '#00ff88',
        neu: '#ffaa00',
        neg: '#ff4466',
        pieColors: ['#00d4ff','#00ff88','#ffaa00','#ff66cc','#aa66ff','#66ffcc','#ff9966','#6699ff'],
        impColors: ['#ff4466','#ff9933','#ffdd33','#66ccff','#99aabb'],
        kwGrad1: '#ff66cc',
        kwGrad2: '#aa66ff',
        labelEmphasis: '#fff'
    };
}

function setTheme(t) {
    document.documentElement.setAttribute('data-theme', t);
    const btn = document.getElementById('theme-btn');
    btn.innerHTML = t === 'dark' ? '\u2600' : '\u263E';
    btn.title = t === 'dark' ? '切换到亮色主题' : '切换到暗色主题';
    try { localStorage.setItem('finfeed_theme', t); } catch(e) {}
    if (sourceChart) {
        sourceChart.dispose();
        trendChart.dispose();
        sentimentChart.dispose();
        categoryChart.dispose();
        importanceChart.dispose();
    }
    initCharts();
    if (lastData) updateCharts(lastData);
}

function toggleTheme() {
    setTheme(getTheme() === 'dark' ? 'light' : 'dark');
}

try {
    const saved = localStorage.getItem('finfeed_theme');
    if (saved) setTheme(saved);
} catch(e) {}

function initCharts() {
    sourceChart = echarts.init(document.getElementById('sourceChart'));
    trendChart = echarts.init(document.getElementById('trendChart'));
    sentimentChart = echarts.init(document.getElementById('sentimentChart'));
    categoryChart = echarts.init(document.getElementById('categoryChart'));
    importanceChart = echarts.init(document.getElementById('importanceChart'));
    window.addEventListener('resize', () => {
        sourceChart.resize();
        trendChart.resize();
        sentimentChart.resize();
        categoryChart.resize();
        importanceChart.resize();
    });
}

function updateCharts(data) {
    lastData = data;
    const c = getThemeColors();
    document.getElementById('totalNews').textContent = data.total_news.toLocaleString();
    document.getElementById('total24h').textContent = data.total_24h.toLocaleString();
    document.getElementById('sourceCount').textContent = data.source_count;
    const total = data.sentiment_stats.positive + data.sentiment_stats.negative + data.sentiment_stats.neutral;
    const posRate = total > 0 ? ((data.sentiment_stats.positive / total) * 100).toFixed(1) + '%' : '-';
    document.getElementById('posRate').textContent = posRate;
    document.getElementById('updateTime').textContent = '更新时间: ' + data.update_time;

    const sourceData = Object.entries(data.source_stats)
        .sort((a, b) => b[1] - a[1])
        .slice(0, 10)
        .map(([name, value]) => ({ name, value }));
    sourceChart.setOption({
        tooltip: { trigger: 'item' },
        grid: { left: '3%', right: '4%', bottom: '3%', containLabel: true },
        xAxis: { type: 'value', axisLabel: { color: c.axis }, splitLine: { lineStyle: { color: c.split } } },
        yAxis: { type: 'category', data: sourceData.map(d => d.name).reverse(), axisLabel: { color: c.axis } },
        series: [{
            type: 'bar',
            data: sourceData.map(d => d.value).reverse(),
            itemStyle: {
                color: new echarts.graphic.LinearGradient(0, 0, 1, 0, [
                    { offset: 0, color: c.barGrad1 },
                    { offset: 1, color: c.barGrad2 }
                ])
            },
            barWidth: '60%'
        }]
    });

    trendChart.setOption({
        tooltip: { trigger: 'axis' },
        grid: { left: '3%', right: '4%', bottom: '3%', containLabel: true },
        xAxis: { type: 'category', data: data.time_trend.map(d => d.time), axisLabel: { color: c.axis } },
        yAxis: { type: 'value', axisLabel: { color: c.axis }, splitLine: { lineStyle: { color: c.split } } },
        series: [{
            type: 'line',
            data: data.time_trend.map(d => d.count),
            smooth: true,
            lineStyle: { color: c.line, width: 2 },
            areaStyle: {
                color: new echarts.graphic.LinearGradient(0, 0, 0, 1, [
                    { offset: 0, color: c.lineArea1 },
                    { offset: 1, color: c.lineArea2 }
                ])
            },
            itemStyle: { color: c.line }
        }]
    });

    const sentimentData = [
        { name: '正面', value: data.sentiment_stats.positive, itemStyle: { color: c.pos } },
        { name: '中性', value: data.sentiment_stats.neutral, itemStyle: { color: c.neu } },
        { name: '负面', value: data.sentiment_stats.negative, itemStyle: { color: c.neg } }
    ];
    sentimentChart.setOption({
        tooltip: { trigger: 'item', formatter: '{b}: {c} ({d}%)' },
        legend: { bottom: 0, textStyle: { color: c.axis } },
        series: [{
            type: 'pie',
            radius: ['40%', '70%'],
            center: ['50%', '45%'],
            avoidLabelOverlap: false,
            label: { show: false },
            emphasis: {
                label: { show: true, fontSize: 16, fontWeight: 'bold', color: c.labelEmphasis }
            },
            data: sentimentData
        }]
    });

    const catData = Object.entries(data.category_stats)
        .sort((a, b) => b[1] - a[1])
        .slice(0, 8);
    categoryChart.setOption({
        tooltip: { trigger: 'item', formatter: '{b}: {c} ({d}%)' },
        legend: { type: 'scroll', bottom: 0, textStyle: { color: c.axis, fontSize: 11 } },
        series: [{
            type: 'pie',
            radius: ['35%', '65%'],
            center: ['50%', '42%'],
            data: catData.map(([name, value]) => ({ name, value })),
            label: { show: false }
        }],
        color: c.pieColors
    });

    const impData = data.importance_distribution;
    importanceChart.setOption({
        tooltip: { trigger: 'axis' },
        grid: { left: '3%', right: '4%', bottom: '3%', containLabel: true },
        xAxis: {
            type: 'category',
            data: ['极重要', '重要', '一般', '较低', '低'],
            axisLabel: { color: c.axis }
        },
        yAxis: { type: 'value', axisLabel: { color: c.axis }, splitLine: { lineStyle: { color: c.split } } },
        series: [{
            type: 'bar',
            data: [impData['极重要'] || 0, impData['重要'] || 0, impData['一般'] || 0, impData['较低'] || 0, impData['低'] || 0],
            itemStyle: {
                color: function(params) {
                    return c.impColors[params.dataIndex];
                }
            },
            barWidth: '50%'
        }]
    });
}

async function loadData() {
    try {
        const resp = await fetch('/api/stats');
        const data = await resp.json();
        updateCharts(data);
    } catch (e) {
        console.error('加载数据失败:', e);
    }
}

initCharts();
loadData();
setInterval(loadData, 30000);
</script>
</body>
</html>"""
