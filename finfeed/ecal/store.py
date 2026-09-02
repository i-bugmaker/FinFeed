#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""日历事件持久化

复用主库连接，独立表 calendar_events / calendar_sync。
写入采用 ON CONFLICT DO UPDATE 幂等 upsert，反复同步不会产生重复行。
"""

import logging
import time
from typing import Any, Dict, List, Optional, Tuple

from finfeed.storage.database import get_db_manager

from .models import CalendarEvent

logger = logging.getLogger("news_monitor")

_COLUMNS = (
    "cal_type", "event_key", "event_date", "end_date", "event_time",
    "category", "sub_type", "title", "content", "code", "name", "region",
    "importance", "period", "prev_value", "forecast_value", "actual_value",
    "url", "extra", "updated_ts",
)

_PLACEHOLDERS = ",".join("?" * len(_COLUMNS))

_UPSERT_SQL = f"""
INSERT INTO calendar_events ({",".join(_COLUMNS)})
VALUES ({_PLACEHOLDERS})
ON CONFLICT(cal_type, event_date, event_key) DO UPDATE SET
    end_date       = excluded.end_date,
    event_time     = excluded.event_time,
    category       = excluded.category,
    sub_type       = excluded.sub_type,
    title          = excluded.title,
    content        = excluded.content,
    code           = excluded.code,
    name           = excluded.name,
    region         = excluded.region,
    importance     = excluded.importance,
    period         = excluded.period,
    prev_value     = excluded.prev_value,
    forecast_value = excluded.forecast_value,
    actual_value   = excluded.actual_value,
    url            = excluded.url,
    extra          = excluded.extra,
    updated_ts     = excluded.updated_ts
"""


# 写入
def upsert_events(events: List[CalendarEvent]) -> int:
    """批量幂等写入，返回处理条数"""
    if not events:
        return 0
    db = get_db_manager()
    rows = [e.to_row() for e in events]
    with db.get_db() as c:
        c.executemany(_UPSERT_SQL, rows)
    return len(rows)


def replace_day(cal_type: str, date: str, events: List[CalendarEvent]) -> int:
    """用最新抓取结果覆盖某天的数据

    先删除该 (cal_type, date) 下本次未出现的旧记录，再 upsert，
    保证官网撤销的事件不会在本地残留。
    """
    db = get_db_manager()
    keys = {e.event_key for e in events}
    with db.get_db() as c:
        if keys:
            marks = ",".join("?" * len(keys))
            c.execute(
                f"DELETE FROM calendar_events "
                f"WHERE cal_type=? AND event_date=? AND event_key NOT IN ({marks})",
                (cal_type, date, *keys),
            )
        else:
            c.execute(
                "DELETE FROM calendar_events WHERE cal_type=? AND event_date=?",
                (cal_type, date),
            )
        if events:
            c.executemany(_UPSERT_SQL, [e.to_row() for e in events])
    return len(events)


def mark_synced(cal_type: str, date: str, row_count: int,
                status: str = "ok", err: str = "") -> None:
    db = get_db_manager()
    with db.get_db() as c:
        c.execute(
            """
            INSERT INTO calendar_sync (cal_type, sync_date, updated_ts, row_count, status, err)
            VALUES (?,?,?,?,?,?)
            ON CONFLICT(cal_type, sync_date) DO UPDATE SET
                updated_ts = excluded.updated_ts,
                row_count  = excluded.row_count,
                status     = excluded.status,
                err        = excluded.err
            """,
            (cal_type, date, int(time.time()), row_count, status, err[:200]),
        )


def get_sync_map(cal_type: str, dates: List[str]) -> Dict[str, Tuple[int, str]]:
    """批量取同步水位: {date: (updated_ts, status)}"""
    if not dates:
        return {}
    db = get_db_manager()
    marks = ",".join("?" * len(dates))
    with db.get_db() as c:
        rows = c.execute(
            f"SELECT sync_date, updated_ts, status FROM calendar_sync "
            f"WHERE cal_type=? AND sync_date IN ({marks})",
            (cal_type, *dates),
        ).fetchall()
    return {r["sync_date"]: (r["updated_ts"] or 0, r["status"] or "") for r in rows}


# 查询
def query_events(
    cal_type: Optional[str] = None,
    start: str = "",
    end: str = "",
    category: str = "",
    region: str = "",
    keyword: str = "",
    importance_min: int = 0,
    limit: int = 3000,
    offset: int = 0,
) -> Dict[str, Any]:
    """按条件查询日历事件"""
    where: List[str] = []
    args: List[Any] = []

    if cal_type and cal_type != "all":
        where.append("cal_type = ?")
        args.append(cal_type)
    if start:
        where.append("event_date >= ?")
        args.append(start)
    if end:
        where.append("event_date <= ?")
        args.append(end)
    if category:
        where.append("category = ?")
        args.append(category)
    if region:
        where.append("region = ?")
        args.append(region)
    if importance_min > 0:
        where.append("importance >= ?")
        args.append(importance_min)
    if keyword:
        kw = f"%{keyword}%"
        where.append("(title LIKE ? OR content LIKE ? OR code LIKE ? OR name LIKE ?)")
        args.extend([kw, kw, kw, kw])

    clause = (" WHERE " + " AND ".join(where)) if where else ""
    db = get_db_manager()

    with db.get_db() as c:
        total = c.execute(
            f"SELECT COUNT(*) AS n FROM calendar_events{clause}", args
        ).fetchone()["n"]

        rows = c.execute(
            f"""SELECT * FROM calendar_events{clause}
                ORDER BY event_date ASC,
                         CASE WHEN event_time='' THEN 1 ELSE 0 END,
                         event_time ASC,
                         importance DESC,
                         id ASC
                LIMIT ? OFFSET ?""",
            (*args, max(1, min(limit, 5000)), max(0, offset)),
        ).fetchall()

    return {
        "total": total,
        "items": [CalendarEvent.from_row(r) for r in rows],
    }


def count_by_date(
    cal_type: Optional[str] = None, start: str = "", end: str = ""
) -> Dict[str, Dict[str, int]]:
    """按日期聚合计数，供月历视图使用

    Returns:
        {date: {"total": n, "high": n, "finance": n, "stock": n, "ipo": n, "global": n}}
    """
    where: List[str] = []
    args: List[Any] = []
    if cal_type and cal_type != "all":
        where.append("cal_type = ?")
        args.append(cal_type)
    if start:
        where.append("event_date >= ?")
        args.append(start)
    if end:
        where.append("event_date <= ?")
        args.append(end)
    clause = (" WHERE " + " AND ".join(where)) if where else ""

    db = get_db_manager()
    with db.get_db() as c:
        rows = c.execute(
            f"""SELECT event_date, cal_type,
                       COUNT(*) AS n,
                       SUM(CASE WHEN importance>=3 THEN 1 ELSE 0 END) AS high
                FROM calendar_events{clause}
                GROUP BY event_date, cal_type""",
            args,
        ).fetchall()

    out: Dict[str, Dict[str, int]] = {}
    for r in rows:
        d = out.setdefault(r["event_date"], {"total": 0, "high": 0})
        d["total"] += r["n"]
        d["high"] += r["high"] or 0
        d[r["cal_type"]] = d.get(r["cal_type"], 0) + r["n"]
    return out


def distinct_values(cal_type: str, column: str, start: str = "", end: str = "") -> List[str]:
    """取某列的去重取值（用于动态生成筛选项）"""
    if column not in ("category", "region", "sub_type"):
        return []
    where = ["cal_type = ?", f"{column} != ''"]
    args: List[Any] = [cal_type]
    if start:
        where.append("event_date >= ?")
        args.append(start)
    if end:
        where.append("event_date <= ?")
        args.append(end)

    db = get_db_manager()
    with db.get_db() as c:
        rows = c.execute(
            f"SELECT {column} AS v, COUNT(*) AS n FROM calendar_events "
            f"WHERE {' AND '.join(where)} GROUP BY {column} ORDER BY n DESC",
            args,
        ).fetchall()
    return [r["v"] for r in rows]


def get_stats() -> Dict[str, Any]:
    """模块总览统计"""
    db = get_db_manager()
    with db.get_db() as c:
        total = c.execute("SELECT COUNT(*) AS n FROM calendar_events").fetchone()["n"]
        by_type = {
            r["cal_type"]: r["n"]
            for r in c.execute(
                "SELECT cal_type, COUNT(*) AS n FROM calendar_events GROUP BY cal_type"
            ).fetchall()
        }
        rng = c.execute(
            "SELECT MIN(event_date) AS mn, MAX(event_date) AS mx FROM calendar_events"
        ).fetchone()
        synced = c.execute("SELECT COUNT(*) AS n FROM calendar_sync").fetchone()["n"]
        last = c.execute(
            "SELECT MAX(updated_ts) AS t FROM calendar_sync"
        ).fetchone()["t"]

    return {
        "total": total,
        "by_type": by_type,
        "min_date": rng["mn"] or "",
        "max_date": rng["mx"] or "",
        "synced_days": synced,
        "last_sync_ts": last or 0,
    }


def purge_before(date: str) -> int:
    """清理指定日期之前的历史数据"""
    db = get_db_manager()
    with db.get_db() as c:
        cur = c.execute("DELETE FROM calendar_events WHERE event_date < ?", (date,))
        n = cur.rowcount or 0
        c.execute("DELETE FROM calendar_sync WHERE sync_date < ?", (date,))
    return n
