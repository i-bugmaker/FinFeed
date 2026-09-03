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
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, dataclass, field
from datetime import datetime
from typing import Any, Optional

from . import config, persist
from .alerting import manager as _alert_manager
from .anomaly import AnomalyReport, detector
from .collector import (
    compute_breadth,
    fetch_all_stocks,
    fetch_board_rankings,
    fetch_indices,
    fetch_stock_detail,
)
from .models import BoardFlow, IndexQuote, MarketSnapshot
from .observability import tracker as _signal_tracker
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
    breadth: dict[str, int] = field(default_factory=dict)
    stats: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_full(cls, full: MarketSnapshot) -> "SnapshotLight":
        return cls(
            ts=full.ts,
            ts_label=full.ts_label,
            boards=[asdict(b) for b in full.boards],
            indices=[asdict(i) for i in full.indices],
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
        self._anomalies: Optional[AnomalyReport] = None
        self._last_refresh_ts: float = 0.0
        self._last_error: str = ""
        self._refresh_count: int = 0
        self._round_duration: float = 0.0
        self._last_success: bool = False

    # -- 写（RefreshWorker 调用） ------------------------------------------
    def update(
        self,
        snapshot: MarketSnapshot,
        rotation: Optional[RotationReport],
        anomalies: Optional[AnomalyReport] = None,
    ) -> None:
        with self._lock:
            self._current = snapshot
            light = SnapshotLight.from_full(snapshot)
            self._history.append(asdict(light))
            if len(self._history) > config.HISTORY_LEN:
                self._history = self._history[-config.HISTORY_LEN:]
            self._rotation = rotation
            self._anomalies = anomalies
            self._last_refresh_ts = time.time()
            self._refresh_count += 1
            # 时序落盘（best-effort，失败不影响主链路）
            try:
                persist.save_boards(snapshot)
            except Exception:  # noqa: BLE001
                pass

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

    def get_anomalies(self) -> Optional[AnomalyReport]:
        with self._lock:
            return self._anomalies

    def bootstrap_from_persist(self) -> None:
        """从落盘数据回填 current 与 history，使重启后大屏立即可见上一时段状态。"""
        try:
            snaps = persist.load_recent_snapshots(config.HISTORY_LEN)
            if not snaps:
                return
            for s in snaps:
                self._history.append(asdict(SnapshotLight.from_full(s)))
            if len(self._history) > config.HISTORY_LEN:
                self._history = self._history[-config.HISTORY_LEN:]
            with self._lock:
                self._current = snaps[-1]
                self._last_refresh_ts = time.time()
            logger.info("已从落盘数据回填 %d 轮历史快照", len(snaps))
        except Exception as exc:  # noqa: BLE001
            logger.warning("持久化回填失败（已降级）: %s", exc)

    def health(self) -> dict[str, Any]:
        with self._lock:
            anom = self._anomalies
            return {
                "status": "ok" if self._current is not None else "init",
                "last_refresh_ts": self._last_refresh_ts,
                "last_error": self._last_error,
                "refresh_count": self._refresh_count,
                "history_len": len(self._history),
                "interval": config.REFRESH_INTERVAL,
                "round_duration": round(self._round_duration, 2),
                "last_success": self._last_success,
                "anomaly_boards": len(anom.boards) if anom else 0,
                "anomaly_stocks": len(anom.stocks) if anom else 0,
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
                self.store._last_success = False
                try:
                    _alert_manager.record_collection_failure(
                        "capital_refresh", f"{type(exc).__name__}: {exc}"
                    )
                except Exception:  # noqa: BLE001
                    pass
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

        # 3. 指数
        indices = fetch_indices()

        # 4. 市场宽度与统计
        breadth, stats = compute_breadth(stocks)

        snapshot = MarketSnapshot(
            ts=now.strftime("%Y-%m-%d %H:%M:%S"),
            ts_label=now.strftime("%H:%M:%S"),
            indices=indices,
            stocks=stocks,
            boards=boards,
            breadth=breadth,
            stats=stats,
        )

        # 5. 个股资金流详情（当日主力/散户流入流出）已解耦至 DetailEnricher 后台线程，
        #    不再阻塞主刷新循环；主循环只负责全市场快速快照与发布。

        # 6. 轮动分析
        history = _history_as_snapshots(self.store)
        rotation = analyze_rotation(snapshot, history)

        # 7. 统计异常检测（z-score / 自适应阈值 / 滞回 / 个股级）
        anomalies = detector.detect(snapshot, history)

        # 8. 告警评估与分发（规则 + 异常 → 日志/Webhook/WS，含自选股定向）
        try:
            _alert_manager.evaluate(snapshot, anomalies)
        except Exception as exc:  # noqa: BLE001
            logger.warning("告警评估异常（已忽略）: %s", exc)

        # 9. 信号可观测性：登记预测 + 跟随验证命中率（P2-7，best-effort）
        try:
            _signal_tracker.record_round(snapshot, anomalies, rotation)
        except Exception as exc:  # noqa: BLE001
            logger.warning("信号命中率追踪异常（已忽略）: %s", exc)

        self.store.update(snapshot, rotation, anomalies)
        self.store._round_duration = time.time() - t0
        self.store._last_success = True
        logger.info(
            "快照完成 ts=%s 股票=%d 板块=%d 异常(板%d/股%d) 耗时=%.1fs",
            snapshot.ts_label, len(stocks), len(boards),
            len(anomalies.boards), len(anomalies.stocks), time.time() - t0,
        )


class DetailEnricher(threading.Thread):
    """个股资金流详情（四档）后台补全线程。

    原实现在主刷新循环内串行补全 40 只个股的 ``get_capital_flow``，会阻塞主循环；
    此处将其解耦到独立后台线程，并借助进程级 ``call_lock`` 并行调用 TDX 客户端，
    既不再拖慢主刷新/发布节奏，又显著加快四档数据覆盖。补全结果就地写回内存快照的
    个股对象，下一轮读取即可见。
    """

    def __init__(self, store: SnapshotStore, max_workers: int = 4) -> None:
        super().__init__(name="capital-detail-enricher", daemon=True)
        self.store = store
        self._stop_evt = threading.Event()
        self._exec = ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix="cap-detail")

    def stop(self) -> None:
        self._stop_evt.set()
        try:
            self._exec.shutdown(wait=False)
        except Exception:  # noqa: BLE001
            pass

    def run(self) -> None:
        logger.info("个股详情补全线程启动，every=%ss", config.DETAIL_REFRESH_EVERY)
        while not self._stop_evt.is_set():
            self._stop_evt.wait(timeout=config.DETAIL_REFRESH_EVERY)
            if self._stop_evt.is_set():
                break
            try:
                self._enrich_once()
            except Exception as exc:  # noqa: BLE001
                logger.warning("个股详情补全异常（已忽略）: %s", exc)

    def _enrich_once(self) -> None:
        snap = self.store.get_snapshot()
        if snap is None or not snap.stocks:
            return
        top_in = sorted(snap.stocks, key=lambda s: s.main_net, reverse=True)[: config.DETAIL_TOP_N]
        top_out = sorted(snap.stocks, key=lambda s: s.main_net)[: config.DETAIL_TOP_N]
        todo = [s for s in (top_in + top_out) if s.main_in is None]
        if not todo:
            return
        list(self._exec.map(self._enrich_one, todo))

    @staticmethod
    def _enrich_one(s) -> None:
        try:
            detail = fetch_stock_detail(s.market, s.code)
        except Exception:  # noqa: BLE001
            return
        if not detail:
            return
        s.main_in = detail.get("main_in")
        s.main_out = detail.get("main_out")
        s.retail_in = detail.get("retail_in")
        s.retail_out = detail.get("retail_out")
        s.large_net_5d = detail.get("large_net_5d")
        s.mid_net_5d = detail.get("mid_net_5d")


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
            )
        )
    return out
