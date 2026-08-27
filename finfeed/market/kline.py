#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""日线 K 线采集（daily_bar）

端点：push2his kline（klt=101 日线，fqt=1 前复权）。

⚠️ 已修复的重大缺陷：
   旧实现 `beg = trade_date or "20250101"`，而调用方传入的是 **带横杠**的
   '2026-08-07'。东财对非法 beg 参数**静默忽略**并回吐 1991 年至今的全部历史
   （单只 7000+ 根 K 线）。叠加 get_all_codes() 当时返回 24759 个标的（含新三板），
   一轮"日线采集"实际会产生 24759 次重请求、上亿行数据 —— 这是本机 IP 被东财
   按滑动窗口限流封禁的直接原因。库内 daily_bar 只有 28 只股票 × 约 7000 行 =
   199023 行，正是该缺陷留下的痕迹。

   现在：
   - 所有日期一律经 compact_date() 归一化为 YYYYMMDD；
   - 默认走**增量模式**（lmt=N 只取最近 N 根），回补才用 beg/end 区间；
   - 批量采集只遍历 stock_meta.is_active=1 的标的；
   - 遇到限流冷却立即中断整批，不做无谓施压。

字段顺序（fields2）：f51 日期, f52 开, f53 收, f54 高, f55 低, f56 量, f57 额,
                      f58 振幅, f59 涨跌幅, f60 涨跌额, f61 换手
"""

import asyncio
import logging
from typing import Dict, List, Optional

from finfeed.utils.time_utils import now_bj

from . import store
from .client import RateLimited, cooldown_remaining, get_json
from .endpoints import (
    FLTT,
    KLINE_FIELDS2,
    PUSH2HIS,
    PUSH2HIS_TRENDS,
    TRENDS_FIELDS2,
    UT,
    compact_date,
    secid_of,
)

# 指数代码 -> 东财 secid。前缀规则对 000001/399001 失效：
# 000001 既是上证指数（沪，1.000001）又是平安银行（深，0.000001），
# 399001 同理。仪表盘固定取这两只指数，故在此显式映射。
INDEX_SECID = {"000001": "1.000001", "399001": "0.399001"}


def _resolve_secid(code: str) -> str:
    """代码 -> 东财 secid，指数走显式映射，其余回退通用规则。"""
    return INDEX_SECID.get((code or "").strip()) or secid_of(code)

logger = logging.getLogger("news_monitor")

# 增量模式默认取最近多少根（覆盖节假日与偶发漏采）
DEFAULT_LIMIT = 10
# 批量采集单轮最大标的数保护阀（防止误传全市场导致长时间施压）
MAX_BATCH = 6000


def _parse_kline(rows: List[str]) -> List[Dict]:
    out: List[Dict] = []
    for line in rows or []:
        p = (line or "").split(",")
        if len(p) < 11:
            continue
        try:
            out.append({
                "trade_date": p[0],
                "open": float(p[1]), "close": float(p[2]),
                "high": float(p[3]), "low": float(p[4]),
                "volume": int(float(p[5])), "amount": float(p[6]),
                "amplitude": float(p[7]), "pct_chg": float(p[8]),
                "turnover": float(p[10]),
            })
        except (ValueError, IndexError):
            continue
    return out


async def fetch_daily_bar(
    code: str,
    end_date: Optional[str] = None,
    limit: int = DEFAULT_LIMIT,
    beg: Optional[str] = None,
    klt: int = 101,
) -> List[Dict]:
    """拉取单只证券 K 线（支持多周期）。

    Args:
        code: 6 位代码（含指数，如 000001 / 399001）
        end_date: 截止日（任意格式，内部归一化为 YYYYMMDD）
        limit: 增量模式下取最近多少根（beg 为空时生效）
        beg: 起始日；给定则切换为区间模式（用于历史回补）
        klt: K 线周期类型
             101 日线 / 102 周线 / 103 月线 / 104 季线 / 105 年线
             （分钟线 1/5/15/30/60 也可传，但本项目仪表盘仅用日级以上）
    """
    params = {
        "secid": _resolve_secid(code),
        "fields1": "f1,f2,f3,f4,f5,f6",
        "fields2": KLINE_FIELDS2,
        "klt": klt, "fqt": 0 if code in INDEX_SECID else 1, "fltt": FLTT, "ut": UT,
        "end": compact_date(end_date) if end_date else "20500101",
    }
    if beg:
        params["beg"] = compact_date(beg)
    else:
        params["lmt"] = max(1, int(limit))

    try:
        data = await get_json(PUSH2HIS, params=params, group="em_push2his")
    except RateLimited:
        raise
    except Exception as e:  # noqa: BLE001
        logger.debug(f"日线 {code} 获取失败: {e}")
        return []

    klines = (data.get("data") or {}).get("klines") or []
    return _parse_kline(klines)


async def fetch_trends(code: str, ndays: int = 1) -> List[Dict]:
    """拉取分时数据（当日/近 N 日 每分钟 价 + 均价）。

    端点：push2his trends2。返回 [{time, price, avg_price}]。
    仅用于指数/个股分时图，与 K 线（kline）数据结构不同。

    Args:
        code: 6 位代码（含指数）
        ndays: 1=当日；5=近 5 个交易日（本仪表盘仅用当日）
    """
    params = {
        "secid": _resolve_secid(code),
        "fields1": "f1,f2,f3,f4,f5,f6",
        "fields2": TRENDS_FIELDS2,
        "ndays": int(ndays),
        "forcect": 1,
        "ut": UT,
    }
    try:
        data = await get_json(PUSH2HIS_TRENDS, params=params, group="em_push2his")
    except RateLimited:
        raise
    except Exception as e:  # noqa: BLE001
        logger.debug(f"分时 {code} 获取失败: {e}")
        return []

    raw = (data.get("data") or {})
    rows = raw.get("trends") or raw.get("klines") or []
    out: List[Dict] = []
    for line in rows or []:
        p = (line or "").split(",")
        if len(p) < 8:  # 完整字段集固定 11 列；少于 8 列视为异常行
            continue
        try:
            out.append({
                "time": p[0],
                "price": float(p[2]),
                "avg_price": float(p[7]),
                "volume": float(p[5] or 0),
            })
        except (ValueError, IndexError):
            continue
    return out


async def collect_daily_bars(
    codes: List[str],
    trade_date: Optional[str] = None,
    limit: int = DEFAULT_LIMIT,
    beg: Optional[str] = None,
    progress_cb=None,
) -> Dict[str, int]:
    """批量采集日线并写入 daily_bar。

    Args:
        progress_cb: 可选回调 progress_cb(done:int, total:int)，按完成标的粒度上报。
                     限流中断与正常完成都会触发；接口签名向后兼容（默认 None）。

    Returns: {'codes': 计划数, 'done': 实际完成数, 'rows': 写入行数, 'aborted': 0/1}
    """
    td = trade_date or now_bj().strftime("%Y-%m-%d")
    if len(codes) > MAX_BATCH:
        logger.warning(f"日线批量 {len(codes)} 只超过保护阀 {MAX_BATCH}，已截断")
        codes = codes[:MAX_BATCH]

    total_rows = 0
    done = 0
    aborted = 0
    total = len(codes)
    if progress_cb:
        try:
            progress_cb(0, total)
        except Exception:  # noqa: BLE001
            pass
    for code in codes:
        if cooldown_remaining("em_push2his") > 0:
            aborted = 1
            logger.warning(
                f"push2his 进入限流冷却，日线采集中断于 {done}/{len(codes)} 只；"
                f"已写入 {total_rows} 行，剩余标的可稍后续采（幂等）"
            )
            break
        try:
            bars = await fetch_daily_bar(code, end_date=td, limit=limit, beg=beg)
        except RateLimited:
            aborted = 1
            logger.warning(f"push2his 限流，日线采集中断于 {done}/{len(codes)} 只")
            break
        bars = [dict(b, code=code) for b in bars if b["trade_date"] <= td]
        if bars:
            total_rows += store.upsert_daily_bar(bars)
        done += 1
        # 每 50 只（且终态必报），避免高频回调拖慢主循环
        if progress_cb and (done % 50 == 0 or done == total):
            try:
                progress_cb(done, total)
            except Exception:  # noqa: BLE001
                pass

    logger.info(f"日线采集：计划 {len(codes)} 只 / 完成 {done} 只 / 写入 {total_rows} 行（截至 {td}）")
    return {"codes": len(codes), "done": done, "rows": total_rows, "aborted": aborted}


def run_collect_daily_bars(codes: List[str], trade_date: Optional[str] = None,
                           limit: int = DEFAULT_LIMIT) -> Dict[str, int]:
    return asyncio.run(collect_daily_bars(codes, trade_date, limit))
