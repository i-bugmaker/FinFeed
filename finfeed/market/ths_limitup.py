#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""同花顺「涨停聚焦」数据层（四模块）

数据源：同花顺涨停聚焦移动版后端接口
    https://data.10jqka.com.cn/mobile/limitup/v2/index.html
完整接口契约见仓库 docs/ths-limitup-api.md（抓取分析日期 2026-08-17）。

四大模块 → 接口映射（与 API 文档一致）：
    涨停强度    dataapi limit_up_pool / open_limit_pool / lower_limit_pool
                （涨停 / 炸板 / 跌停池；涨停池以 mobileapi get_limit_up_stocks
                 的命名字段做富化，连板数 / 封板时间 / 主力净额等）
    强势股      dataapi continuous_limit_up（连板天梯）
                + mobileapi stock_pool get_limit_up_stocks（连板分层全量）
    最强风口    mobileapi market_state get_wind_vane_stock（风向标股）
    市场情绪    mobileapi market_state overview（情绪总览）
                + dataapi limit_up trade_status（交易状态）

与 ths_hotrank 同构的设计：
    - 持久 httpx.AsyncClient（同事件循环复用，cookie jar 跨请求保持）
    - 首次请求前 GET 根域名预热会话 Cookie（同花顺移动版接口前置要求）
    - 60s 内存 TTL 缓存（去抖 + 避免频繁请求）
    - 每个模块：当天实时拉取 → 失败回退最近一次 DB 快照
    - 实时成功即幂等落库，支撑历史交易日回看

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

# ---------------------------------------------------------------------------
# 常量与请求头
# ---------------------------------------------------------------------------
_ROOT = "https://data.10jqka.com.cn/"
_DATA = "https://data.10jqka.com.cn/dataapi"
_MOBILE = "https://data.10jqka.com.cn/mobileapi/hotspot_focus"

_REFERER = "https://data.10jqka.com.cn/mobile/limitup/v2/index.html"
_SOURCE_ID = "PROGRAM-limt-up-focus"   # 注意：同花顺文档原文即此拼写（limt）
_PLATFORM = "mobileweb"
_UA = "Mozilla/5.0"

# dataapi 涨停/炸板/跌停池：数字字段 ID（文档实测）
#   199112=代码  10=名称  9001=涨停原因  330323=最新价  330324=涨跌幅
_POOL_FIELDS = "199112,10,9001,330323,330324"
_POOL_FIELD_MAP = {
    "199112": "code", "10": "name", "9001": "reason",
    "330323": "price", "330324": "change_pct",
}

# 内存 TTL 缓存：同花顺涨停数据盘中日更数次，60s 足以去抖且避免频繁请求
_TTL = 60.0
_CACHE: Dict[tuple, tuple] = {}  # key -> (ts, result)

_client: Optional[httpx.AsyncClient] = None
_client_loop: Any = None
_warm_lock: Optional[asyncio.Lock] = None
_warmed = False


# ---------------------------------------------------------------------------
# 客户端与会话预热
# ---------------------------------------------------------------------------
def _get_client() -> httpx.AsyncClient:
    """按事件循环创建/复用持久客户端（cookie jar 跨请求保持会话）。"""
    global _client, _client_loop
    loop = asyncio.get_running_loop()
    if _client is None or _client.is_closed or _client_loop is not loop:
        _client = httpx.AsyncClient(
            timeout=25.0, follow_redirects=True,
            headers={"User-Agent": _UA},
            limits=httpx.Limits(max_connections=4, max_keepalive_connections=2),
        )
        _client_loop = loop
    return _client


async def _ensure_session() -> None:
    """建会话 Cookie：首次请求前 GET 根域名，使后续 dataapi/mobileapi 请求带会话。"""
    global _warmed, _warm_lock
    if _warmed:
        return
    if _warm_lock is None:
        _warm_lock = asyncio.Lock()
    async with _warm_lock:
        if _warmed:
            return
        try:
            client = _get_client()
            await client.get(_ROOT, headers={"User-Agent": _UA, "Referer": _REFERER})
            _warmed = True
        except Exception as e:  # noqa: BLE001
            logger.warning("同花顺会话预热失败（Cookie 未建立，部分接口可能拒绝）: %s", e)


async def _request(path: str, params: Optional[dict] = None,
                   mobile: bool = False, timeout: float = 25.0) -> dict:
    """GET 并解析 JSON，内置会话预热与业务级拒绝判定。

    mobile=True 时附加 Source-id / PlatForm 头（mobileapi 强制要求）。
    返回完整响应 dict；业务级拒绝（status_code!=0）抛 RuntimeError 由调用方降级。
    """
    await _ensure_session()
    client = _get_client()
    url = (_MOBILE if mobile else _DATA) + path
    headers = {
        "User-Agent": _UA,
        "Referer": _REFERER,
        "Accept": "application/json, text/plain, */*",
    }
    if mobile:
        headers["Source-id"] = _SOURCE_ID
        headers["PlatForm"] = _PLATFORM
    try:
        resp = await client.get(url, params=params, headers=headers, timeout=timeout)
        resp.raise_for_status()
        data = resp.json()
    except Exception as e:  # noqa: BLE001
        raise RuntimeError(f"同花顺请求失败 {path}: {e}") from e
    if isinstance(data, dict) and data.get("status_code", 0) != 0:
        raise RuntimeError(
            f"同花顺业务拒绝 {path}: status_code={data.get('status_code')} "
            f"msg={data.get('status_msg')}"
        )
    return data


def _data_of(resp: Any) -> Any:
    """剥离 status_code 外层，取 data 载荷；无 data 键则原样返回。"""
    if isinstance(resp, dict) and "data" in resp:
        return resp["data"]
    return resp


# ---------------------------------------------------------------------------
# 工具
# ---------------------------------------------------------------------------
def _num(v: Any) -> float:
    try:
        return float(v) if v is not None else 0.0
    except (TypeError, ValueError):
        return 0.0


def _int(v: Any) -> int:
    try:
        return int(v) if v is not None else 0
    except (TypeError, ValueError):
        try:
            return int(float(v))
        except (TypeError, ValueError):
            return 0


def _ymd(td: str) -> str:
    """YYYY-MM-DD -> yyyyMMdd（同花顺接口日期格式）。"""
    return td.replace("-", "")


def _json_load(s: Any) -> Any:
    if not s:
        return None
    if isinstance(s, str):
        try:
            return json.loads(s)
        except (json.JSONDecodeError, TypeError):
            return s
    return s


async def _cached_get(key: tuple, coro_factory) -> Any:
    """带 60s 内存 TTL 的获取（实时拉取与历史回看共用，去抖）。"""
    now = time.time()
    hit = _CACHE.get(key)
    if hit and now - hit[0] < _TTL:
        return hit[1]
    val = await coro_factory()
    _CACHE[key] = (now, val)
    return val


# ---------------------------------------------------------------------------
# 原始接口拉取（带缓存）
# ---------------------------------------------------------------------------
async def _get_dataapi_pool(kind: str, td: str) -> Dict[str, Any]:
    """dataapi 涨停/炸板/跌停池。返回 {total, list}。"""
    params = {
        "page": 1, "limit": 500, "field": _POOL_FIELDS,
        "filter": "HS,GEM2STAR", "order_field": "330324", "order_type": 0,
        "_": int(time.time() * 1000),
    }
    data = _data_of(await _request(f"/limit_up/{kind}", params, mobile=False))
    if isinstance(data, dict):
        total = data.get("total") or data.get("count") or 0
        lst = data.get("list") or data.get("data") or []
    else:
        total = 0
        lst = data if isinstance(data, list) else []
    return {"total": int(total) if total else len(lst), "list": lst}


async def _get_limit_up_stocks(cate: str, td: str) -> List[Dict[str, Any]]:
    """mobileapi 连板分层涨停池（命名字段，富化源）。返回规整后的个股列表。"""
    params = {
        "date": _ymd(td), "cate": cate, "sort_field": "limit_up_time",
        "sort_dir": "desc", "page": 1, "size": 500,
    }
    data = _data_of(await _request(
        "/stock_pool/v1/get_limit_up_stocks", params, mobile=True))
    lst = (data.get("stock_list") if isinstance(data, dict) else None)
    if lst is None:
        lst = data if isinstance(data, list) else []
    return [_norm_mobile_stock(it) for it in lst]


async def _get_continuous_ladder(td: str) -> List[Dict[str, Any]]:
    """dataapi 连板天梯。返回 [{height, number, code_list}]。"""
    params = {"date": _ymd(td), "page": 1, "limit": 200}
    data = _data_of(await _request(
        "/limit_up/continuous_limit_up", params, mobile=False))
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        return data.get("list") or data.get("data") or []
    return []


async def _get_wind(td: str) -> List[Dict[str, Any]]:
    """mobileapi 风向标股 / 最强风口。返回 tab_list。"""
    params = {"date": _ymd(td)}
    data = _data_of(await _request(
        "/market_state/v1/get_wind_vane_stock", params, mobile=True))
    if isinstance(data, dict):
        return data.get("tab_list") or []
    return []


async def _get_overview(td: str) -> Dict[str, Any]:
    """mobileapi 市场情绪总览。返回 data 载荷 dict。"""
    params = {"date": _ymd(td)}
    data = _data_of(await _request(
        "/market_state/v1/overview", params, mobile=True))
    return data if isinstance(data, dict) else {}


async def _get_trade_status() -> Dict[str, Any]:
    """dataapi 交易状态。返回 {stat, timestamp} 或裸 {stat}。"""
    data = _data_of(await _request("/limit_up/trade_status", mobile=False))
    return data if isinstance(data, dict) else {}


# ---------------------------------------------------------------------------
# 字段规整
# ---------------------------------------------------------------------------
def _norm_dataapi_pool_item(it: Dict[str, Any]) -> Dict[str, Any]:
    """把 dataapi 数字字段 ID 的个股行规整为命名结构。"""
    out: Dict[str, Any] = {}
    for k, v in (it or {}).items():
        name = _POOL_FIELD_MAP.get(str(k))
        if name:
            out[name] = v
    return out


def _norm_mobile_stock(it: Dict[str, Any]) -> Dict[str, Any]:
    """把 mobileapi get_limit_up_stocks 命名字段个股行规整。"""
    return {
        "code": it.get("stock_code"),
        "name": it.get("stock_name"),
        "market_code": it.get("market_code"),
        "board": it.get("list_board"),
        "price": _num(it.get("price")),
        "change_pct": _num(it.get("change")),
        "amplitude": _num(it.get("amplitude")),
        "reason": it.get("limit_up_reason") or it.get("reason") or "",
        "continue_day_cnt": _int(it.get("continue_day") or it.get("continue_day_cnt")),
        "limit_up_time": it.get("limit_up_time") or "",
        "main_net_amount": _num(it.get("main_net_amount")),
        "effective_circulation": _num(it.get("effective_circulation")),
        "turnover_ratio": _num(it.get("effective_turnover_ratio")),
        "is_st": _int(it.get("is_st")),
        "is_new": _int(it.get("is_new")),
    }


def _merge_up_pool(basic_list: List[Dict[str, Any]],
                   rich_list: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """涨停池：dataapi 基础行 + mobileapi 富化字段（按代码合并）。"""
    rich_map = {r.get("code"): r for r in rich_list}
    out: List[Dict[str, Any]] = []
    for it in basic_list:
        norm = _norm_dataapi_pool_item(it)
        code = norm.get("code")
        rch = rich_map.get(code) or {}
        out.append({
            "code": code,
            "name": norm.get("name"),
            "price": _num(norm.get("price")),
            "change_pct": _num(norm.get("change_pct")),
            "reason": (norm.get("reason") or rch.get("reason") or ""),
            "board": rch.get("board") or "",
            "continue_day_cnt": rch.get("continue_day_cnt") or 0,
            "amplitude": rch.get("amplitude") or 0,
            "limit_up_time": rch.get("limit_up_time") or "",
            "main_net_amount": rch.get("main_net_amount") or 0,
            "effective_circulation": rch.get("effective_circulation") or 0,
            "turnover_ratio": rch.get("turnover_ratio") or 0,
            "is_st": rch.get("is_st") or 0,
            "is_new": rch.get("is_new") or 0,
            "market_code": rch.get("market_code") or "",
        })
    return out


def _norm_open_lower(it: Dict[str, Any]) -> Dict[str, Any]:
    """炸板/跌停池（仅 dataapi 基础字段）规整。"""
    norm = _norm_dataapi_pool_item(it)
    return {
        "code": norm.get("code"),
        "name": norm.get("name"),
        "price": _num(norm.get("price")),
        "change_pct": _num(norm.get("change_pct")),
        "reason": norm.get("reason") or "",
        "board": "",
        "continue_day_cnt": 0,
        "amplitude": 0,
        "limit_up_time": "",
        "main_net_amount": 0,
        "effective_circulation": 0,
        "turnover_ratio": 0,
        "is_st": 0,
        "is_new": 0,
        "market_code": "",
    }


def _norm_wind_tabs(tabs: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """风向标股 tab_list 规整为前端友好结构。"""
    out: List[Dict[str, Any]] = []
    for t in tabs:
        stocks: List[Dict[str, Any]] = []
        for s in (t.get("stock_list") or []):
            stocks.append({
                "stock_code": s.get("stock_code") or s.get("code"),
                "stock_name": s.get("stock_name") or s.get("name"),
                "reason": s.get("reason") or "",
                "price": _num(s.get("price")),
                "change": _num(s.get("change")),
                "five_rise": _num(s.get("fiveRise")),
                "tags": s.get("tags") or "",
            })
        out.append({
            "tab_name": t.get("tab_name"),
            "average_change": _num(t.get("average_change")),
            "stock_num": _int(t.get("stock_num")),
            "stocks": stocks,
        })
    return out


def _intensity_metrics(up: int, op: int, lo: int) -> Dict[str, Any]:
    """涨停强度衍生指标：炸板率 / 封板率。"""
    seal = up + op
    broken_rate = round(op / seal, 4) if seal else 0.0
    seal_rate = round(up / seal, 4) if seal else 0.0
    return {
        "limit_up": up, "broken": op, "lower": lo,
        "broken_rate": broken_rate, "seal_rate": seal_rate,
    }


# ---------------------------------------------------------------------------
# 持久化行构造
# ---------------------------------------------------------------------------
def _pool_persist_rows(td: str, pool_type: str,
                       items: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    return [{
        "trade_date": td, "pool_type": pool_type, "rank": i + 1,
        "code": it.get("code"), "name": it.get("name"),
        "price": it.get("price"), "change_pct": it.get("change_pct"),
        "amplitude": it.get("amplitude", 0), "reason": it.get("reason"),
        "board": it.get("board"), "continue_day_cnt": it.get("continue_day_cnt", 0),
        "limit_up_time": it.get("limit_up_time"),
        "main_net_amount": it.get("main_net_amount", 0),
        "effective_circulation": it.get("effective_circulation", 0),
        "turnover_ratio": it.get("turnover_ratio", 0),
        "is_st": it.get("is_st", 0), "is_new": it.get("is_new", 0),
        "market_code": it.get("market_code", ""), "detail_json": "{}",
    } for i, it in enumerate(items)]


def _ladder_persist_rows(td: str,
                         ladder_raw: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    for item in ladder_raw:
        height = _int(item.get("height"))
        number = _int(item.get("number"))
        for c in (item.get("code_list") or []):
            out.append({
                "trade_date": td, "height": height, "number": number,
                "code": c.get("code"), "name": c.get("name"),
                "market_id": c.get("market_id"),
                "continue_num": _int(c.get("continue_num")),
            })
    return out


def _wind_persist_rows(td: str, tabs: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    for t in tabs:
        tab_name = t.get("tab_name")
        avg = _num(t.get("average_change"))
        snum = _int(t.get("stock_num"))
        for i, s in enumerate(t.get("stock_list") or []):
            out.append({
                "trade_date": td, "tab_name": tab_name,
                "average_change": avg, "stock_num": snum,
                "stock_code": s.get("stock_code") or s.get("code"),
                "stock_name": s.get("stock_name") or s.get("name"),
                "reason": s.get("reason") or "", "price": _num(s.get("price")),
                "change": _num(s.get("change")),
                "five_rise": _num(s.get("fiveRise")),
                "tags": s.get("tags") or "", "rank": i + 1,
            })
    return out


def _sentiment_persist_row(td: str, s: Dict[str, Any]) -> Dict[str, Any]:
    ts = s.get("trade_status")
    ts_stat = ts.get("stat", "") if isinstance(ts, dict) else str(ts or "")
    ts_ts = ts.get("timestamp", "") if isinstance(ts, dict) else ""
    north = s.get("north_flow")
    north_json = json.dumps(north, ensure_ascii=False) if not isinstance(north, str) else (north or "")
    return {
        "trade_date": td,
        "turnover_pre": _num(s.get("turnover", {}).get("pre")),
        "turnover_now": _num(s.get("turnover", {}).get("now")),
        "turnover_flag": str(s.get("turnover", {}).get("flag", "")),
        "north_flow": north_json,
        "limit_up_pre": _int(s.get("limit_up", {}).get("pre")),
        "limit_up_now": _int(s.get("limit_up", {}).get("now")),
        "limit_up_flag": str(s.get("limit_up", {}).get("flag", "")),
        "rise": _int(s.get("rise_fall", {}).get("rise")),
        "fall": _int(s.get("rise_fall", {}).get("fall")),
        "deuce": _int(s.get("rise_fall", {}).get("deuce")),
        "rise_limit": _int(s.get("rise_fall", {}).get("limit_up")),
        "rise_down": _int(s.get("rise_fall", {}).get("limit_down")),
        "hgt_market_status": str(s.get("hgt_market_status", "")),
        "config_start_date": str(s.get("config_start_date", "")),
        "trade_status": ts_stat,
        "trade_status_ts": str(ts_ts),
        "collected_at": now_bj().strftime("%Y-%m-%d %H:%M:%S"),
    }


# ---------------------------------------------------------------------------
# DB -> 前端结构（历史回看）
# ---------------------------------------------------------------------------
def _row_to_pool_item(r: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "code": r.get("code"), "name": r.get("name"),
        "price": r.get("price"), "change_pct": r.get("change_pct"),
        "reason": r.get("reason"), "board": r.get("board"),
        "continue_day_cnt": r.get("continue_day_cnt", 0),
        "amplitude": r.get("amplitude", 0),
        "limit_up_time": r.get("limit_up_time"),
        "main_net_amount": r.get("main_net_amount", 0),
        "effective_circulation": r.get("effective_circulation", 0),
        "turnover_ratio": r.get("turnover_ratio", 0),
        "is_st": r.get("is_st", 0), "is_new": r.get("is_new", 0),
        "market_code": r.get("market_code", ""),
    }


def _build_intensity_from_db(td: str) -> Dict[str, Any]:
    from finfeed.market import store
    rows_u = store.get_ths_limitup_pool(td, "up")
    rows_o = store.get_ths_limitup_pool(td, "open")
    rows_l = store.get_ths_limitup_pool(td, "lower")
    up_total, open_total, lower_total = len(rows_u), len(rows_o), len(rows_l)
    return {
        "date": td,
        "up_total": up_total, "open_total": open_total, "lower_total": lower_total,
        "metrics": _intensity_metrics(up_total, open_total, lower_total),
        "up": [_row_to_pool_item(r) for r in rows_u],
        "open": [_row_to_pool_item(r) for r in rows_o],
        "lower": [_row_to_pool_item(r) for r in rows_l],
        "source": "db",
    }


def _build_ladder_from_db(td: str) -> Optional[Dict[str, Any]]:
    from finfeed.market import store
    rows = store.get_ths_limitup_ladder(td)
    if not rows:
        return None
    by_height: Dict[int, Dict[str, Any]] = {}
    max_height = 0
    for r in rows:
        h = r["height"]
        max_height = max(max_height, h)
        by_height.setdefault(h, {"height": h, "number": r["number"], "stocks": []})
        by_height[h]["stocks"].append({
            "code": r["code"], "name": r["name"],
            "market_id": r["market_id"], "continue_num": r["continue_num"],
        })
    ladder = [by_height[h] for h in sorted(by_height, reverse=True)]
    return {"date": td, "ladder": ladder, "max_height": max_height, "source": "db"}


def _build_wind_from_db(td: str) -> Optional[Dict[str, Any]]:
    from finfeed.market import store
    rows = store.get_ths_limitup_wind(td)
    if not rows:
        return None
    tabs: Dict[str, Dict[str, Any]] = {}
    for r in rows:
        t = r["tab_name"]
        if t not in tabs:
            tabs[t] = {
                "tab_name": t, "average_change": r["average_change"],
                "stock_num": r["stock_num"], "stocks": [],
            }
        tabs[t]["stocks"].append({
            "stock_code": r["stock_code"], "stock_name": r["stock_name"],
            "reason": r["reason"], "price": r["price"], "change": r["change"],
            "five_rise": r["five_rise"], "tags": r["tags"], "rank": r["rank"],
        })
    return {"date": td, "tabs": list(tabs.values()), "source": "db"}


def _build_sentiment_from_db(td: str) -> Optional[Dict[str, Any]]:
    from finfeed.market import store
    r = store.get_ths_limitup_sentiment(td)
    if not r:
        return None
    return {
        "date": td,
        "turnover": {
            "pre": r["turnover_pre"], "now": r["turnover_now"], "flag": r["turnover_flag"],
        },
        "north_flow": _json_load(r["north_flow"]),
        "limit_up": {
            "pre": r["limit_up_pre"], "now": r["limit_up_now"], "flag": r["limit_up_flag"],
        },
        "rise_fall": {
            "rise": r["rise"], "fall": r["fall"], "deuce": r["deuce"],
            "limit_up": r["rise_limit"], "limit_down": r["rise_down"],
        },
        "hgt_market_status": r["hgt_market_status"],
        "config_start_date": r["config_start_date"],
        "trade_status": {"stat": r["trade_status"], "timestamp": r["trade_status_ts"]},
        "source": "db",
    }


# ---------------------------------------------------------------------------
# 对外：四大模块 fetch（实时 + DB 回退 + 落库）
# ---------------------------------------------------------------------------
async def fetch_limit_up_intensity(trade_date: Optional[str] = None) -> Dict[str, Any]:
    """涨停强度：涨停 / 炸板 / 跌停池 + 衍生指标。"""
    from finfeed.market import store
    td = trade_date or now_bj().strftime("%Y-%m-%d")
    today = now_bj().strftime("%Y-%m-%d")

    if td != today:
        if not (store.get_ths_limitup_pool(td, "up")
                or store.get_ths_limitup_pool(td, "open")
                or store.get_ths_limitup_pool(td, "lower")):
            return {"error": f"{td} 暂无涨停聚焦采集数据", "section": "intensity", "date": td}
        return _build_intensity_from_db(td)

    try:
        up_basic = await _cached_get(
            ("pool", "limit_up_pool", td), lambda: _get_dataapi_pool("limit_up_pool", td))
        op_basic = await _cached_get(
            ("pool", "open_limit_pool", td), lambda: _get_dataapi_pool("open_limit_pool", td))
        lo_basic = await _cached_get(
            ("pool", "lower_limit_pool", td), lambda: _get_dataapi_pool("lower_limit_pool", td))
        up_rich = await _cached_get(
            ("lus", "limit_up_all", td), lambda: _get_limit_up_stocks("limit_up_all", td))

        up = _merge_up_pool(up_basic["list"], up_rich)
        op = [_norm_open_lower(it) for it in op_basic["list"]]
        lo = [_norm_open_lower(it) for it in lo_basic["list"]]
        up_total, open_total, lower_total = (
            up_basic["total"], op_basic["total"], lo_basic["total"])
        result = {
            "date": td, "up_total": up_total, "open_total": open_total,
            "lower_total": lower_total,
            "metrics": _intensity_metrics(up_total, open_total, lower_total),
            "up": up, "open": op, "lower": lo, "source": "live",
        }
        try:
            saved = (
                store.upsert_ths_limitup_pool(_pool_persist_rows(td, "up", up))
                + store.upsert_ths_limitup_pool(_pool_persist_rows(td, "open", op))
                + store.upsert_ths_limitup_pool(_pool_persist_rows(td, "lower", lo))
            )
            result["persisted"] = saved
        except Exception as e:  # noqa: BLE001
            logger.warning("涨停强度快照持久化失败: %s", e)
        return result
    except Exception as e:  # noqa: BLE001
        logger.warning("涨停强度实时获取失败，尝试历史快照: %s", e)
        cached = store.get_latest_ths_limitup_date()
        if cached and cached != today:
            if (store.get_ths_limitup_pool(cached, "up")
                    or store.get_ths_limitup_pool(cached, "open")
                    or store.get_ths_limitup_pool(cached, "lower")):
                d = _build_intensity_from_db(cached)
                d["cached_date"] = cached
                return d
        return {"error": "涨停强度实时获取失败，且无可用历史快照",
                "section": "intensity", "date": td}


async def fetch_board_ladder(trade_date: Optional[str] = None) -> Dict[str, Any]:
    """强势股 / 连板天梯：连板高度梯队 + 个股富化详情。"""
    from finfeed.market import store
    td = trade_date or now_bj().strftime("%Y-%m-%d")
    today = now_bj().strftime("%Y-%m-%d")

    if td != today:
        d = _build_ladder_from_db(td)
        if not d:
            return {"error": f"{td} 暂无连板天梯采集数据", "section": "ladder", "date": td}
        return d

    try:
        ladder_raw = await _cached_get(
            ("ladder", td), lambda: _get_continuous_ladder(td))
        up_rich = await _cached_get(
            ("lus", "limit_up_all", td), lambda: _get_limit_up_stocks("limit_up_all", td))
        rich_map = {s.get("code"): s for s in up_rich}

        ladder: List[Dict[str, Any]] = []
        max_height = 0
        for item in ladder_raw:
            h = _int(item.get("height"))
            max_height = max(max_height, h)
            stocks: List[Dict[str, Any]] = []
            for c in (item.get("code_list") or []):
                code = c.get("code")
                rch = rich_map.get(code) or {}
                stocks.append({
                    "code": code, "name": c.get("name"),
                    "market_id": c.get("market_id"),
                    "continue_num": _int(c.get("continue_num")),
                    "price": rch.get("price", 0),
                    "change_pct": rch.get("change_pct", 0),
                    "reason": rch.get("reason", ""),
                    "board": rch.get("board", ""),
                    "limit_up_time": rch.get("limit_up_time", ""),
                    "main_net_amount": rch.get("main_net_amount", 0),
                    "effective_circulation": rch.get("effective_circulation", 0),
                    "turnover_ratio": rch.get("turnover_ratio", 0),
                })
            ladder.append({"height": h, "number": _int(item.get("number")), "stocks": stocks})
        ladder.sort(key=lambda x: -x["height"])

        result = {"date": td, "ladder": ladder, "max_height": max_height, "source": "live"}
        try:
            result["persisted"] = store.upsert_ths_limitup_ladder(
                _ladder_persist_rows(td, ladder_raw))
        except Exception as e:  # noqa: BLE001
            logger.warning("连板天梯快照持久化失败: %s", e)
        return result
    except Exception as e:  # noqa: BLE001
        logger.warning("连板天梯实时获取失败，尝试历史快照: %s", e)
        cached = store.get_latest_ths_limitup_date()
        if cached and cached != today:
            d = _build_ladder_from_db(cached)
            if d:
                d["cached_date"] = cached
                return d
        return {"error": "连板天梯实时获取失败，且无可用历史快照",
                "section": "ladder", "date": td}


async def fetch_strong_wind(trade_date: Optional[str] = None) -> Dict[str, Any]:
    """最强风口：风向标股（按类目分组）。"""
    from finfeed.market import store
    td = trade_date or now_bj().strftime("%Y-%m-%d")
    today = now_bj().strftime("%Y-%m-%d")

    if td != today:
        d = _build_wind_from_db(td)
        if not d:
            return {"error": f"{td} 暂无最强风口采集数据", "section": "wind", "date": td}
        return d

    try:
        tabs = await _cached_get(("wind", td), lambda: _get_wind(td))
        result = {"date": td, "tabs": _norm_wind_tabs(tabs), "source": "live"}
        try:
            result["persisted"] = store.upsert_ths_limitup_wind(_wind_persist_rows(td, tabs))
        except Exception as e:  # noqa: BLE001
            logger.warning("最强风口快照持久化失败: %s", e)
        return result
    except Exception as e:  # noqa: BLE001
        logger.warning("最强风口实时获取失败，尝试历史快照: %s", e)
        cached = store.get_latest_ths_limitup_date()
        if cached and cached != today:
            d = _build_wind_from_db(cached)
            if d:
                d["cached_date"] = cached
                return d
        return {"error": "最强风口实时获取失败，且无可用历史快照",
                "section": "wind", "date": td}


async def fetch_market_sentiment(trade_date: Optional[str] = None) -> Dict[str, Any]:
    """市场情绪：情绪总览 + 交易状态。"""
    from finfeed.market import store
    td = trade_date or now_bj().strftime("%Y-%m-%d")
    today = now_bj().strftime("%Y-%m-%d")

    if td != today:
        d = _build_sentiment_from_db(td)
        if not d:
            return {"error": f"{td} 暂无市场情绪采集数据", "section": "sentiment", "date": td}
        return d

    try:
        ov = await _cached_get(("overview", td), lambda: _get_overview(td))
        ts = await _cached_get(("tstatus", td), lambda: _get_trade_status())
        ov = ov if isinstance(ov, dict) else {}
        ts = ts if isinstance(ts, dict) else {"stat": str(ts)}
        result = {
            "date": td,
            "turnover": ov.get("turnover") or {},
            "north_flow": ov.get("north_flow"),
            "limit_up": ov.get("limit_up") or {},
            "rise_fall": ov.get("rise_fall") or {},
            "hgt_market_status": ov.get("hgt_market_status"),
            "config_start_date": ov.get("config_start_date"),
            "trade_status": ts,
            "source": "live",
        }
        try:
            result["persisted"] = store.upsert_ths_limitup_sentiment(
                _sentiment_persist_row(td, result))
        except Exception as e:  # noqa: BLE001
            logger.warning("市场情绪快照持久化失败: %s", e)
        return result
    except Exception as e:  # noqa: BLE001
        logger.warning("市场情绪实时获取失败，尝试历史快照: %s", e)
        cached = store.get_latest_ths_limitup_date()
        if cached and cached != today:
            d = _build_sentiment_from_db(cached)
            if d:
                d["cached_date"] = cached
                return d
        return {"error": "市场情绪实时获取失败，且无可用历史快照",
                "section": "sentiment", "date": td}


async def fetch_limitup_focus(trade_date: Optional[str] = None,
                              sections: str = "all") -> Dict[str, Any]:
    """聚合取数：intensity / ladder / wind / sentiment 四模块。

    sections: "all" 或逗号分隔的子模块名（如 "intensity,ladder"）。
    """
    td = trade_date or now_bj().strftime("%Y-%m-%d")
    wanted = (["intensity", "ladder", "wind", "sentiment"]
              if sections == "all" else [s.strip() for s in sections.split(",") if s.strip()])
    out: Dict[str, Any] = {"date": td}
    if "intensity" in wanted:
        out["intensity"] = await fetch_limit_up_intensity(td)
    if "ladder" in wanted:
        out["ladder"] = await fetch_board_ladder(td)
    if "wind" in wanted:
        out["wind"] = await fetch_strong_wind(td)
    if "sentiment" in wanted:
        out["sentiment"] = await fetch_market_sentiment(td)
    return out


async def collect_all(trade_date: Optional[str] = None) -> Dict[str, Any]:
    """后台自动采集：四模块全部落库为某交易日快照。

    返回 {trade_date, saved, attempted, errors}。
    """
    from finfeed.market import store
    td = trade_date or now_bj().strftime("%Y-%m-%d")
    saved = 0
    attempted = 0
    errors: List[str] = []

    async def _safe(fn: str, coro):
        nonlocal saved, attempted
        attempted += 1
        try:
            res = await coro
            saved += res.get("persisted", 0)
        except Exception as e:  # noqa: BLE001
            logger.warning("涨停聚焦采集失败 %s: %s", fn, e)
            errors.append(f"{fn}: {e}")

    await _safe("intensity", fetch_limit_up_intensity(td))
    await _safe("ladder", fetch_board_ladder(td))
    await _safe("wind", fetch_strong_wind(td))
    await _safe("sentiment", fetch_market_sentiment(td))
    return {"trade_date": td, "saved": saved, "attempted": attempted, "errors": errors}
