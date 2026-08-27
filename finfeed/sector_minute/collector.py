# -*- coding: utf-8 -*-
"""板块分时 —— 数据采集层。

基于 easy-tdx MAC 协议实现板块列表 / 分时数据抓取：

- 板块列表        : ``get_board_list(BoardType.X)`` 行业/概念/风格/地区等
- 分时图          : ``get_tick_chart(market, code)`` 单日 240 点分时
- 个股池          : 复用 capital_dashboard 的全市场 A 股资金流快照

TDX 连接复用 ``finfeed.capital_dashboard.tdx`` 的进程级单例，
避免与资金流大屏各自建立连接、共享全局频率限制。
"""

from __future__ import annotations

import logging
from datetime import date
from typing import Optional

from easy_tdx import BoardType, MacClient
from finfeed.capital_dashboard.tdx import ensure_alive, get_client

from .models import BoardMeta, StockMeta, TickChart, TickPoint

logger = logging.getLogger("finfeed.sector_minute.collector")

# 板块类型 → (BoardType 枚举, 中文名)
BOARD_TYPES: dict[str, tuple[BoardType, str]] = {
    "hy": (BoardType.HY, "行业"),
    "hy2": (BoardType.HY2, "二级行业"),
    "gn": (BoardType.GN, "概念"),
    "fg": (BoardType.FG, "风格"),
    "dq": (BoardType.DQ, "地区"),
}

# 常用指数池（宽基 / 风格），market 遵循 TDX：1=沪 / 0=深。
# 指数与板块/个股同走 0x122D 分时命令，可查询任意交易日的 240 点分时。
# 注：北证50（899050）经实测服务器不返回分时，故不纳入。
INDEX_LIST: list[dict] = [
    {"market": 1, "code": "000001", "name": "上证指数"},
    {"market": 0, "code": "399001", "name": "深证成指"},
    {"market": 0, "code": "399006", "name": "创业板指"},
    {"market": 1, "code": "000688", "name": "科创50"},
    {"market": 1, "code": "000300", "name": "沪深300"},
    {"market": 1, "code": "000016", "name": "上证50"},
    {"market": 1, "code": "000905", "name": "中证500"},
    {"market": 1, "code": "000852", "name": "中证1000"},
    {"market": 0, "code": "399330", "name": "深证100"},
]


def _safe(fn, default=None, tag: str = ""):
    """执行采集函数，异常打日志并返回默认值（单点故障不拖垮整轮采集）。"""
    try:
        return fn()
    except Exception as exc:  # noqa: BLE001
        logger.warning("采集失败[%s]: %s", tag or getattr(fn, "__name__", "?"), exc)
        return default


def stock_market(code: str) -> int:
    """由个股代码推断市场：沪市=1 / 深市=0（6/9/5 开头为沪，其余为深）。"""
    code = str(code).strip().zfill(6)
    return 1 if code.startswith(("6", "9", "5", "7")) else 0


def _pct(price: float, pre_close: float) -> float:
    if pre_close <= 0:
        return 0.0
    return round((price - pre_close) / pre_close * 100.0, 2)


# --------------------------------------------------------------------------- #
# 板块列表
# --------------------------------------------------------------------------- #

def fetch_board_list(board_type: str, client: MacClient | None = None) -> list[BoardMeta]:
    """获取指定类型板块列表（含实时涨跌幅）。

    失败返回空列表。
    """
    pair = BOARD_TYPES.get(board_type)
    if pair is None:
        return []
    ensure_alive()
    client = client or get_client()
    df = _safe(
        lambda: client.get_board_list(pair[0], count=10000),
        tag=f"board_list_{board_type}",
    )
    if df is None or len(df) == 0:
        return []
    out: list[BoardMeta] = []
    for _, r in df.iterrows():
        price = float(r.get("price", 0.0) or 0.0)
        pre_close = float(r.get("pre_close", 0.0) or 0.0)
        out.append(
            BoardMeta(
                market=int(r.get("market", 1) or 1),
                code=str(r.get("code", "")).strip(),
                name=str(r.get("name", "")).strip(),
                board_type=board_type,
                price=round(price, 2),
                pre_close=round(pre_close, 2),
                rise_pct=_pct(price, pre_close),
            )
        )
    return out


# --------------------------------------------------------------------------- #
# 分时图
# --------------------------------------------------------------------------- #

def fetch_tick_chart(
    market: int,
    code: str,
    query_date: Optional[date] = None,
    client: MacClient | None = None,
) -> Optional[TickChart]:
    """获取单个标的单日分时图。

    Args:
        market: 市场代码（板块恒为 1；个股按代码推断 0/1）。
        code:   标的代码（板块 88xxxx / 个股 6 位代码）。
        query_date: 查询日期；``None`` 表示「今天」（服务器返回最近一个交易日的分时，
                   周末/节假日时即为上一交易日）。

    通过原始 0x122D 命令取得完整分时（含昨收/开高低收/名称元数据）；
    返回 ``TickChart``；失败或无数据返回 None。
    """
    from easy_tdx.mac.commands.symbol_tick_chart import SymbolTickChartCmd

    ensure_alive()
    client = client or get_client()
    chart = _safe(
        lambda: client._execute(SymbolTickChartCmd(int(market), str(code), query_date)),
        tag=f"tick_{market}_{code}_{query_date or 'today'}",
    )
    if chart is None or not getattr(chart, "charts", None):
        return None

    points: list[TickPoint] = []
    for tick in chart.charts:
        points.append(
            TickPoint(
                time=tick.time.strftime("%H:%M:%S"),
                price=round(float(tick.price), 3),
                avg=round(float(tick.avg), 3),
                vol=int(tick.vol or 0),
            )
        )
    if not points:
        return None

    close = float(chart.close or points[-1].price)
    pre_close = float(chart.pre_close or 0.0)
    if pre_close <= 0:
        pre_close = points[0].price
    return TickChart(
        kind="board",
        market=int(market),
        code=str(code).strip(),
        name=str(chart.name or "").strip(),
        board_type="",
        trade_date=query_date.isoformat() if query_date is not None else "",
        pre_close=round(pre_close, 3),
        open=round(float(chart.open or points[0].price), 3),
        high=round(float(chart.high or close), 3),
        low=round(float(chart.low or close), 3),
        close=round(close, 3),
        change_pct=_pct(close, pre_close),
        change_amt=round(close - pre_close, 3),
        points=points,
    )


# --------------------------------------------------------------------------- #
# 个股池
# --------------------------------------------------------------------------- #

def fetch_stock_pool(client: MacClient | None = None) -> list[StockMeta]:
    """获取沪深两市全部 A 股（含代码/名称/现价/涨跌幅）。

    复用资金流大屏的全市场采集（一次请求全量），失败返回空列表。
    """
    from finfeed.capital_dashboard.collector import fetch_all_stocks

    ensure_alive()
    stocks = _safe(lambda: fetch_all_stocks(client=client), tag="stock_pool")
    if not stocks:
        return []
    out: list[StockMeta] = []
    for s in stocks:
        out.append(
            StockMeta(
                market=int(s.market),
                code=str(s.code),
                name=str(s.name),
                price=round(float(s.price), 2),
                change_pct=round(float(s.change_pct), 2),
            )
        )
    return out
