#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""日历数据解析器

把四类异构原始数据归一化为 CalendarEvent：
  parse_finance(rows, date)  财经日历   RPT_CPH_FECALENDAR
  parse_stock(rows, date)    股市日历   RPT_SPECIAL_ALL
  parse_ipo(rows, date)      新股日历   RPT_IPO_CALENDAR
  parse_global(html, date)   全球经济   FC.html 表格
"""

import html as html_lib
import logging
import re
import time
from typing import Any, Dict, List

from .models import CalendarEvent
from .sources import (
    FINANCE_HIGH_TYPES,
    FINANCE_TYPE_CODE_MAP,
    GLOBAL_COL_INDEX,
    GLOBAL_IMPORTANCE_MAP,
    IPO_IMPORTANCE,
    IPO_SECURITY_TYPE,
    LIFT_IMPORTANCE_MARKET_CAP,
    REPORT_CATEGORIES,
    REPORT_IMPORTANCE_MAP,
    STOCK_CATEGORY_IMPORTANCE,
    STOCK_CATEGORY_RULES,
)

logger = logging.getLogger("news_monitor")

_RE_TAG = re.compile(r"<[^>]+>")
_RE_TR = re.compile(r"<tr[^>]*>([\s\S]*?)</tr>", re.I)
_RE_TD = re.compile(r"<td[^>]*>([\s\S]*?)</td>", re.I)
_RE_FONT_COLOR = re.compile(r'<font[^>]*color=["\']?([^"\'>\s]*)', re.I)
_RE_WS = re.compile(r"\s+")


def _d(v: Any) -> str:
    """截取 'YYYY-MM-DD HH:MM:SS' 的日期部分"""
    if not v:
        return ""
    return str(v)[:10]


def _t(v: Any) -> str:
    """安全转字符串并去空白"""
    if v is None:
        return ""
    return str(v).strip()


def _clean_html(s: str) -> str:
    s = _RE_TAG.sub("", s or "")
    s = html_lib.unescape(s).replace("\xa0", " ")
    return _RE_WS.sub(" ", s).strip()


def _norm_value(s: str) -> str:
    """'-' / '--' 视为空值"""
    s = _t(s)
    return "" if s in ("-", "--", "—", "") else s


# 1. 财经日历
def parse_finance(rows: List[Dict[str, Any]], date: str) -> List[CalendarEvent]:
    """RPT_CPH_FECALENDAR -> CalendarEvent

    注意：该源返回的是「在 date 当天处于进行中」的事件，含跨天会议。
    STD_TYPE_CODE 可能为 None（政策/公告类），归入「其它」。
    """
    now = int(time.time())
    out: List[CalendarEvent] = []
    for r in rows:
        title = _t(r.get("FE_NAME"))
        if not title:
            continue

        code = _t(r.get("STD_TYPE_CODE"))
        fe_type = _t(r.get("FE_TYPE"))
        category = FINANCE_TYPE_CODE_MAP.get(code, "其它")

        if fe_type in FINANCE_HIGH_TYPES:
            importance = 3
        elif code == "2":
            importance = 2
        elif code == "1":
            importance = 2
        else:
            importance = 1

        start = _d(r.get("START_DATE"))
        end = _d(r.get("END_DATE")) or start
        fe_code = _t(r.get("FE_CODE"))

        sponsor = _t(r.get("SPONSOR_NAME"))
        city = _t(r.get("CITY"))

        out.append(CalendarEvent(
            cal_type="finance",
            event_date=date,
            event_key=fe_code or f"{start}|{title[:60]}",
            title=title,
            end_date=end,
            category=category,
            sub_type=fe_type or category,
            content=_t(r.get("CONTENT")),
            region=city,
            importance=importance,
            updated_ts=now,
            extra={
                "sponsor": sponsor,
                "city": city,
                "start_date": start,
                "end_date": end,
                "multi_day": bool(start and end and start != end),
            },
        ))
    return out


# 2. 股市日历
def _stock_category(event_type: str) -> str:
    for keys, cat in STOCK_CATEGORY_RULES:
        for k in keys:
            if k in event_type:
                return cat
    return "其它"


def parse_stock(rows: List[Dict[str, Any]], date: str) -> List[CalendarEvent]:
    """RPT_SPECIAL_ALL -> CalendarEvent（个股公司行为）"""
    now = int(time.time())
    out: List[CalendarEvent] = []
    for r in rows:
        code = _t(r.get("SECURITY_CODE"))
        event_type = _t(r.get("EVENT_TYPE"))
        if not event_type:
            continue

        name = _t(r.get("SECURITY_NAME_ABBR"))
        secucode = _t(r.get("SECUCODE"))
        category = _stock_category(event_type)

        out.append(CalendarEvent(
            cal_type="stock",
            event_date=_d(r.get("TRADE_DATE")) or date,
            event_key=f"{code}|{event_type}",
            title=f"{name} {event_type}".strip() if name else event_type,
            category=category,
            sub_type=event_type,
            content=_t(r.get("EVENT_CONTENT")),
            code=code,
            name=name,
            importance=STOCK_CATEGORY_IMPORTANCE.get(category, 1),
            url=f"https://quote.eastmoney.com/{_quote_slug(secucode, code)}.html" if code else "",
            updated_ts=now,
            extra={"secucode": secucode},
        ))
    return out


def _quote_slug(secucode: str, code: str) -> str:
    """构造东财行情页 slug：sh600000 / sz000001 / bj920925"""
    suffix = (secucode.split(".")[-1] if "." in secucode else "").upper()
    prefix = {"SH": "sh", "SZ": "sz", "BJ": "bj"}.get(suffix, "")
    if prefix:
        return prefix + code
    if code.startswith(("60", "68", "51", "58", "11")):
        return "sh" + code
    if code.startswith(("00", "30", "12", "15", "16")):
        return "sz" + code
    return "bj" + code


# 3. 新股申购日历
def parse_ipo(rows: List[Dict[str, Any]], date: str) -> List[CalendarEvent]:
    """RPT_IPO_CALENDAR -> CalendarEvent（新股 / 可转债节点）"""
    now = int(time.time())
    out: List[CalendarEvent] = []
    for r in rows:
        code = _t(r.get("SECURITY_CODE"))
        date_type = _t(r.get("DATE_TYPE"))
        if not date_type:
            continue

        name = _t(r.get("SECURITY_NAME_ABBR"))
        sec_type = _t(r.get("SECURITY_TYPE"))
        sec_label = IPO_SECURITY_TYPE.get(sec_type, "新股")
        secucode = _t(r.get("SECUCODE"))

        out.append(CalendarEvent(
            cal_type="ipo",
            event_date=_d(r.get("TRADE_DATE")) or date,
            event_key=f"{code}|{date_type}",
            title=f"{name} {date_type}".strip() if name else date_type,
            category=date_type,
            sub_type=sec_label,
            content=f"{sec_label} · {name}（{code}）{date_type}" if name else "",
            code=code,
            name=name,
            importance=IPO_IMPORTANCE.get(date_type, 1),
            url=f"https://data.eastmoney.com/xg/xg/detail/{code}.html" if code else "",
            updated_ts=now,
            extra={
                "secucode": secucode,
                "security_type": sec_type,
                "security_label": sec_label,
                "org_code": _t(r.get("ORG_CODE")),
            },
        ))
    return out


# 4. 全球经济日历
def parse_global(html_text: str, date: str) -> List[CalendarEvent]:
    """解析 forex.eastmoney.com/FC.html 服务端渲染表格

    表头：序号 | 公布日 | 时间 | 国家/地区 | 事件 | 报告期 |
          公布值 | 预测值 | 前值 | 重要性 | 趋势
    """
    now = int(time.time())
    out: List[CalendarEvent] = []
    idx = GLOBAL_COL_INDEX

    for row_html in _RE_TR.findall(html_text or ""):
        tds = _RE_TD.findall(row_html)
        if len(tds) < 10:
            continue

        cells = [_clean_html(x) for x in tds]
        ev_date = _t(cells[idx["date"]])
        if not re.match(r"^\d{4}-\d{2}-\d{2}$", ev_date):
            continue

        title = _t(cells[idx["title"]])
        if not title:
            continue

        region = _t(cells[idx["region"]])
        raw_time = _t(cells[idx["time"]])
        # 源站对「未公布具体时间」的事件填 00:00，视为无时刻，避免噪音
        ev_time = "" if raw_time == "00:00" else raw_time

        imp_text = _t(cells[idx["importance"]])
        importance = GLOBAL_IMPORTANCE_MAP.get(imp_text, 0)
        if not importance:
            # 兜底：靠 font color 判断（red=高）
            m = _RE_FONT_COLOR.search(tds[idx["importance"]])
            importance = 3 if (m and m.group(1).lower() == "red") else 1

        trend = _norm_value(cells[idx["trend"]]) if len(cells) > idx["trend"] else ""

        out.append(CalendarEvent(
            cal_type="global",
            event_date=ev_date,
            event_key=f"{region}|{title}|{raw_time}",
            title=title,
            event_time=ev_time,
            category=region or "其它",
            sub_type="经济数据",
            region=region,
            importance=importance,
            period=_norm_value(cells[idx["period"]]),
            actual_value=_norm_value(cells[idx["actual"]]),
            forecast_value=_norm_value(cells[idx["forecast"]]),
            prev_value=_norm_value(cells[idx["prev"]]),
            updated_ts=now,
            extra={"trend": trend, "importance_text": imp_text},
        ))
    return out


# 5. 业绩预告日历
def _report_category(pred_type: str) -> str:
    """业绩方向归类：命中 REPORT_CATEGORIES 同名原值，否则回退到最接近的方向"""
    for c in REPORT_CATEGORIES:
        if c == pred_type or c in pred_type:
            return c
    # 兜底：按利好 / 利空关键词判定
    for p in ("预增", "扭亏", "续盈", "略增", "预盈"):
        if p in pred_type:
            return p
    for n in ("预减", "首亏", "续亏", "略减", "增亏"):
        if n in pred_type:
            return n
    return "不确定"


def _fmt_amt(v: Any) -> str:
    """金额值格式化为万元表达（源为元，空/null -> ''）"""
    if v is None or v == "":
        return ""
    try:
        f = float(v)
    except (TypeError, ValueError):
        return _t(v)
    return f"{f / 10000:.2f}万元"


def _fmt_pct(v: Any) -> str:
    """幅度百分比（源为百分数数值，空/null -> ''）"""
    if v is None or v == "":
        return ""
    try:
        return f"{float(v):g}%"
    except (TypeError, ValueError):
        return _t(v)


def _report_period(date: str) -> str:
    """由报告期(YYYY-MM-DD)推导简短标签：2026-06-30 -> 2026中报"""
    if not date:
        return ""
    d = _d(date)
    if not d:
        return ""
    m = int(d[5:7])
    label = {6: "中报", 9: "三季报", 3: "一季报", 12: "年报"}.get(m, "报")
    return f"{d[:4]}{label}"


def parse_report(rows: List[Dict[str, Any]], date: str) -> List[CalendarEvent]:
    """RPT_PUBLIC_OP_NEWPREDICT -> CalendarEvent（上市公司业绩预告）"""
    now = int(time.time())
    out: List[CalendarEvent] = []
    for r in rows:
        code = _t(r.get("SECURITY_CODE"))
        name = _t(r.get("SECURITY_NAME_ABBR"))
        pred_type = _t(r.get("PREDICT_TYPE"))
        if not name or not pred_type:
            continue

        category = _report_category(pred_type)
        report_date = _d(r.get("REPORT_DATE"))
        secucode = _t(r.get("SECUCODE"))

        amt_low = _fmt_amt(r.get("PREDICT_AMT_LOWER"))
        amt_high = _fmt_amt(r.get("PREDICT_AMT_UPPER"))
        amp_low = _fmt_pct(r.get("ADD_AMP_LOWER"))
        amp_high = _fmt_pct(r.get("ADD_AMP_UPPER"))

        # 幅度区间文本，用于标题后补充
        amp_str = ""
        if amp_low and amp_high and amp_low == amp_high:
            amp_str = f"（{amp_low}）"
        elif amp_low and amp_high:
            amp_str = f"（{amp_low}~{amp_high}）"
        elif amp_low:
            amp_str = f"（{amp_low}）"
        elif amp_high:
            amp_str = f"（{amp_high}）"

        content = _t(r.get("PREDICT_CONTENT"))
        finance = _t(r.get("PREDICT_FINANCE"))

        out.append(CalendarEvent(
            cal_type="report",
            event_date=date,
            event_key=f"{code}|{pred_type}|{report_date}|{finance}",
            title=f"{name} {category}{amp_str}",
            category=category,
            sub_type=pred_type,
            content=content or f"{finance}：{category}",
            code=code,
            name=name,
            period=_report_period(report_date) or report_date,
            prev_value=_t(r.get("PREYEAR_SAME_PERIOD")) or "",
            importance=REPORT_IMPORTANCE_MAP.get(category, 2),
            url=f"https://quote.eastmoney.com/{_quote_slug(secucode, code)}.html" if code else "",
            updated_ts=now,
            extra={
                "secucode": secucode,
                "report_date": report_date,
                "finance": finance,
                "amt_lower": amt_low,
                "amt_upper": amt_high,
                "amp_lower": amp_low,
                "amp_upper": amp_high,
                "market": _t(r.get("TRADE_MARKET")),
            },
        ))
    return out


# 6. 限售解禁日历
def _fmt_wan(value: Any) -> str:
    """金额/数量（万元原始值）转易读文本：<1亿用"xxxx万"，>=1亿用"x.xx亿" """
    if value is None or value == "":
        return ""
    try:
        v = float(value)
    except (TypeError, ValueError):
        return _t(value)
    if abs(v) >= 10000:
        return f"{v / 10000:.2f}亿"
    return f"{v:.0f}万"


def _fmt_ratio(value: Any) -> str:
    """占比（小数 0.012 -> 1.2%）"""
    if value is None or value == "":
        return ""
    try:
        v = float(value) * 100
    except (TypeError, ValueError):
        return _t(value)
    return f"{v:.2f}%"


def _lift_importance(market_cap: Any) -> int:
    """解禁市值（万元）决定重要性：抛压越大，风险越高"""
    try:
        v = float(market_cap or 0)
    except (TypeError, ValueError):
        return 1
    for th, imp in LIFT_IMPORTANCE_MARKET_CAP:
        if v >= th:
            return imp
    return 1


def parse_lift(rows: List[Dict[str, Any]], date: str) -> List[CalendarEvent]:
    """RPT_LIFT_STAGE -> CalendarEvent（限售股解禁）"""
    now = int(time.time())
    out: List[CalendarEvent] = []
    for r in rows:
        code = _t(r.get("SECURITY_CODE"))
        name = _t(r.get("SECURITY_NAME_ABBR"))
        share_type = _t(r.get("FREE_SHARES_TYPE"))
        if not code or not name:
            continue

        free_date = _d(r.get("FREE_DATE")) or date
        market_cap = r.get("LIFT_MARKET_CAP")  # 万元
        shares = r.get("CURRENT_FREE_SHARES")  # 万股
        ratio = r.get("FREE_RATIO")            # 小数

        cap_str = _fmt_wan(market_cap)
        share_str = _fmt_wan(shares)
        ratio_str = _fmt_ratio(ratio)
        secucode = _t(r.get("SECUCODE"))

        # 详情文本：数量/市值/占比
        parts = []
        if share_str:
            parts.append(f"解禁股份 {share_str}")
        if cap_str:
            parts.append(f"解禁市值 {cap_str}")
        if ratio_str:
            parts.append(f"占总股本 {ratio_str}")
        content = " · ".join(parts) or f"{share_type}解禁"

        title = f"{name} {share_type}解禁" if share_type else f"{name} 限售解禁"
        if cap_str and market_cap is not None:
            title += f"（{cap_str}）"

        out.append(CalendarEvent(
            cal_type="lift",
            event_date=free_date,
            event_key=f"{code}|{share_type}|{free_date}",
            title=title,
            category=share_type or "其它",
            sub_type=share_type or "解禁",
            content=content,
            code=code,
            name=name,
            importance=_lift_importance(market_cap),
            url=f"https://quote.eastmoney.com/{_quote_slug(secucode, code)}.html",
            updated_ts=now,
            extra={
                "secucode": secucode,
                "free_shares": _t(shares) if shares is not None else "",
                "shares_text": share_str,
                "market_cap": _t(market_cap) if market_cap is not None else "",
                "market_cap_text": cap_str,
                "ratio": ratio_str,
            },
        ))
    return out


PARSERS = {
    "finance": parse_finance,
    "stock": parse_stock,
    "ipo": parse_ipo,
    "global": parse_global,
    "report": parse_report,
    "lift": parse_lift,
}
