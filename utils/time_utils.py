#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""时间工具函数"""

import re
from datetime import datetime, timezone, timedelta

TZ_BJ = timezone(timedelta(hours=8))

_RE_DIGITS = re.compile(r"(\d+)")
_RE_HHMM = re.compile(r"(\d{1,2}):(\d{2})")
_RE_DATE_PREFIX = re.compile(r"\d{4}-\d{2}-\d{2}")
_RE_MDHM = re.compile(r"^(\d{1,2})-(\d{1,2})\s+(\d{1,2}):(\d{2})$")
_RE_MD_HHMM = re.compile(r"(\d{1,2})月(\d{1,2})日\s+(\d{1,2}):(\d{2})")


def now_bj() -> datetime:
    """获取当前北京时间（无时区信息的 datetime）"""
    return datetime.now(TZ_BJ).replace(tzinfo=None)


def ts_from_bj_str(s: str) -> int:
    """将北京时间字符串转换为 Unix 时间戳

    支持格式:
      - 'YYYY-MM-DD HH:MM:SS' (北京时间)
      - RSS RFC-822 格式: 'Wed, 04 Jun 2026 10:47:03 GMT'
      - 含时区偏移: '2026-06-04T17:47:03+08:00'
    """
    if not s:
        return 0
    s = s.strip()
    try:
        dt = datetime.strptime(s[:19], "%Y-%m-%d %H:%M:%S")
        return int(dt.replace(tzinfo=TZ_BJ).timestamp())
    except (ValueError, TypeError):
        pass
    try:
        s_iso = s.replace("T", " ")
        dt = datetime.strptime(s_iso[:19], "%Y-%m-%d %H:%M:%S")
        return int(dt.replace(tzinfo=TZ_BJ).timestamp())
    except (ValueError, TypeError):
        pass
    for fmt in (
        "%a, %d %b %Y %H:%M:%S %z",
        "%a, %d %b %Y %H:%M:%S GMT",
        "%d %b %Y %H:%M:%S %z",
    ):
        try:
            dt = datetime.strptime(s.strip(), fmt)
            return int(dt.timestamp())
        except (ValueError, TypeError):
            continue
    try:
        m = re.match(
            r"(?:\w+,\s+)?(\d{1,2})\s+(\w+)\s+(\d{4})\s+(\d{2}):(\d{2}):(\d{2})\s*(.*)",
            s,
        )
        if m:
            day, mon_str, year, hour, minute, sec, tz_str = m.groups()
            months = {"Jan":1,"Feb":2,"Mar":3,"Apr":4,"May":5,"Jun":6,
                      "Jul":7,"Aug":8,"Sep":9,"Oct":10,"Nov":11,"Dec":12}
            mon = months.get(mon_str, 0)
            if mon:
                dt = datetime(int(year), mon, int(day), int(hour), int(minute), int(sec))
                if tz_str and tz_str not in ("GMT", "UTC"):
                    tz_m = re.match(r"([+-]?)(\d{2}):?(\d{2})", tz_str)
                    if tz_m:
                        sign = -1 if tz_m.group(1) == "-" else 1
                        off_h, off_m = int(tz_m.group(2)), int(tz_m.group(3))
                        dt = dt - timedelta(hours=sign * off_h, minutes=sign * off_m)
                    dt = dt.replace(tzinfo=timezone.utc)
                    return int(dt.timestamp())
                else:
                    dt = dt.replace(tzinfo=timezone.utc)
                    return int(dt.timestamp())
    except (ValueError, TypeError, AttributeError):
        pass
    return 0


def bj_str_from_ts(ts: int) -> str:
    """将 Unix 时间戳转换为北京时间字符串"""
    if not ts:
        return now_bj().strftime("%Y-%m-%d %H:%M:%S")
    return datetime.fromtimestamp(ts, tz=TZ_BJ).strftime("%Y-%m-%d %H:%M:%S")


def parse_relative_time(time_str: str) -> int:
    """解析相对时间字符串，如 '5分钟前', '2小时前', '昨天 23:05', '今天 22:58'"""
    now = now_bj()
    if not time_str:
        return 0
    try:
        if "分钟前" in time_str:
            m = _RE_DIGITS.search(time_str)
            if m:
                return int((now - timedelta(minutes=int(m.group(1)))).replace(tzinfo=TZ_BJ).timestamp())
        elif "小时前" in time_str:
            m = _RE_DIGITS.search(time_str)
            if m:
                return int((now - timedelta(hours=int(m.group(1)))).replace(tzinfo=TZ_BJ).timestamp())
        elif "天前" in time_str:
            m = _RE_DIGITS.search(time_str)
            if m:
                return int((now - timedelta(days=int(m.group(1)))).replace(tzinfo=TZ_BJ).timestamp())
        elif time_str.startswith("昨天"):
            m = _RE_HHMM.search(time_str)
            if m:
                hour, minute = int(m.group(1)), int(m.group(2))
                dt = (now - timedelta(days=1)).replace(hour=hour, minute=minute, second=0)
                return int(dt.replace(tzinfo=TZ_BJ).timestamp())
        elif time_str.startswith("今天"):
            m = _RE_HHMM.search(time_str)
            if m:
                hour, minute = int(m.group(1)), int(m.group(2))
                dt = now.replace(hour=hour, minute=minute, second=0)
                return int(dt.replace(tzinfo=TZ_BJ).timestamp())
        elif "前天" in time_str:
            return int((now - timedelta(days=2)).replace(hour=0, minute=0, second=0, tzinfo=TZ_BJ).timestamp())
        m = _RE_MDHM.match(time_str)
        if m:
            month, day, hour, minute = int(m.group(1)), int(m.group(2)), int(m.group(3)), int(m.group(4))
            dt = now.replace(month=month, day=day, hour=hour, minute=minute, second=0)
            ts = int(dt.replace(tzinfo=TZ_BJ).timestamp())
            if ts > int(now.replace(tzinfo=TZ_BJ).timestamp()):
                dt = dt.replace(year=dt.year - 1)
            return int(dt.replace(tzinfo=TZ_BJ).timestamp())
    except (ValueError, AttributeError):
        pass
    return 0


def parse_url_date(url: str) -> tuple[int, int, int] | None:
    """从 URL 中提取日期（格式: /YYYYMMDD/）"""
    m = re.search(r"/(\d{8})/", str(url))
    if m:
        yyyymmdd = m.group(1)
        return int(yyyymmdd[:4]), int(yyyymmdd[4:6]), int(yyyymmdd[6:8])
    return None
