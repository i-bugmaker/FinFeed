#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Web 仪表盘服务

提供 HTTP API 和前端页面，支持：
- 实时新闻列表
- 来源筛选
- 日期范围选择
- JSON/CSV 导出
- FTS5 全文搜索
- 收藏/标记/已读状态管理
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
    db_toggle_favorite, db_get_favorites, db_mark_read, db_get_news_by_id,
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
_dashboard_cache: str | None = None
_template_lock = threading.Lock()


def _get_template() -> str:
    """获取 HTML 模板（带缓存，线程安全）"""
    global _template_cache
    with _template_lock:
        if _template_cache is not None:
            return _template_cache
    template_path = os.path.join(
        os.path.dirname(os.path.abspath(__file__)),
        "templates", "index.html"
    )
    try:
        with open(template_path, "r", encoding="utf-8") as f:
            content = f.read()
        with _template_lock:
            _template_cache = content
            return _template_cache
    except Exception as e:
        logger.warning(f"加载模板失败: {e}")
        with _template_lock:
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
        elif parsed.path.startswith("/api/favorites"):
            self._serve_favorites()
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
        content_length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(content_length).decode("utf-8") if content_length > 0 else ""

        if parsed.path.startswith("/api/favorite/toggle"):
            self._handle_favorite_toggle(body)
        elif parsed.path.startswith("/api/read"):
            self._handle_mark_read(body)
        else:
            self.send_error(404)

    def _serve_html(self):
        data = _get_template().encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _serve_news(self):
        with _web_state_lock:
            state = dict(_web_state)
        state["server_ts"] = time.time()
        data = json.dumps(state, ensure_ascii=False).encode("utf-8")
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

    def _serve_favorites(self):
        news = db_get_favorites(limit=200)
        result = {
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

    def _handle_favorite_toggle(self, body: str):
        try:
            data = json.loads(body) if body else {}
            news_id = data.get("id", 0)
            if news_id:
                new_state = db_toggle_favorite(int(news_id))
                result = {"success": True, "is_favorite": new_state}
            else:
                result = {"success": False, "error": "Invalid id"}
        except Exception as e:
            result = {"success": False, "error": str(e)}
        resp = json.dumps(result, ensure_ascii=False).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Content-Length", str(len(resp)))
        self.end_headers()
        self.wfile.write(resp)

    def _handle_mark_read(self, body: str):
        try:
            data = json.loads(body) if body else {}
            news_id = data.get("id", 0)
            is_read = data.get("is_read", True)
            if news_id:
                db_mark_read(int(news_id), is_read)
                result = {"success": True}
            else:
                result = {"success": False, "error": "Invalid id"}
        except Exception as e:
            result = {"success": False, "error": str(e)}
        resp = json.dumps(result, ensure_ascii=False).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Content-Length", str(len(resp)))
        self.end_headers()
        self.wfile.write(resp)

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
    news_dicts = [n.to_dict() if isinstance(n, NewsItem) else n for n in news[:300]]
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
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>FinFeed 数据可视化大屏</title>
<script src="https://cdn.jsdelivr.net/npm/echarts@5.4.3/dist/echarts.min.js"></script>
<style>
* { margin: 0; padding: 0; box-sizing: border-box; }
body {
    background: linear-gradient(135deg, #0c1929 0%, #1a2a4a 50%, #0f1f35 100%);
    color: #fff;
    font-family: 'Microsoft YaHei', sans-serif;
    min-height: 100vh;
    overflow-x: hidden;
}
.header {
    text-align: center;
    padding: 20px 0;
    background: linear-gradient(90deg, transparent, rgba(0, 200, 255, 0.1), transparent);
    border-bottom: 1px solid rgba(0, 200, 255, 0.2);
}
.header h1 {
    font-size: 32px;
    background: linear-gradient(90deg, #00d4ff, #00ff88);
    -webkit-background-clip: text;
    -webkit-text-fill-color: transparent;
    letter-spacing: 4px;
}
.header .subtitle {
    color: #8899aa;
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
    background: linear-gradient(135deg, rgba(0, 150, 255, 0.1), rgba(0, 200, 255, 0.05));
    border: 1px solid rgba(0, 200, 255, 0.3);
    border-radius: 10px;
    padding: 15px 30px;
    text-align: center;
    min-width: 150px;
}
.stat-card .number {
    font-size: 36px;
    font-weight: bold;
    color: #00d4ff;
    text-shadow: 0 0 20px rgba(0, 200, 255, 0.5);
}
.stat-card .label {
    color: #8899aa;
    font-size: 14px;
    margin-top: 5px;
}
.charts-grid {
    display: grid;
    grid-template-columns: 1fr 1fr 1fr;
    grid-template-rows: auto auto;
    gap: 20px;
    padding: 20px 40px;
}
.chart-box {
    background: rgba(0, 30, 60, 0.5);
    border: 1px solid rgba(0, 200, 255, 0.2);
    border-radius: 10px;
    padding: 15px;
    height: 320px;
}
.chart-box h3 {
    color: #00d4ff;
    font-size: 16px;
    margin-bottom: 10px;
    padding-bottom: 8px;
    border-bottom: 1px solid rgba(0, 200, 255, 0.2);
}
.chart {
    width: 100%;
    height: calc(100% - 35px);
}
.footer {
    text-align: center;
    padding: 15px;
    color: #556677;
    font-size: 12px;
}
@media (max-width: 1200px) {
    .charts-grid { grid-template-columns: 1fr 1fr; }
}
@media (max-width: 768px) {
    .charts-grid { grid-template-columns: 1fr; }
    .stat-card { min-width: 120px; padding: 10px 15px; }
    .stat-card .number { font-size: 24px; }
}
</style>
</head>
<body>
<div class="header">
    <h1>FinFeed 财经新闻数据大屏</h1>
    <div class="subtitle" id="updateTime">加载中...</div>
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
    <div class="chart-box">
        <h3>🔥 热门关键词</h3>
        <div class="chart" id="keywordChart"></div>
    </div>
</div>

<div class="footer">FinFeed 实时财经新闻监控系统 | 数据每 30 秒自动刷新</div>

<script>
let sourceChart, trendChart, sentimentChart, categoryChart, importanceChart, keywordChart;

function initCharts() {
    sourceChart = echarts.init(document.getElementById('sourceChart'));
    trendChart = echarts.init(document.getElementById('trendChart'));
    sentimentChart = echarts.init(document.getElementById('sentimentChart'));
    categoryChart = echarts.init(document.getElementById('categoryChart'));
    importanceChart = echarts.init(document.getElementById('importanceChart'));
    keywordChart = echarts.init(document.getElementById('keywordChart'));
    window.addEventListener('resize', () => {
        sourceChart.resize();
        trendChart.resize();
        sentimentChart.resize();
        categoryChart.resize();
        importanceChart.resize();
        keywordChart.resize();
    });
}

function updateCharts(data) {
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
        xAxis: { type: 'value', axisLabel: { color: '#8899aa' }, splitLine: { lineStyle: { color: 'rgba(0,200,255,0.1)' } } },
        yAxis: { type: 'category', data: sourceData.map(d => d.name).reverse(), axisLabel: { color: '#8899aa' } },
        series: [{
            type: 'bar',
            data: sourceData.map(d => d.value).reverse(),
            itemStyle: {
                color: new echarts.graphic.LinearGradient(0, 0, 1, 0, [
                    { offset: 0, color: '#00d4ff' },
                    { offset: 1, color: '#0066ff' }
                ])
            },
            barWidth: '60%'
        }]
    });

    trendChart.setOption({
        tooltip: { trigger: 'axis' },
        grid: { left: '3%', right: '4%', bottom: '3%', containLabel: true },
        xAxis: { type: 'category', data: data.time_trend.map(d => d.time), axisLabel: { color: '#8899aa' } },
        yAxis: { type: 'value', axisLabel: { color: '#8899aa' }, splitLine: { lineStyle: { color: 'rgba(0,200,255,0.1)' } } },
        series: [{
            type: 'line',
            data: data.time_trend.map(d => d.count),
            smooth: true,
            lineStyle: { color: '#00ff88', width: 2 },
            areaStyle: {
                color: new echarts.graphic.LinearGradient(0, 0, 0, 1, [
                    { offset: 0, color: 'rgba(0, 255, 136, 0.3)' },
                    { offset: 1, color: 'rgba(0, 255, 136, 0)' }
                ])
            },
            itemStyle: { color: '#00ff88' }
        }]
    });

    const sentimentData = [
        { name: '正面', value: data.sentiment_stats.positive, itemStyle: { color: '#00ff88' } },
        { name: '中性', value: data.sentiment_stats.neutral, itemStyle: { color: '#ffaa00' } },
        { name: '负面', value: data.sentiment_stats.negative, itemStyle: { color: '#ff4466' } }
    ];
    sentimentChart.setOption({
        tooltip: { trigger: 'item', formatter: '{b}: {c} ({d}%)' },
        legend: { bottom: 0, textStyle: { color: '#8899aa' } },
        series: [{
            type: 'pie',
            radius: ['40%', '70%'],
            center: ['50%', '45%'],
            avoidLabelOverlap: false,
            label: { show: false },
            emphasis: {
                label: { show: true, fontSize: 16, fontWeight: 'bold', color: '#fff' }
            },
            data: sentimentData
        }]
    });

    const catData = Object.entries(data.category_stats)
        .sort((a, b) => b[1] - a[1])
        .slice(0, 8);
    categoryChart.setOption({
        tooltip: { trigger: 'item', formatter: '{b}: {c} ({d}%)' },
        legend: { type: 'scroll', bottom: 0, textStyle: { color: '#8899aa', fontSize: 11 } },
        series: [{
            type: 'pie',
            radius: ['35%', '65%'],
            center: ['50%', '42%'],
            data: catData.map(([name, value]) => ({ name, value })),
            label: { show: false }
        }],
        color: ['#00d4ff', '#00ff88', '#ffaa00', '#ff66cc', '#aa66ff', '#66ffcc', '#ff9966', '#6699ff']
    });

    const impData = data.importance_distribution;
    importanceChart.setOption({
        tooltip: { trigger: 'axis' },
        grid: { left: '3%', right: '4%', bottom: '3%', containLabel: true },
        xAxis: {
            type: 'category',
            data: ['极重要', '重要', '一般', '较低', '低'],
            axisLabel: { color: '#8899aa' }
        },
        yAxis: { type: 'value', axisLabel: { color: '#8899aa' }, splitLine: { lineStyle: { color: 'rgba(0,200,255,0.1)' } } },
        series: [{
            type: 'bar',
            data: [impData['极重要'] || 0, impData['重要'] || 0, impData['一般'] || 0, impData['较低'] || 0, impData['低'] || 0],
            itemStyle: {
                color: function(params) {
                    const colors = ['#ff4466', '#ff9933', '#ffdd33', '#66ccff', '#99aabb'];
                    return colors[params.dataIndex];
                }
            },
            barWidth: '50%'
        }]
    });

    const kwData = data.top_keywords.slice(0, 10).reverse();
    keywordChart.setOption({
        tooltip: { trigger: 'item' },
        grid: { left: '3%', right: '4%', bottom: '3%', containLabel: true },
        xAxis: { type: 'value', axisLabel: { color: '#8899aa' }, splitLine: { lineStyle: { color: 'rgba(0,200,255,0.1)' } } },
        yAxis: { type: 'category', data: kwData.map(d => d.keyword), axisLabel: { color: '#8899aa' } },
        series: [{
            type: 'bar',
            data: kwData.map(d => d.count),
            itemStyle: {
                color: new echarts.graphic.LinearGradient(0, 0, 1, 0, [
                    { offset: 0, color: '#ff66cc' },
                    { offset: 1, color: '#aa66ff' }
                ])
            },
            barWidth: '60%'
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
