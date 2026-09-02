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
import re
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


# 预览
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


# 采集
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


def collect_for_stock(code: str, hours: int = 48, max_items: int = 300,
                      end_ts: Optional[int] = None) -> Tuple[List[NewsRecord], Dict[str, Any]]:
    """采集窗口内与指定标的关联的新闻（news_stock_link 关联，标题/正文双匹配兜底）。"""
    code = (code or "").strip()
    hours = normalize_window(hours)
    start_ts, real_end = window_bounds(hours, end_ts)
    max_items = max(20, min(int(max_items or 300), 2000))

    db = get_db_manager()
    with db.get_db() as c:
        c.execute(
            "SELECT COUNT(*) AS n FROM news WHERE publish_ts >= ? AND publish_ts <= ? "
            "AND (stocks LIKE ? OR id IN (SELECT news_id FROM news_stock_link WHERE code = ?))",
            [start_ts, real_end, f'%"{code}"%', code],
        )
        scanned = c.fetchone()["n"]

        c.execute(
            f"SELECT {_SELECT_COLS} FROM news "
            f"WHERE publish_ts >= ? AND publish_ts <= ? "
            f"AND (stocks LIKE ? OR id IN (SELECT news_id FROM news_stock_link WHERE code = ?)) "
            f"ORDER BY importance DESC, publish_ts DESC, id DESC LIMIT ?",
            [start_ts, real_end, f'%"{code}"%', code, max_items],
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
        "scope": SCOPE_ALL,
        "scope_label": f"标的 {code} 关联资讯",
        "start_ts": start_ts,
        "end_ts": real_end,
        "start_str": bj_str_from_ts(start_ts),
        "end_str": bj_str_from_ts(real_end),
        "scanned_count": scanned,
        "selected_count": len(records),
        "truncated": scanned > len(records),
        "min_importance": 0.0,
        "order": ORDER_IMPORTANCE,
        "max_items": max_items,
    }
    logger.info(f"LLM 个股采集：{code} 窗口 {hours}h / 命中 {scanned} 条 / 送分析 {len(records)} 条")
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


# ---------- 快讯聚焦相关 ----------

def _focus_keywords(focus: str) -> List[str]:
    """从 focus（快讯标题/内容/来源混排）提取可检索的关注词。"""
    if not focus:
        return []
    text = focus.strip()
    # 去掉"（来源：xx）/（xx网）"式的来源后缀与时间戳
    text = re.sub(r"[（(]\s*来源[：:]\s*[^）)]*[）)]", "", text)
    text = re.sub(r"\d{4}-\d{2}-\d{2}(\s+\d{2}:\d{2}(:\d{2})?)?", "", text)
    # 优先整句（截断避免过长），再降级为词
    words: List[str] = []
    for sep in ("：", ":", "，", ",", "。", "！", "？", "!", "?"):
        if sep in text:
            for w in text.split(sep):
                w = (w or "").strip(" 　·｜|")
                if len(w) >= 2:
                    words.append(w)
        else:
            break
    if not words:
        words = [text]
    words = list(dict.fromkeys(w for w in words if 2 <= len(w) <= 18))
    return words[:6]


def _reorder_by_focus(records: List[NewsRecord], focus: str) -> List[NewsRecord]:
    """按 focus 相关性对记录重排：相关新闻置顶（保持内部时间升序），无关的排在后面。"""
    if not focus or not records:
        return records
    kws = _focus_keywords(focus)
    if not kws:
        return records

    def score(r: NewsRecord) -> int:
        hay = f"{r.title} {r.intro} {' '.join(r.stocks)} {' '.join(r.keywords)}"
        return sum(2 if w in r.title else (1 if w in hay else 0) for w in kws)

    scored = [(score(r), r) for r in records]
    rel = [(s, r) for s, r in scored if s > 0]
    irr = [(s, r) for s, r in scored if s <= 0]
    rel.sort(key=lambda x: x[1].publish_ts)
    irr.sort(key=lambda x: x[1].publish_ts)
    return [r for _, r in rel + irr]


def _to_records(rows) -> List[NewsRecord]:
    """统一把查询返回的行转成 NewsRecord（供 collect / collect_for_stock / collect_flash 复用）。"""
    return [
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


def collect_flash(news_id: Optional[int] = None, focus: str = "", hours: int = 24,
                  max_related: int = 15,
                  end_ts: Optional[int] = None) -> Tuple[List[NewsRecord], Dict[str, Any]]:
    """采集单条目标快讯 + 少量相关佐证资讯（单批可容纳，直成文，绝不分批）。

    - news_id 精确回查目标快讯（重要性低也不会被截断丢弃）
    - focus 关键词在窗口内 title 命中相关资讯作为佐证
    - 目标快讯置顶，佐证资讯按时间排列，总条数受 max_related 约束
    """
    hours = normalize_window(hours)
    start_ts, real_end = window_bounds(hours, end_ts)
    max_related = max(1, min(int(max_related or 15), 50))

    target: List[NewsRecord] = []
    if news_id:
        try:
            db = get_db_manager()
            with db.get_db() as c:
                c.execute(f"SELECT {_SELECT_COLS} FROM news WHERE id = ?", (int(news_id),))
                row = c.fetchone()
            if row:
                target = _to_records([row])
        except (TypeError, ValueError):
            target = []

    rel_kws = _focus_keywords(focus or (target[0].title if target else ""))
    scanned = len(target)
    related: List[NewsRecord] = []
    if rel_kws:
        conds, params = [], []
        for kw in rel_kws[:4]:
            conds.append("title LIKE ?")
            params.append(f"%{kw}%")
        where = "(" + " OR ".join(conds) + ")"
        db = get_db_manager()
        with db.get_db() as c:
            c.execute(
                f"SELECT COUNT(*) AS n FROM news WHERE publish_ts >= ? AND publish_ts <= ? AND {where}",
                [start_ts, real_end] + params,
            )
            scanned = max(scanned, c.fetchone()["n"])
            c.execute(
                f"SELECT {_SELECT_COLS} FROM news WHERE publish_ts >= ? AND publish_ts <= ? AND {where} "
                f"ORDER BY importance DESC, publish_ts DESC LIMIT ?",
                [start_ts, real_end] + params + [max_related],
            )
            related = _to_records(c.fetchall())
    related.sort(key=lambda x: x.publish_ts)

    seen = {r.id for r in target}
    records: List[NewsRecord] = list(target)
    for r in related:
        if r.id not in seen:
            records.append(r)
            seen.add(r.id)
    records = _reorder_by_focus(records, focus or (target[0].title if target else ""))

    meta = {
        "hours": hours,
        "scope": SCOPE_ALL,
        "scope_label": "单条快讯聚焦",
        "start_ts": start_ts,
        "end_ts": real_end,
        "start_str": bj_str_from_ts(start_ts),
        "end_str": bj_str_from_ts(real_end),
        "scanned_count": scanned,
        "selected_count": len(records),
        "truncated": scanned > len(records),
        "min_importance": 0.0,
        "order": ORDER_IMPORTANCE,
        "max_items": max_related + 1,
    }
    logger.info(f"LLM 快讯采集：news_id={news_id} 命中相关 {scanned} 条 / 送分析 {len(records)} 条")
    return records, meta
