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

import contextlib
import logging
import threading
import time
from datetime import date
from typing import Optional

from easy_tdx import BoardType, Category, MacClient, SortOrder, SortType
from easy_tdx.codec.bitmap import PresetField
from finfeed.capital_dashboard.tdx import call_lock, ensure_alive, get_client

from . import config
from .models import BoardMeta, StockMeta, TickChart, TickPoint

logger = logging.getLogger("finfeed.sector_minute.collector")

_null_cm = contextlib.nullcontext  # 私有连接路径：无需全局串行锁

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
    shared = client is None
    if shared:
        client = get_client()
    # 共享连接须串行（easy-tdx MacClient 非线程安全）；显式传入的私有连接不经全局锁
    cm = call_lock() if shared else _null_cm()
    with cm:
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
    strict: bool = False,
) -> Optional[TickChart]:
    """获取单个标的单日分时图。

    Args:
        market: 市场代码（板块恒为 1；个股按代码推断 0/1）。
        code:   标的代码（板块 88xxxx / 个股 6 位代码）。
        query_date: 查询日期；``None`` 表示「今天」（服务器返回最近一个交易日的分时，
                   周末/节假日时即为上一交易日）。
        client: 显式传入的 MacClient。为 ``None`` 时使用全局进程级单例
                （受 ``call_lock`` 串行保护，与资金流大屏共享连接）；
                传入线程私有连接时**不经全局锁直接执行**——供并发批量
                ``fetch_tick_charts_batch`` 使用（MacClient 非线程安全，
                每个并发 worker 必须持有独立连接实例）。
        strict: True 时抓取异常向上抛出（供调用方区分「网络/服务异常」与
               「服务器正常应答但无分时点」）；默认 False 时异常打日志并返回 None。

    通过原始 0x122D 命令取得完整分时（含昨收/开高低收/名称元数据）；
    返回 ``TickChart``；失败或无数据返回 None。
    """
    from easy_tdx.mac.commands.symbol_tick_chart import SymbolTickChartCmd

    shared = client is None
    if shared:
        ensure_alive()
        client = get_client()
    try:
        # 共享连接须串行执行（easy-tdx MacClient 非线程安全）；私有连接无需全局锁
        if shared:
            with call_lock():
                chart = client._execute(SymbolTickChartCmd(int(market), str(code), query_date))
        else:
            chart = client._execute(SymbolTickChartCmd(int(market), str(code), query_date))
    except Exception as exc:  # noqa: BLE001
        if strict:
            raise
        logger.warning("采集失败[tick_%s_%s_%s]: %s", market, code, query_date or "today", exc)
        chart = None
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
# 并发批量分时抓取（多标的对比响应提速）
# --------------------------------------------------------------------------- #

def _clone_client() -> MacClient:
    """克隆一个 TDX 连接（复用已测速的最佳主机，避免重复全量测速）。

    easy-tdx 的 MacClient **非线程安全**：一个实例同一时刻只能被单线程使用。
    并发批量抓取时每个 worker 必须持有独立连接实例；连接参数从进程级单例
    （capital_dashboard.tdx）的当前连接克隆，主机已测速无需重复探测。
    """
    from easy_tdx import MacClient as _MC

    base = get_client()  # 确保进程级单例已建立（含 best-host 测速结果）
    host = getattr(base, "_host", None)
    port = getattr(base, "_port", None)
    cli = _MC(
        host=host,
        port=port,
        timeout=config.TDX_TIMEOUT if hasattr(config, "TDX_TIMEOUT") else None,
        auto_reconnect=True,
    )
    cli.connect()
    return cli


def fetch_tick_charts_batch(
    targets: list[tuple[int, str]],
    query_date: Optional[date] = None,
    workers: int = 3,
    sleep_between: float = 0.0,
) -> tuple[list[Optional[TickChart]], dict[int, Exception]]:
    """并发批量抓取多个标的分时（结果顺序与 targets 一致）。

    Args:
        targets: ``(market, code)`` 列表。
        query_date: 查询日期（None = 今天，语义同 ``fetch_tick_chart``）。
        workers: 并发连接数。TDX 单请求本身毫秒级，真正的耗时来自 TCP
                 往返 + 服务器处理；3~4 条独立连接即可把 N 标的耗时从
                 ``N * (RTT + sleep)`` 压到约 ``N/workers * RTT``。
        sleep_between: 单 worker 相邻请求间隔（秒）；默认 0 不等待。
                       历史场景若担心风控可传小值，如 0.05。

    Returns:
        ``(charts, errors)``：charts 与 targets 等长（成功为 TickChart，
        正常应答但无分时点/失败为 None）；errors 为 ``{下标: 异常}``，
        仅含**网络/协议级异常**（供调用方区分「瞬时失败待重试」与
        「服务器正常应答无数据 → 记负缓存」，对齐历史日期抓取语义）。
        实时主刷新可忽略 errors。

    线程模型：线程池内每个 worker 各持一条独立克隆连接，互不共享实例，
    规避 easy-tdx 非线程安全限制；与全局单例（call_lock 串行）完全解耦。
    """
    if not targets:
        return [], {}
    n = max(1, min(workers, len(targets)))
    results: list[Optional[TickChart]] = [None] * len(targets)
    errors: dict[int, Exception] = {}
    _err_lock = threading.Lock()
    # 每 worker 一条连接：worker 与下标分片绑定，线程内串行请求
    slices: list[list[int]] = [[] for _ in range(n)]
    for i in range(len(targets)):
        slices[i % n].append(i)

    def run_worker(conn: MacClient, idxs: list[int]) -> None:
        for j, idx in enumerate(idxs):
            mkt, code = targets[idx]
            try:
                ch = fetch_tick_chart(
                    mkt, code, query_date=query_date,
                    client=conn, strict=True,
                )
                results[idx] = ch
            except Exception as exc:  # noqa: BLE001  网络/协议异常（区别于正常无点）
                with _err_lock:
                    errors[idx] = exc
                logger.warning("并发分时抓取失败[%s:%s]: %s", mkt, code, exc)
                results[idx] = None
            if sleep_between > 0 and j < len(idxs) - 1:
                time.sleep(sleep_between)

    def worker_entry(idxs: list[int]) -> None:
        conn = None
        try:
            conn = _clone_client()
            run_worker(conn, idxs)
        except Exception as exc:  # noqa: BLE001  克隆失败降级：用全局串行锁兜底
            logger.warning("并发连接建立失败，降级串行: %s", exc)
            for idx in idxs:
                mkt, code = targets[idx]
                try:
                    results[idx] = fetch_tick_chart(
                        mkt, code, query_date=query_date, strict=True,
                    )
                except Exception as exc2:  # noqa: BLE001
                    with _err_lock:
                        errors[idx] = exc2
                    results[idx] = None
        finally:
            if conn is not None:
                try:
                    conn.close()
                except Exception:  # noqa: BLE001
                    pass

    threads = [
        threading.Thread(target=worker_entry, args=(slices[i],), daemon=True)
        for i in range(n) if slices[i]
    ]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    return results, errors


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


# --------------------------------------------------------------------------- #
# ETF 池
# --------------------------------------------------------------------------- #

def fetch_etf_pool(client: MacClient | None = None) -> list[StockMeta]:
    """获取全部场内 ETF（含代码/名称/现价/涨跌幅），失败返回空列表。

    走 MAC ``Category.ETF`` 全市场分类（约 1700+ 只），一次调用自动分页；
    涨跌幅由 close/pre_close 计算（协议无直接涨跌幅字段）。
    """
    ensure_alive()
    client = client or get_client()
    with call_lock():
        df = _safe(
            lambda: client.get_stock_quotes_list(
                Category.ETF,
                count=5000,
                sort_type=SortType.CODE,
                sort_order=SortOrder.ASC,
                fields=PresetField.BASIC,
            ),
            tag="etf_pool",
        )
    if df is None or len(df) == 0:
        return []
    out: list[StockMeta] = []
    for _, r in df.iterrows():
        code = str(r.get("code", "")).strip()
        if not code:
            continue
        price = float(r.get("close", 0.0) or 0.0)
        pre_close = float(r.get("pre_close", 0.0) or 0.0)
        out.append(
            StockMeta(
                market=int(r.get("market", 1) or 1),
                code=code,
                name=str(r.get("name", "")).strip(),
                price=round(price, 3),
                change_pct=_pct(price, pre_close),
            )
        )
    return out
