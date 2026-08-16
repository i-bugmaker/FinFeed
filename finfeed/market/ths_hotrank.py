#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""同花顺热榜（thsTopRank）数据层。

数据源：同花顺公开热榜接口
    https://dq.10jqka.com.cn/fuyao/hot_list_data/out/hot_list/v1/stock

已实测可用的子榜单（list_type 为接口实际接受值）：
    normal     大家都在看   （支持 1 小时 / 24 小时）
    skyrocket  快速飙升中   （支持 1 小时 / 24 小时）
    tech       技术交易派   （仅 24 小时）
    value      价值投资派   （仅 24 小时）
    trend      趋势投资派   （仅 24 小时）

「新股热度榜」(new_stock) 使用独立鉴权接口（/open/api/hot_list/rank），
公开免鉴权通道不可达，故标记为 unsupported，由前端友好提示。

合规底线：仅限个人学习与技术研究，遵守 robots 与频率限制，勿商用分发原始数据。
"""

import time
import json
import logging
from typing import Dict, List, Optional

import httpx
from finfeed.storage.database import now_bj

logger = logging.getLogger("news_monitor")

HOT_LIST_URL = "https://dq.10jqka.com.cn/fuyao/hot_list_data/out/hot_list/v1/stock"
THS_REFERER = "https://eq.10jqka.com.cn/"
THS_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36"
)

# 子榜单配置：标题与可切换的时间维度
SUB_LISTS: Dict[str, Dict] = {
    "normal": {"title": "大家都在看", "periods": ["hour", "day"], "default_period": "hour"},
    "skyrocket": {"title": "快速飙升中", "periods": ["hour", "day"], "default_period": "hour"},
    "new_stock": {
        "title": "新股热度榜", "periods": ["day"], "default_period": "day",
        "unsupported": True,
    },
    "tech": {"title": "技术交易派", "periods": ["day"], "default_period": "day"},
    "value": {"title": "价值投资派", "periods": ["day"], "default_period": "day"},
    "trend": {"title": "趋势投资派", "periods": ["day"], "default_period": "day"},
}

# 顶部类目导航（与原始网站「同花顺热榜」逐一致；仅 热股 已接入数据）
CATEGORIES: List[Dict] = [
    {"value": "stock", "title": "热股"},
    {"value": "plate", "title": "板块"},
    {"value": "etf", "title": "ETF"},
    {"value": "hot", "title": "热门"},
    {"value": "bond", "title": "可转债"},
    {"value": "hkus", "title": "港美"},
    {"value": "fund", "title": "热基"},
    {"value": "future", "title": "期货"},
    {"value": "insurance", "title": "保险"},
]

# 内存 TTL 缓存：同花顺热榜约 5 分钟更新一次，60s 缓存足以去抖且避免频繁请求
_TTL = 60.0
_CACHE: Dict[tuple, tuple] = {}  # key -> (ts, result)


def _normalize_item(it: Dict) -> Dict:
    """把同花顺原始字段规整为前端友好的结构。"""
    try:
        heat = float(it.get("rate") or 0)
    except (TypeError, ValueError):
        heat = 0.0
    try:
        chg = float(it["rise_and_fall"]) if it.get("rise_and_fall") is not None else None
    except (TypeError, ValueError):
        chg = None
    tag = it.get("tag") or {}
    return {
        "rank": it.get("order"),
        "code": it.get("code"),
        "name": it.get("name"),
        "market": it.get("market"),
        "heat": heat,
        "change_pct": chg,
        "rank_chg": it.get("hot_rank_chg"),
        "popularity_tag": (tag.get("popularity_tag") or "").replace("\n", ""),
        "concept_tags": tag.get("concept_tag") or [],
        "topic": it.get("topic"),
    }


async def _fetch_live(list_type: str, period: str, limit: int) -> Dict:
    """真实请求同花顺接口并规整（不缓存、不持久化，异常直接上抛）。"""
    params = f"stock_type=a&type={period}&list_type={list_type}"
    url = f"{HOT_LIST_URL}?{params}"
    headers = {
        "Referer": THS_REFERER,
        "User-Agent": THS_UA,
        "Accept": "application/json, text/plain, */*",
    }
    async with httpx.AsyncClient(timeout=20.0, headers=headers) as client:
        resp = await client.get(url)
        data = resp.json()
    if data.get("status_code") != 0:
        raise ValueError(f"同花顺接口返回错误: status_code={data.get('status_code')}")
    raw = (data.get("data") or {}).get("stock_list") or []
    rows: List[Dict] = []
    max_heat = 0.0
    for it in raw[:limit]:
        item = _normalize_item(it)
        rows.append(item)
        if item["heat"] > max_heat:
            max_heat = item["heat"]
    return {
        "list_type": list_type,
        "title": SUB_LISTS[list_type]["title"],
        "period": period,
        "max_heat": max_heat,
        "count": len(rows),
        "updated_at": int(time.time()),
        "rows": rows,
        "source": "live",
    }


async def _get_live(list_type: str, period: str, limit: int) -> Dict:
    """带 60s 内存 TTL 的实时获取（前端实时查看与后台自动采集共用，去抖）。"""
    key = (list_type, period, limit)
    now = time.time()
    cached = _CACHE.get(key)
    if cached and now - cached[0] < _TTL:
        return cached[1]
    data = await _fetch_live(list_type, period, limit)
    _CACHE[key] = (now, data)
    return data


def _to_persist_row(list_type: str, period: str, item: Dict,
                    trade_date: str, collected_at: str) -> Dict:
    """把规整后的热榜行转换为可写入 ths_hotrank 表的字典。"""
    concept = item.get("concept_tags") or []
    if not isinstance(concept, str):
        concept = json.dumps(concept, ensure_ascii=False)
    return {
        "trade_date": trade_date,
        "list_type": list_type,
        "period": period,
        "rank": item.get("rank"),
        "code": item.get("code"),
        "name": item.get("name") or "",
        "market": item.get("market") or "",
        "heat": item.get("heat") or 0,
        "change_pct": item.get("change_pct") or 0,
        "rank_chg": item.get("rank_chg") or 0,
        "popularity_tag": item.get("popularity_tag") or "",
        "concept_tags": concept,
        "topic": item.get("topic") or "",
        "collected_at": collected_at,
    }


def _build_from_rows(list_type: str, period: str, rows: List[Dict],
                     source: str, trade_date: Optional[str] = None,
                     cached_date: Optional[str] = None) -> Dict:
    """把 DB 快照行还原为前端友好的结构。"""
    out: List[Dict] = []
    max_heat = 0.0
    collected_at = ""
    for r in rows:
        try:
            ct = json.loads(r.get("concept_tags") or "[]")
        except (json.JSONDecodeError, TypeError):
            ct = []
        chg = r.get("change_pct")
        if chg not in (None, ""):
            try:
                chg = float(chg)
            except (TypeError, ValueError):
                chg = None
        else:
            chg = None
        out.append({
            "rank": r.get("rank"),
            "code": r.get("code"),
            "name": r.get("name"),
            "market": r.get("market"),
            "heat": r.get("heat") or 0,
            "change_pct": chg,
            "rank_chg": r.get("rank_chg") or 0,
            "popularity_tag": r.get("popularity_tag") or "",
            "concept_tags": ct,
            "topic": r.get("topic") or "",
        })
        if (r.get("heat") or 0) > max_heat:
            max_heat = r["heat"]
        if not collected_at:
            collected_at = r.get("collected_at") or ""
    return {
        "list_type": list_type,
        "title": SUB_LISTS[list_type]["title"],
        "period": period,
        "max_heat": max_heat,
        "count": len(out),
        "rows": out,
        "source": source,
        "trade_date": trade_date or (rows[0].get("trade_date") if rows else None),
        "collected_at": collected_at,
        "cached_date": cached_date,
    }


async def fetch_hotrank(
    list_type: str = "normal",
    period: str = "hour",
    limit: int = 100,
    date: Optional[str] = None,
) -> Dict:
    """获取同花顺热榜。

    - ``date`` 为过去交易日：只读该日已采集的快照（无则报缺）。
    - ``date`` 为 None 或当日：实时拉取；成功则持久化当天快照，
      失败则回退到最近一次采集的快照（缓存兜底，解决实时接口不可达）。
    """
    from finfeed.market import store

    meta = SUB_LISTS.get(list_type)
    if not meta:
        return {"error": f"不支持的榜单: {list_type}"}
    if meta.get("unsupported"):
        return {
            "error": "新股热度榜数据源需同花顺鉴权，暂未接入",
            "unsupported": True,
            "list_type": list_type,
            "title": meta["title"],
        }
    if period not in meta["periods"]:
        period = meta["default_period"]

    today = now_bj().strftime("%Y-%m-%d")

    # 历史快照：按日期只读，不触发实时请求
    if date and date != today:
        rows = store.get_ths_hotrank(date, list_type, period, limit)
        if not rows:
            return {
                "error": f"{date} 暂无热榜采集数据",
                "list_type": list_type,
                "title": meta["title"],
            }
        return _build_from_rows(list_type, period, rows, source="db", trade_date=date)

    # 当天/实时：优先拉取，失败回退最近快照
    try:
        data = await _get_live(list_type, period, limit)
    except Exception as e:  # noqa: BLE001
        logger.warning("热榜实时获取失败，尝试历史快照: %s", e)
        cached_date = store.get_latest_ths_hotrank_date(list_type, period)
        if cached_date and cached_date != today:
            rows = store.get_ths_hotrank(cached_date, list_type, period, limit)
            if rows:
                return _build_from_rows(
                    list_type, period, rows, source="cache", cached_date=cached_date
                )
        return {
            "error": "实时数据获取失败，且无可用历史快照",
            "list_type": list_type,
            "title": meta["title"],
        }

    # 持久化当天快照（幂等，供历史回看与实时失败回退）
    try:
        collected_at = now_bj().strftime("%Y-%m-%d %H:%M:%S")
        persist = [
            _to_persist_row(list_type, period, r, today, collected_at)
            for r in data["rows"]
        ]
        store.upsert_ths_hotrank(persist)
    except Exception as e:  # noqa: BLE001
        logger.warning("热榜快照持久化失败: %s", e)
    return data


async def collect_all(trade_date: Optional[str] = None) -> Dict[str, Any]:
    """后台自动采集：遍历全部可用子榜单 × 时间维度，落库为某交易日快照。

    返回 ``{trade_date, saved, attempted, errors}``。
    """
    from finfeed.market import store

    td = trade_date or now_bj().strftime("%Y-%m-%d")
    collected_at = now_bj().strftime("%Y-%m-%d %H:%M:%S")
    total_saved = 0
    attempted = 0
    errors: List[str] = []
    for list_type, meta in SUB_LISTS.items():
        if meta.get("unsupported"):
            continue
        for period in meta["periods"]:
            attempted += 1
            try:
                data = await _get_live(list_type, period, 200)
                rows = [
                    _to_persist_row(list_type, period, r, td, collected_at)
                    for r in data["rows"]
                ]
                total_saved += store.upsert_ths_hotrank(rows)
            except Exception as e:  # noqa: BLE001
                logger.warning("热榜采集失败 %s/%s: %s", list_type, period, e)
                errors.append(f"{list_type}/{period}: {e}")
    return {"trade_date": td, "saved": total_saved, "attempted": attempted, "errors": errors}
