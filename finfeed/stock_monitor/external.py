#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""股票监控模块 — 系统外数据源（东方财富公开接口）。

- ``fetch_stock_news``      个股资讯列表（np-listapi.getListInfo）
- ``fetch_stock_announcements``  个股公告列表（np-anotice-stock）
- ``resolve_name_online``   行情接口核验代码并解析名称（push2.eastmoney）

所有函数均为同步实现（FastAPI 线程池 / 后台线程调用），异常向上抛出由
调用方兜底，保证单数据源故障不影响其他渠道。
"""

from __future__ import annotations

import logging
import re
from datetime import datetime
from typing import Any, Dict, List, Optional

import httpx

logger = logging.getLogger("stock_monitor")

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/126.0 Safari/537.36"
    ),
    "Referer": "https://quote.eastmoney.com/",
}
_TIMEOUT = 12.0

# A 股代码 -> 东财 secid 市场号：沪 1，深/北 0
def market_no(market: str) -> str:
    return "1" if market == "SH" else "0"


def _parse_time(time_str: str) -> int:
    """'2026-08-28 12:45:02'（或含毫秒/冒号尾段）-> Unix 秒。"""
    if not time_str:
        return 0
    m = re.match(r"(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})", time_str.strip())
    if not m:
        return 0
    try:
        return int(datetime.strptime(m.group(1), "%Y-%m-%d %H:%M:%S").timestamp())
    except ValueError:
        return 0


# ============================================================
# 个股资讯
# ============================================================
def fetch_stock_news(code: str, market: str, page_size: int = 15) -> List[Dict[str, Any]]:
    """拉取个股相关资讯（东财 getListInfo，type=1 为个股新闻）。"""
    url = "https://np-listapi.eastmoney.com/comm/web/getListInfo"
    params = {
        "client": "web",
        "mTypeAndCode": f"{market_no(market)}.{code}",
        "type": "1",
        "pageSize": str(page_size),
    }
    out: List[Dict[str, Any]] = []
    with httpx.Client(timeout=_TIMEOUT, headers=_HEADERS) as client:
        resp = client.get(url, params=params)
        resp.raise_for_status()
        data = resp.json() or {}
    for it in (data.get("data") or {}).get("list") or []:
        title = (it.get("Art_Title") or "").strip()
        if not title:
            continue
        ts = _parse_time(it.get("Art_ShowTime") or "")
        out.append({
            "code": code,
            "channel": "news",
            "title": title,
            "url": it.get("Art_Url") or it.get("Art_OriginUrl") or "",
            "summary": (it.get("Art_Summary") or "").strip(),
            "source": it.get("Art_MediaName") or "东方财富",
            "publish_time": (it.get("Art_ShowTime") or "")[:19],
            "publish_ts": ts,
            "dedup_key": f"news:{it.get('Art_Code') or title}",
        })
    return out


# ============================================================
# 个股公告
# ============================================================
def fetch_stock_announcements(code: str, page_size: int = 15) -> List[Dict[str, Any]]:
    """拉取个股公告（东财 np-anotice-stock，覆盖沪深北全市场）。"""
    url = "https://np-anotice-stock.eastmoney.com/api/security/ann"
    params = {
        "sr": "-1",
        "page_size": str(page_size),
        "page_index": "1",
        "ann_type": "A",
        "client_source": "web",
        "stock_list": code,
        "f_node": "0",
        "s_node": "0",
    }
    out: List[Dict[str, Any]] = []
    with httpx.Client(timeout=_TIMEOUT, headers=_HEADERS) as client:
        resp = client.get(url, params=params)
        resp.raise_for_status()
        data = resp.json() or {}
    for it in (data.get("data") or {}).get("list") or []:
        title = (it.get("title") or "").strip()
        if not title:
            continue
        ei = it.get("eiTime") or it.get("display_time") or ""
        ts = _parse_time(ei)
        art_code = it.get("art_code") or ""
        codes = it.get("codes") or []
        col_names = [c.get("column_name") for c in (it.get("columns") or []) if c.get("column_name")]
        out.append({
            "code": code,
            "channel": "announcement",
            "title": title,
            "url": (
                f"https://data.eastmoney.com/notices/detail/{code}/{art_code}.html"
                if art_code else ""
            ),
            "summary": "、".join(col_names),
            "source": "巨潮/东财公告",
            "publish_time": ei[:19],
            "publish_ts": ts,
            "dedup_key": f"ann:{art_code or title}",
        })
    return out


# ============================================================
# 全市场股票名单（名称/拼音解析的数据底座）
# ============================================================
_CLIST_FS = "m:0+t:6,m:0+t:80,m:1+t:2,m:1+t:23,m:0+t:81+s:2048"  # 沪深主板+科创+创业+北交


def fetch_all_a_names(page_size: int = 100, max_pages: int = 80) -> List[Dict[str, str]]:
    """分页拉取全市场 A 股 {code, name, market} 名单（东财 clist 接口，单页上限 100）。

    供名称/拼音简称解析构建索引；部分页失败时跳过继续，保证尽力而为。
    """
    url = "https://push2.eastmoney.com/api/qt/clist/get"
    out: List[Dict[str, str]] = []
    seen = set()
    with httpx.Client(timeout=_TIMEOUT, headers=_HEADERS) as client:
        for pn in range(1, max_pages + 1):
            params = {
                "pn": str(pn), "pz": str(page_size), "po": "1", "np": "1",
                "fltt": "2", "invt": "2", "fid": "f12", "fs": _CLIST_FS,
                "fields": "f12,f14",
            }
            try:
                resp = client.get(url, params=params)
                resp.raise_for_status()
                data = (resp.json() or {}).get("data") or {}
            except Exception as e:  # noqa: BLE001
                logger.warning("全市场名单第 %s 页拉取失败: %s", pn, e)
                continue
            rows = data.get("diff") or []
            if not rows:
                break
            for r in rows:
                code = str(r.get("f12") or "")
                name = str(r.get("f14") or "").strip()
                if code and name and code not in seen:
                    seen.add(code)
                    out.append({"code": code, "name": name})
            if len(out) >= int(data.get("total") or 0):
                break
    return out


# ============================================================
# 代码核验 / 名称解析
# ============================================================
def resolve_name_online(code: str, market: str) -> Optional[Dict[str, Any]]:
    """通过东财行情接口核验代码是否存在，返回 {code,name} 或 None。

    抛出异常表示网络不可达（与「确认代码不存在」区分开）。
    """
    url = "https://push2.eastmoney.com/api/qt/stock/get"
    params = {"secid": f"{market_no(market)}.{code}", "fields": "f57,f58", "invt": "2"}
    with httpx.Client(timeout=_TIMEOUT, headers=_HEADERS) as client:
        resp = client.get(url, params=params)
        resp.raise_for_status()
        data = resp.json() or {}
    d = data.get("data") or {}
    name = (d.get("f58") or "").strip()
    if not name or d.get("f57") != code:
        return None
    return {"code": code, "name": name}


def fetch_all_for_codes(entries: List[Dict[str, str]]) -> List[Dict[str, Any]]:
    """批量拉取外部消息（每只股票 = 资讯 + 公告），单只失败不影响其余。"""
    items: List[Dict[str, Any]] = []
    for e in entries:
        code, market = e["code"], e.get("market", "")
        try:
            items.extend(fetch_stock_news(code, market))
        except Exception as e:  # noqa: BLE001
            logger.warning("外部资讯拉取失败 %s: %s", code, e)
        try:
            items.extend(fetch_stock_announcements(code))
        except Exception as e:  # noqa: BLE001
            logger.warning("外部公告拉取失败 %s: %s", code, e)
    return items
