# -*- coding: utf-8 -*-
"""板块分时 —— 内存快照与后台刷新线程。

- ``SectorStore``：线程安全的进程内数据仓库，保存：
  * 订阅标的 ``subscriptions``（前端选择要对比的板块/个股）
  * 各标的分时图缓存 ``ticks``（key = kind:market:code）
  * 板块列表缓存 ``board_lists``（按板块类型）
  * 个股池缓存 ``stock_pool``
- ``RefreshWorker``：后台 daemon 线程，按交易时段规则周期拉取行情并更新缓存；
  暴露 ``refresh_now()`` 支持手动强制刷新。

刷新策略（对齐需求文档「后台自动刷新与时效控制」）：
- 交易时段（9:15-11:30 / 13:00-15:00）：按 ``REFRESH_INTERVAL`` 刷新；
- 午间休市 / 收盘后 / 非交易日：低频空转，仅冷启动时补一次数据；
- 串行刷新，相邻请求间隔 ``SLEEP_BETWEEN_REQUESTS`` 秒，规避集中请求风控。

线程模型：RefreshWorker 是唯一写者；所有读操作在锁内完成，保证一致性。
"""

from __future__ import annotations

import logging
import threading
import time
from datetime import datetime
from typing import Any, Optional

from . import config
from .collector import (
    fetch_board_list,
    fetch_stock_pool,
    fetch_tick_chart,
    stock_market,
)
from .models import BoardMeta, StockMeta, Subscription, TickChart, to_dict

logger = logging.getLogger("finfeed.sector_minute.store")


# --------------------------------------------------------------------------- #
# 交易日 / 交易时段判断（简化内置日历：周一~周五）
# --------------------------------------------------------------------------- #

def is_trading_day(now: Optional[datetime] = None) -> bool:
    """是否为工作日（周一~周五）。节假日精确日历暂不内置。"""
    now = now or datetime.now()
    return now.weekday() < 5


def is_trading_time(now: Optional[datetime] = None) -> bool:
    """是否处于连续竞价交易时段（含集合竞价 9:15 起）。"""
    now = now or datetime.now()
    if not is_trading_day(now):
        return False
    h, m = now.hour, now.minute
    sec = h * 3600 + m * 60 + now.second
    return (9 * 3600 + 15 * 60) <= sec <= (11 * 3600 + 30 * 60) or (
        13 * 3600
    ) <= sec <= (15 * 3600)


def _ts_label() -> str:
    return datetime.now().strftime("%H:%M:%S")


# --------------------------------------------------------------------------- #
# 快照仓库
# --------------------------------------------------------------------------- #

class SectorStore:
    """线程安全的内存数据仓库（板块分时）。"""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._subscriptions: list[Subscription] = []
        self._ticks: dict[str, TickChart] = {}
        self._board_lists: dict[str, list[BoardMeta]] = {}
        self._board_lists_ts: float = 0.0
        self._stock_pool: list[StockMeta] = []
        self._stock_pool_ts: float = 0.0
        self._last_refresh_ts: float = 0.0
        self._last_error: str = ""
        self._refresh_count: int = 0

    # -- 订阅 ---------------------------------------------------------------
    def set_subscriptions(self, items: list[dict]) -> list[Subscription]:
        """整体替换订阅列表（去重），返回规范化后的订阅。"""
        with self._lock:
            seen: set[str] = set()
            subs: list[Subscription] = []
            for it in items or []:
                kind = "stock" if it.get("kind") == "stock" else "board"
                market = int(it.get("market", 0))
                code = str(it.get("code", "")).strip()
                name = str(it.get("name", "")).strip()
                if not code:
                    continue
                if kind == "stock" and not market:
                    market = stock_market(code)
                sub = Subscription(
                    kind=kind,
                    market=market,
                    code=code,
                    name=name,
                    board_type=str(it.get("board_type", "") or ""),
                )
                if sub.key not in seen:
                    seen.add(sub.key)
                    subs.append(sub)
            # 截断至单屏上限
            if len(subs) > config.MAX_TARGETS:
                subs = subs[: config.MAX_TARGETS]
            self._subscriptions = subs
            return list(subs)

    def subscriptions(self) -> list[Subscription]:
        with self._lock:
            return list(self._subscriptions)

    # -- 写（RefreshWorker 调用） ------------------------------------------
    def update_tick(self, sub: Subscription, chart: Optional[TickChart]) -> None:
        with self._lock:
            if chart is None:
                self._ticks.pop(sub.key, None)
                return
            chart.kind = sub.kind
            chart.board_type = sub.board_type
            chart.name = sub.name or chart.name
            chart.ts = _ts_label()
            self._ticks[sub.key] = chart

    def set_board_list(self, board_type: str, boards: list[BoardMeta]) -> None:
        with self._lock:
            self._board_lists[board_type] = boards
            self._board_lists_ts = time.time()

    def set_stock_pool(self, stocks: list[StockMeta]) -> None:
        with self._lock:
            self._stock_pool = stocks
            self._stock_pool_ts = time.time()

    def mark_refreshed(self) -> None:
        with self._lock:
            self._last_refresh_ts = time.time()
            self._refresh_count += 1

    def set_error(self, msg: str) -> None:
        with self._lock:
            self._last_error = msg

    # -- 读 ----------------------------------------------------------------
    def get_ticks(self) -> list[TickChart]:
        with self._lock:
            subs = list(self._subscriptions)
        out: list[TickChart] = []
        with self._lock:
            for s in subs:
                ch = self._ticks.get(s.key)
                if ch is not None:
                    out.append(ch)
        return out

    def has_any_ticks(self) -> bool:
        with self._lock:
            return bool(self._ticks)

    def has_tick(self, sub: Subscription) -> bool:
        with self._lock:
            return sub.key in self._ticks

    def get_board_list(self, board_type: str) -> list[BoardMeta]:
        with self._lock:
            return list(self._board_lists.get(board_type, []))

    def board_list_fresh(self, board_type: str, ttl: int) -> bool:
        with self._lock:
            ts = self._board_lists_ts
        return bool(ts) and (time.time() - ts) < ttl

    def get_stock_pool(self) -> list[StockMeta]:
        with self._lock:
            return list(self._stock_pool)

    def stock_pool_fresh(self, ttl: int) -> bool:
        with self._lock:
            ts = self._stock_pool_ts
        return bool(ts) and (time.time() - ts) < ttl

    def health(self) -> dict[str, Any]:
        with self._lock:
            return {
                "status": "ok" if self._ticks else "init",
                "last_refresh_ts": self._last_refresh_ts,
                "last_error": self._last_error,
                "refresh_count": self._refresh_count,
                "subscriptions": len(self._subscriptions),
                "ticks": len(self._ticks),
                "interval": config.REFRESH_INTERVAL,
                "trading": is_trading_time(),
            }


# --------------------------------------------------------------------------- #
# 后台刷新线程
# --------------------------------------------------------------------------- #

class RefreshWorker(threading.Thread):
    """周期性采集板块/个股分时数据并写入快照仓库。"""

    def __init__(self, store: SectorStore) -> None:
        super().__init__(name="sector-minute-refresh", daemon=True)
        self.store = store
        self._stop_evt = threading.Event()
        self._manual_evt = threading.Event()
        self._done_lock = threading.Lock()
        self._done_evt: Optional[threading.Event] = None  # 本轮采集完成信号

    # -- 生命周期 ----------------------------------------------------------
    def stop(self) -> None:
        self._stop_evt.set()
        self._manual_evt.set()  # 唤醒可能阻塞的循环

    def refresh_now(self, timeout: float = 0.0) -> bool:
        """触发一轮采集。

        Args:
            timeout: >0 时同步等待该轮完成，返回是否在超时内完成；
                     0 时仅唤醒（异步触发），立即返回 True。
        """
        done = threading.Event()
        with self._done_lock:
            self._done_evt = done
        self._manual_evt.set()
        if timeout > 0:
            return done.wait(timeout)
        return True

    def _signal_done(self) -> None:
        """每轮采集结束后置位完成信号（若有等待者）。"""
        with self._done_lock:
            if self._done_evt is not None:
                self._done_evt.set()
                self._done_evt = None

    def run(self) -> None:
        logger.info(
            "板块分时后台刷新线程启动 interval=%ss", config.REFRESH_INTERVAL
        )
        while not self._stop_evt.is_set():
            try:
                self._collect_round()
            except Exception as exc:  # noqa: BLE001
                logger.error("板块分时刷新轮次异常: %s", exc)
                self.store.set_error(f"{type(exc).__name__}: {exc}")
            finally:
                self._signal_done()
            interval = (
                config.REFRESH_INTERVAL if is_trading_time() else config.IDLE_INTERVAL
            )
            self._manual_evt.clear()
            self._manual_evt.wait(timeout=interval)
        logger.info("板块分时后台刷新线程已停止")

    # -- 采集 --------------------------------------------------------------
    def _collect_round(self) -> None:
        trading = is_trading_time()

        # 1. 板块列表：交易时段按 TTL 刷新；非交易时段仅冷启动补一次
        for bt in ("hy", "hy2", "gn", "fg", "dq"):
            if trading or not self.store.board_list_fresh(
                bt, config.BOARD_LIST_TTL * 2
            ):
                boards = fetch_board_list(bt)
                if boards:
                    self.store.set_board_list(bt, boards)

        # 2. 分时：交易时段全量刷新；非交易时段补拉"尚无数据"的标的
        #    （首次勾选后有缓存，若整体跳过会导致后续新增板块/个股永远取不到分时）
        subs = self.store.subscriptions()
        targets: list[Subscription] = []
        if subs:
            targets = (
                list(subs) if trading else [s for s in subs if not self.store.has_tick(s)]
            )
        if targets:
            for i, sub in enumerate(targets):
                if self._stop_evt.is_set():
                    break
                chart = fetch_tick_chart(sub.market, sub.code)
                self.store.update_tick(sub, chart)
                # 错峰：相邻标的串行间隔，避免集中请求触发风控
                if i < len(targets) - 1:
                    time.sleep(config.SLEEP_BETWEEN_REQUESTS)
            self.store.mark_refreshed()
            logger.info(
                "板块分时刷新完成 标的=%d", len(targets),
            )

    def ensure_stock_pool(self) -> None:
        """按 TTL 刷新个股池（供个股搜索使用，仅首次/过期时触网）。"""
        if self.store.stock_pool_fresh(config.STOCK_POOL_TTL):
            return
        stocks = fetch_stock_pool()
        if stocks:
            self.store.set_stock_pool(stocks)
