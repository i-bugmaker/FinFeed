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
    fetch_etf_pool,
    fetch_stock_pool,
    fetch_tick_chart,
    stock_market,
)
from .models import BoardMeta, StockMeta, Subscription, TickChart

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
        self._etf_pool: list[StockMeta] = []
        self._etf_pool_ts: float = 0.0
        self._last_refresh_ts: float = 0.0
        self._last_error: str = ""
        self._refresh_count: int = 0
        self._fail_streak: int = 0  # 连续「整轮全部抓取失败」的轮次（供连接自愈/健康检查）
        # 历史日期分时缓存：date_str("YYYY-MM-DD") -> {sub_key -> TickChart}
        self._hist_ticks: dict[str, dict[str, TickChart]] = {}
        self._hist_order: list[str] = []       # LRU 顺序（尾部最新）
        self._hist_busy: set[str] = set()      # 正在后台抓取的日期（去重）
        # 历史日期抓取异常计数：(date_str, sub_key) -> 连续异常次数。
        # 与负缓存区分：异常在达到上限前不算「已就绪」，下次请求会重试。
        self._hist_fail: dict[tuple[str, str], int] = {}

    # -- 订阅 ---------------------------------------------------------------
    def set_subscriptions(self, items: list[dict]) -> list[Subscription]:
        """整体替换订阅列表（去重），返回规范化后的订阅。"""
        with self._lock:
            seen: set[str] = set()
            subs: list[Subscription] = []
            for it in items or []:
                kind = it.get("kind") if it.get("kind") in ("board", "stock", "index", "etf") else "board"
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
    def update_tick(self, sub: Subscription, chart: Optional[TickChart]) -> bool:
        """写入单标的分时缓存，返回是否成功更新。

        抓取失败（chart 为 None）时**保留旧缓存**（stale-while-revalidate）：
        瞬时网络抖动/超时不应清空已有分时，否则前端图表会闪回「加载中」，
        且用户无法区分「后端在失败」与「数据没变化」。
        """
        with self._lock:
            if chart is None:
                return False
            chart.kind = sub.kind
            chart.board_type = sub.board_type
            chart.name = sub.name or chart.name
            chart.ts = _ts_label()
            self._ticks[sub.key] = chart
            return True

    def get_tick(self, key: str) -> Optional[TickChart]:
        """按缓存 key 取分时（key 形如 board:hy:1:000883 / stock:1:600000）。"""
        with self._lock:
            return self._ticks.get(key)

    # -- 历史日期分时缓存（日期切换组件） -----------------------------------
    # 与实时缓存（_ticks，RefreshWorker 持续写今日数据）相互独立：
    # 历史日期为一次性静态快照，按 date_str 分桶缓存，LRU 淘汰。

    def _hist_touch(self, date_str: str) -> None:
        """LRU 触碰并把该日期移到队列尾部；超容量时淘汰最旧日期。"""
        with self._lock:
            if date_str in self._hist_order:
                self._hist_order.remove(date_str)
            self._hist_order.append(date_str)
            while len(self._hist_order) > config.MAX_HIST_DATES:
                old = self._hist_order.pop(0)
                self._hist_ticks.pop(old, None)
                self._hist_fail = {k: v for k, v in self._hist_fail.items() if k[0] != old}

    def hist_set(self, date_str: str, sub: Subscription, chart: Optional[TickChart]) -> None:
        """写入某历史日期的单标的分时（chart 为 None 时记录为缺失，避免重复触网）。"""
        with self._lock:
            bucket = self._hist_ticks.setdefault(date_str, {})
            if chart is None:
                bucket.setdefault(sub.key, None)
            else:
                chart.kind = sub.kind
                chart.board_type = sub.board_type
                chart.name = sub.name or chart.name
                chart.trade_date = date_str
                bucket[sub.key] = chart
            self._hist_touch(date_str)

    def hist_note_error(self, date_str: str, key: str) -> bool:
        """记录某历史日期某标的的一次抓取异常，返回是否已达重试上限。

        达到上限返回 True：调用方应写入负缓存（hist_set None）止损，
        避免对持续性坏标的无限重试；未达到则不写缓存，留给下次请求重试。
        """
        with self._lock:
            n = self._hist_fail.get((date_str, key), 0) + 1
            self._hist_fail[(date_str, key)] = n
            return n >= config.HIST_FETCH_MAX_TRIES

    def hist_clear_error(self, date_str: str, key: str) -> None:
        """标的抓取成功（含正常的无数据应答）后清除异常计数。"""
        with self._lock:
            self._hist_fail.pop((date_str, key), None)

    def hist_get(self, date_str: str, key: str) -> Optional[TickChart]:
        with self._lock:
            bucket = self._hist_ticks.get(date_str)
            ch = bucket.get(key) if bucket else None
            return ch if isinstance(ch, TickChart) else None

    def hist_has(self, date_str: str, key: str) -> bool:
        """该日期是否已记录过该标的（含明确无数据的缺失记录，避免重复触网）。"""
        with self._lock:
            bucket = self._hist_ticks.get(date_str)
            return bool(bucket) and key in bucket

    def hist_ticks(self, date_str: str) -> list[TickChart]:
        """按订阅顺序返回某历史日期的分时列表（未抓到的标的跳过）。"""
        with self._lock:
            subs = list(self._subscriptions)
            bucket = self._hist_ticks.get(date_str) or {}
        out: list[TickChart] = []
        with self._lock:
            for s in subs:
                ch = bucket.get(s.key)
                if isinstance(ch, TickChart):
                    out.append(ch)
        return out

    def hist_any_points(self, date_str: str) -> bool:
        """该历史日期是否已有任一标的分时点（用于判断是否交易日）。"""
        with self._lock:
            bucket = self._hist_ticks.get(date_str) or {}
            return any(isinstance(ch, TickChart) and bool(ch.points) for ch in bucket.values())

    def hist_all_ready(self, date_str: str, subs: Optional[list[Subscription]] = None) -> bool:
        """该历史日期的全部订阅标的是否都已抓到（含明确无数据/失败的缺失记录）。"""
        with self._lock:
            bucket = self._hist_ticks.get(date_str) or {}
            missing = [s for s in (subs or self._subscriptions) if s.key not in bucket]
        return not missing

    def hist_fetch_start(self, date_str: str) -> bool:
        """登记某历史日期开始后台抓取；返回 True 表示由调用方发起本轮抓取。"""
        with self._lock:
            if date_str in self._hist_busy:
                return False
            self._hist_busy.add(date_str)
            return True

    def hist_fetch_end(self, date_str: str) -> None:
        with self._lock:
            self._hist_busy.discard(date_str)

    def hist_cached_dates(self) -> list[str]:
        with self._lock:
            return list(self._hist_order)

    def set_board_list(self, board_type: str, boards: list[BoardMeta]) -> None:
        with self._lock:
            self._board_lists[board_type] = boards
            self._board_lists_ts = time.time()

    def set_stock_pool(self, stocks: list[StockMeta]) -> None:
        with self._lock:
            self._stock_pool = stocks
            self._stock_pool_ts = time.time()

    def set_etf_pool(self, etfs: list[StockMeta]) -> None:
        with self._lock:
            self._etf_pool = etfs
            self._etf_pool_ts = time.time()

    def mark_refreshed(self) -> None:
        with self._lock:
            self._last_refresh_ts = time.time()
            self._refresh_count += 1

    def note_round_result(self, success: bool) -> None:
        """记录一轮采集的成败，维护连续失败轮次计数（连接自愈 / 健康检查用）。"""
        with self._lock:
            self._fail_streak = 0 if success else self._fail_streak + 1

    def fail_streak(self) -> int:
        with self._lock:
            return self._fail_streak

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

    def get_etf_pool(self) -> list[StockMeta]:
        with self._lock:
            return list(self._etf_pool)

    def etf_pool_fresh(self, ttl: int) -> bool:
        with self._lock:
            ts = self._etf_pool_ts
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
                "server_date": datetime.now().strftime("%Y-%m-%d"),
                "hist_dates": list(self._hist_order),
                "fetch_fail_streak": self._fail_streak,
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
            ok = 0
            for i, sub in enumerate(targets):
                if self._stop_evt.is_set():
                    break
                chart = fetch_tick_chart(sub.market, sub.code)
                if self.store.update_tick(sub, chart):
                    ok += 1
                # 错峰：相邻标的串行间隔，避免集中请求触发风控
                if i < len(targets) - 1:
                    time.sleep(config.SLEEP_BETWEEN_REQUESTS)
            if ok:
                # 至少一个标的成功才推进刷新时间戳；全部失败时保持旧 ts，
                # 前端据此可感知后端未在刷新并自动触发兜底唤醒
                self.store.mark_refreshed()
                self.store.note_round_result(True)
                logger.info("板块分时刷新完成 标的=%d 成功=%d", len(targets), ok)
            else:
                self.store.note_round_result(False)
                logger.warning("板块分时本轮全部失败（%d 个标的），保留旧缓存", len(targets))
                if self.store.fail_streak() >= config.CONSECUTIVE_FAIL_RESET:
                    logger.warning(
                        "连续 %d 轮全部抓取失败，强制重建 TDX 连接",
                        config.CONSECUTIVE_FAIL_RESET,
                    )
                    from finfeed.capital_dashboard.tdx import ensure_alive

                    try:
                        ensure_alive()
                    except Exception:  # noqa: BLE001
                        pass
                    self.store.note_round_result(True)  # 重置失败计数，避免每轮重复重建

    def ensure_stock_pool(self) -> None:
        """按 TTL 刷新个股池（供个股搜索使用，仅首次/过期时触网）。"""
        if self.store.stock_pool_fresh(config.STOCK_POOL_TTL):
            return
        stocks = fetch_stock_pool()
        if stocks:
            self.store.set_stock_pool(stocks)

    def ensure_etf_pool(self) -> None:
        """按 TTL 刷新 ETF 池（供 ETF 搜索使用，仅首次/过期时触网）。"""
        if self.store.etf_pool_fresh(config.ETF_POOL_TTL):
            return
        etfs = fetch_etf_pool()
        if etfs:
            self.store.set_etf_pool(etfs)
