#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""按时间窗口从库中采集新闻

窗口以「当前时刻往前 N 小时」计算，N 支持 24 / 48 / 72（也接受 1~168 的任意值）。
提供：
  - preview_window(): 只统计条数与分布，供前端点击前预估
  - collect(): 取回条目并按预算裁剪
"""

import json
import logging
import time
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

from finfeed.storage.database import get_db_manager
from finfeed.utils.time_utils import bj_str_from_ts

logger = logging.getLogger("news_monitor")

ALLOWED_WINDOWS = (24, 48, 72)
MIN_WINDOW, MAX_WINDOW = 1, 168

SCOPE_ALL = "all"
SCOPE_FINANCE = "finance"
SCOPE_FORUM = "forum"
SCOPES = {
    SCOPE_ALL: "全部（财经新闻 + 论坛舆情）",
    SCOPE_FINANCE: "财经新闻",
    SCOPE_FORUM: "论坛舆情",
}

ORDER_IMPORTANCE = "importance"
ORDER_TIME = "time"

_SELECT_COLS = (
    "id, title, intro, source, category, publish_time, publish_ts, "
    "sentiment, importance, stocks, keywords, duplicate_count, url"
)


@dataclass
class NewsRecord:
    id: int
    title: str
    intro: str
    source: str
    category: str
    publish_time: str
    publish_ts: int
    sentiment: str
    importance: float
    stocks: List[str]
    keywords: List[str]
    duplicate_count: int
    url: str = ""

    def to_line(self, idx: int, intro_chars: int = 80) -> str:
        """压缩成单行喂给模型的文本"""
        t = (self.publish_time or bj_str_from_ts(self.publish_ts))[5:16]
        parts = [f"[{idx}] {t} 〔{self.source}〕{_clean(self.title)}"]
        if self.intro:
            intro = _clean(self.intro)
            if intro and intro[:20] not in self.title:
                parts.append(f"｜{intro[:intro_chars]}")
        if self.stocks:
            parts.append(f"｜股票:{','.join(self.stocks[:6])}")
        if self.duplicate_count:
            parts.append(f"｜{self.duplicate_count + 1}源印证")
        return "".join(parts)


def _clean(s: str) -> str:
    if not s:
        return ""
    return " ".join(str(s).split()).replace("|", "／")


def _json_list(raw: Any) -> List[str]:
    if not raw:
        return []
    if isinstance(raw, list):
        return [str(x) for x in raw]
    try:
        v = json.loads(raw)
        return [str(x) for x in v] if isinstance(v, list) else []
    except Exception:
        return []


def normalize_window(hours: Any) -> int:
    try:
        h = int(hours)
    except (TypeError, ValueError):
        return 24
    return max(MIN_WINDOW, min(MAX_WINDOW, h))


def _scope_clause(scope: str) -> Tuple[str, List[Any]]:
    if scope == SCOPE_FORUM:
        return "AND category = ?", ["forum"]
    if scope == SCOPE_FINANCE:
        return "AND category != ?", ["forum"]
    return "", []


def window_bounds(hours: int, end_ts: Optional[int] = None) -> Tuple[int, int]:
    end = int(end_ts or time.time())
    return end - hours * 3600, end


# ============================================================
# 预览
# ============================================================
def preview_window(hours: int = 24, scope: str = SCOPE_ALL,
                   min_importance: float = 0.0) -> Dict[str, Any]:
    """统计窗口内数据量与结构分布，不取正文"""
    hours = normalize_window(hours)
    start_ts, end_ts = window_bounds(hours)
    clause, params = _scope_clause(scope)
    base_params = [start_ts, end_ts] + params

    db = get_db_manager()
    with db.get_db() as c:
        c.execute(
            f"SELECT COUNT(*) AS n FROM news WHERE publish_ts >= ? AND publish_ts <= ? {clause}",
            base_params,
        )
        total = c.fetchone()["n"]

        c.execute(
            f"SELECT COUNT(*) AS n FROM news WHERE publish_ts >= ? AND publish_ts <= ? {clause} "
            "AND importance >= ?",
            base_params + [min_importance],
        )
        matched = c.fetchone()["n"]

        c.execute(
            f"SELECT source, COUNT(*) AS n FROM news WHERE publish_ts >= ? AND publish_ts <= ? {clause} "
            "GROUP BY source ORDER BY n DESC LIMIT 20",
            base_params,
        )
        sources = [{"name": r["source"], "count": r["n"]} for r in c.fetchall()]

        c.execute(
            f"SELECT sentiment, COUNT(*) AS n FROM news WHERE publish_ts >= ? AND publish_ts <= ? {clause} "
            "GROUP BY sentiment",
            base_params,
        )
        sentiment = {r["sentiment"] or "neutral": r["n"] for r in c.fetchall()}

    return {
        "hours": hours,
        "scope": scope,
        "scope_label": SCOPES.get(scope, scope),
        "start_ts": start_ts,
        "end_ts": end_ts,
        "start_str": bj_str_from_ts(start_ts),
        "end_str": bj_str_from_ts(end_ts),
        "total": total,
        "matched": matched,
        "min_importance": min_importance,
        "sources": sources,
        "sentiment": sentiment,
    }


# ============================================================
# 采集
# ============================================================
def collect(hours: int = 24, scope: str = SCOPE_ALL, min_importance: float = 0.0,
            max_items: int = 500, order: str = ORDER_IMPORTANCE,
            end_ts: Optional[int] = None) -> Tuple[List[NewsRecord], Dict[str, Any]]:
    """取回窗口内新闻

    order:
      importance - 先按重要性降序截断（保留高价值信息），再按时间升序排列
      time       - 直接按时间倒序截断，保留最新的 max_items 条
    """
    hours = normalize_window(hours)
    start_ts, real_end = window_bounds(hours, end_ts)
    clause, params = _scope_clause(scope)
    max_items = max(20, min(int(max_items or 500), 5000))

    order_sql = (
        "importance DESC, publish_ts DESC, id DESC"
        if order == ORDER_IMPORTANCE
        else "publish_ts DESC, id DESC"
    )

    db = get_db_manager()
    with db.get_db() as c:
        c.execute(
            f"SELECT COUNT(*) AS n FROM news WHERE publish_ts >= ? AND publish_ts <= ? {clause} "
            "AND importance >= ?",
            [start_ts, real_end] + params + [min_importance],
        )
        scanned = c.fetchone()["n"]

        c.execute(
            f"SELECT {_SELECT_COLS} FROM news "
            f"WHERE publish_ts >= ? AND publish_ts <= ? {clause} AND importance >= ? "
            f"ORDER BY {order_sql} LIMIT ?",
            [start_ts, real_end] + params + [min_importance, max_items],
        )
        rows = c.fetchall()

    records = [
        NewsRecord(
            id=r["id"],
            title=r["title"] or "",
            intro=r["intro"] or "",
            source=r["source"] or "",
            category=r["category"] or "",
            publish_time=r["publish_time"] or "",
            publish_ts=int(r["publish_ts"] or 0),
            sentiment=r["sentiment"] or "neutral",
            importance=float(r["importance"] or 0),
            stocks=_json_list(r["stocks"]),
            keywords=_json_list(r["keywords"]),
            duplicate_count=int(r["duplicate_count"] or 0),
            url=r["url"] or "",
        )
        for r in rows
    ]
    records.sort(key=lambda x: x.publish_ts)

    meta = {
        "hours": hours,
        "scope": scope,
        "scope_label": SCOPES.get(scope, scope),
        "start_ts": start_ts,
        "end_ts": real_end,
        "start_str": bj_str_from_ts(start_ts),
        "end_str": bj_str_from_ts(real_end),
        "scanned_count": scanned,
        "selected_count": len(records),
        "truncated": scanned > len(records),
        "min_importance": min_importance,
        "order": order,
        "max_items": max_items,
    }
    logger.info(
        f"LLM 采集：窗口 {hours}h / 范围 {SCOPES.get(scope, scope)} / "
        f"命中 {scanned} 条 / 送分析 {len(records)} 条"
    )
    return records, meta


def build_chunks(records: List[NewsRecord], chunk_chars: int = 8000,
                 max_chunks: int = 24, intro_chars: int = 80) -> List[List[str]]:
    """按字符预算切块，返回每块的文本行列表"""
    chunks: List[List[str]] = []
    cur: List[str] = []
    cur_len = 0
    for i, rec in enumerate(records, 1):
        line = rec.to_line(i, intro_chars=intro_chars)
        if cur and cur_len + len(line) > chunk_chars:
            chunks.append(cur)
            cur, cur_len = [], 0
            if len(chunks) >= max_chunks:
                logger.warning(f"LLM 分块达到上限 {max_chunks}，剩余内容被丢弃")
                return chunks
        cur.append(line)
        cur_len += len(line) + 1
    if cur:
        chunks.append(cur)
    return chunks
