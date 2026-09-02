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
    最强风口    dataapi limit_up block_top（涨停简图 · 题材板块榜：
                题材名 / 涨停数 / 连板高度 / 涨停个股及原因）
    市场情绪    mobileapi market_state overview（情绪总览）
                + mobileapi market_state get_wind_vane_stock（风向标股，
                  原误配给最强风口，已纠正回市场情绪）

稳定性设计（详见 docs/ths-limitup-strategy.md）：
    - 复用 finfeed.market.client 共享限流客户端（group="ths"）：令牌桶限速
      + 组级冷却熔断 + 指数退避重试，规避此前无限速导致的 [WinError 10054]
    - 首次请求前 GET 根域名预热会话 Cookie（同花顺移动版接口前置要求）
    - 60s 内存 TTL 缓存（去抖 + 削减重复请求）
    - 两层容错：
        L1 子请求级 —— 单接口失败仅降级该字段/子榜（degraded 标签），
                       用当日 DB 快照或空值补位，其余子接口照常呈现
        L2 模块级   —— 关键子接口全灭或实时全空（盘前/非交易日）时，
                       依次回退 当日 DB → 最近交易日 DB → error
    - 实时全量成功即幂等落库 + prune 对齐（裁剪炸板/跌榜等残留行），
      支撑盘中增量采集与历史交易日回看

合规底线：仅限个人学习与技术研究，遵守 robots 与频率限制，勿商用分发原始数据。
"""

import asyncio
import json
import logging
import time
from typing import Any, Dict, List, Optional

from finfeed.market.client import RateLimited, get_json, warm
from finfeed.storage.database import now_bj

logger = logging.getLogger("news_monitor")

# 常量与请求头
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

# 客户端：复用 finfeed.market.client 的限流基础设施（group=ths）
# 令牌桶限速 + 组级冷却熔断 + 退避重试，规避此前无限速导致的 [WinError 10054] 断连与限流。
_MOBILE_HEADERS = {"Source-id": _SOURCE_ID, "PlatForm": _PLATFORM}

_ths_warm_lock: Optional[asyncio.Lock] = None
_ths_warmed = False


async def _ensure_ths_session() -> None:
    """首次请求前 GET 根域建立会话 Cookie（best-effort，失败不阻断主链路）。"""
    global _ths_warmed, _ths_warm_lock
    if _ths_warmed:
        return
    if _ths_warm_lock is None:
        _ths_warm_lock = asyncio.Lock()
    async with _ths_warm_lock:
        if _ths_warmed:
            return
        try:
            await warm(_ROOT, _REFERER, group="ths")
        except Exception as e:  # noqa: BLE001
            logger.warning("同花顺会话预热失败（部分接口可能拒绝）: %s", e)
        finally:
            # 无论成败都置位，避免冷却期/失败时的重复预热风暴
            _ths_warmed = True


async def _request(path: str, params: Optional[dict] = None,
                   mobile: bool = False, timeout: float = 25.0) -> dict:
    """GET 并解析 JSON，走共享限流客户端（group=ths）。

    mobile=True 时附加 Source-id / PlatForm 头（mobileapi 强制要求）。
    业务级拒绝（status_code!=0）抛 RuntimeError 由调用方降级；
    冷却期 / 重试耗尽同样抛 RuntimeError。
    """
    await _ensure_ths_session()
    url = (_MOBILE if mobile else _DATA) + path
    try:
        data = await get_json(
            url, params=params, group="ths",
            extra_headers=(_MOBILE_HEADERS if mobile else None),
            timeout=timeout,
        )
    except RateLimited as e:
        raise RuntimeError(f"同花顺限流冷却中: {e}") from e
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


# 工具
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


# 原始接口拉取（带缓存）
async def _get_dataapi_pool(kind: str, td: str) -> Dict[str, Any]:
    """dataapi 涨停/炸板/跌停池。返回 {total, list}。

    dataapi 限制 limit<=200，故单页上限 200，必要时分页拉取（上限 5 页 / 1000 只）。
    实测返回结构为 {"page": {"total": N, "count": M, ...}, "info": [...]}：
    total 须从 page.total 读取、个股列表从 info 读取（此前误读 list/data 导致恒为空）。
    """
    out: List[Dict[str, Any]] = []
    total = 0
    page = 1
    while page <= 5:
        params = {
            "page": page, "limit": 200, "field": _POOL_FIELDS,
            "filter": "HS,GEM2STAR", "order_field": "330324", "order_type": 0,
            "date": _ymd(td), "_": int(time.time() * 1000),
        }
        data = _data_of(await _request(f"/limit_up/{kind}", params, mobile=False))
        if isinstance(data, dict):
            pg = data.get("page") or {}
            page_total = (pg.get("total") or data.get("total")
                          or pg.get("count") or data.get("count") or 0)
            lst = (data.get("info") or data.get("list") or data.get("data")
                   or pg.get("info") or [])
        else:
            page_total = 0
            lst = data if isinstance(data, list) else []
        if page == 1:
            total = int(page_total) if page_total else 0
        out.extend(lst)
        if len(lst) < 200:
            break
        page += 1
    return {"total": total or len(out), "list": out}


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
    """mobileapi 风向标股（market_state）。返回 tab_list。

    注：该接口真实归属「市场情绪」模块（同花顺前端 fetchWindStocks 调用），
    此前被误配给「最强风口」，现已纠正回市场情绪。
    """
    params = {"date": _ymd(td)}
    data = _data_of(await _request(
        "/market_state/v1/get_wind_vane_stock", params, mobile=True))
    if isinstance(data, dict):
        return data.get("tab_list") or []
    return []


async def _get_block_top(td: str) -> List[Dict[str, Any]]:
    """dataapi 涨停简图（最强风口）。返回题材板块榜 list。

    端点：dataapi/limit_up/block_top?date=YYYYMMDD&filter=HS,GEM2STAR
    每个板块：题材名 / 涨停数 / 连板高度 / 涨停个股（含涨停原因、连板、最新价）。
    """
    params = {"date": _ymd(td), "filter": "HS,GEM2STAR"}
    data = _data_of(await _request("/limit_up/block_top", params, mobile=False))
    return data if isinstance(data, list) else []


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


# 字段规整
def _norm_dataapi_pool_item(it: Dict[str, Any]) -> Dict[str, Any]:
    """把 dataapi 涨停/炸板/跌停池个股行规整为命名结构。

    实测 dataapi 直接返回命名字段（code / name / latest / change_rate /
    reason_type），非文档所述数字字段 ID；为兼容接口切换，两种形态都处理：
    数字 ID 走 _POOL_FIELD_MAP 映射，命名字段直通覆盖。
    """
    out: Dict[str, Any] = {}
    for k, v in (it or {}).items():
        name = _POOL_FIELD_MAP.get(str(k))
        if name:
            out[name] = v
    if "code" in it:
        out["code"] = it["code"]
    if "name" in it:
        out["name"] = it["name"]
    if "latest" in it:
        out["price"] = it["latest"]
    if "change_rate" in it:
        out["change_pct"] = it["change_rate"]
    if "reason_type" in it:
        out["reason"] = it["reason_type"]
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
    """风向标股 tab_list 规整为前端友好结构（现归属市场情绪）。"""
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


def _norm_block_top_stock(s: Dict[str, Any]) -> Dict[str, Any]:
    """涨停简图单只涨停股规整。"""
    return {
        "code": s.get("code"),
        "name": s.get("name"),
        "market_type": s.get("market_type") or "",
        "latest": _num(s.get("latest")),
        "change_rate": _num(s.get("change_rate")),
        "high": s.get("high") or "",
        "continue_num": _int(s.get("continue_num")),
        "reason_type": s.get("reason_type") or "",
        "reason_info": s.get("reason_info") or "",
        "is_st": _int(s.get("is_st")),
        "is_new": _int(s.get("is_new")),
        "first_limit_up_time": s.get("first_limit_up_time") or "",
        "last_limit_up_time": s.get("last_limit_up_time") or "",
    }


def _norm_block_top(blocks: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """涨停简图题材板块榜规整，按涨停数降序。"""
    out: List[Dict[str, Any]] = []
    for b in blocks:
        stocks = [_norm_block_top_stock(s) for s in (b.get("stock_list") or [])]
        out.append({
            "code": b.get("code"),
            "name": b.get("name"),
            "change": _num(b.get("change")),
            "limit_up_num": _int(b.get("limit_up_num")),
            "continuous_plate_num": _int(b.get("continuous_plate_num")),
            "high": b.get("high") or "",
            "high_num": _int(b.get("high_num")),
            "days": _int(b.get("days")),
            "stocks": stocks,
        })
    out.sort(key=lambda x: -x["limit_up_num"])
    return out


def _block_top_persist_rows(td: str, blocks: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """涨停简图板块榜 → 持久化行（个股明细存 detail_json）。"""
    normed = _norm_block_top(blocks)
    return [{
        "trade_date": td, "rank": i + 1,
        "topic_code": b.get("code"), "topic_name": b.get("name"),
        "change": b.get("change"), "limit_up_num": b.get("limit_up_num"),
        "continuous_plate_num": b.get("continuous_plate_num"),
        "high": b.get("high"), "high_num": b.get("high_num"), "days": b.get("days"),
        "detail_json": json.dumps(b.get("stocks") or [], ensure_ascii=False),
    } for i, b in enumerate(normed)]


def _intensity_metrics(up: int, op: int, lo: int) -> Dict[str, Any]:
    """涨停强度衍生指标：炸板率 / 封板率。"""
    seal = up + op
    broken_rate = round(op / seal, 4) if seal else 0.0
    seal_rate = round(up / seal, 4) if seal else 0.0
    return {
        "limit_up": up, "broken": op, "lower": lo,
        "broken_rate": broken_rate, "seal_rate": seal_rate,
    }


# 持久化行构造
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


def _build_down_ladder_from_pool(rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """从通达信跌停池（limit_pool direction=down）构建连跌天梯。

    通达信 DT 池字段（quote.py 契约）：limit_streak=连续跌停天数、
    price(元) / pct_chg(涨跌幅%) / reason(行业) / last_limit_time(封板时间)
    / limit_amount(封单额亿元) / turnover(换手率%)。
    按连跌天数分组，返回与涨停天梯同构的 [{height, number, stocks}]。
    """
    by_streak: Dict[int, Dict[str, Any]] = {}
    for it in rows:
        streak = _int(it.get("limit_streak")) or 1
        code = it.get("code")
        if not code:
            continue
        g = by_streak.setdefault(
            streak, {"height": streak, "number": 0, "stocks": []})
        g["stocks"].append({
            "code": code, "name": it.get("name", ""),
            "market_id": str(it.get("market") or "") or "",
            "continue_num": streak,
            "price": _num(it.get("price")),
            "change_pct": _num(it.get("pct_chg")),
            "reason": it.get("reason", ""),
            "board": "",
            "limit_up_time": it.get("last_limit_time", ""),
            "main_net_amount": _num(it.get("limit_amount")),
            "effective_circulation": _num(it.get("circ_mv")),
            "turnover_ratio": _num(it.get("turnover")),
        })
    for g in by_streak.values():
        g["number"] = len(g["stocks"])
    return [by_streak[s] for s in sorted(by_streak, reverse=True)]


def _build_broken_ladder(td: str) -> Dict[str, Any]:
    """断板梯队：昨日连板个股中今日未封板（断板）者。

    断板股按「昨日高度 + 1」归入其本应冲击的层级——昨日 2 连板今日断板
    → 归入 3 板层级，供前端在晋级天梯对应位置以虚化打叉呈现（二连板断板
    即在三连板位置打叉）。首板断板数量巨大且信息价值低，仅作统计计数返回。

    返回 {prev_date, broken_ladder: [{height, number, stocks}], first_board_broken_count}。
    任一环节无数据（无上一交易日快照 / 今日涨停池为空）即返回空，best-effort。
    """
    from finfeed.market import store
    from finfeed.storage.database import get_db_manager

    dates = (store.get_ths_limitup_dates().get("dates") or [])
    prev = next((d for d in dates if d < td), None)
    if not prev:
        return {"prev_date": None, "broken_ladder": [], "first_board_broken_count": 0}

    prev_rows = store.get_ths_limitup_ladder(prev)
    if not prev_rows:
        return {"prev_date": prev, "broken_ladder": [], "first_board_broken_count": 0}

    # 今日涨停池（封板成功者）；盘前 / 未采集时为空，此时断板判断无意义
    today_up = store.get_ths_limitup_pool(td, "up")
    if not today_up:
        return {"prev_date": prev, "broken_ladder": [], "first_board_broken_count": 0}
    up_codes = {r["code"] for r in today_up}

    # 今日资金流富化（best-effort：断板股今日涨跌幅 / 主力净额）
    flow_map: Dict[str, Dict[str, Any]] = {}
    try:
        db = get_db_manager()
        with db.get_db() as c:
            c.execute(
                "SELECT code, pct_chg, main_net FROM money_flow WHERE trade_date = ?",
                (td,),
            )
            for r in c.fetchall():
                flow_map[r["code"]] = {"change_pct": _num(r["pct_chg"]),
                                       "main_net": _num(r["main_net"])}
    except Exception as e:  # noqa: BLE001
        logger.warning("断板梯队资金流富化失败（降级为空）: %s", e)
        flow_map = {}

    broken: Dict[int, Dict[str, Any]] = {}
    first_broken = 0
    for r in prev_rows:
        code = r["code"]
        if not code or code in up_codes:
            continue  # 今日继续封板 → 晋级，不计断板
        h = _int(r["height"])
        if h <= 1:
            first_broken += 1  # 首板断板仅计数
            continue
        target = h + 1  # 归入本应冲击的层级
        g = broken.setdefault(target, {"height": target, "number": 0, "stocks": []})
        flow = flow_map.get(code) or {}
        g["stocks"].append({
            "code": code,
            "name": r["name"],
            "market_id": r.get("market_id") or "",
            "prev_height": h,
            "prev_continue_num": _int(r.get("continue_num")) or h,
            "price": _num(flow.get("price")),
            "change_pct": _num(flow.get("change_pct")),
            "reason": f"昨日{h}连板 · 今日断板",
            "board": "",
            "limit_up_time": "",
            "main_net_amount": _num(flow.get("main_net")),
            "effective_circulation": 0,
            "turnover_ratio": 0,
        })
    ladders = [broken[h] for h in sorted(broken, reverse=True)]
    for g in ladders:
        g["number"] = len(g["stocks"])
    return {
        "prev_date": prev,
        "broken_ladder": ladders,
        "first_board_broken_count": first_broken,
    }


def _ladder_persist_rows(td: str,
                         ladder: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """手游天梯（含合成 1板）持久化行。输入已规整的 [{height, number, stocks}]。"""
    out: List[Dict[str, Any]] = []
    for item in ladder:
        height = _int(item.get("height"))
        number = _int(item.get("number"))
        for s in (item.get("stocks") or []):
            out.append({
                "trade_date": td, "height": height, "number": number,
                "code": s.get("code"), "name": s.get("name"),
                "market_id": s.get("market_id"),
                "continue_num": _int(s.get("continue_num")),
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


# DB -> 前端结构（历史回看）
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
    # 用当日涨停池富化：价格 / 涨跌幅 / 原因 / 封板时间 / 主力净额 / 换手率
    try:
        pool_items = {p["code"]: _row_to_pool_item(p)
                      for p in store.get_ths_limitup_pool(td, "up")}
    except Exception:  # noqa: BLE001
        pool_items = {}
    by_height: Dict[int, Dict[str, Any]] = {}
    max_height = 0
    for r in rows:
        h = r["height"]
        max_height = max(max_height, h)
        by_height.setdefault(h, {"height": h, "number": r["number"], "stocks": []})
        pool = pool_items.get(r["code"]) or {}
        by_height[h]["stocks"].append({
            "code": r["code"], "name": r["name"],
            "market_id": r["market_id"], "continue_num": r["continue_num"],
            "price": pool.get("price", 0),
            "change_pct": pool.get("change_pct", 0),
            "reason": pool.get("reason", ""),
            "board": pool.get("board", ""),
            "limit_up_time": pool.get("limit_up_time", ""),
            "main_net_amount": pool.get("main_net_amount", 0),
            "effective_circulation": pool.get("effective_circulation", 0),
            "turnover_ratio": pool.get("turnover_ratio", 0),
        })
    ladder = [by_height[h] for h in sorted(by_height, reverse=True)]
    d = {"date": td, "ladder": ladder, "max_height": max_height, "source": "db"}
    # 断板梯队：昨日连板今日未封板（best-effort，失败不阻断）
    try:
        brk = _build_broken_ladder(td)
        d["prev_date"] = brk["prev_date"]
        d["broken_ladder"] = brk["broken_ladder"]
        d["first_board_broken_count"] = brk["first_board_broken_count"]
    except Exception as e:  # noqa: BLE001
        logger.warning("断板梯队 DB 读取失败: %s", e)
        d["broken_ladder"] = []
        d["prev_date"] = None
        d["first_board_broken_count"] = 0
    # 历史回看 / DB 回退：同样附带通达信跌停天梯
    try:
        rows = store.get_limit_pool(td, "down")
        d["down_ladder"] = _build_down_ladder_from_pool(rows)
        d["tdx_down_total"] = len(rows)
        d["tdx_up_total"] = len(store.get_limit_pool(td, "up"))
    except Exception as e:  # noqa: BLE001
        logger.warning("通达信跌停天梯 DB 读取失败: %s", e)
        d["down_ladder"] = []
        d["tdx_down_total"] = 0
        d["tdx_up_total"] = 0
    return d


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


def _build_block_top_from_db(td: str) -> Optional[Dict[str, Any]]:
    from finfeed.market import store
    rows = store.get_ths_limitup_block_top(td)
    if not rows:
        return None
    blocks: List[Dict[str, Any]] = []
    for r in rows:
        stocks = _json_load(r["detail_json"])
        if not isinstance(stocks, list):
            stocks = []
        blocks.append({
            "code": r["topic_code"], "name": r["topic_name"],
            "change": r["change"], "limit_up_num": r["limit_up_num"],
            "continuous_plate_num": r["continuous_plate_num"],
            "high": r["high"], "high_num": r["high_num"], "days": r["days"],
            "stocks": stocks,
        })
    return {"date": td, "blocks": blocks, "source": "db"}


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
        "wind_vane": {"tabs": (_build_wind_from_db(td) or {}).get("tabs", [])},
        "source": "db",
    }


# 容错：子请求级降级 + 模块级多级回退
#
# 旧实现是「整模块 try/except」：任一子接口失败即丢弃整个模块，返回 error。
# 同花顺一个模块要打 2~4 个子接口，单点抖动就会让整块数据消失。
# 新实现分两层：
#   L1 子请求级 —— _try_req 捕获单接口异常，记入 degraded 标签，
#                  由调用方用「当日 DB 快照 / 空值」补位，其余子接口照常呈现。
#   L2 模块级   —— 关键子接口全灭（或实时返回全空，如盘前/非交易日）时，
#                  _db_fallback 依次尝试 当日 DB → 最近交易日 DB → error。
async def _try_req(label: str, key: tuple, factory, default: Any,
                   degraded: List[str]) -> tuple:
    """单子接口容错取数。返回 (value, ok)；失败不抛出，仅记 degraded 标签。"""
    try:
        return await _cached_get(key, factory), True
    except Exception as e:  # noqa: BLE001
        degraded.append(label)
        logger.warning("同花顺子接口失败（局部降级 %s）: %s", label, e)
        return default, False


def _db_fallback(section: str, td: str, builder, degraded: List[str],
                 err_msg: str, reason: str = "live_failed") -> Dict[str, Any]:
    """模块级多级回退：当日 DB 快照 → 最近交易日快照 → error。

    builder(date) 返回 dict 或 None（None 表示该日无快照）。
    reason 区分回退动因：live_failed（实时失败）/ empty_live（实时成功但空）。
    """
    from finfeed.market import store
    d = builder(td)
    if d:
        d["degraded"] = degraded
        d["fallback"] = f"{reason}->db_today"
        return d
    try:
        cached = store.get_latest_ths_limitup_date()
    except Exception:  # noqa: BLE001
        cached = None
    if cached and cached != td:
        d = builder(cached)
        if d:
            d["cached_date"] = cached
            d["degraded"] = degraded
            d["fallback"] = f"{reason}->db_latest"
            return d
    return {"error": err_msg, "section": section, "date": td, "degraded": degraded}


def _build_intensity_from_db_or_none(td: str) -> Optional[Dict[str, Any]]:
    """涨停强度 DB 快照；三池全空返回 None（供 _db_fallback 继续下探）。"""
    from finfeed.market import store
    if not (store.get_ths_limitup_pool(td, "up")
            or store.get_ths_limitup_pool(td, "open")
            or store.get_ths_limitup_pool(td, "lower")):
        return None
    return _build_intensity_from_db(td)


def _pool_from_db(td: str, pool_type: str) -> tuple:
    """单池 DB 补位（子请求失败时）。返回 (items, total)。"""
    from finfeed.market import store
    try:
        rows = store.get_ths_limitup_pool(td, pool_type)
    except Exception as e:  # noqa: BLE001
        logger.warning("涨停池 DB 补位失败 %s/%s: %s", td, pool_type, e)
        rows = []
    return [_row_to_pool_item(r) for r in rows], len(rows)


def _source_tag(degraded: List[str]) -> str:
    """实时数据源标签：全成功 live，部分子接口降级 live_partial。"""
    return "live_partial" if degraded else "live"


# 对外：四大模块 fetch（实时 + 子请求降级 + DB 多级回退 + 落库）
async def fetch_limit_up_intensity(trade_date: Optional[str] = None) -> Dict[str, Any]:
    """涨停强度：涨停 / 炸板 / 跌停池 + 衍生指标。"""
    from finfeed.market import store
    td = trade_date or now_bj().strftime("%Y-%m-%d")
    today = now_bj().strftime("%Y-%m-%d")

    if td != today:
        d = _build_intensity_from_db_or_none(td)
        if not d:
            return {"error": f"{td} 暂无涨停聚焦采集数据", "section": "intensity", "date": td}
        return d

    degraded: List[str] = []
    _empty = {"total": 0, "list": []}
    # 三池各自独立降级；富化源（连板数/封板时间/主力净额）失败只丢字段不丢主榜
    up_basic, ok_up = await _try_req(
        "limit_up_pool", ("pool", "limit_up_pool", td),
        lambda: _get_dataapi_pool("limit_up_pool", td), _empty, degraded)
    op_basic, ok_op = await _try_req(
        "open_limit_pool", ("pool", "open_limit_pool", td),
        lambda: _get_dataapi_pool("open_limit_pool", td), _empty, degraded)
    lo_basic, ok_lo = await _try_req(
        "lower_limit_pool", ("pool", "lower_limit_pool", td),
        lambda: _get_dataapi_pool("lower_limit_pool", td), _empty, degraded)
    up_rich, _ok_rich = await _try_req(
        "get_limit_up_stocks", ("lus", "limit_up_all", td),
        lambda: _get_limit_up_stocks("limit_up_all", td), [], degraded)

    if not (ok_up or ok_op or ok_lo):
        return _db_fallback("intensity", td, _build_intensity_from_db_or_none, degraded,
                            "涨停强度实时获取失败，且无可用历史快照")

    up = _merge_up_pool(up_basic["list"], up_rich)
    op = [_norm_open_lower(it) for it in op_basic["list"]]
    lo = [_norm_open_lower(it) for it in lo_basic["list"]]
    up_total, open_total, lower_total = (
        up_basic["total"], op_basic["total"], lo_basic["total"])

    # L1 补位：失败的池改用当日 DB 快照（盘中增量采集已落库），避免显示为 0
    if not ok_up:
        up, up_total = _pool_from_db(td, "up")
    if not ok_op:
        op, open_total = _pool_from_db(td, "open")
    if not ok_lo:
        lo, lower_total = _pool_from_db(td, "lower")

    # L2 回退：实时成功但全空（盘前 / 非交易日）→ 最近交易日快照
    if not (up or op or lo):
        return _db_fallback("intensity", td, _build_intensity_from_db_or_none, degraded,
                            f"{td} 暂无涨停聚焦数据", reason="empty_live")

    result = {
        "date": td, "up_total": up_total, "open_total": open_total,
        "lower_total": lower_total,
        "metrics": _intensity_metrics(up_total, open_total, lower_total),
        "up": up, "open": op, "lower": lo,
        "source": _source_tag(degraded), "degraded": degraded,
    }
    # 落库：仅对本次实时成功的池写入 + 全量对齐（裁剪已炸板等残留行）
    saved = 0
    for pool_type, items, ok in (("up", up, ok_up), ("open", op, ok_op),
                                 ("lower", lo, ok_lo)):
        if not ok:
            continue
        try:
            saved += store.upsert_ths_limitup_pool(
                _pool_persist_rows(td, pool_type, items))
            store.prune_ths_limitup_pool(
                td, pool_type, [it.get("code") for it in items])
        except Exception as e:  # noqa: BLE001
            logger.warning("涨停强度快照持久化失败 %s: %s", pool_type, e)
    result["persisted"] = saved
    return result


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

    degraded: List[str] = []
    # 天梯骨架为关键子接口；富化源失败仅退化为「无价格/原因」的裸天梯
    ladder_raw, ok_ladder = await _try_req(
        "continuous_limit_up", ("ladder", td),
        lambda: _get_continuous_ladder(td), [], degraded)
    up_rich, _ok_rich = await _try_req(
        "get_limit_up_stocks", ("lus", "limit_up_all", td),
        lambda: _get_limit_up_stocks("limit_up_all", td), [], degraded)

    if not ok_ladder:
        return _db_fallback("ladder", td, _build_ladder_from_db, degraded,
                            "连板天梯实时获取失败，且无可用历史快照")

    rich_map = {s.get("code"): s for s in up_rich}
    ladder: List[Dict[str, Any]] = []
    max_height = 0
    seen_codes: set = set()
    for item in ladder_raw:
        h = _int(item.get("height"))
        max_height = max(max_height, h)
        stocks: List[Dict[str, Any]] = []
        for c in (item.get("code_list") or []):
            code = c.get("code")
            seen_codes.add(code)
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

    # 合成 1板（首板）梯队：涨停池中首次涨停（连板天数<=1）、且未被更高梯队收录的个股
    if not any(t["height"] == 1 for t in ladder):
        one_stocks = [
            s for s in up_rich
            if (_int(s.get("continue_day_cnt")) <= 1
                and s.get("code") and s.get("code") not in seen_codes)
        ]
        if one_stocks:
            max_height = max(max_height, 1)
            ladder.append({
                "height": 1,
                "number": len(one_stocks),
                "stocks": [{
                    "code": s.get("code"), "name": s.get("name"),
                    "market_id": s.get("market_code", ""),
                    "continue_num": 1,
                    "price": s.get("price", 0),
                    "change_pct": s.get("change_pct", 0),
                    "reason": s.get("reason", ""),
                    "board": s.get("board", ""),
                    "limit_up_time": s.get("limit_up_time", ""),
                    "main_net_amount": s.get("main_net_amount", 0),
                    "effective_circulation": s.get("effective_circulation", 0),
                    "turnover_ratio": s.get("turnover_ratio", 0),
                } for s in one_stocks],
            })

    ladder.sort(key=lambda x: -x["height"])

    if not ladder:
        return _db_fallback("ladder", td, _build_ladder_from_db, degraded,
                            f"{td} 暂无连板天梯数据", reason="empty_live")

    result = {
        "date": td, "ladder": ladder, "max_height": max_height,
        "source": _source_tag(degraded), "degraded": degraded,
    }
    # 断板梯队：昨日连板今日未封板 → 按冲击层级（昨日高度+1）归位（best-effort）
    try:
        brk = _build_broken_ladder(td)
        result["prev_date"] = brk["prev_date"]
        result["broken_ladder"] = brk["broken_ladder"]
        result["first_board_broken_count"] = brk["first_board_broken_count"]
    except Exception as e:  # noqa: BLE001
        logger.warning("断板梯队计算失败: %s", e)
        result["broken_ladder"] = []
        result["prev_date"] = None
        result["first_board_broken_count"] = 0
    # 通达信跌停天梯：读 limit_pool(down) 按连跌天数分组；失败则回退当天 DB 快照
    try:
        down_rows = store.get_limit_pool(td, "down")
        result["down_ladder"] = _build_down_ladder_from_pool(down_rows)
        result["tdx_down_total"] = len(down_rows)
    except Exception as e:  # noqa: BLE001
        logger.warning("通达信跌停天梯读取失败: %s", e)
        result["down_ladder"] = []
        result["tdx_down_total"] = 0
    # 通达信涨停池计数（供前端与全市场卡对齐口径）
    try:
        result["tdx_up_total"] = len(store.get_limit_pool(td, "up"))
    except Exception:  # noqa: BLE001
        result["tdx_up_total"] = 0
    try:
        rows = _ladder_persist_rows(td, ladder)
        result["persisted"] = store.upsert_ths_limitup_ladder(rows)
        store.prune_ths_limitup_ladder(
            td, [(r["height"], r["code"]) for r in rows])
    except Exception as e:  # noqa: BLE001
        logger.warning("连板天梯快照持久化失败: %s", e)
    return result


async def fetch_strong_wind(trade_date: Optional[str] = None) -> Dict[str, Any]:
    """最强风口：涨停简图（题材板块榜）。"""
    from finfeed.market import store
    td = trade_date or now_bj().strftime("%Y-%m-%d")
    today = now_bj().strftime("%Y-%m-%d")

    if td != today:
        d = _build_block_top_from_db(td)
        if not d:
            return {"error": f"{td} 暂无最强风口采集数据", "section": "wind", "date": td}
        return d

    degraded: List[str] = []
    blocks_raw, ok = await _try_req(
        "block_top", ("block_top", td), lambda: _get_block_top(td), [], degraded)
    if not ok:
        return _db_fallback("wind", td, _build_block_top_from_db, degraded,
                            "最强风口实时获取失败，且无可用历史快照")

    blocks = _norm_block_top(blocks_raw)
    if not blocks:
        return _db_fallback("wind", td, _build_block_top_from_db, degraded,
                            f"{td} 暂无最强风口数据", reason="empty_live")

    result = {
        "date": td, "blocks": blocks,
        "source": _source_tag(degraded), "degraded": degraded,
    }
    try:
        rows = _block_top_persist_rows(td, blocks_raw)
        result["persisted"] = store.upsert_ths_limitup_block_top(rows)
        store.prune_ths_limitup_block_top(td, [r["topic_code"] for r in rows])
    except Exception as e:  # noqa: BLE001
        logger.warning("最强风口（涨停简图）快照持久化失败: %s", e)
    return result


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

    degraded: List[str] = []
    # 总览与风向标股相互独立：任一成功即可呈现半屏；交易状态为纯装饰位
    ov, ok_ov = await _try_req(
        "overview", ("overview", td), lambda: _get_overview(td), {}, degraded)
    ts, _ok_ts = await _try_req(
        "trade_status", ("tstatus", td), lambda: _get_trade_status(), {}, degraded)
    wind_tabs, ok_wind = await _try_req(
        "get_wind_vane_stock", ("wind_vane", td), lambda: _get_wind(td), [], degraded)

    if not (ok_ov or ok_wind):
        return _db_fallback("sentiment", td, _build_sentiment_from_db, degraded,
                            "市场情绪实时获取失败，且无可用历史快照")

    ov = ov if isinstance(ov, dict) else {}
    ts = ts if isinstance(ts, dict) else {"stat": str(ts)}
    db_snap: Optional[Dict[str, Any]] = None
    if not ok_ov or not ov:
        db_snap = _build_sentiment_from_db(td)  # 总览失败 → 当日 DB 补位

    def _ov(field: str, default: Any) -> Any:
        v = ov.get(field)
        if v:
            return v
        if db_snap:
            return db_snap.get(field) or default
        return default

    tabs = (_norm_wind_tabs(wind_tabs) if ok_wind
            else (_build_wind_from_db(td) or {}).get("tabs", []))

    if not (ov or tabs or db_snap):
        return _db_fallback("sentiment", td, _build_sentiment_from_db, degraded,
                            f"{td} 暂无市场情绪数据", reason="empty_live")

    result = {
        "date": td,
        "turnover": _ov("turnover", {}),
        "north_flow": _ov("north_flow", None),
        "limit_up": _ov("limit_up", {}),
        "rise_fall": _ov("rise_fall", {}),
        "hgt_market_status": _ov("hgt_market_status", None),
        "config_start_date": _ov("config_start_date", None),
        "trade_status": ts or (db_snap or {}).get("trade_status") or {},
        "wind_vane": {"tabs": tabs},
        "source": _source_tag(degraded), "degraded": degraded,
    }
    saved = 0
    if ok_ov and ov:  # 仅实时总览成功才覆写当日情绪行，避免用 DB 补位值回写
        try:
            saved += store.upsert_ths_limitup_sentiment(_sentiment_persist_row(td, result))
        except Exception as e:  # noqa: BLE001
            logger.warning("市场情绪总览快照持久化失败: %s", e)
    if ok_wind and wind_tabs:
        try:
            rows = _wind_persist_rows(td, wind_tabs)
            saved += store.upsert_ths_limitup_wind(rows)
            store.prune_ths_limitup_wind(
                td, [(r["tab_name"], r["stock_code"]) for r in rows])
        except Exception as e:  # noqa: BLE001
            logger.warning("风向标股快照持久化失败: %s", e)
    result["persisted"] = saved
    return result


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
