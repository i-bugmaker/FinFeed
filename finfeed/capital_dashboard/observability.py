# -*- coding: utf-8 -*-
"""全市场资金流与板块轮动监控大屏 —— 信号可观测性 / 命中率回验。

目标（P2-7）：把「信号是否真的有用」从主观判断变为可量化指标。

方法论说明（重要，避免误读为收益回测）：
- 本模块**不做**收益率/PnL 回测，仅做**方向跟随验证（follow-through）**——
  即信号触发后，在 ``HORIZON_ROUNDS`` 个采集轮次窗口内，目标板块/个股的价格
  是否沿信号预测方向继续移动。这是衡量信号「有效性」的轻量代理指标，用于校准
  P0-1 的置信度与告警阈值，而非承诺盈利。
- 仅追踪 z-score / 显著度达 ``MIN_Z`` 的信号，过滤噪声；同 (scope, code) 已有
  同向预测则不去重重复计入。
- 结果 best-effort 落盘到 ``logs/signal_tracker.json``，重启后保留历史统计。

所有外部依赖为零（仅标准库），采集线程与 HTTP 线程均通过锁保护。
"""

from __future__ import annotations

import json
import logging
import os
import threading
import time
from dataclasses import asdict, dataclass
from typing import Any, Optional

logger = logging.getLogger("finfeed.capital_dashboard.observability")

SIGNAL_DB = os.environ.get("CAPITAL_SIGNAL_DB", "").strip() or os.path.join(
    "logs", "signal_tracker.json"
)
# 验证窗口（采集轮次）：信号触发后最多观测 N 轮；窗口内方向延续即判为命中。
HORIZON_ROUNDS = int(os.environ.get("SIGNAL_HORIZON", "5"))
# 仅追踪显著信号（z-score 绝对值门槛），过滤统计噪声。
MIN_Z = float(os.environ.get("SIGNAL_MIN_Z", "2.0"))


# --------------------------------------------------------------------------- #
# 预测记录
# --------------------------------------------------------------------------- #

@dataclass
class Prediction:
    scope: str = ""            # board / stock
    code: str = ""
    name: str = ""
    kind: str = ""
    direction: int = 0         # +1 看多 / -1 看空 / 0 中性
    fired_ts: float = 0.0
    fired_round: int = 0
    fired_change: float = 0.0  # 触发时的涨跌幅 %
    fired_main_net: float = 0.0
    z_score: float = 0.0
    resolved: bool = False
    outcome: Optional[bool] = None   # True 命中 / False 未命中 / None 无法验证
    resolved_round: int = 0
    held_rounds: int = 0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


# 异常类型 -> 预测方向
_BOARD_DIR = {
    "inflow_surge": 1,          # 资金涌入 -> 看多延续
    "outflow_surge": -1,         # 资金出逃 -> 看空延续
    "capital_accumulation": 1,   # 资金吸筹 -> 看多
    # price_flow_divergence 视主力净占比符号决定方向（见 record_round）
}
_STOCK_DIR = {
    "net_cross_spike": 0,       # 由 main_net 符号决定
    "limit_up_divergence": -1,  # 涨停但主力净流出 -> 看空背离
    "limit_down_divergence": 1, # 跌停但主力净流入 -> 看多承接
    "tail_raid": 1,             # 尾盘突袭且主力为正 -> 看多
}


# --------------------------------------------------------------------------- #
# 追踪器（进程级单例）
# --------------------------------------------------------------------------- #

class SignalTracker:
    """信号命中率追踪器：记录预测 + 后续轮次跟随验证。"""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._open: dict[tuple[str, str], Prediction] = {}
        self._history: list[Prediction] = []
        self._round = 0
        self._load()

    # ------------------------------------------------------------------
    def _load(self) -> None:
        try:
            if not os.path.exists(SIGNAL_DB):
                return
            with open(SIGNAL_DB, "r", encoding="utf-8") as f:
                data = json.load(f)
            self._round = int(data.get("round", 0))
            for d in data.get("open", []):
                try:
                    self._open[(d["scope"], d["code"])] = Prediction(**d)
                except Exception:  # noqa: BLE001
                    pass
            for d in data.get("history", []):
                try:
                    self._history.append(Prediction(**d))
                except Exception:  # noqa: BLE001
                    pass
            logger.info("信号追踪已载入：open=%d history=%d", len(self._open), len(self._history))
        except Exception as exc:  # noqa: BLE001
            logger.warning("信号追踪载入失败（已忽略）: %s", exc)

    def _save(self) -> None:
        try:
            os.makedirs(os.path.dirname(SIGNAL_DB) or ".", exist_ok=True)
            data = {
                "round": self._round,
                "open": [p.to_dict() for p in self._open.values()],
                "history": [p.to_dict() for p in self._history[-500:]],
            }
            tmp = SIGNAL_DB + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False)
            os.replace(tmp, SIGNAL_DB)
        except Exception as exc:  # noqa: BLE001
            logger.warning("信号追踪落盘失败（已忽略）: %s", exc)

    # ------------------------------------------------------------------
    def record_round(self, snapshot, anomalies, rotation) -> None:
        """在每轮采集结束时调用：登记新预测 + 验证已有预测。

        - ``snapshot``   : MarketSnapshot
        - ``anomalies``  : AnomalyReport | None
        - ``rotation``   : RotationReport | None
        """
        with self._lock:
            self._round += 1
            r = self._round

            board_change = {b.code: b.change_pct for b in (snapshot.boards or [])}
            stock_change = {s.code: s.change_pct for s in (snapshot.stocks or [])}
            stock_main = {s.code: s.main_net for s in (snapshot.stocks or [])}

            # 1) 新预测登记
            new_preds: list[Prediction] = []
            for a in (anomalies.boards if anomalies else []):
                if abs(a.z_score) < MIN_Z:
                    continue
                if a.kind == "price_flow_divergence":
                    # 主力净占比为正(资金流入)却涨 -> 看空背离；为负却涨 -> 看多反常
                    direction = -1 if a.magnitude >= 0 else 1
                else:
                    direction = _BOARD_DIR.get(a.kind, 0)
                new_preds.append(Prediction(
                    scope="board", code=a.board_code, name=a.board_name, kind=a.kind,
                    direction=direction, fired_ts=time.time(), fired_round=r,
                    fired_change=board_change.get(a.board_code, 0.0),
                    fired_main_net=a.main_net, z_score=a.z_score,
                ))
            for a in (anomalies.stocks if anomalies else []):
                if abs(a.z_score) < MIN_Z:
                    continue
                direction = _STOCK_DIR.get(a.kind, 0)
                if direction == 0:  # net_cross_spike 由 main_net 符号决定
                    direction = 1 if (stock_main.get(a.code, 0.0) > 0) else -1
                new_preds.append(Prediction(
                    scope="stock", code=a.code, name=a.name, kind=a.kind,
                    direction=direction, fired_ts=time.time(), fired_round=r,
                    fired_change=stock_change.get(a.code, 0.0),
                    fired_main_net=stock_main.get(a.code, 0.0), z_score=a.z_score,
                ))
            # 轮动信号：rotate_in/accumulate 看多，rotate_out 看空，diverge 跳过（方向不明）
            for s in (rotation.signals if rotation else []):
                direction = {"rotate_in": 1, "accumulate": 1, "rotate_out": -1}.get(s.signal, 0)
                if direction == 0:
                    continue
                new_preds.append(Prediction(
                    scope="board", code=s.board_code, name=s.board_name,
                    kind="rotation_" + s.signal, direction=direction,
                    fired_ts=time.time(), fired_round=r,
                    fired_change=board_change.get(s.board_code, 0.0),
                    fired_main_net=s.main_net, z_score=0.0,
                ))

            # 2) 验证已有预测（跟随延续）
            for key, pred in list(self._open.items()):
                cur = board_change.get(pred.code) if pred.scope == "board" else stock_change.get(pred.code)
                if cur is None:
                    pred.resolved = True
                    pred.outcome = None
                    pred.resolved_round = r
                    self._history.append(pred)
                    self._open.pop(key, None)
                    continue
                pred.held_rounds += 1
                drift = cur - pred.fired_change
                if pred.direction != 0:
                    followed = (drift >= 0) if pred.direction > 0 else (drift <= 0)
                else:
                    followed = abs(drift) <= 0.3  # 中性：基本不动算中
                if followed:
                    pred.resolved = True
                    pred.outcome = True
                    pred.resolved_round = r
                    self._history.append(pred)
                    self._open.pop(key, None)
                elif pred.held_rounds >= HORIZON_ROUNDS:
                    pred.resolved = True
                    pred.outcome = False  # 窗口内未延续 -> 未命中
                    pred.resolved_round = r
                    self._history.append(pred)
                    self._open.pop(key, None)

            # 3) 加入新预测（去重：同 key 已有则跳过）
            for p in new_preds:
                k = (p.scope, p.code)
                if k not in self._open:
                    self._open[k] = p

            # 周期性落盘（每 10 轮）
            if r % 10 == 0:
                self._save()

    # ------------------------------------------------------------------
    def summary(self) -> dict[str, Any]:
        with self._lock:
            resolved = [p for p in self._history if p.outcome is not None]
            hits = [p for p in resolved if p.outcome]
            misses = [p for p in resolved if not p.outcome]
            by_kind: dict[str, dict[str, int]] = {}
            for p in resolved:
                d = by_kind.setdefault(p.kind, {"fired": 0, "hits": 0})
                d["fired"] += 1
                d["hits"] += 1 if p.outcome else 0
            recent = [
                {
                    "scope": p.scope, "code": p.code, "name": p.name,
                    "kind": p.kind, "direction": p.direction,
                    "outcome": p.outcome, "held": p.held_rounds,
                    "z": round(p.z_score, 2),
                }
                for p in self._history[-12:]
            ]
            return {
                "total_fired": len(self._history) + len(self._open),
                "open": len(self._open),
                "resolved": len(resolved),
                "hits": len(hits),
                "misses": len(misses),
                "hit_rate": round(len(hits) / len(resolved), 3) if resolved else None,
                "by_kind": by_kind,
                "recent": recent,
            }


# 模块级单例（进程内共享追踪状态）
tracker = SignalTracker()
