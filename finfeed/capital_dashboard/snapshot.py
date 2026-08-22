# -*- coding: utf-8 -*-
"""全市场资金流与板块轮动监控大屏 —— 内存快照与后台刷新线程。

- ``SnapshotStore``：线程安全的进程内数据仓库，保存：
  * 最新完整快照 ``current``（含全市场个股，供榜单 API 实时排序）
  * 精简历史快照 ``history``（仅板块/指数/宽度，供轮动趋势与热力图）
  * 轮动分析结果缓存 ``rotation``
- ``RefreshWorker``：后台 daemon 线程，按 ``REFRESH_INTERVAL`` 周期轮询
  TDX 服务器，实现「定时轮询」实时刷新；暴露 ``refresh_now()`` 支持手动触发。

线程模型：RefreshWorker 是唯一写者；所有读操作在锁内完成，保证一致性。
"""

from __future__ import annotations

import logging
import threading
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime
from typing import Any, Optional

from . import config
from .collector import (
    compute_breadth,
    enrich_top_stocks,
    fetch_all_stocks,
    fetch_board_rankings,
    fetch_indices,
    fetch_unusual,
)
from .models import BoardFlow, IndexQuote, MarketSnapshot, UnusualEvent
from .rotation import RotationReport, analyze_rotation

logger = logging.getLogger("finfeed.capital_dashboard.snapshot")


# --------------------------------------------------------------------------- #
# 轻量历史快照（仅保留轮动分析所需字段，控制内存）
# --------------------------------------------------------------------------- #

@dataclass
class SnapshotLight:
    ts: str = ""
    ts_label: str = ""
    boards: list[BoardFlow] = field(default_factory=list)
    indices: list[IndexQuote] = field(default_factory=list)
    unusual: list[UnusualEvent] = field(default_factory=list)
    breadth: dict[str, int] = field(default_factory=dict)
    stats: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_full(cls, full: MarketSnapshot) -> "SnapshotLight":
        return cls(
            ts=full.ts,
            ts_label=full.ts_label,
            boards=[asdict(b) for b in full.boards],
            indices=[asdict(i) for i in full.indices],
            unusual=[asdict(u) for u in full.unusual],
            breadth=asdict(full.breadth),
            stats=asdict(full.stats),
        )


# --------------------------------------------------------------------------- #
# 快照仓库
# --------------------------------------------------------------------------- #

class SnapshotStore:
    """线程安全的内存数据仓库。"""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._current: Optional[MarketSnapshot] = None
        self._history: list[dict] = []          # SnapshotLight dict 列表（时间升序）
        self._rotation: Optional[RotationReport] = None
        self._last_refresh_ts: float = 0.0
        self._last_error: str = ""
        self._refresh_count: int = 0

    # -- 写（RefreshWorker 调用） ------------------------------------------
    def update(
        self,
        snapshot: MarketSnapshot,
        rotation: Optional[RotationReport],
    ) -> None:
        with self._lock:
            self._current = snapshot
            light = SnapshotLight.from_full(snapshot)
            self._history.append(asdict(light))
            if len(self._history) > config.HISTORY_LEN:
                self._history = self._history[-config.HISTORY_LEN:]
            self._rotation = rotation
            self._last_refresh_ts = time.time()
            self._refresh_count += 1

    def set_error(self, msg: str) -> None:
        with self._lock:
            self._last_error = msg

    # -- 读 ----------------------------------------------------------------
    def get_snapshot(self) -> Optional[MarketSnapshot]:
        with self._lock:
            return self._current

    def get_history(self) -> list[dict]:
        with self._lock:
            return list(self._history)

    def get_rotation(self) -> Optional[RotationReport]:
        with self._lock:
            return self._rotation

    def health(self) -> dict[str, Any]:
        with self._lock:
            return {
                "status": "ok" if self._current is not None else "init",
                "last_refresh_ts": self._last_refresh_ts,
                "last_error": self._last_error,
                "refresh_count": self._refresh_count,
                "history_len": len(self._history),
                "interval": config.REFRESH_INTERVAL,
            }


# --------------------------------------------------------------------------- #
# 后台刷新线程
# --------------------------------------------------------------------------- #

class RefreshWorker(threading.Thread):
    """周期性采集 TDX 数据并写入快照仓库。"""

    def __init__(self, store: SnapshotStore) -> None:
        super().__init__(name="capital-dashboard-refresh", daemon=True)
        self.store = store
        self._stop_evt = threading.Event()
        self._manual_evt = threading.Event()
        self._last_detail_ts = 0.0

    # -- 生命周期 ----------------------------------------------------------
    def stop(self) -> None:
        self._stop_evt.set()
        self._manual_evt.set()  # 唤醒可能阻塞的循环

    def refresh_now(self) -> None:
        """手动触发一轮采集（供 API 调用）。"""
        self._manual_evt.set()

    def run(self) -> None:
        logger.info("后台刷新线程启动，interval=%ss", config.REFRESH_INTERVAL)
        while not self._stop_evt.is_set():
            try:
                self._collect_round()
            except Exception as exc:  # noqa: BLE001
                logger.error("刷新轮次异常: %s", exc)
                self.store.set_error(f"{type(exc).__name__}: {exc}")
            # 等待下一轮（可被手动触发提前唤醒）
            self._manual_evt.clear()
            self._manual_evt.wait(timeout=config.REFRESH_INTERVAL)
        logger.info("后台刷新线程已停止")

    # -- 采集 --------------------------------------------------------------
    def _collect_round(self) -> None:
        t0 = time.time()
        now = datetime.now()

        # 1. 全市场个股资金流（一次请求全量，1~2s）
        stocks = fetch_all_stocks()
        if not stocks:
            raise RuntimeError("全市场个股资金流采集为空，可能已收盘或连接异常")

        # 2. 板块排行（行业 + 概念）
        board_map = fetch_board_rankings()
        boards: list[BoardFlow] = []
        boards.extend(board_map.get("HY", []))
        boards.extend(board_map.get("GN", []))

        # 3. 指数与异动
        indices = fetch_indices()
        unusual = fetch_unusual()

        # 4. 市场宽度与统计
        breadth, stats = compute_breadth(stocks)

        snapshot = MarketSnapshot(
            ts=now.strftime("%Y-%m-%d %H:%M:%S"),
            ts_label=now.strftime("%H:%M:%S"),
            indices=indices,
            stocks=stocks,
            boards=boards,
            unusual=unusual,
            breadth=breadth,
            stats=stats,
        )

        # 5. 低频补全个股资金流详情（当日主力/散户流入流出）
        if time.time() - self._last_detail_ts >= config.DETAIL_REFRESH_EVERY:
            top_in = sorted(
                stocks, key=lambda s: s.main_net, reverse=True
            )[: config.DETAIL_TOP_N]
            top_out = sorted(stocks, key=lambda s: s.main_net)[: config.DETAIL_TOP_N]
            enrich_top_stocks(top_in + top_out, top_n=config.DETAIL_TOP_N)
            self._last_detail_ts = time.time()

        # 6. 轮动分析
        rotation = analyze_rotation(snapshot, _history_as_snapshots(self.store))

        self.store.update(snapshot, rotation)
        logger.info(
            "快照完成 ts=%s 股票=%d 板块=%d 耗时=%.1fs",
            snapshot.ts_label, len(stocks), len(boards), time.time() - t0,
        )


def _history_as_snapshots(store: SnapshotStore) -> list[MarketSnapshot]:
    """将轻量历史快照还原为 MarketSnapshot（仅含轮动分析所需字段）。"""
    out: list[MarketSnapshot] = []
    for h in store.get_history():
        light = SnapshotLight(**h)
        out.append(
            MarketSnapshot(
                ts=light.ts,
                ts_label=light.ts_label,
                indices=light.indices,
                boards=[BoardFlow(**b) for b in light.boards],
                unusual=light.unusual,
            )
        )
    return out
