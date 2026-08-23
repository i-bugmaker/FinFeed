# -*- coding: utf-8 -*-
"""全市场资金流与板块轮动监控大屏 —— 告警子系统。

补齐原模块「只在大屏显示信号卡片、无主动推送」的缺陷，并**复用项目既有设施**
而非另起炉灶：

- **采集失败告警**：对接 ``finfeed.market.alerting.FailureAlertManager``（含冷却 /
  Webhook / WS 回调），替换原 ``_safe`` 静默记日志。
- **信号 / 异常 → 主动推送**：对接 ``finfeed.market.ws_feed`` 的 ``alert`` 通道，
  让已存在的行情 WebSocket 客户端也能收到资金流告警。
- **规则引擎**：基于环境变量的可配置阈值（板块主力净额、个股 5 分钟净额），
  并自动把 P0-1 的统计异常转为告警。
- **订阅定向**：复用 ``finfeed.alerts.subscription`` 自选股，命中自选股的告警升级标记。
- **分级 / 冷却 / 去重**：severity + 同签名冷却窗口，避免告警风暴。

所有外部依赖均惰性导入并 try/except 兜底，任一设施缺失都不影响资金流主链路。
"""

from __future__ import annotations

import logging
import os
import time
from collections import deque
from dataclasses import asdict, dataclass, field
from typing import Any, Callable, Optional

logger = logging.getLogger("finfeed.capital_dashboard.alerting")

# --------------------------------------------------------------------------- #
# 可调阈值（环境变量可覆盖）
# --------------------------------------------------------------------------- #
ALERT_BOARD_MAIN_NET = float(os.environ.get("ALERT_BOARD_MAIN_NET", "0"))   # 板块主力净额阈值(元)，0=关闭
ALERT_STOCK_NET_5M = float(os.environ.get("ALERT_STOCK_NET_5M", "0"))       # 个股5分钟净额阈值(元)，0=关闭
ALERT_COOLDOWN = float(os.environ.get("ALERT_COOLDOWN", "300"))             # 同签名冷却(s)
ALERT_WEBHOOK = os.environ.get("CAPITAL_ALERT_WEBHOOK", "").strip()

SEV_RANK = {"critical": 3, "warn": 2, "info": 1}


# --------------------------------------------------------------------------- #
# 数据模型
# --------------------------------------------------------------------------- #

@dataclass
class AlertRecord:
    ts: float = 0.0
    time: str = ""
    source: str = ""        # rotation_signal / anomaly_board / anomaly_stock / collect_fail
    kind: str = ""
    severity: str = "info"
    title: str = ""
    detail: str = ""
    watched: bool = False   # 是否命中自选股

    def to_dict(self) -> dict:
        return asdict(self)

    @property
    def signature(self) -> str:
        return f"{self.source}:{self.kind}"


# --------------------------------------------------------------------------- #
# 通知器
# --------------------------------------------------------------------------- #

class _LogNotifier:
    name = "log"

    def notify(self, rec: AlertRecord) -> None:
        try:
            logger.warning(
                "[资金流告警] %s/%s %s :: %s", rec.severity, rec.source, rec.title, rec.detail
            )
        except Exception:  # noqa: BLE001
            pass


class _WebhookNotifier:
    def __init__(self, url: str, timeout: float = 5.0):
        self.url = url
        self.timeout = timeout
        self.name = "webhook"

    def notify(self, rec: AlertRecord) -> None:
        try:
            import json
            import urllib.request

            data = json.dumps(rec.to_dict(), ensure_ascii=False).encode("utf-8")
            req = urllib.request.Request(
                self.url, data=data,
                headers={"Content-Type": "application/json"}, method="POST",
            )
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:  # noqa: S310
                if resp.status >= 400:
                    logger.warning("资金流告警 Webhook 返回非 2xx: %s", resp.status)
        except Exception as e:  # noqa: BLE001
            logger.warning("资金流告警 Webhook 推送失败（已忽略）: %s", e)


# --------------------------------------------------------------------------- #
# 管理器
# --------------------------------------------------------------------------- #

class CapitalAlertManager:
    """资金流告警管理器（进程级单例）。"""

    def __init__(self) -> None:
        self._cooldown_until: dict[str, float] = {}
        self._recent: deque = deque(maxlen=200)
        self._notifiers: list = [_LogNotifier()]
        if ALERT_WEBHOOK:
            self._notifiers.append(_WebhookNotifier(ALERT_WEBHOOK))
        # 实时推送钩子（如 ws_feed.service.push_alert）；惰性设置
        self.on_alert_callback: Optional[Callable[[dict], None]] = None
        # 采集失败计数（对接 market.alerting，避免重复实现）
        self._market_alerting = self._lazy_market_alerting()

    # ------------------------------------------------------------------
    @staticmethod
    def _lazy_market_alerting():
        try:
            from finfeed.market import alerting as ma
            return ma.manager
        except Exception:  # noqa: BLE001
            return None

    # ------------------------------------------------------------------
    def record_collection_failure(self, task: str, error: str) -> None:
        """采集失败：优先走 market.alerting（冷却/Webhook/WS），否则仅记日志。"""
        if self._market_alerting is not None:
            try:
                self._market_alerting.record_failure(task, error, kind="exception")
                return
            except Exception:  # noqa: BLE001
                pass
        logger.warning("[采集失败] %s: %s", task, error)

    # ------------------------------------------------------------------
    def evaluate(self, snapshot, anomalies) -> list[AlertRecord]:
        """对一轮快照 + 异常报告评估规则，生成并分发告警。"""
        now = time.time()
        stamp = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(now))
        out: list[AlertRecord] = []

        # 1) 板块主力净额阈值规则
        if ALERT_BOARD_MAIN_NET > 0:
            for b in snapshot.boards:
                if abs(b.main_net) >= ALERT_BOARD_MAIN_NET:
                    out.append(AlertRecord(
                        ts=now, time=stamp, source="rule_board_net",
                        kind="board_net_surge" if b.main_net > 0 else "board_net_out",
                        severity="warn", title=f"板块 {b.name} 主力净额越阈",
                        detail=f"主力净额 {b.main_net/1e8:+.2f}亿 / 涨跌 {b.change_pct:+.2f}%",
                    ))

        # 2) 个股 5 分钟净额阈值规则
        if ALERT_STOCK_NET_5M > 0:
            for s in snapshot.stocks:
                if s.main_net_5m is not None and abs(s.main_net_5m) >= ALERT_STOCK_NET_5M:
                    out.append(AlertRecord(
                        ts=now, time=stamp, source="rule_stock_5m",
                        kind="stock_5m_surge" if s.main_net_5m > 0 else "stock_5m_out",
                        severity="warn", title=f"{s.name}({s.code}) 5分钟主力异动",
                        detail=f"5分钟净额 {s.main_net_5m/1e8:+.2f}亿 / 涨跌 {s.change_pct:+.2f}%",
                        watched=self._is_watched(s.code),
                    ))

        # 3) 统计异常 -> 告警（含自选股升级）
        if anomalies is not None:
            for a in anomalies.boards:
                out.append(AlertRecord(
                    ts=now, time=stamp, source="anomaly_board", kind=a.kind,
                    severity=a.severity, title=f"板块异常 {a.board_name}",
                    detail=f"{a.kind_label} z={a.z_score} 净占比{a.magnitude:+.2f}% 置信{a.confidence}",
                ))
            for a in anomalies.stocks:
                out.append(AlertRecord(
                    ts=now, time=stamp, source="anomaly_stock", kind=a.kind,
                    severity=a.severity, title=f"个股异常 {a.name}({a.code})",
                    detail=f"{a.kind_label} z={a.z_score} 涨跌{a.change_pct:+.2f}%",
                    watched=self._is_watched(a.code),
                ))

        # 4) 冷却 + 分发
        dispatched: list[AlertRecord] = []
        for r in out:
            sig = r.signature
            if self._cooldown_until.get(sig, 0.0) > now:
                continue
            self._cooldown_until[sig] = now + ALERT_COOLDOWN
            self._recent.append(r)
            self._dispatch(r)
            dispatched.append(r)
        return dispatched

    # ------------------------------------------------------------------
    def get_recent(self, limit: int = 50) -> list[dict]:
        items = list(self._recent)
        items.reverse()
        return [r.to_dict() for r in items[: max(1, min(limit, 200))]]

    def get_config(self) -> dict:
        return {
            "board_main_net_threshold": ALERT_BOARD_MAIN_NET,
            "stock_net_5m_threshold": ALERT_STOCK_NET_5M,
            "cooldown_sec": ALERT_COOLDOWN,
            "webhook_enabled": bool(ALERT_WEBHOOK),
            "ws_push": self.on_alert_callback is not None,
            "market_alerting": self._market_alerting is not None,
        }

    # ------------------------------------------------------------------
    def _is_watched(self, code: str) -> bool:
        try:
            from finfeed.alerts import subscription as sub
            return bool(sub.is_stock_watched(code))
        except Exception:  # noqa: BLE001
            return False

    def _dispatch(self, rec: AlertRecord) -> None:
        for n in self._notifiers:
            try:
                n.notify(rec)
            except Exception:  # noqa: BLE001
                pass
        cb = self.on_alert_callback
        if cb is not None:
            try:
                cb(rec.to_dict())
            except Exception:  # noqa: BLE001
                pass


# 模块级单例
manager = CapitalAlertManager()


def wire_ws_push() -> None:
    """把资金流告警接到行情 WebSocket 的 alert 通道（惰性、幂等）。"""
    if manager.on_alert_callback is not None:
        return
    try:
        from finfeed.market import ws_feed
        manager.on_alert_callback = ws_feed.service.push_alert
        logger.info("资金流告警 → 行情 WebSocket alert 通道已挂载")
    except Exception as e:  # noqa: BLE001
        logger.warning("资金流告警挂载 WS 通道失败（已降级）: %s", e)
