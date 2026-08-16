#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""行情交叉校验模块（多源对账，检测东财单点故障）

对一组 A 股代码，同时从东方财富（基准）、腾讯与同花顺（独立源）抓取实时行情，
对比最新价与涨跌幅。任一独立源相对东财的「价格偏差百分比」或「涨跌幅偏差（百分点）」
超过阈值时记为告警（Warning 日志），用于检测单点数据源故障或数据异常。

设计要点：
- **东财为基准**，走 finfeed.market.client.get_json（复用 Referer 注入 + 令牌桶 +
  组级冷却 + 熔断）。字段契约（2026-08-15 实测）：ulist.np/get 默认不带 fltt，
  f2（最新价）/ f3（涨跌幅）/ f4（涨跌额）均需 **/100**；f12 代码、f13 市场、f14 名称。
- **腾讯 qt.gtimg.cn** 响应为 **GBK** 编码（必须 GBK 解码），按 `~` 切分，字段索引（实测）：
  idx1=名称, idx2=代码, idx3=最新价, idx4=昨收, idx5=今开, idx31=涨跌额, idx32=涨跌幅,
  idx33=最高, idx34=最低, idx38=换手率, idx39=PE, idx44=流通市值(亿), idx45=总市值(亿),
  idx47=涨停价, idx48=跌停价。
- **同花顺 d.10jqka.com.cn/v2/realhead** 为 JSONP（UTF-8），需剥包装。items 键（实测）：
  '5'=代码, '6'=昨收, '7'=今开, '8'=最高, '9'=最低, '10'=最新价, '69'=涨停价, '70'=跌停价,
  'name'=名称。
  ⚠️ items 中的涨跌幅/涨跌额使用**大整数动态键**（如 '199112'/'264648'，随行情波动变化，
  索引不稳定），故本模块统一由「最新价/昨收」推算：pct = (price / prev - 1) * 100。
  若未来键名变化导致 6/10 键缺失，仅该源跳过对比（东财 vs 腾讯仍保证可对比）。
- **无 import 副作用**：本模块顶层不发起任何网络请求，HTTP 客户端按需懒建（首次调用时）。

用法（调度器接入建议见 README / 报告）：
    from finfeed.market.crosscheck import crosscheck_quotes
    devs = crosscheck_quotes(["600519", "000001", "600036"], threshold_pct=0.5)
"""

import asyncio
import json
import logging
import re
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

import httpx

from .client import RateLimited, get_json
from .endpoints import PUSH2, PUSH2_DELAY, UT, secid_of

logger = logging.getLogger("news_monitor")

# ---------------------------------------------------------------------------
# 端点常量
# ---------------------------------------------------------------------------
# 东财基准 ulist：push2 为主，push2delay 为降级主机（2026-08-15 实测两者
# 对纯行情字段 f2/f3/f4/f12/f13/f14 语义一致，均需 /100；push2delay 仅可用于
# 纯行情字段，见 board.py 对资金流字段的语义护栏说明）。
EM_ULIST_URL = f"{PUSH2}/ulist.np/get"
EM_ULIST_URL_DELAY = f"{PUSH2_DELAY}/ulist.np/get"
EM_FIELDS = "f2,f3,f4,f12,f13,f14"
TX_URL = "https://qt.gtimg.cn/q="
THS_URL_TMPL = "https://d.10jqka.com.cn/v2/realhead/hs_{code}/last.js"
THS_REFERER = "https://www.10jqka.com.cn/"
UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)
# 腾讯/同花顺最小请求间隔（秒），避免高频探测
_MIN_SRC_INTERVAL = 0.5

# 独立源原始 HTTP 客户端（懒建，按事件循环复用；与 client.py 同思路但不共享，
# 因为腾讯/同花顺需要 GBK 文本与 JSONP 处理，client.get_json 的 resp.json() 不适用）
_http_client: Optional[httpx.AsyncClient] = None
_http_loop: Optional[asyncio.AbstractEventLoop] = None
_src_lock = threading.Lock()
_src_last_call: Dict[str, float] = {"tencent": 0.0, "ths": 0.0}


@dataclass
class QuoteDeviation:
    """单只股票的三源行情对账结果。

    price_* / pct_* 为 None 表示该源本次未取到数据（不参与偏差计算）。
    max_price_dev_pct 与 max_pct_dev_pts 只统计「有东财基准 + 独立源数据」的对比对。
    deviant=True 表示任一对比对超出阈值，此时已写入 Warning 日志。
    """

    ticker: str
    name: str
    price_east: Optional[float]
    pct_east: Optional[float]
    price_tencent: Optional[float]
    pct_tencent: Optional[float]
    price_ths: Optional[float]
    pct_ths: Optional[float]
    max_price_dev_pct: Optional[float]
    max_pct_dev_pts: Optional[float]
    deviant: bool
    sources: List[str] = field(default_factory=list)
    note: str = ""


# ---------------------------------------------------------------------------
# 基础工具
# ---------------------------------------------------------------------------
def _to_f(v: Any) -> Optional[float]:
    """安全转 float；None / '' / '-' / 非法串 返回 None。"""
    if v is None or v == "" or v == "-":
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _normalize(code: str) -> str:
    """归一化代码：'sh600519' / 'sz000001' / 'hs_600519' / '1.600519' -> '600519'。"""
    digits = re.sub(r"\D", "", (code or "").strip())
    return digits[-6:] if len(digits) >= 6 else ""


def _tx_symbol(code: str) -> str:
    """6 位代码 -> 腾讯符号（sh600519 / sz000001）。"""
    sec = secid_of(code)
    market, _ = sec.split(".", 1)
    return ("sh" if market == "1" else "sz") + code


def _get_raw_client() -> httpx.AsyncClient:
    """按事件循环懒建独立源 HTTP 客户端（无 import 副作用）。"""
    global _http_client, _http_loop
    loop = asyncio.get_running_loop()
    if _http_client is None or _http_client.is_closed or _http_loop is not loop:
        _http_client = httpx.AsyncClient(
            timeout=15.0,
            follow_redirects=True,
            headers={"User-Agent": UA},
            limits=httpx.Limits(max_connections=4, max_keepalive_connections=2),
        )
        _http_loop = loop
    return _http_client


async def _throttle_src(name: str) -> None:
    with _src_lock:
        last = _src_last_call[name]
        _src_last_call[name] = time.monotonic()
    wait = _MIN_SRC_INTERVAL - (time.monotonic() - last)
    if wait > 0:
        await asyncio.sleep(wait)


# ---------------------------------------------------------------------------
# 各源抓取
# ---------------------------------------------------------------------------
async def _fetch_east(codes: List[str]) -> Dict[str, Dict[str, Any]]:
    """东财基准：ulist.np/get 批量报价。f2/f3/f4 无 fltt 时需 /100。

    push2 主集群失败（限流/断连）时自动降级到 push2delay 延时集群
    （纯行情字段语义一致，见模块头注释），仍失败才返回空。
    """
    secids = ",".join(secid_of(c) for c in codes)
    params = {"secids": secids, "fields": EM_FIELDS, "ut": UT}
    data: Dict[str, Any] = {}
    for url, group in ((EM_ULIST_URL, "em_push2"), (EM_ULIST_URL_DELAY, "em_push2delay")):
        try:
            data = await get_json(url, params=params, group=group)
            if data:
                break
        except RateLimited as e:
            logger.warning(f"东财行情基准 {group} 跳过（限流/熔断）: {e}")
        except Exception as e:  # noqa: BLE001
            logger.warning(f"东财行情基准 {group} 获取失败: {e}")
    if not data:
        return {}

    diff = (data.get("data") or {}).get("diff") or []
    if isinstance(diff, dict):  # 单只返回 dict 的兼容处理
        diff = [diff]
    out: Dict[str, Dict[str, Any]] = {}
    for it in diff:
        code = str(it.get("f12") or "").strip()
        if not code:
            continue
        f2 = _to_f(it.get("f2"))
        f3 = _to_f(it.get("f3"))
        f4 = _to_f(it.get("f4"))
        out[code] = {
            "name": str(it.get("f14") or "").strip(),
            "price": f2 / 100 if f2 is not None else None,
            "pct": f3 / 100 if f3 is not None else None,
            "chg": f4 / 100 if f4 is not None else None,
        }
    return out


async def _fetch_tencent(codes: List[str]) -> Dict[str, Dict[str, Any]]:
    """腾讯：qt.gtimg.cn 批量报价（GBK 解码，按 ~ 切分）。"""
    symbols = ",".join(_tx_symbol(c) for c in codes)
    await _throttle_src("tencent")
    client = _get_raw_client()
    try:
        resp = await client.get(TX_URL + symbols)
        resp.raise_for_status()
        raw = resp.content
    except Exception as e:  # noqa: BLE001
        logger.warning(f"腾讯行情获取失败: {e}")
        return {}
    text = raw.decode("gbk", errors="replace")
    out: Dict[str, Dict[str, Any]] = {}

    def _g(parts: List[str], i: int) -> Optional[str]:
        return parts[i] if i < len(parts) else None

    for line in text.strip().split(";"):
        line = line.strip()
        if not line or "=" not in line:
            continue
        key, val = line.split("=", 1)
        parts = val.strip().strip('"').split("~")
        if len(parts) < 35:
            continue
        code = _normalize(key[2:])  # 'v_sh600519' -> '600519'
        if not code:
            continue
        out[code] = {
            "name": str(_g(parts, 1) or "").strip(),
            "price": _to_f(_g(parts, 3)),
            "prev": _to_f(_g(parts, 4)),
            "open": _to_f(_g(parts, 5)),
            "chg": _to_f(_g(parts, 31)),
            "pct": _to_f(_g(parts, 32)),
            "high": _to_f(_g(parts, 33)),
            "low": _to_f(_g(parts, 34)),
            "turnover": _to_f(_g(parts, 38)),
            "pe": _to_f(_g(parts, 39)),
            "circ_mv": _to_f(_g(parts, 44)),
            "total_mv": _to_f(_g(parts, 45)),
            "up_limit": _to_f(_g(parts, 47)),
            "down_limit": _to_f(_g(parts, 48)),
        }
    return out


async def _fetch_ths(code: str) -> Optional[Dict[str, Any]]:
    """同花顺单只实时行情：JSONP 剥包装，items 键 5/6/7/8/9/10/69/70。"""
    url = THS_URL_TMPL.format(code=code)
    await _throttle_src("ths")
    client = _get_raw_client()
    try:
        resp = await client.get(url, headers={"Referer": THS_REFERER})
        resp.raise_for_status()
        text = resp.text
    except Exception as e:  # noqa: BLE001
        logger.warning(f"同花顺行情 {code} 获取失败: {e}")
        return None

    m = re.search(r"\((\{.*\})\)\s*$", text.strip(), re.S)
    if not m:
        logger.warning(f"同花顺 {code} JSONP 剥包装失败（跳过该源对比）")
        return None
    try:
        items = (json.loads(m.group(1)) or {}).get("items") or {}
    except json.JSONDecodeError as e:
        logger.warning(f"同花顺 {code} JSON 解析失败（跳过该源对比）: {e}")
        return None

    price = _to_f(items.get("10"))
    prev = _to_f(items.get("6"))
    pct: Optional[float] = None
    if price is not None and prev:
        pct = round((price / prev - 1) * 100, 4)
    return {
        "name": str(items.get("name") or "").strip(),
        "price": price,
        "prev": prev,
        "open": _to_f(items.get("7")),
        "high": _to_f(items.get("8")),
        "low": _to_f(items.get("9")),
        "pct": pct,
        "up_limit": _to_f(items.get("69")),
        "down_limit": _to_f(items.get("70")),
    }


# ---------------------------------------------------------------------------
# 对账
# ---------------------------------------------------------------------------
def _build_deviation(
    code: str,
    em: Dict[str, Any],
    tx: Optional[Dict[str, Any]],
    ths: Optional[Dict[str, Any]],
    threshold_pct: float,
) -> QuoteDeviation:
    pe = em.get("price")
    epct = em.get("pct")
    pt = tx.get("price") if tx else None
    pct_t = tx.get("pct") if tx else None
    ph = ths.get("price") if ths else None
    pct_h = ths.get("pct") if ths else None

    sources = ["east"]
    if pt is not None or pct_t is not None:
        sources.append("tencent")
    if ph is not None or pct_h is not None:
        sources.append("ths")

    price_devs: List[float] = []
    pct_devs: List[float] = []
    if pe:
        if pt is not None:
            price_devs.append(abs(pt - pe) / pe * 100)
        if ph is not None:
            price_devs.append(abs(ph - pe) / pe * 100)
    if epct is not None:
        if pct_t is not None:
            pct_devs.append(abs(pct_t - epct))
        if pct_h is not None:
            pct_devs.append(abs(pct_h - epct))

    max_price = max(price_devs) if price_devs else None
    max_pct = max(pct_devs) if pct_devs else None
    deviant = (max_price is not None and max_price > threshold_pct) or (
        max_pct is not None and max_pct > threshold_pct
    )
    note = ""
    if deviant:
        note = (
            f"价格偏差 {max_price:.2f}% / 涨跌幅偏差 {max_pct:.2f}pt"
            f" 超阈值 {threshold_pct}"
        )

    name = em.get("name") or ""
    if not name and tx:
        name = tx.get("name") or ""
    if not name and ths:
        name = ths.get("name") or ""

    dev = QuoteDeviation(
        ticker=code,
        name=name,
        price_east=pe,
        pct_east=epct,
        price_tencent=pt,
        pct_tencent=pct_t,
        price_ths=ph,
        pct_ths=pct_h,
        max_price_dev_pct=max_price,
        max_pct_dev_pts=max_pct,
        deviant=deviant,
        sources=sources,
        note=note,
    )
    if deviant:
        logger.warning(f"行情交叉校验告警 {code}({name or '?'}): {note}")
    return dev


async def crosscheck_quotes_async(
    tickers: List[str],
    threshold_pct: float = 0.5,
) -> List[QuoteDeviation]:
    """多源行情交叉校验（异步内核）。

    Args:
        tickers: A 股 6 位代码列表（兼容 'sh600519' / 'hs_600519' 等带前缀写法）。
        threshold_pct: 偏差阈值（%）—— 价格差百分比 或 涨跌幅差（百分点）任一超出即告警。

    Returns:
        List[QuoteDeviation]。东财基准整体不可用时返回空列表（此时无法对账，
        视为东财单点故障迹象，已写 Warning 日志）。单个独立源失败不影响其余。
    """
    codes = [c for c in (_normalize(t) for t in tickers) if c]
    if not codes:
        logger.warning("crosscheck: 无有效股票代码，跳过")
        return []
    if threshold_pct <= 0:
        logger.warning(f"crosscheck: 阈值必须为正数，收到 {threshold_pct}，按 0.5 处理")
        threshold_pct = 0.5

    em = await _fetch_east(codes)
    if not em:
        logger.warning(
            "crosscheck: 东财基准不可用（疑似东财单点故障），本次不做交叉对比"
        )
        return []

    tx = await _fetch_tencent(codes)
    ths_map: Dict[str, Dict[str, Any]] = {}
    for c in codes:
        r = await _fetch_ths(c)
        if r:
            ths_map[c] = r

    out: List[QuoteDeviation] = []
    for c in codes:
        e = em.get(c)
        if not e:
            logger.debug(f"crosscheck: 东财无 {c} 的数据，跳过")
            continue
        out.append(_build_deviation(c, e, tx.get(c), ths_map.get(c), threshold_pct))
    return out


def crosscheck_quotes(tickers: List[str], threshold_pct: float = 0.5) -> List[QuoteDeviation]:
    """多源行情交叉校验（同步入口，供调度器/脚本直接调用）。

    Args:
        tickers: A 股 6 位代码列表（兼容带前缀写法）。
        threshold_pct: 偏差阈值（%），默认 0.5。

    Returns:
        List[QuoteDeviation]；东财基准不可用时返回空列表（不抛异常）。
    """
    return asyncio.run(crosscheck_quotes_async(list(tickers), threshold_pct))


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    logging.getLogger("httpx").setLevel(logging.WARNING)  # 静默 httpx 访问日志
    print("行情交叉校验演示（东财基准 vs 腾讯/同花顺独立源）")
    print("-" * 78)
    demo_tickers = ["600519", "000001", "600036", "601318", "000858"]
    result = crosscheck_quotes(demo_tickers)
    header = (
        f"{'代码':<7}{'名称':<8}{'东财价':>10}{'腾讯价':>10}{'同花价':>10}"
        f"{'价偏%':>8}{'涨跌偏':>8}  源"
    )
    print(header)
    print("-" * 78)
    for d in result:
        fmt_price = lambda v: f"{v:.2f}" if v is not None else "-"  # noqa: E731
        fmt_dev = lambda v: f"{v:.3f}" if v is not None else "-"  # noqa: E731
        mark = " <== 偏差超阈值" if d.deviant else ""
        print(
            f"{d.ticker:<7}{d.name:<8}{fmt_price(d.price_east):>10}"
            f"{fmt_price(d.price_tencent):>10}{fmt_price(d.price_ths):>10}"
            f"{fmt_dev(d.max_price_dev_pct):>8}{fmt_dev(d.max_pct_dev_pts):>8}  "
            f"{','.join(d.sources)}{mark}"
        )
    print("-" * 78)
    print(f"共 {len(result)} 只；其中偏差告警 {sum(1 for d in result if d.deviant)} 只")
