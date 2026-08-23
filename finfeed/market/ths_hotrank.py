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

import asyncio
import json
import logging
import time
from typing import Any, Dict, List, Optional

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

# 板块（plate）子榜单：概念 / 行业（同花顺热榜实际可用项；region 等返回 -1）
# 板块无 hour/day 时间维度，type 即子榜单，period 恒为 day。
PLATE_TYPES: Dict[str, Dict] = {
    "concept": {"title": "概念", "periods": ["day"], "default_period": "day"},
    "industry": {"title": "行业", "periods": ["day"], "default_period": "day"},
}
PLATE_URL = "https://dq.10jqka.com.cn/fuyao/hot_list_data/out/hot_list/v1/plate"

# 同花顺热榜统一 API 基址（所有免费 GET 类目共用）
API_BASE = "https://dq.10jqka.com.cn/fuyao/hot_list_data/out/hot_list/v1"

# 免费 GET 类目端点配置：path=接口路径；build=构造请求参数；
# key=返回数据中承载列表的字段（None 表示 data 本身就是列表）；norm=归一化函数名
CAT_ENDPOINT: Dict[str, Dict] = {
    "etf":    {"path": "etf",    "build": lambda lt, p: {"type": p},
               "key": "list", "norm": "item"},
    "bond":   {"path": "bond",   "build": lambda lt, p: {"type": p},
               "key": None, "norm": "bond"},
    "future": {"path": "future", "build": lambda lt, p: {"type": p},
               "key": "futures_list", "norm": "future"},
    "hot":    {"path": "topic",  "build": lambda lt, p: {"type": p},
               "key": "topic_list", "norm": "topic"},
    "hkus":   {"path": "stock",  "build": lambda lt, p: {"stock_type": lt, "type": "day", "list_type": "normal"},
               "key": "stock_list", "norm": "item"},
}

# 各免费类目的子榜单与时间维度（与前端 ThsHotList.vue 对齐）
CAT_SUB_TYPES: Dict[str, Dict] = {
    "etf":    {"day": {"title": "ETF热门", "periods": ["day", "hour"], "default_period": "hour"}},
    "bond":   {"day": {"title": "可转债", "periods": ["day", "hour"], "default_period": "hour"}},
    "future": {"day": {"title": "期货", "periods": ["day", "hour"], "default_period": "hour"}},
    "hot":    {"day": {"title": "热门话题", "periods": ["day", "hour"], "default_period": "hour"}},
    "hkus": {
        "hk": {"title": "港股", "periods": ["day"], "default_period": "day"},
        "us": {"title": "美股", "periods": ["day"], "default_period": "day"},
    },
    "fund":   {"day": {"title": "人气榜", "periods": ["day"], "default_period": "day"}},
}

# 问财（iwencai）热基接口：免登录 GET，返回 answer.components[0].data.datas[0].body
IWENCAI_URL = "https://ai.iwencai.com/index/urp/getdata/basic"
FUND_TAG = "同花顺热榜_热基"
IWENCAI_REFERER = "https://www.iwencai.com/"

# ===== 东方财富替代源：美股 / 保险 =====
# 同花顺热榜的「美股」「保险」两类需登录账号方可查看，公开免登录通道不可达。
# 为补齐这两类真实数据，改由东方财富实时行情接口提供（透明标注来源，仅作替代展示）。
EASTMONEY_CLIST = "https://push2.eastmoney.com/api/qt/clist/get"
EASTMONEY_ULIST = "https://push2.eastmoney.com/api/qt/ulist.np/get"
EASTMONEY_REFERER = "https://quote.eastmoney.com/"
# 美股市场（纽交所 m:105 + 纳斯达克 m:106）
EM_US_FS = "m:105,m:106"
# 美股列表中需剔除的权证/单位/权利类条目（名称含以下子串），保留正股与 ETF
EM_US_EXCLUDE = ("rt", "wt", "warrant", "right", "unit", "ws", "rt-a", "wt-")
# 保险板块个股池（A股保险及保险系金控，东方财富实时行情）。
# 剔除 *ST天茂（000627，已暂停上市，无行情）。
EM_INSURANCE_SECIDS = [
    "1.601318",  # 中国平安
    "1.601628",  # 中国人寿
    "1.601601",  # 中国太保
    "1.601319",  # 中国人保
    "1.601336",  # 新华保险
    "0.002423",  # 中粮资本（中英人寿）
    "1.600120",  # 浙江东方（中韩人寿）
    "1.600643",  # 爱建集团
    "1.600061",  # 国投资本
    "0.000567",  # 海德股份（AMC）
    "1.600830",  # 香溢融通
    "1.600318",  # 新力金融
]

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


def _normalize_plate(it: Dict) -> Dict:
    """把同花顺板块原始字段规整为前端友好的结构（附带 ETF 联动字段）。"""
    try:
        heat = float(it.get("rate") or it.get("hot") or 0)
    except (TypeError, ValueError):
        heat = 0.0
    try:
        chg = float(it["rise_and_fall"]) if it.get("rise_and_fall") is not None else None
    except (TypeError, ValueError):
        chg = None
    tag = it.get("tag")
    extra = {
        "etf_name": it.get("etf_name"),
        "etf_product_id": it.get("etf_product_id"),
        "etf_rise_and_fall": it.get("etf_rise_and_fall"),
        "hot_tag": it.get("hot_tag"),
        "market_id": it.get("market_id"),
    }
    return {
        "rank": it.get("order"),
        "code": it.get("code"),
        "name": it.get("name"),
        "market": it.get("market_id"),
        "heat": heat,
        "change_pct": chg,
        "rank_chg": it.get("hot_rank_chg"),
        "popularity_tag": (it.get("hot_tag") or "").replace("\n", ""),
        "concept_tags": [tag] if tag else [],
        "topic": "",
        "extra": extra,
    }


def _normalize_bond(it: Dict) -> Dict:
    """可转债：热度用 hot 字段，涨跌幅可能为 null。"""
    try:
        heat = float(it.get("hot") or 0)
    except (TypeError, ValueError):
        heat = 0.0
    try:
        chg = float(it["rise_and_fall"]) if it.get("rise_and_fall") is not None else None
    except (TypeError, ValueError):
        chg = None
    return {
        "rank": it.get("order"), "code": it.get("code"), "name": it.get("name"),
        "market": it.get("market"), "heat": heat, "change_pct": chg,
        "rank_chg": it.get("hot_rank_chg"), "popularity_tag": "",
        "concept_tags": [], "topic": "",
    }


def _normalize_future(it: Dict) -> Dict:
    """期货：rate 为热度（字符串），rise_and_fall 为涨跌幅；附带资金与关联个股。"""
    try:
        heat = float(it.get("rate") or 0)
    except (TypeError, ValueError):
        heat = 0.0
    try:
        chg = float(it["rise_and_fall"]) if it.get("rise_and_fall") is not None else None
    except (TypeError, ValueError):
        chg = None
    extra: Dict[str, Any] = {}
    if it.get("funds") is not None:
        extra["funds"] = it.get("funds")
    rel = it.get("stock_list") or []
    if rel:
        extra["rel_stocks"] = [
            {"name": s.get("name"), "code": s.get("code"), "rise_and_fall": s.get("rise_and_fall")}
            for s in rel[:5]
        ]
    return {
        "rank": it.get("order"), "code": it.get("code"), "name": it.get("name"),
        "market": it.get("market"), "heat": heat, "change_pct": chg,
        "rank_chg": it.get("hot_rank_chg"), "popularity_tag": "",
        "concept_tags": [], "topic": "", "extra": extra if extra else None,
    }


def _normalize_topic(it: Dict) -> Dict:
    """热门话题：讨论型条目，无热度/涨跌幅，标题与描述为核心。"""
    return {
        "rank": it.get("order") or it.get("hot_rank") or 0,
        "code": it.get("code"), "name": it.get("title"),
        "market": "", "heat": 0, "change_pct": None,
        "rank_chg": it.get("hot_rank_chg"),
        "popularity_tag": (it.get("popularity_tag") or "").replace("\n", ""),
        "concept_tags": [], "topic": it.get("description") or "",
    }


def _normalize_dispatch(norm: str, it: Dict) -> Dict:
    """按 norm 名称分派到对应归一化函数。"""
    if norm == "bond":
        return _normalize_bond(it)
    if norm == "future":
        return _normalize_future(it)
    if norm == "topic":
        return _normalize_topic(it)
    return _normalize_item(it)


async def _fetch_free_category_live(cat: str, list_type: str, period: str, limit: int) -> Dict:
    """真实请求免费 GET 类目（etf/bond/future/hot/hkus）并规整。"""
    cfg = CAT_ENDPOINT[cat]
    url = f"{API_BASE}/{cfg['path']}"
    params = cfg["build"](list_type, period) if cat == "hkus" else cfg["build"](list_type, period)
    headers = {
        "Referer": THS_REFERER, "User-Agent": THS_UA,
        "Accept": "application/json, text/plain, */*",
    }
    async with httpx.AsyncClient(timeout=20.0, headers=headers) as client:
        resp = await client.get(url, params=params)
        data = resp.json()
    if data.get("status_code") != 0:
        raise ValueError(
            f"同花顺接口返回错误: status_code={data.get('status_code')} {data.get('status_msg', '')}"
        )
    raw_data = data.get("data")
    if cfg["key"] is None:
        raw = raw_data if isinstance(raw_data, list) else []
    else:
        raw = (raw_data or {}).get(cfg["key"]) or []
    rows: List[Dict] = []
    max_heat = 0.0
    for idx, it in enumerate(raw[:limit]):
        item = _normalize_dispatch(cfg["norm"], it)
        if not item.get("rank"):
            item["rank"] = idx + 1
        rows.append(item)
        if (item.get("heat") or 0) > max_heat:
            max_heat = item["heat"]
    meta = CAT_SUB_TYPES.get(cat, {}).get(list_type) or {}
    return {
        "list_type": list_type,
        "title": meta.get("title") or cat,
        "period": period,
        "max_heat": max_heat,
        "count": len(rows),
        "updated_at": int(time.time()),
        "rows": rows,
        "source": "live",
    }


async def _get_free_category_live(cat: str, list_type: str, period: str, limit: int) -> Dict:
    """带 60s 内存 TTL 的免费类目实时获取。"""
    key = ("free", cat, list_type, period, limit)
    now = time.time()
    cached = _CACHE.get(key)
    if cached and now - cached[0] < _TTL:
        return cached[1]
    data = await _fetch_free_category_live(cat, list_type, period, limit)
    _CACHE[key] = (now, data)
    return data


async def _fetch_fund_live(limit: int) -> Dict:
    """真实请求问财热基接口并规整（body 为位置数组：
    [净值nav, 类型fund_type, 涨跌幅chgpct_1d, 基金名, 基金代码, 排名list_rank_1d]）。"""
    filt = {
        "offset": 0, "limit": limit,
        "sort": [["list_rank_1d", "ASC"]],
        "where": {"list_rank_1d": {"$lte": 200}, "class_name": {"$eq": "人气"}},
    }
    params = {"tag": FUND_TAG, "appName": "thsHotList", "filter": json.dumps(filt, ensure_ascii=False)}
    headers = {
        "Referer": IWENCAI_REFERER, "User-Agent": THS_UA,
        "Accept": "application/json, text/plain, */*",
    }
    async with httpx.AsyncClient(timeout=25.0, headers=headers, follow_redirects=True) as client:
        resp = await client.get(IWENCAI_URL, params=params)
        d = resp.json()
    comp = (d.get("answer") or {}).get("components") or []
    if not comp:
        raise ValueError(f"问财接口返回异常: {d.get('status_msg', '')}")
    datas = (((comp[0] or {}).get("data") or {}).get("datas") or [{}])
    body = (datas[0] if datas else {}).get("body") or []
    rows: List[Dict] = []
    max_heat = 0.0
    for idx, row in enumerate(body[:limit]):
        nav = row[0] if len(row) > 0 else None
        ftype = row[1] if len(row) > 1 else ""
        chg = row[2] if len(row) > 2 else None
        fname = row[3] if len(row) > 3 else ""
        fcode = row[4] if len(row) > 4 else ""
        rank = row[5] if len(row) > 5 else (idx + 1)
        try:
            chg = float(chg) if chg is not None else None
        except (TypeError, ValueError):
            chg = None
        try:
            rank = int(rank)
        except (TypeError, ValueError):
            rank = idx + 1
        try:
            heat = float(nav) if nav is not None else 0.0
        except (TypeError, ValueError):
            heat = 0.0
        item = {
            "rank": rank, "code": str(fcode), "name": fname, "market": "",
            "heat": heat, "change_pct": chg, "rank_chg": 0,
            "popularity_tag": "", "concept_tags": [], "topic": "",
            "extra": {"nav": nav, "fund_type": ftype},
        }
        rows.append(item)
        if heat > max_heat:
            max_heat = heat
    return {
        "list_type": "day", "title": "热基人气榜", "period": "day",
        "max_heat": max_heat, "count": len(rows),
        "updated_at": int(time.time()), "rows": rows, "source": "live",
    }


async def _get_fund_live(limit: int) -> Dict:
    """带 60s 内存 TTL 的热基实时获取。"""
    key = ("fund", limit)
    now = time.time()
    cached = _CACHE.get(key)
    if cached and now - cached[0] < _TTL:
        return cached[1]
    data = await _fetch_fund_live(limit)
    _CACHE[key] = (now, data)
    return data


def _em_market(code: str) -> str:
    """由股票代码推断市场（用于东方财富替代源的行展示）。"""
    if code.startswith("6"):
        return "SH"
    if code.startswith(("0", "3")):
        return "SZ"
    return ""


async def _em_get(url: str, params: Dict, headers: Dict, tries: int = 8) -> Dict:
    """东方财富行情接口 GET，带重试与抖动。

    该接口在本环境偶发「服务端未响应即断开」(RemoteDisconnected)，重试可显著提升成功率。
    """
    last_exc: Optional[Exception] = None
    for i in range(tries):
        try:
            async with httpx.AsyncClient(timeout=20.0, headers=headers, follow_redirects=True) as client:
                resp = await client.get(url, params=params)
                return resp.json()
        except Exception as e:  # noqa: BLE001
            last_exc = e
            await asyncio.sleep(0.8 + i * 0.4)
    raise last_exc if last_exc else RuntimeError("东方财富请求失败")


def _normalize_em_row(it: Dict, provider: str) -> Dict:
    """把东方财富 clist/ulist 行规整为与同花顺热榜一致的前端结构。"""
    def _fnum(key):
        v = it.get(key)
        if v in (None, "-", ""):
            return None
        try:
            return float(v)
        except (TypeError, ValueError):
            return None

    code = str(it.get("f12") or "")
    chg = _fnum("f3")
    inflow = _fnum("f62")
    amount = _fnum("f6")
    return {
        "rank": 0,
        "code": code,
        "name": it.get("f14") or "",
        "market": _em_market(code),
        "heat": None,
        "change_pct": chg,
        "rank_chg": None,
        "popularity_tag": "",
        "concept_tags": [],
        "topic": "",
        "main_inflow": inflow,
        "amount": amount,
        "provider": provider,
    }


def _rank_em(rows: List[Dict]) -> List[Dict]:
    """按当前顺序补填排名。"""
    for i, r in enumerate(rows, 1):
        r["rank"] = i
    return rows


async def _fetch_eastmoney_us(limit: int) -> Dict:
    """美股活跃榜：东方财富美股全市场，按成交额降序，剔除权证/单位/权利。

    同花顺美股热榜需登录，此处以东方财富实时行情替代，透明标注来源。
    """
    limit = min(limit, 50)
    params = {
        "pn": "1", "pz": str(min(limit * 3, 300)), "po": "1", "np": "1",
        "fltt": "2", "invt": "2", "fid": "f6",
        "fs": EM_US_FS, "fields": "f12,f14,f2,f3,f62,f6,f104,f105",
    }
    headers = {
        "User-Agent": THS_UA, "Referer": EASTMONEY_REFERER,
        "Accept": "*/*", "Connection": "keep-alive",
    }
    try:
        data = await _em_get(EASTMONEY_CLIST, params, headers)
    except Exception as e:  # noqa: BLE001
        logger.warning("东方财富美股行情获取失败: %s", e)
        return {
            "category": "hkus", "list_type": "us", "title": "美股活跃榜",
            "period": "day", "max_heat": 0, "count": 0,
            "updated_at": int(time.time()), "rows": [],
            "source": "eastmoney", "provider": "东方财富",
            "error": "东方财富行情暂时获取失败，请稍后刷新重试",
            "note": "美股数据由东方财富实时行情提供（同花顺美股热榜需登录）。按成交额排序，已剔除权证/单位。",
        }
    diff = ((data.get("data") or {}).get("diff") or [])
    rows: List[Dict] = []
    for it in diff:
        nm = (it.get("f14") or "").lower()
        if any(b in nm for b in EM_US_EXCLUDE):
            continue
        rows.append(_normalize_em_row(it, "东方财富"))
        if len(rows) >= limit:
            break
    _rank_em(rows)
    return {
        "category": "hkus", "list_type": "us", "title": "美股活跃榜",
        "period": "day", "max_heat": 0, "count": len(rows),
        "updated_at": int(time.time()), "rows": rows,
        "source": "eastmoney", "provider": "东方财富",
        "note": "美股数据由东方财富实时行情提供（同花顺美股热榜需登录）。按成交额排序，已剔除权证/单位。",
    }


async def _fetch_eastmoney_insurance(limit: int) -> Dict:
    """保险板块：东方财富实时行情，个股池为 A 股保险及保险系金控。

    同花顺保险热榜需登录，此处以东方财富实时行情替代，透明标注来源。
    排序：优先按涨跌幅（直观），无行情个股自动剔除。
    """
    limit = min(limit, 20)
    params = {
        "fltt": "2", "invt": "2", "fid": "f3",
        "secids": ",".join(EM_INSURANCE_SECIDS),
        "fields": "f12,f14,f2,f3,f62,f6", "np": "1",
    }
    headers = {
        "User-Agent": THS_UA, "Referer": EASTMONEY_REFERER,
        "Accept": "*/*", "Connection": "keep-alive",
    }
    try:
        data = await _em_get(EASTMONEY_ULIST, params, headers)
    except Exception as e:  # noqa: BLE001
        logger.warning("东方财富保险行情获取失败: %s", e)
        return {
            "category": "insurance", "list_type": "day", "title": "保险板块",
            "period": "day", "max_heat": 0, "count": 0,
            "updated_at": int(time.time()), "rows": [],
            "source": "eastmoney", "provider": "东方财富",
            "error": "东方财富行情暂时获取失败，请稍后刷新重试",
            "note": "保险板块行情由东方财富实时提供（同花顺保险热榜需登录）。含 A 股保险及保险系金控。",
        }
    diff = ((data.get("data") or {}).get("diff") or [])
    rows = [_normalize_em_row(it, "东方财富") for it in diff]
    rows = [r for r in rows if r.get("change_pct") is not None or r.get("amount") is not None]
    rows.sort(key=lambda r: (r.get("change_pct") or 0), reverse=True)
    _rank_em(rows)
    return {
        "category": "insurance", "list_type": "day", "title": "保险板块",
        "period": "day", "max_heat": 0, "count": len(rows),
        "updated_at": int(time.time()), "rows": rows[:limit],
        "source": "eastmoney", "provider": "东方财富",
        "note": "保险板块行情由东方财富实时提供（同花顺保险热榜需登录）。含 A 股保险及保险系金控。",
    }


async def _get_eastmoney_us(limit: int) -> Dict:
    """带 60s 内存 TTL 的美股实时获取。"""
    key = ("em_us", limit)
    now = time.time()
    cached = _CACHE.get(key)
    if cached and now - cached[0] < _TTL:
        return cached[1]
    data = await _fetch_eastmoney_us(limit)
    _CACHE[key] = (now, data)
    return data


async def _get_eastmoney_insurance(limit: int) -> Dict:
    """带 60s 内存 TTL 的保险实时获取。"""
    key = ("em_ins", limit)
    now = time.time()
    cached = _CACHE.get(key)
    if cached and now - cached[0] < _TTL:
        return cached[1]
    data = await _fetch_eastmoney_insurance(limit)
    _CACHE[key] = (now, data)
    return data


async def _fetch_free_hotrank(cat: str, list_type: str, period: str, limit: int,
                              date: Optional[str], category: str) -> Dict:
    """免费 GET 类目统一获取（实时 + 历史快照兜底 + 落库）。"""
    from finfeed.market import store

    sub = CAT_SUB_TYPES.get(cat, {}).get(list_type)
    if not sub:
        return {"error": f"不支持的榜单: {cat}/{list_type}", "category": category, "title": cat}
    if period not in sub["periods"]:
        period = sub.get("default_period") or sub["periods"][0]

    today = now_bj().strftime("%Y-%m-%d")
    if date and date != today:
        rows = store.get_ths_hotrank(date, list_type, period, limit, category=category)
        if not rows:
            return {"error": f"{date} 暂无{sub['title']}采集数据", "category": category,
                    "list_type": list_type, "title": sub["title"]}
        return _build_from_rows(list_type, period, rows, source="db", trade_date=date,
                                category=category, title=sub["title"])

    try:
        data = await _get_free_category_live(cat, list_type, period, limit)
    except Exception as e:  # noqa: BLE001
        logger.warning("%s 实时获取失败，尝试历史快照: %s", cat, e)
        cached_date = store.get_latest_ths_hotrank_date(list_type, period, category=category)
        if cached_date and cached_date != today:
            rows = store.get_ths_hotrank(cached_date, list_type, period, limit, category=category)
            if rows:
                return _build_from_rows(list_type, period, rows, source="cache",
                                        cached_date=cached_date, category=category, title=sub["title"])
        return {"error": f"{sub['title']}实时数据获取失败，且无可用历史快照",
                "category": category, "list_type": list_type, "title": sub["title"]}

    try:
        collected_at = now_bj().strftime("%Y-%m-%d %H:%M:%S")
        persist = [
            _to_persist_row(list_type, period, r, today, collected_at,
                            category=category, extra=r.get("extra"))
            for r in data["rows"]
        ]
        store.upsert_ths_hotrank(persist)
    except Exception as e:  # noqa: BLE001
        logger.warning("%s 快照持久化失败: %s", cat, e)
    return data


async def _fetch_fund_hotrank(limit: int, date: Optional[str], category: str = "fund") -> Dict:
    """热基（问财）统一获取（实时 + 历史快照兜底 + 落库）。"""
    from finfeed.market import store

    today = now_bj().strftime("%Y-%m-%d")
    if date and date != today:
        rows = store.get_ths_hotrank(date, "day", "day", limit, category=category)
        if not rows:
            return {"error": f"{date} 暂无热基采集数据", "category": category,
                    "list_type": "day", "title": "热基人气榜"}
        return _build_from_rows("day", "day", rows, source="db", trade_date=date,
                                category=category, title="热基人气榜")

    try:
        data = await _get_fund_live(limit)
    except Exception as e:  # noqa: BLE001
        logger.warning("热基实时获取失败，尝试历史快照: %s", e)
        cached_date = store.get_latest_ths_hotrank_date("day", "day", category=category)
        if cached_date and cached_date != today:
            rows = store.get_ths_hotrank(cached_date, "day", "day", limit, category=category)
            if rows:
                return _build_from_rows("day", "day", rows, source="cache",
                                        cached_date=cached_date, category=category, title="热基人气榜")
        return {"error": "热基实时数据获取失败，且无可用历史快照",
                "category": category, "list_type": "day", "title": "热基人气榜"}

    try:
        collected_at = now_bj().strftime("%Y-%m-%d %H:%M:%S")
        persist = [
            _to_persist_row("day", "day", r, today, collected_at,
                            category=category, extra=r.get("extra"))
            for r in data["rows"]
        ]
        store.upsert_ths_hotrank(persist)
    except Exception as e:  # noqa: BLE001
        logger.warning("热基快照持久化失败: %s", e)
    return data


async def _fetch_plate_live(sub: str, limit: int) -> Dict:
    """真实请求同花顺板块接口并规整（不缓存、不持久化，异常直接上抛）。"""
    if sub not in PLATE_TYPES:
        sub = "concept"
    url = f"{PLATE_URL}?type={sub}"
    headers = {
        "Referer": THS_REFERER,
        "User-Agent": THS_UA,
        "Accept": "application/json, text/plain, */*",
    }
    async with httpx.AsyncClient(timeout=20.0, headers=headers) as client:
        resp = await client.get(url)
        data = resp.json()
    if data.get("status_code") != 0:
        raise ValueError(f"同花顺板块接口返回错误: status_code={data.get('status_code')}")
    raw = (data.get("data") or {}).get("plate_list") or []
    rows: List[Dict] = []
    max_heat = 0.0
    for it in raw[:limit]:
        item = _normalize_plate(it)
        rows.append(item)
        if item["heat"] > max_heat:
            max_heat = item["heat"]
    return {
        "list_type": sub,
        "title": PLATE_TYPES[sub]["title"],
        "period": "day",
        "max_heat": max_heat,
        "count": len(rows),
        "updated_at": int(time.time()),
        "rows": rows,
        "source": "live",
    }


async def _get_plate_live(sub: str, limit: int) -> Dict:
    """带 60s 内存 TTL 的板块实时获取（与 _get_live 同构，去抖）。"""
    key = ("plate", sub, limit)
    now = time.time()
    cached = _CACHE.get(key)
    if cached and now - cached[0] < _TTL:
        return cached[1]
    data = await _fetch_plate_live(sub, limit)
    _CACHE[key] = (now, data)
    return data


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
                    trade_date: str, collected_at: str,
                    category: str = "stock", extra: Optional[Dict] = None) -> Dict:
    """把规整后的热榜行转换为可写入 ths_hotrank 表的字典。"""
    concept = item.get("concept_tags") or []
    if not isinstance(concept, str):
        concept = json.dumps(concept, ensure_ascii=False)
    extra_json = "[]"
    if extra:
        try:
            extra_json = json.dumps(extra, ensure_ascii=False)
        except (TypeError, ValueError):
            extra_json = "[]"
    return {
        "trade_date": trade_date,
        "list_type": list_type,
        "period": period,
        "category": category,
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
        "extra_json": extra_json,
        "collected_at": collected_at,
    }


def _build_from_rows(list_type: str, period: str, rows: List[Dict],
                     source: str, trade_date: Optional[str] = None,
                     cached_date: Optional[str] = None,
                     category: str = "stock", title: Optional[str] = None) -> Dict:
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
        # 类目特有字段（板块的 ETF 联动等）从 extra_json 还原并扁平化到行
        extra = r.get("extra_json")
        if extra:
            try:
                extra = json.loads(extra)
            except (json.JSONDecodeError, TypeError):
                extra = {}
        else:
            extra = {}
        row = {
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
        }
        row.update(extra or {})
        out.append(row)
        if (r.get("heat") or 0) > max_heat:
            max_heat = r["heat"]
        if not collected_at:
            collected_at = r.get("collected_at") or ""
    meta = SUB_LISTS.get(list_type) or PLATE_TYPES.get(list_type)
    title = title or (meta["title"] if meta else list_type)
    return {
        "list_type": list_type,
        "title": title,
        "period": period,
        "max_heat": max_heat,
        "count": len(out),
        "rows": out,
        "source": source,
        "category": category,
        "trade_date": trade_date or (rows[0].get("trade_date") if rows else None),
        "collected_at": collected_at,
        "cached_date": cached_date,
    }


async def _fetch_plate_hotrank(list_type: str, period: str, limit: int,
                                date: Optional[str],
                                category: str = "plate") -> Dict:
    """获取同花顺板块热榜（与 _fetch_stock_hotrank 同构，按 category 区分落库）。"""
    from finfeed.market import store

    meta = PLATE_TYPES.get(list_type)
    if not meta:
        return {"error": f"不支持的板块榜单: {list_type}", "category": category, "title": "板块"}
    if period not in meta["periods"]:
        period = meta["default_period"]

    today = now_bj().strftime("%Y-%m-%d")

    # 历史快照：按日期只读，不触发实时请求
    if date and date != today:
        rows = store.get_ths_hotrank(date, list_type, period, limit, category=category)
        if not rows:
            return {
                "error": f"{date} 暂无板块热榜采集数据",
                "category": category, "list_type": list_type, "title": meta["title"],
            }
        return _build_from_rows(list_type, period, rows, source="db",
                                trade_date=date, category=category)

    # 当天/实时：优先拉取，失败回退最近快照
    try:
        data = await _get_plate_live(list_type, limit)
    except Exception as e:  # noqa: BLE001
        logger.warning("板块实时获取失败，尝试历史快照: %s", e)
        cached_date = store.get_latest_ths_hotrank_date(list_type, period, category=category)
        if cached_date and cached_date != today:
            rows = store.get_ths_hotrank(cached_date, list_type, period, limit, category=category)
            if rows:
                return _build_from_rows(list_type, period, rows, source="cache",
                                        cached_date=cached_date, category=category)
        return {
            "error": "板块实时数据获取失败，且无可用历史快照",
            "category": category, "list_type": list_type, "title": meta["title"],
        }

    # 持久化当天快照（幂等，供历史回看与实时失败回退）
    try:
        collected_at = now_bj().strftime("%Y-%m-%d %H:%M:%S")
        persist = [
            _to_persist_row(list_type, period, r, today, collected_at,
                            category=category, extra=r.get("extra"))
            for r in data["rows"]
        ]
        store.upsert_ths_hotrank(persist)
    except Exception as e:  # noqa: BLE001
        logger.warning("板块快照持久化失败: %s", e)
    return data


async def _fetch_stock_hotrank(list_type: str, period: str, limit: int,
                               date: Optional[str]) -> Dict:
    """热股（stock）获取：实时拉取 + 历史快照兜底 + 落库。"""
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
            return {"error": f"{date} 暂无热榜采集数据", "list_type": list_type, "title": meta["title"]}
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


async def fetch_hotrank(
    list_type: str = "normal",
    period: str = "hour",
    limit: int = 100,
    date: Optional[str] = None,
    category: str = "stock",
) -> Dict:
    """获取同花顺热榜（全类目统一入口）。

    类目（category）：
      stock 热股 | plate 板块 | etf ETF | hot 热门 |
      bond 可转债 | hkus 港美 | fund 热基 | future 期货 | insurance 保险

    - ``date`` 为过去交易日：只读该日已采集快照（无则报缺）。
    - ``date`` 为 None 或当日：实时拉取并持久化当天快照，失败回退最近快照。
    """
    if category == "plate":
        return await _fetch_plate_hotrank(list_type, period, limit, date)
    if category == "stock":
        return await _fetch_stock_hotrank(list_type, period, limit, date)
    if category == "insurance":
        # 同花顺保险热榜需登录，改由东方财富实时行情替代
        return await _get_eastmoney_insurance(limit)
    if category == "fund":
        return await _fetch_fund_hotrank(limit, date)
    if category in CAT_ENDPOINT:
        if category == "hkus" and list_type == "us":
            # 同花顺美股热榜需登录，改由东方财富实时行情替代
            return await _get_eastmoney_us(limit)
        return await _fetch_free_hotrank(category, list_type, period, limit, date, category)
    return {"error": f"未知类目: {category}"}


async def collect_all(trade_date: Optional[str] = None) -> Dict[str, Any]:
    """后台自动采集：遍历全部可用类目 × 子榜单 × 时间维度，落库为某交易日快照。

    返回 ``{trade_date, saved, attempted, errors}``。
    """
    from finfeed.market import store

    td = trade_date or now_bj().strftime("%Y-%m-%d")
    collected_at = now_bj().strftime("%Y-%m-%d %H:%M:%S")
    total_saved = 0
    attempted = 0
    errors: List[str] = []

    # 热股（stock）
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

    # 板块（plate）
    for list_type, meta in PLATE_TYPES.items():
        for period in meta["periods"]:
            attempted += 1
            try:
                data = await _get_plate_live(list_type, 200)
                rows = [
                    _to_persist_row(list_type, period, r, td, collected_at,
                                    category="plate", extra=r.get("extra"))
                    for r in data["rows"]
                ]
                total_saved += store.upsert_ths_hotrank(rows)
            except Exception as e:  # noqa: BLE001
                logger.warning("板块采集失败 %s/%s: %s", list_type, period, e)
                errors.append(f"plate/{list_type}/{period}: {e}")

    # 免费 GET 类目（etf / bond / future / hot / hkus）
    for cat in ("etf", "bond", "future", "hot", "hkus"):
        for list_type, meta in CAT_SUB_TYPES.get(cat, {}).items():
            if meta.get("unsupported"):
                continue
            period = meta.get("default_period") or meta["periods"][0]
            attempted += 1
            try:
                data = await _get_free_category_live(cat, list_type, period, 200)
                rows = [
                    _to_persist_row(list_type, period, r, td, collected_at,
                                    category=cat, extra=r.get("extra"))
                    for r in data["rows"]
                ]
                total_saved += store.upsert_ths_hotrank(rows)
            except Exception as e:  # noqa: BLE001
                logger.warning("%s 采集失败 %s: %s", cat, list_type, e)
                errors.append(f"{cat}/{list_type}: {e}")

    # 热基（fund，问财接口）
    attempted += 1
    try:
        data = await _get_fund_live(200)
        rows = [
            _to_persist_row("day", "day", r, td, collected_at,
                            category="fund", extra=r.get("extra"))
            for r in data["rows"]
        ]
        total_saved += store.upsert_ths_hotrank(rows)
    except Exception as e:  # noqa: BLE001
        logger.warning("热基采集失败: %s", e)
        errors.append(f"fund: {e}")

    # 保险（insurance）：同花顺以 amis iframe 提供，无免登录 JSON，跳过采集
    return {"trade_date": td, "saved": total_saved, "attempted": attempted, "errors": errors}
