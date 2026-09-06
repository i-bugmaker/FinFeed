# -*- coding: utf-8 -*-
"""全市场资金流与板块轮动监控大屏 —— A 股交易时段判定。

## 为什么需要采样门控

通达信在**收盘后 / 午间休市 / 非交易日**返回的是静止快照：主力净额为当日累计值，
多轮采样数值恒定。若不加区分地写入轮动历史，会产生四类问题：

1. **趋势失真**：轮动趋势折线被大量重复点拉平成直线，丢失「资金轮入/轮出」信息；
2. **热力图无效**：横轴被无信息量的休市时点占据，颜色梯度失去对比意义；
3. **样本被挤出**：``HISTORY_LEN`` 是固定长度环形缓冲，重复点会把真实盘口样本淘汰；
4. **异常检测误报**：z-score 基线被重复点压低标准差，微小波动即被判为异常。

因此**板块轮动趋势与板块资金轮动热力图**的采样统计只在交易时段内进行；
非交易时段这两个视图定格于最近一个交易时点，其余面板（榜单、信号、异动）
仍照常刷新最新快照。

## 日历口径

- 交易日：周一至周五；
- 交易时段：``09:15-11:30``（含集合竞价）与 ``13:00-15:00``，端点闭区间。

节假日未内置精确日历。休市日行情同样静止，本模块按非交易时段处理，
属安全降级——只影响「是否采样」，不影响快照刷新与接口可用性。
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from finfeed.utils.time_utils import now_bj

# 连续竞价时段（含集合竞价），闭区间：((时, 分, 秒), (时, 分, 秒))
SESSIONS: tuple[tuple[tuple[int, int, int], tuple[int, int, int]], ...] = (
    ((9, 15, 0), (11, 30, 0)),   # 早盘
    ((13, 0, 0), (15, 0, 0)),    # 午盘
)

_SESSION_SECS = tuple(
    (s[0] * 3600 + s[1] * 60 + s[2], e[0] * 3600 + e[1] * 60 + e[2])
    for s, e in SESSIONS
)

# 时段相位
PHASE_HOLIDAY = "holiday"        # 非交易日（周末）
PHASE_PRE_OPEN = "pre_open"      # 开盘前
PHASE_MORNING = "morning"        # 早盘交易中
PHASE_LUNCH = "lunch"            # 午间休市
PHASE_AFTERNOON = "afternoon"    # 午盘交易中
PHASE_CLOSED = "closed"          # 已收盘

PHASE_LABEL = {
    PHASE_HOLIDAY: "非交易日",
    PHASE_PRE_OPEN: "未开盘",
    PHASE_MORNING: "早盘交易中",
    PHASE_LUNCH: "午间休市",
    PHASE_AFTERNOON: "午盘交易中",
    PHASE_CLOSED: "已收盘",
}


def _sec_of_day(dt: datetime) -> int:
    return dt.hour * 3600 + dt.minute * 60 + dt.second


def is_trading_day(dt: datetime | None = None) -> bool:
    """是否为交易日（周一至周五；节假日精确日历未内置）。"""
    dt = dt or now_bj()
    return dt.weekday() < 5


def is_trading_time(dt: datetime | None = None) -> bool:
    """是否处于交易时段（09:15-11:30 / 13:00-15:00）。"""
    dt = dt or now_bj()
    if not is_trading_day(dt):
        return False
    sec = _sec_of_day(dt)
    return any(start <= sec <= end for start, end in _SESSION_SECS)


def session_phase(dt: datetime | None = None) -> str:
    """返回当前所属时段相位（见 ``PHASE_*`` 常量）。"""
    dt = dt or now_bj()
    if not is_trading_day(dt):
        return PHASE_HOLIDAY
    sec = _sec_of_day(dt)
    # before_any 区分「首个时段之前=未开盘」与「时段之间的间隙=午间休市」
    before_any = True
    for start, end in _SESSION_SECS:
        if sec < start:
            return PHASE_PRE_OPEN if before_any else PHASE_LUNCH
        before_any = False
        if sec <= end:
            return PHASE_MORNING if start < 12 * 3600 else PHASE_AFTERNOON
    return PHASE_CLOSED


def next_open(now: datetime | None = None) -> str:
    """下一交易时段起点，返回 ``HH:MM``；当日无后续时段返回空串。"""
    now = now or now_bj()
    if not is_trading_day(now):
        return ""
    sec = _sec_of_day(now)
    for start, end in _SESSION_SECS:
        if sec < start:
            return f"{start // 3600:02d}:{start % 3600 // 60:02d}"
    return ""


def session_state(dt: datetime | None = None) -> dict[str, Any]:
    """聚合交易时段状态，供日志 / API / 前端消费。

    返回：
        in_session    是否处于交易时段（决定是否采样轮动历史）
        phase         相位（``PHASE_*``）
        label         中文标签，如「午间休市」
        next_open     下一时段起点 ``HH:MM``，无则空串
        trading_day   是否交易日
        now           判定所用时间 ``YYYY-MM-DD HH:MM:SS``
    """
    dt = dt or now_bj()
    phase = session_phase(dt)
    return {
        "in_session": phase in (PHASE_MORNING, PHASE_AFTERNOON),
        "phase": phase,
        "label": PHASE_LABEL.get(phase, ""),
        "next_open": next_open(dt),
        "trading_day": is_trading_day(dt),
        "now": dt.strftime("%Y-%m-%d %H:%M:%S"),
    }
