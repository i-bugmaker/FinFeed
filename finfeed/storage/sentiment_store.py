#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""全市场舆情聚合存储层（混合分层架构 P0）

负责 stock_sentiment / sector_sentiment / market_sentiment_daily / sector_members
四张聚合表的读写与聚合计算。所有写入均按 (code/date/source) 幂等 upsert，
支持方案E(第三方直采)、方案D(LLM聚合)、方案A(人气榜)多源汇入后再聚合。
"""

import json
import logging
from typing import Any, Dict, List, Optional, Tuple

from ..utils.time_utils import now_bj
from .database import get_db_manager

logger = logging.getLogger("news_monitor")


def _now() -> str:
    return now_bj().strftime("%Y-%m-%d %H:%M:%S")


# ---------------------------------------------------------------------------
# 板块成分映射
# ---------------------------------------------------------------------------
def upsert_sector_member(sector_code: str, sector_name: str, sector_type: str,
                         code: str, name: str = "", weight: float = 0.0) -> None:
    """写入一条板块-成分股关系（幂等）"""
    db = get_db_manager()
    with db.get_db() as c:
        c.execute(
            """INSERT INTO sector_members (sector_code, sector_name, sector_type, code, name, weight)
               VALUES (?, ?, ?, ?, ?, ?)
               ON CONFLICT(sector_code, code) DO UPDATE SET
                   sector_name=excluded.sector_name,
                   sector_type=excluded.sector_type,
                   name=excluded.name,
                   weight=excluded.weight
            """,
            (sector_code, sector_name, sector_type, code, name, weight),
        )


def upsert_sector_members_bulk(rows: List[Tuple[str, str, str, str, str, float]]) -> int:
    """批量写入板块-成分股关系。rows: (sector_code, sector_name, sector_type, code, name, weight)"""
    if not rows:
        return 0
    db = get_db_manager()
    with db.get_db() as c:
        c.executemany(
            """INSERT INTO sector_members (sector_code, sector_name, sector_type, code, name, weight)
               VALUES (?, ?, ?, ?, ?, ?)
               ON CONFLICT(sector_code, code) DO UPDATE SET
                   sector_name=excluded.sector_name,
                   sector_type=excluded.sector_type,
                   name=excluded.name,
                   weight=excluded.weight
            """,
            rows,
        )
        return len(rows)


def get_sector_members(sector_code: str) -> List[Dict[str, Any]]:
    """获取某板块的全部成分股"""
    db = get_db_manager()
    with db.get_db() as c:
        c.execute(
            "SELECT code, name, weight FROM sector_members WHERE sector_code = ? ORDER BY weight DESC",
            (sector_code,),
        )
        return [{"code": r["code"], "name": r["name"], "weight": r["weight"]} for r in c.fetchall()]


def get_sectors_of_stock(code: str) -> List[Dict[str, Any]]:
    """反查某股票所属的板块（用于"主题→成分股"反向定位）"""
    db = get_db_manager()
    with db.get_db() as c:
        c.execute(
            "SELECT sector_code, sector_name, sector_type FROM sector_members WHERE code = ?",
            (code,),
        )
        return [{"sector_code": r["sector_code"], "sector_name": r["sector_name"], "sector_type": r["sector_type"]} for r in c.fetchall()]


# ---------------------------------------------------------------------------
# 个股情绪
# ---------------------------------------------------------------------------
def upsert_stock_sentiment(records: List[Dict[str, Any]]) -> int:
    """批量写入个股情绪。records 字段:
    code, trade_date, sentiment_score, sentiment_label, heat,
    mention_count, pos_mentions, neg_mentions, source
    """
    if not records:
        return 0
    db = get_db_manager()
    now = _now()
    rows = []
    for r in records:
        rows.append((
            r["code"], r.get("name", ""), r.get("trade_date", now_bj().strftime("%Y-%m-%d")),
            r.get("sentiment_score", 0.0), r.get("sentiment_label", "neutral"),
            r.get("heat", 0.0), r.get("mention_count", 0),
            r.get("pos_mentions", 0), r.get("neg_mentions", 0),
            r.get("source", ""), now,
        ))
    with db.get_db() as c:
        c.executemany(
            """INSERT INTO stock_sentiment
               (code, name, trade_date, sentiment_score, sentiment_label, heat, mention_count,
                pos_mentions, neg_mentions, source, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(code, trade_date, source) DO UPDATE SET
                   name=excluded.name,
                   sentiment_score=excluded.sentiment_score,
                   sentiment_label=excluded.sentiment_label,
                   heat=excluded.heat,
                   mention_count=excluded.mention_count,
                   pos_mentions=excluded.pos_mentions,
                   neg_mentions=excluded.neg_mentions,
                   created_at=excluded.created_at
            """,
            rows,
        )
        return len(rows)


def get_stock_sentiment(code: str, start_date: Optional[str] = None,
                        end_date: Optional[str] = None) -> List[Dict[str, Any]]:
    db = get_db_manager()
    with db.get_db() as c:
        conditions = ["code = ?"]
        params: List[Any] = [code]
        if start_date:
            conditions.append("trade_date >= ?")
            params.append(start_date)
        if end_date:
            conditions.append("trade_date <= ?")
            params.append(end_date)
        c.execute(
            f"SELECT * FROM stock_sentiment WHERE {' AND '.join(conditions)} ORDER BY trade_date DESC",
            params,
        )
        return [dict(r) for r in c.fetchall()]


def get_top_heat_stocks(trade_date: str, limit: int = 50, source: Optional[str] = None) -> List[Dict[str, Any]]:
    """个股热度榜（方案A/方案E 输出）"""
    db = get_db_manager()
    with db.get_db() as c:
        if source:
            c.execute(
                "SELECT code, name, heat, sentiment_score, sentiment_label, mention_count FROM stock_sentiment "
                "WHERE trade_date = ? AND source = ? ORDER BY heat DESC LIMIT ?",
                (trade_date, source, limit),
            )
        else:
            c.execute(
                "SELECT code, name, heat, sentiment_score, sentiment_label, mention_count FROM stock_sentiment "
                "WHERE trade_date = ? ORDER BY heat DESC LIMIT ?",
                (trade_date, limit),
            )
        return [dict(r) for r in c.fetchall()]


# ---------------------------------------------------------------------------
# 板块情绪
# ---------------------------------------------------------------------------
def upsert_sector_sentiment(records: List[Dict[str, Any]]) -> int:
    if not records:
        return 0
    db = get_db_manager()
    now = _now()
    rows = []
    for r in records:
        rows.append((
            r["sector_code"], r["sector_name"], r["sector_type"],
            r.get("trade_date", now_bj().strftime("%Y-%m-%d")),
            r.get("sentiment_score", 0.0), r.get("heat", 0.0),
            r.get("member_count", 0),
            json.dumps(r.get("top_stocks", []), ensure_ascii=False),
            now,
        ))
    with db.get_db() as c:
        c.executemany(
            """INSERT INTO sector_sentiment
               (sector_code, sector_name, sector_type, trade_date, sentiment_score, heat, member_count, top_stocks, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(sector_code, trade_date) DO UPDATE SET
                   sector_name=excluded.sector_name,
                   sector_type=excluded.sector_type,
                   sentiment_score=excluded.sentiment_score,
                   heat=excluded.heat,
                   member_count=excluded.member_count,
                   top_stocks=excluded.top_stocks,
                   created_at=excluded.created_at
            """,
            rows,
        )
        return len(rows)


def aggregate_sector_from_stocks(trade_date: str, sector_type: Optional[str] = None) -> int:
    """由个股情绪聚合板块情绪指数（方案B 核心）。

    对每一板块，取其成分股当日情绪分的均值作为板块情绪分，
    取热度均值作为板块热度，取情绪最强 Top5 成分股作为代表。
    """
    db = get_db_manager()
    with db.get_db() as c:
        type_cond = "" if not sector_type else "AND sm.sector_type = ?"
        params = [trade_date]
        if sector_type:
            params.append(sector_type)
        c.execute(
            f"""SELECT sm.sector_code, sm.sector_name, sm.sector_type,
                       AVG(ss.sentiment_score) as avg_sent,
                       AVG(ss.heat) as avg_heat,
                       COUNT(*) as cnt
                FROM sector_members sm
                JOIN stock_sentiment ss ON ss.code = sm.code
                WHERE ss.trade_date = ? {type_cond}
                GROUP BY sm.sector_code, sm.sector_name, sm.sector_type
            """,
            params,
        )
        sectors = c.fetchall()
        if not sectors:
            return 0
        recs = []
        for s in sectors:
            sc, sn, st = s["sector_code"], s["sector_name"], s["sector_type"]
            c.execute(
                "SELECT code, name, heat, sentiment_score FROM stock_sentiment "
                "WHERE trade_date = ? AND code IN (SELECT code FROM sector_members WHERE sector_code = ?) "
                "ORDER BY sentiment_score DESC LIMIT 5",
                (trade_date, sc),
            )
            top = [{"code": r["code"], "name": r["name"],
                    "sentiment_score": r["sentiment_score"], "heat": r["heat"]} for r in c.fetchall()]
            recs.append({
                "sector_code": sc, "sector_name": sn, "sector_type": st,
                "trade_date": trade_date,
                "sentiment_score": round(s["avg_sent"] or 0.0, 4),
                "heat": round(s["avg_heat"] or 0.0, 4),
                "member_count": s["cnt"],
                "top_stocks": top,
            })
        if recs:
            return upsert_sector_sentiment(recs)
        return 0


# ---------------------------------------------------------------------------
# 全市场每日舆情温度
# ---------------------------------------------------------------------------
def upsert_market_sentiment(trade_date: str, sentiment_index: float = 0.0,
                            up_limit: int = 0, down_limit: int = 0, breadth: int = 0,
                            forum_heat: float = 0.0, news_sentiment: float = 0.0) -> None:
    """写入全市场每日舆情温度（方案C）"""
    db = get_db_manager()
    with db.get_db() as c:
        c.execute(
            """INSERT INTO market_sentiment_daily
               (trade_date, sentiment_index, up_limit, down_limit, breadth, forum_heat, news_sentiment, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(trade_date) DO UPDATE SET
                   sentiment_index=excluded.sentiment_index,
                   up_limit=excluded.up_limit,
                   down_limit=excluded.down_limit,
                   breadth=excluded.breadth,
                   forum_heat=excluded.forum_heat,
                   news_sentiment=excluded.news_sentiment,
                   created_at=excluded.created_at
            """,
            (trade_date, sentiment_index, up_limit, down_limit, breadth, forum_heat, news_sentiment, _now()),
        )


def get_market_sentiment(trade_date: Optional[str] = None) -> Optional[Dict[str, Any]]:
    db = get_db_manager()
    with db.get_db() as c:
        if trade_date:
            c.execute("SELECT * FROM market_sentiment_daily WHERE trade_date = ?", (trade_date,))
        else:
            c.execute("SELECT * FROM market_sentiment_daily ORDER BY trade_date DESC LIMIT 1")
        row = c.fetchone()
        return dict(row) if row else None


def get_market_sentiment_range(start_date: str, end_date: str) -> List[Dict[str, Any]]:
    db = get_db_manager()
    with db.get_db() as c:
        c.execute(
            "SELECT * FROM market_sentiment_daily WHERE trade_date >= ? AND trade_date <= ? ORDER BY trade_date",
            (start_date, end_date),
        )
        return [dict(r) for r in c.fetchall()]


# ---------------------------------------------------------------------------
# 散户情绪指数（自建·聚合全路 UGC 舆情源）
# ---------------------------------------------------------------------------
def _ensure_forum_table() -> None:
    """确保 forum_sentiment_daily 表存在（自愈式，兼容未走 market 初始化启动路径）"""
    db = get_db_manager()
    with db.get_db() as c:
        c.execute(
            """CREATE TABLE IF NOT EXISTS forum_sentiment_daily (
                trade_date TEXT PRIMARY KEY,
                retail_index REAL DEFAULT 0.0,
                heat REAL DEFAULT 0.0,
                up_count INTEGER DEFAULT 0,
                down_count INTEGER DEFAULT 0,
                neutral_count INTEGER DEFAULT 0,
                volume INTEGER DEFAULT 0,
                stock_coverage INTEGER DEFAULT 0,
                active_sources TEXT DEFAULT '[]',
                top_stocks TEXT DEFAULT '[]',
                created_at TEXT
            )"""
        )


def upsert_forum_sentiment(trade_date: str, retail_index: float = 0.0, heat: float = 0.0,
                           up_count: int = 0, down_count: int = 0, neutral_count: int = 0,
                           volume: int = 0, stock_coverage: int = 0,
                           active_sources: Optional[List[str]] = None,
                           top_stocks: Optional[List[Dict[str, Any]]] = None) -> None:
    """写入当日散户情绪指数（幂等 upsert，trade_date 主键）。"""
    _ensure_forum_table()
    db = get_db_manager()
    with db.get_db() as c:
        c.execute(
            """INSERT INTO forum_sentiment_daily
               (trade_date, retail_index, heat, up_count, down_count, neutral_count,
                volume, stock_coverage, active_sources, top_stocks, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(trade_date) DO UPDATE SET
                   retail_index=excluded.retail_index,
                   heat=excluded.heat,
                   up_count=excluded.up_count,
                   down_count=excluded.down_count,
                   neutral_count=excluded.neutral_count,
                   volume=excluded.volume,
                   stock_coverage=excluded.stock_coverage,
                   active_sources=excluded.active_sources,
                   top_stocks=excluded.top_stocks,
                   created_at=excluded.created_at
            """,
            (trade_date, retail_index, heat, up_count, down_count, neutral_count,
             volume, stock_coverage,
             json.dumps(active_sources or [], ensure_ascii=False),
             json.dumps(top_stocks or [], ensure_ascii=False), _now()),
        )


def get_forum_sentiment(trade_date: Optional[str] = None) -> Optional[Dict[str, Any]]:
    """读取当日散户情绪指数；不传日期取最近一条。"""
    _ensure_forum_table()
    db = get_db_manager()
    with db.get_db() as c:
        if trade_date:
            c.execute("SELECT * FROM forum_sentiment_daily WHERE trade_date = ?", (trade_date,))
        else:
            c.execute("SELECT * FROM forum_sentiment_daily ORDER BY trade_date DESC LIMIT 1")
        row = c.fetchone()
        if not row:
            return None
        d = dict(row)
        for key in ("active_sources", "top_stocks"):
            try:
                d[key] = json.loads(d.get(key) or "[]")
            except Exception:
                d[key] = []
        return d
