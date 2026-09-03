# -*- coding: utf-8 -*-
"""全市场资金流与板块轮动监控大屏 —— 数据采集层。

基于 easy-tdx MAC 协议实现沪深两市全市场个股/板块资金流向抓取：

- 全市场个股资金流  : ``get_stock_quotes_list(Category.A)`` 一次性拉取全部 A 股
  （含 主力净流入/主力净比/5分钟主力净额/3日净额/5日净额/成交额/换手 等实时字段）
- 板块资金流        : ``get_board_ranking(HY/GN)`` 行业/概念板块排行
  （含 涨跌幅/成交额/主力净流入/涨跌家数）
- 指数行情          : ``get_stock_quotes_list(Category.ZS)``
- 个股资金流详情    : ``get_capital_flow`` 当日主力/散户流入流出 + 5日大单/中单净额

所有函数均返回纯 Python 数据结构（见 models.py），不暴露 pandas。
"""

from __future__ import annotations

import logging
from typing import Any

from easy_tdx import BoardType, Category, MacClient, SortOrder, SortType
from easy_tdx.codec.bitmap import FieldBit, PresetField
from easy_tdx.exceptions import TdxError

from . import config
from .models import (
    BoardFlow,
    IndexQuote,
    MarketBreadth,
    MarketStats,
    StockFlow,
)
from .tdx import call_lock, ensure_alive, get_client

logger = logging.getLogger("finfeed.capital_dashboard.collector")

# 批量报价请求字段：基础 OHLC + 量额 + 资金流关键字段
FIELDS = (
    PresetField.BASIC
    + PresetField.VOLUME
    + FieldBit.MAIN_NET_AMOUNT
    + FieldBit.MAIN_NET_RATIO
    + FieldBit.MAIN_NET_5M_AMOUNT
    + FieldBit.MAIN_NET_3D_AMOUNT
    + FieldBit.MAIN_NET_5D_AMOUNT
    + FieldBit.AMOUNT
    + FieldBit.TURNOVER
)

# 过滤标志：剔除科创/创业/北交等板块权重影响？保留全部 A 股即可。
_EXCLUDE: list[Any] = []


def _safe(fn, default: Any = None, tag: str = ""):
    """执行采集函数，异常打日志并返回默认值（单点故障不拖垮整轮采集）。"""
    try:
        return fn()
    except Exception as exc:  # noqa: BLE001
        logger.warning("采集失败[%s]: %s", tag or getattr(fn, "__name__", "?"), exc)
        return default


def _chg_pct(row: Any) -> float:
    """由 close/pre_close 计算涨跌幅%。"""
    pre = float(row.get("pre_close") or 0.0)
    close = float(row.get("close") or 0.0)
    if pre <= 0:
        return 0.0
    return round((close - pre) / pre * 100.0, 4)


# --------------------------------------------------------------------------- #
# 全市场个股资金流
# --------------------------------------------------------------------------- #

def fetch_all_stocks(client: MacClient | None = None) -> list[StockFlow]:
    """一次性抓取沪深两市全部 A 股资金流（约 5500+ 只，1~2 秒）。

    返回全量列表，由上层负责排序取榜单。
    """
    ensure_alive()
    client = client or get_client()
    with call_lock():
        df = client.get_stock_quotes_list(
            Category.A,
            count=12000,
            sort_type=SortType.CODE,
            sort_order=SortOrder.ASC,
            fields=FIELDS,
        )
    rows: list[StockFlow] = []
    for _, r in df.iterrows():
        rows.append(
            StockFlow(
                market=int(r.get("market", 0)),
                code=str(r.get("code", "")).strip(),
                name=str(r.get("name", "")).strip(),
                price=round(float(r.get("close", 0.0) or 0.0), 4),
                change_pct=_chg_pct(r),
                amount=float(r.get("amount", 0.0) or 0.0),
                turnover=float(r.get("turnover", 0.0) or 0.0),
                main_net=float(r.get("main_net_amount", 0.0) or 0.0),
                main_net_ratio=float(r.get("main_net_ratio", 0.0) or 0.0),
                main_net_5m=float(r.get("main_net_5m_amount", 0.0) or 0.0),
                main_net_3d=float(r.get("main_net_3d_amount", 0.0) or 0.0),
                main_net_5d=float(r.get("main_net_5d_amount", 0.0) or 0.0),
            )
        )
    return rows


# --------------------------------------------------------------------------- #
# 板块排行
# --------------------------------------------------------------------------- #

def _board_rows(df, board_type: str) -> list[BoardFlow]:
    rows: list[BoardFlow] = []
    for _, r in df.iterrows():
        rows.append(
            BoardFlow(
                code=str(r.get("code", "")).strip(),
                name=str(r.get("name", "")).strip(),
                board_type=board_type,
                change_pct=round(float(r.get("change_pct", 0.0) or 0.0), 4),
                amount=float(r.get("amount", 0.0) or 0.0),
                vol=float(r.get("vol", 0.0) or 0.0),
                main_net=float(r.get("main_net_amount", 0.0) or 0.0),
                up_count=int(r.get("up_count", 0) or 0),
                down_count=int(r.get("down_count", 0) or 0),
                member_count=int(r.get("member_count", 0) or 0),
            )
        )
    return rows


def _board_ranking_locked(client, board_type, top_n):
    """在调用锁内执行板块排行请求（保证 TDX 客户端线程安全）。"""
    with call_lock():
        return client.get_board_ranking(board_type, top_n=top_n)


def fetch_board_rankings(client: MacClient | None = None) -> dict[str, list[BoardFlow]]:
    """获取行业(HY)与概念(GN)板块排行（含主力资金流）。"""
    ensure_alive()
    client = client or get_client()
    result: dict[str, list[BoardFlow]] = {}

    hy = _safe(
        lambda: _board_ranking_locked(client, BoardType.HY, config.BOARD_TOP_N * 2),
        tag="board_ranking_hy",
    )
    if hy is not None and len(hy):
        result["HY"] = _board_rows(hy, "HY")

    gn = _safe(
        lambda: _board_ranking_locked(client, BoardType.GN, config.GN_RANKING_TOP),
        tag="board_ranking_gn",
    )
    if gn is not None and len(gn):
        result["GN"] = _board_rows(gn, "GN")

    return result


# --------------------------------------------------------------------------- #
# 指数行情
# --------------------------------------------------------------------------- #

def fetch_indices(client: MacClient | None = None) -> list[IndexQuote]:
    """获取主要指数行情（按白名单过滤）。"""
    ensure_alive()
    client = client or get_client()
    with call_lock():
        df = client.get_stock_quotes_list(
            Category.ZS, count=120, fields=FIELDS
        )
    wanted = set(config.MAIN_INDEX_CODES)
    out: list[IndexQuote] = []
    for _, r in df.iterrows():
        code = str(r.get("code", "")).strip()
        if code not in wanted:
            continue
        out.append(
            IndexQuote(
                code=code,
                name=str(r.get("name", "")).strip(),
                price=round(float(r.get("close", 0.0) or 0.0), 4),
                change_pct=_chg_pct(r),
                amount=float(r.get("amount", 0.0) or 0.0),
            )
        )
    # 按配置白名单顺序固定输出：上证/深成/创业板/科创50/沪深300/中证500
    order = {code: i for i, code in enumerate(config.MAIN_INDEX_CODES)}
    out.sort(key=lambda q: order.get(q.code, 999))
    return out


# --------------------------------------------------------------------------- #
# 个股资金流详情（当日主力/散户 + 5日大/中单）
# --------------------------------------------------------------------------- #

def fetch_stock_detail(market: int, code: str) -> dict[str, Any]:
    """获取单只个股的资金流详情（0x1218 接口）。

    返回字段：
        main_in/main_out/main_net  当日主力(≈超大单+大单)流入/流出/净额
        retail_in/retail_out       当日散户(≈中单+小单)流入/流出
        large_net_5d               5日大单净额
        mid_net_5d                 5日中单净额

    失败返回空 dict。
    """
    ensure_alive()
    client = get_client()
    try:
        with call_lock():
            df = client.get_capital_flow(int(market), str(code))
    except TdxError as exc:
        logger.debug("个股资金流详情失败 %s/%s: %s", market, code, exc)
        return {}
    if df is None or len(df) == 0:
        return {}
    r = df.iloc[0]
    return {
        "main_in": float(r.get("main_in", 0.0) or 0.0),
        "main_out": float(r.get("main_out", 0.0) or 0.0),
        "main_net": float(r.get("main_net", 0.0) or 0.0),
        "retail_in": float(r.get("small_in", 0.0) or 0.0),
        "retail_out": float(r.get("small_out", 0.0) or 0.0),
        "retail_net": float(r.get("small_net", 0.0) or 0.0),
        "large_net_5d": float(r.get("large_net", 0.0) or 0.0),
        "mid_net_5d": float(r.get("mid_net", 0.0) or 0.0),
    }


def enrich_top_stocks(stocks: list[StockFlow], top_n: int = 20) -> None:
    """对榜单前 N 只股票补全当日资金流详情（就地修改）。

    仅在股票同时缺少详情字段时调用；调用方应控制频率（见 snapshot.RefreshWorker）。
    """
    for st in stocks:
        if st.main_in is not None:
            continue
        detail = fetch_stock_detail(st.market, st.code)
        if not detail:
            continue
        st.main_in = detail["main_in"]
        st.main_out = detail["main_out"]
        st.retail_in = detail["retail_in"]
        st.retail_out = detail["retail_out"]
        st.large_net_5d = detail["large_net_5d"]
        st.mid_net_5d = detail["mid_net_5d"]


# --------------------------------------------------------------------------- #
# 市场宽度与统计
# --------------------------------------------------------------------------- #

def compute_breadth(stocks: list[StockFlow]) -> tuple[MarketBreadth, MarketStats]:
    """由全市场个股计算涨跌家数与资金流统计。"""
    up = down = flat = 0
    limit_up = limit_down = 0
    main_in_n = main_out_n = 0
    total_amount = 0.0
    total_main_net = 0.0
    for s in stocks:
        chg = s.change_pct
        if chg > 1e-9:
            up += 1
        elif chg < -1e-9:
            down += 1
        else:
            flat += 1
        if chg >= 9.8:
            limit_up += 1
        elif chg <= -9.8:
            limit_down += 1
        total_amount += s.amount
        if s.main_net > 0:
            main_in_n += 1
        elif s.main_net < 0:
            main_out_n += 1
        total_main_net += s.main_net
    breadth = MarketBreadth(
        up=up, down=down, flat=flat, total=len(stocks),
        limit_up=limit_up, limit_down=limit_down,
    )
    stats = MarketStats(
        total_amount=total_amount,
        total_main_net=total_main_net,
        main_in_stocks=main_in_n,
        main_out_stocks=main_out_n,
    )
    return breadth, stats
