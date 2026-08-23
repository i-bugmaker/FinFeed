# -*- coding: utf-8 -*-
"""全市场资金流与板块轮动监控大屏 —— 统计异常检测引擎。

相对原 ``rotation.py`` 中「相邻两采样点排名跳变」的朴素信号，本引擎引入：

1. **统计基线**：基于历史采样窗口计算板块主力净占比的均值/标准差，
   用 z-score 衡量当前值偏离常态的程度（而非与上一秒机械比较）。
2. **自适应阈值**：板块需满足最小成交额/最小绝对主力净额门槛，过滤微盘噪声；
   概念板块与行业板块共用但按流动性门槛过滤。
3. **滞回去抖（hysteresis）**：异常需连续出现在时间窗口内才确认，消失后进入
   冷却期，避免大屏信号卡片每轮（每 ~10s）闪烁抖动。
4. **股票级异常**：个股主力净流入的横截面离群（z-score）、涨停但资金背离、
   尾盘突袭（5 分钟净额主导当日净额）等。
5. **概率型置信度**：由证据强度（z 分数）经 logistic 映射得到，替代原
   ``0.55 + 0.06*delta`` 的伪造公式，与信号强度单调相关。

本模块为纯 Python（仅依赖标准库 ``statistics``），不引入新第三方依赖；
easy-tdx / pandas 缺失时仍可正常导入与计算（只要传入纯数据对象）。
"""

from __future__ import annotations

import logging
import math
import os
import time
from dataclasses import dataclass, field
from typing import Iterable

from . import config
from .models import BoardFlow, MarketSnapshot, StockFlow
from .rotation import STATUS_ACCUMULATE, STATUS_DIVERGE, STATUS_STRONG, STATUS_WEAK

logger = logging.getLogger("finfeed.capital_dashboard.anomaly")

# --------------------------------------------------------------------------- #
# 可调参数（环境变量可覆盖，全部可选）
# --------------------------------------------------------------------------- #
ANOM_Z = float(os.environ.get("ANOM_Z", "2.5"))              # 板块 z-score 触发阈值
ANOM_STOCK_Z = float(os.environ.get("ANOM_STOCK_Z", "3.0"))  # 个股横截面 z 触发阈值
ANOM_MIN_AMOUNT = float(os.environ.get("ANOM_MIN_AMOUNT", "5e7"))   # 板块最小成交额(元)门槛
ANOM_MIN_MAIN_NET = float(os.environ.get("ANOM_MIN_MAIN_NET", "5e6"))  # 板块最小净门槛(元)
ANOM_PERSIST_SEC = float(os.environ.get("ANOM_PERSIST_SEC", "25"))    # 确认所需持续时长(s)
ANOM_COOLDOWN_SEC = float(os.environ.get("ANOM_COOLDOWN_SEC", "90"))  # 消失后冷却(s)
ANOM_SEV_Z = float(os.environ.get("ANOM_SEV_Z", "3.5"))     # 严重级别 z 门槛
ANOM_HISTORY_MIN = int(os.environ.get("ANOM_HISTORY_MIN", "5"))  # 最少历史点数才做统计

# 板块状态 -> 异常类型映射
_KIND_BY_STATUS = {
    STATUS_STRONG: "inflow_surge",
    STATUS_WEAK: "outflow_surge",
    STATUS_DIVERGE: "price_flow_divergence",
    STATUS_ACCUMULATE: "capital_accumulation",
}


# --------------------------------------------------------------------------- #
# 数据模型
# --------------------------------------------------------------------------- #

@dataclass
class BoardAnomaly:
    board_code: str = ""
    board_name: str = ""
    board_type: str = "HY"
    kind: str = ""            # inflow_surge / outflow_surge / price_flow_divergence / capital_accumulation
    kind_label: str = ""
    severity: str = "info"    # info / warn / critical
    z_score: float = 0.0
    magnitude: float = 0.0    # 主力净占比（%），正=流入
    main_net: float = 0.0
    confidence: float = 0.0   # 0~1 概率型置信度
    confirmed: bool = False   # 是否经过滞回确认


@dataclass
class StockAnomaly:
    code: str = ""
    name: str = ""
    kind: str = ""            # net_cross_spike / limit_up_divergence / limit_down_divergence / tail_raid
    kind_label: str = ""
    severity: str = "info"
    z_score: float = 0.0
    change_pct: float = 0.0
    main_net: float = 0.0
    main_net_5m: float = 0.0
    confidence: float = 0.0
    price: float = 0.0


@dataclass
class AnomalyReport:
    ts: str = ""
    ts_label: str = ""
    boards: list[BoardAnomaly] = field(default_factory=list)
    stocks: list[StockAnomaly] = field(default_factory=list)
    history_points: int = 0

    def to_dict(self) -> dict:
        import dataclasses
        return dataclasses.asdict(self)


# --------------------------------------------------------------------------- #
# 置信度 / 严重度映射（原则化，替代伪造公式）
# --------------------------------------------------------------------------- #

def _logistic_confidence(z_abs: float, threshold: float = ANOM_Z) -> float:
    """证据强度 -> 置信度：z 越大置信越高，单调、有界。

    公式：conf = 0.5 + 0.5 * tanh((|z| - threshold/2) / 2)，裁剪到 [0, 0.98]。
    """
    c = 0.5 + 0.5 * math.tanh((abs(z_abs) - threshold / 2.0) / 2.0)
    return round(min(0.98, max(0.0, c)), 2)


def _severity(z_abs: float) -> str:
    if z_abs >= ANOM_SEV_Z:
        return "critical"
    if z_abs >= ANOM_Z:
        return "warn"
    return "info"


_KIND_LABEL = {
    "inflow_surge": "资金涌入",
    "outflow_surge": "资金出逃",
    "price_flow_divergence": "价量背离",
    "capital_accumulation": "资金吸筹",
    "net_cross_spike": "主力净额异动",
    "limit_up_divergence": "涨停资金背离",
    "limit_down_divergence": "跌停资金背离",
    "tail_raid": "尾盘突袭",
}


# --------------------------------------------------------------------------- #
# 检测引擎（有状态：保存滞回/冷却状态）
# --------------------------------------------------------------------------- #

class AnomalyDetector:
    """资金流异常检测器（进程内单例，持滞回与冷却状态）。"""

    def __init__(self) -> None:
        # key=(scope, code) -> 最近一次观测到的时间戳列表
        self._seen: dict[tuple[str, str], list[float]] = {}
        # key -> 冷却到期时间戳
        self._cooldown: dict[tuple[str, str], float] = {}
        self._last_report: AnomalyReport | None = None

    # -- 板块统计异常 -------------------------------------------------------
    def detect_board_anomalies(
        self, current: MarketSnapshot, history: list[MarketSnapshot]
    ) -> list[BoardAnomaly]:
        if not current.boards:
            return []
        now = time.time()
        # 构建每板块的历史主力净占比序列
        series: dict[str, list[float]] = {}
        for snap in history:
            for b in snap.boards:
                series.setdefault(b.code, []).append(_main_net_ratio(b))
        out: list[BoardAnomaly] = []
        for b in current.boards:
            ratio = _main_net_ratio(b)
            seq = series.get(b.code, [])
            # 流动性门槛：过滤微盘噪声
            if b.amount < ANOM_MIN_AMOUNT or abs(b.main_net) < ANOM_MIN_MAIN_NET:
                continue
            mean = sum(seq) / len(seq) if seq else ratio
            std = _stdev(seq, mean) if len(seq) >= ANOM_HISTORY_MIN else 0.0
            z = (ratio - mean) / std if std > 1e-9 else 0.0
            # 状态驱动的异常类型
            kind = _KIND_BY_STATUS.get(_status_of(b), "")
            if not kind:
                # 中性板块且偏离不显著则不报
                if abs(z) < ANOM_Z:
                    continue
                kind = "inflow_surge" if z > 0 else "outflow_surge"
            if abs(z) < ANOM_Z and kind not in (STATUS_DIVERGE, STATUS_ACCUMULATE):
                continue
            key = ("board", b.code)
            confirmed = self._hysteresis(key, now, active=abs(z) >= ANOM_Z)
            if not confirmed:
                continue
            out.append(
                BoardAnomaly(
                    board_code=b.code,
                    board_name=b.name,
                    board_type=b.board_type,
                    kind=kind,
                    kind_label=_KIND_LABEL.get(kind, kind),
                    severity=_severity(abs(z)),
                    z_score=round(z, 2),
                    magnitude=round(ratio, 4),
                    main_net=b.main_net,
                    confidence=_logistic_confidence(abs(z)),
                    confirmed=True,
                )
            )
        # 清理：对不再出现的板块做冷却登记
        self._gc_cooldown([("board", b.code) for b in current.boards], now)
        return out

    # -- 个股横截面异常 -----------------------------------------------------
    def detect_stock_anomalies(self, current: MarketSnapshot) -> list[StockAnomaly]:
        stocks = [s for s in current.stocks if s.amount and s.amount > 1e6]
        now = time.time()
        # 横截面 z 需要足够样本；样本不足时跳过该统计项（规则型检测不受影响）
        vals = [s.main_net_5m for s in stocks if s.main_net_5m is not None]
        mean = sum(vals) / len(vals) if vals else 0.0
        std = _stdev(vals, mean) if len(vals) >= 30 else 0.0
        out: list[StockAnomaly] = []
        for s in stocks:
            kind = ""
            z = 0.0
            if std > 1e-6 and s.main_net_5m is not None:
                z = (s.main_net_5m - mean) / std
                if abs(z) >= ANOM_STOCK_Z:
                    kind = "net_cross_spike"
            # 规则型：涨停但主力净流出（背离）
            if s.change_pct >= 9.5 and s.main_net < 0:
                kind = "limit_up_divergence"
                z = max(z, 2.0)
            elif s.change_pct <= -9.5 and s.main_net > 0:
                kind = "limit_down_divergence"
                z = max(z, 2.0)
            # 规则型：尾盘突袭（5 分钟净额主导且为正）
            if (
                kind == ""
                and s.main_net > 0
                and s.main_net_5m is not None
                and abs(s.main_net) > 1e7
                and s.main_net_5m > 0.5 * abs(s.main_net)
            ):
                kind = "tail_raid"
                z = max(z, 2.2)
            if not kind:
                continue
            key = ("stock", s.code)
            confirmed = self._hysteresis(key, now, active=True)
            if not confirmed:
                continue
            out.append(
                StockAnomaly(
                    code=s.code,
                    name=s.name,
                    kind=kind,
                    kind_label=_KIND_LABEL.get(kind, kind),
                    severity=_severity(abs(z)) if abs(z) >= ANOM_SEV_Z else "warn",
                    z_score=round(z, 2),
                    change_pct=s.change_pct,
                    main_net=s.main_net,
                    main_net_5m=s.main_net_5m or 0.0,
                    confidence=_logistic_confidence(abs(z), ANOM_STOCK_Z),
                    price=s.price,
                )
            )
        self._gc_cooldown([("stock", s.code) for s in stocks], now)
        return out

    # -- 滞回/冷却核心 ------------------------------------------------------
    def _hysteresis(self, key: tuple[str, str], now: float, active: bool) -> bool:
        """返回 True 表示该异常应被确认/上报。

        - 持续观测：最近一次观测若在 PERSIST 窗口内，累计出现多次即确认。
        - 冷却：刚消失的异常在 COOLDOWN 内不重新触发，避免闪烁。
        """
        if key in self._cooldown and now < self._cooldown[key]:
            self._seen.pop(key, None)
            return False
        stamps = self._seen.setdefault(key, [])
        stamps.append(now)
        # 仅保留窗口内观测
        stamps[:] = [t for t in stamps if now - t <= max(ANOM_PERSIST_SEC, 60)]
        if active and len(stamps) >= 2 and (now - stamps[0]) >= min(ANOM_PERSIST_SEC, 20):
            return True
        if active and len(stamps) >= 3:  # 连续 3 轮（即便窗口略短）亦确认
            return True
        if not active:
            # 消失 -> 进入冷却
            self._cooldown[key] = now + ANOM_COOLDOWN_SEC
            self._seen.pop(key, None)
        return False

    def _gc_cooldown(self, live_keys: list[tuple[str, str]], now: float) -> None:
        for k in list(self._cooldown.keys()):
            if k not in {lk for lk in live_keys} and now >= self._cooldown[k]:
                self._cooldown.pop(k, None)

    # -- 入口 --------------------------------------------------------------
    def detect(
        self, current: MarketSnapshot, history: list[MarketSnapshot]
    ) -> AnomalyReport:
        boards = self.detect_board_anomalies(current, history)
        stocks = self.detect_stock_anomalies(current)
        rep = AnomalyReport(
            ts=current.ts,
            ts_label=current.ts_label,
            boards=sorted(boards, key=lambda a: (-_sev_rank(a.severity), -abs(a.z_score))),
            stocks=sorted(stocks, key=lambda a: (-_sev_rank(a.severity), -abs(a.z_score))),
            history_points=len(history),
        )
        self._last_report = rep
        return rep


# --------------------------------------------------------------------------- #
# 工具
# --------------------------------------------------------------------------- #

def _main_net_ratio(b: BoardFlow) -> float:
    if b.amount <= 0:
        return 0.0
    return b.main_net / b.amount * 100.0


def _status_of(b: BoardFlow) -> str:
    # 与 rotation.classify_status 保持一致（避免循环导入，内联阈值）
    up = b.change_pct > 0.05
    down = b.change_pct < -0.05
    inflow = b.main_net > 1e6
    outflow = b.main_net < -1e6
    if up and inflow:
        return STATUS_STRONG
    if down and outflow:
        return STATUS_WEAK
    if up and outflow:
        return STATUS_DIVERGE
    if down and inflow:
        return STATUS_ACCUMULATE
    return ""


def _stdev(seq: Iterable[float], mean: float) -> float:
    vals = list(seq)
    if len(vals) < 2:
        return 0.0
    var = sum((x - mean) ** 2 for x in vals) / (len(vals) - 1)
    return math.sqrt(var)


def _sev_rank(sev: str) -> int:
    return {"critical": 3, "warn": 2, "info": 1}.get(sev, 0)


# 模块级单例（进程内共享滞回状态）
detector = AnomalyDetector()
