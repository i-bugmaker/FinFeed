#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""日历模块 HTTP 接口

被 finfeed/ui/web_fastapi（routers/calendar.py）以「前缀路由」方式挂载，模块自洽：
    GET  /api/calendar/*  -> handle_get(path, query_dict)
    POST /api/calendar/*  -> handle_post(path, json_body)
返回 (status_code, dict)；返回 None 表示该路径不属于本模块。

端点一览：
    GET  /api/calendar/init                 前端初始化（类型、分类、默认日期）
    GET  /api/calendar/list                 按类型+日期区间查询事件
    GET  /api/calendar/overview             单日四类总览
    GET  /api/calendar/month                月历视图计数
    GET  /api/calendar/filters              动态筛选项
    GET  /api/calendar/stats                模块统计
    GET  /api/calendar/export               导出（由 server 层写响应体）
    POST /api/calendar/refresh              强制刷新指定区间
    POST /api/calendar/purge                清理历史数据
"""

import csv
import io
import json
import logging
from typing import Any, Dict, List, Optional, Tuple

from finfeed.utils.time_utils import now_bj

from . import service, store
from .schema import ensure_tables
from .sources import (
    CAL_TYPE_KEYS,
    CAL_TYPES,
    FINANCE_CATEGORIES,
    GLOBAL_COUNTRIES,
    IMPORTANCE_LABELS,
    IPO_CATEGORIES,
    STOCK_CATEGORIES,
)

logger = logging.getLogger("news_monitor")

Response = Optional[Tuple[int, Dict[str, Any]]]

MAX_LIMIT = 5000


def _q(qs: Dict[str, List[str]], key: str, default: str = "") -> str:
    v = qs.get(key)
    return (v[0] if v else default).strip()


def _qi(qs: Dict[str, List[str]], key: str, default: int = 0) -> int:
    try:
        return int(_q(qs, key, str(default)))
    except (TypeError, ValueError):
        return default


def _qb(qs: Dict[str, List[str]], key: str, default: bool = False) -> bool:
    v = _q(qs, key, "1" if default else "0").lower()
    return v in ("1", "true", "yes", "on")


def _cal_type(qs: Dict[str, List[str]], default: str = "all") -> str:
    """解析日历类型参数；缺省视为 'all'（全类型），避免静默退化为单类型"""
    t = _q(qs, "type", default)
    return t if t in CAL_TYPE_KEYS or t == "all" else default


# ============================================================
# GET
# ============================================================
def handle_get(path: str, qs: Dict[str, List[str]]) -> Response:
    if not path.startswith("/api/calendar"):
        return None
    ensure_tables()

    try:
        if path in ("/api/calendar/init", "/api/calendar"):
            return 200, _init_payload()

        if path == "/api/calendar/list":
            return 200, _list(qs)

        if path == "/api/calendar/overview":
            return 200, service.get_overview(
                date=_q(qs, "date"), refresh=_qb(qs, "refresh")
            )

        if path == "/api/calendar/month":
            return 200, service.get_month(
                cal_type=_cal_type(qs, "all"),
                month=_q(qs, "month"),
                refresh=_qb(qs, "refresh"),
            )

        if path == "/api/calendar/filters":
            return 200, _filters(qs)

        if path == "/api/calendar/stats":
            return 200, store.get_stats()

        return 404, {"error": "not found", "path": path}

    except Exception as e:  # noqa: BLE001
        logger.error(f"[calendar-api] GET {path} 失败: {type(e).__name__} {e}", exc_info=True)
        return 500, {"error": f"{type(e).__name__}: {e}"}


# ============================================================
# POST
# ============================================================
def handle_post(path: str, body: Dict[str, Any]) -> Response:
    if not path.startswith("/api/calendar"):
        return None
    ensure_tables()

    try:
        if path == "/api/calendar/refresh":
            ct = body.get("type") or "finance"
            types = CAL_TYPE_KEYS if ct == "all" else [ct]
            start = body.get("start") or service.today_str()
            end = body.get("end") or start
            info = service.sync_range(types, start, end, force=True)
            return 200, {"ok": not info.get("errors"), "sync": info}

        if path == "/api/calendar/purge":
            before = body.get("before") or ""
            if not before:
                return 400, {"error": "缺少 before 参数 (YYYY-MM-DD)"}
            n = store.purge_before(before)
            return 200, {"ok": True, "deleted": n}

        return 404, {"error": "not found", "path": path}

    except Exception as e:  # noqa: BLE001
        logger.error(f"[calendar-api] POST {path} 失败: {type(e).__name__} {e}", exc_info=True)
        return 500, {"error": f"{type(e).__name__}: {e}"}


# ============================================================
# 具体实现
# ============================================================
def _init_payload() -> Dict[str, Any]:
    today = service.today_str()
    return {
        "types": [{"key": k, **v} for k, v in CAL_TYPES.items()],
        "categories": {
            "finance": FINANCE_CATEGORIES,
            "stock": STOCK_CATEGORIES,
            "ipo": IPO_CATEGORIES,
            "global": GLOBAL_COUNTRIES,
        },
        "importance_labels": IMPORTANCE_LABELS,
        "today": today,
        "stats": store.get_stats(),
        "limits": {
            "max_sync_days_single": service.MAX_SYNC_DAYS_SINGLE,
            "max_sync_days_all": service.MAX_SYNC_DAYS_ALL,
        },
    }


def _list(qs: Dict[str, List[str]]) -> Dict[str, Any]:
    return service.get_events(
        cal_type=_cal_type(qs),
        start=_q(qs, "start"),
        end=_q(qs, "end"),
        category=_q(qs, "category"),
        region=_q(qs, "region"),
        keyword=_q(qs, "q"),
        importance_min=_qi(qs, "importance", 0),
        limit=min(_qi(qs, "limit", 3000), MAX_LIMIT),
        offset=_qi(qs, "offset", 0),
        refresh=_qb(qs, "refresh"),
        sync=_qb(qs, "sync", True),
    )


def _filters(qs: Dict[str, List[str]]) -> Dict[str, Any]:
    ct = _cal_type(qs)
    start, end = service.normalize_range(_q(qs, "start"), _q(qs, "end"))
    return {
        "cal_type": ct,
        "categories": store.distinct_values(ct, "category", start, end),
        "sub_types": store.distinct_values(ct, "sub_type", start, end),
        "regions": store.distinct_values(ct, "region", start, end),
    }


# ============================================================
# 导出（由 server 层直接写响应体）
# ============================================================
_EXPORT_FIELDS = [
    ("event_date", "日期"), ("event_time", "时间"), ("category", "分类"),
    ("sub_type", "类型"), ("code", "代码"), ("name", "名称"),
    ("region", "地区"), ("title", "事件"), ("importance", "重要性"),
    ("period", "报告期"), ("prev_value", "前值"),
    ("forecast_value", "预测值"), ("actual_value", "公布值"),
    ("content", "详情"),
]


def export_events(qs: Dict[str, List[str]]) -> Tuple[bytes, str, str]:
    """导出日历数据

    Returns:
        (payload_bytes, content_type, filename)
    """
    ensure_tables()
    fmt = (_q(qs, "format", "csv") or "csv").lower()
    ct = _cal_type(qs)
    data = service.get_events(
        cal_type=ct,
        start=_q(qs, "start"),
        end=_q(qs, "end"),
        category=_q(qs, "category"),
        region=_q(qs, "region"),
        keyword=_q(qs, "q"),
        importance_min=_qi(qs, "importance", 0),
        limit=MAX_LIMIT,
        sync=_qb(qs, "sync", True),
    )
    items = data["items"]
    stamp = now_bj().strftime("%Y%m%d_%H%M%S")
    base = f"calendar_{ct}_{data['start']}_{data['end']}_{stamp}"

    if fmt == "json":
        payload = json.dumps(
            {"cal_type": ct, "start": data["start"], "end": data["end"],
             "total": data["total"], "items": items},
            ensure_ascii=False, indent=2,
        ).encode("utf-8")
        return payload, "application/json; charset=utf-8", base + ".json"

    if fmt in ("md", "markdown"):
        lines = [
            f"# 财经日历导出 · {CAL_TYPES.get(ct, {}).get('label', ct)}",
            "",
            f"- 区间：{data['start']} ~ {data['end']}",
            f"- 条数：{data['total']}",
            f"- 导出时间：{now_bj().strftime('%Y-%m-%d %H:%M:%S')}",
            "",
        ]
        cur = None
        for it in items:
            if it["event_date"] != cur:
                cur = it["event_date"]
                lines.append(f"\n## {cur}\n")
            star = "★" * max(0, int(it.get("importance") or 0))
            tm = f"`{it['event_time']}` " if it.get("event_time") else ""
            tag = f"[{it['category']}]" if it.get("category") else ""
            lines.append(f"- {tm}{tag} **{it['title']}** {star}")
            detail = []
            if it.get("code"):
                detail.append(f"代码 {it['code']}")
            if it.get("prev_value"):
                detail.append(f"前值 {it['prev_value']}")
            if it.get("forecast_value"):
                detail.append(f"预测 {it['forecast_value']}")
            if it.get("actual_value"):
                detail.append(f"公布 {it['actual_value']}")
            if detail:
                lines.append(f"  - {' · '.join(detail)}")
        payload = "\n".join(lines).encode("utf-8")
        return payload, "text/markdown; charset=utf-8", base + ".md"

    # 默认 CSV（带 BOM，便于 Excel 打开）
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow([label for _, label in _EXPORT_FIELDS])
    for it in items:
        w.writerow([it.get(k, "") for k, _ in _EXPORT_FIELDS])
    payload = ("\ufeff" + buf.getvalue()).encode("utf-8")
    return payload, "text/csv; charset=utf-8", base + ".csv"
