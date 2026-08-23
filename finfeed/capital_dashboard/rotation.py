# -*- coding: utf-8 -*-
"""全市场资金流与板块轮动监控大屏 —— 板块轮动分析引擎。

核心逻辑：
1. **当日板块资金状态分类** —— 结合板块涨跌幅与主力净流入，将每个板块归入
   强势领涨 / 价升背离 / 资金吸筹 / 弱势领跌 / 中性 五类之一；
2. **轮动趋势追踪** —— 记录每个板块主力净占比(主力净流入/成交额)的时间序列，
   据此识别「资金轮入/轮出」方向；
3. **切换信号识别** —— 板块主力净流入排名相对上一采样点跳变超过阈值，且方向
   与当前资金流一致时发出 rotate_in / rotate_out 信号；
4. **轮动热力图与趋势序列** —— 供大屏 ECharts 渲染。
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Iterable

from . import config
from .models import (
    BoardFlow,
    MarketSnapshot,
    RotationReport,
    RotationSignal,
)

logger = logging.getLogger("finfeed.capital_dashboard.rotation")

# 资金状态标签
STATUS_STRONG = "strong"        # 强势领涨：涨 + 资金净流入
STATUS_WEAK = "weak"            # 弱势领跌：跌 + 资金净流出
STATUS_DIVERGE = "diverge"      # 价升背离：涨 + 资金净流出（警惕）
STATUS_ACCUMULATE = "accumulate"  # 资金吸筹：跌 + 资金净流入（关注）
STATUS_NEUTRAL = "neutral"      # 中性

STATUS_LABEL = {
    STATUS_STRONG: "强势领涨",
    STATUS_WEAK: "弱势领跌",
    STATUS_DIVERGE: "价升背离",
    STATUS_ACCUMULATE: "资金吸筹",
    STATUS_NEUTRAL: "中性",
}


def classify_status(change_pct: float, main_net: float) -> str:
    """按涨跌幅与主力净流入方向分类板块资金状态。"""
    up = change_pct > 0.05
    down = change_pct < -0.05
    inflow = main_net > 1e6          # 净流入阈值 100 万
    outflow = main_net < -1e6
    if up and inflow:
        return STATUS_STRONG
    if down and outflow:
        return STATUS_WEAK
    if up and outflow:
        return STATUS_DIVERGE
    if down and inflow:
        return STATUS_ACCUMULATE
    return STATUS_NEUTRAL


def main_net_ratio(board: BoardFlow) -> float:
    """板块主力净占比（%）：主力净流入 / 成交额。用于跨板块横向比较。"""
    if board.amount <= 0:
        return 0.0
    return board.main_net / board.amount * 100.0


def signal_confidence(delta_abs: int, main_net: float, board_amount: float) -> float:
    """轮动信号置信度（原则化，替换旧的 ``0.55 + 0.06*delta`` 伪造公式）。

    置信度由两类证据共同决定，且均与信号强度单调相关：
      - 排名跳变证据：``delta_abs`` 越大越可信（归一化到 8 档封顶）；
      - 资金强度证据：主力净占比（``main_net/board_amount``）越大越可信。
    结果裁剪到 [0, 0.98]。
    """
    rank_evidence = min(1.0, delta_abs / 8.0)
    mag = abs(main_net) / max(board_amount, 1.0) if board_amount > 0 else 0.0
    mag_evidence = min(1.0, mag * 20.0)  # 主力净占比约 5% 即达满分
    score = 0.4 + 0.6 * (0.5 * rank_evidence + 0.5 * mag_evidence)
    return round(min(0.98, max(0.0, score)), 2)


def _rank_map(boards: Iterable[BoardFlow]) -> dict[str, int]:
    """按主力净流入从大到小生成 {code: rank}（rank 从 1 开始）。"""
    ordered = sorted(boards, key=lambda b: b.main_net, reverse=True)
    return {b.code: i + 1 for i, b in enumerate(ordered)}


def analyze_rotation(
    current: MarketSnapshot,
    history: list[MarketSnapshot],
) -> RotationReport:
    """对最新快照执行轮动分析。

    Args:
        current: 最新快照。
        history: 历史快照列表（含 current 之前的历史，按时间升序）。
    """
    report = RotationReport(ts=current.ts)

    if not current.boards:
        return report

    # ---------- 1. 板块资金状态 ----------
    for b in current.boards:
        b.status = classify_status(b.change_pct, b.main_net)
        b.rank_delta = 0

    # ---------- 2. 排名变化（与上一采样点比较） ----------
    if history:
        prev = history[-1]
        if prev.boards:
            prev_rank = _rank_map(prev.boards)
            cur_rank = _rank_map(current.boards)
            for b in current.boards:
                b.rank_delta = prev_rank.get(b.code, 999) - cur_rank.get(b.code, 999)

    # ---------- 3. 轮动趋势序列 ----------
    focus = _focus_boards(current.boards)
    focus_codes = [b.code for b in focus]
    # 每个板块的（时间标签, 主力净占比）序列
    series_map: dict[str, list[tuple[str, float]]] = {c: [] for c in focus_codes}
    # 热力图：纵轴板块 x 横轴时间 -> 主力净占比
    heat_boards: list[str] = []
    heat_times: list[str] = []
    heat_values: list[list[float]] = []

    timeline = [s for s in history] + [current]
    for snap in timeline:
        if not snap.boards:
            continue
        heat_times.append(snap.ts_label)
        row: dict[str, float] = {}
        for b in snap.boards:
            if b.code in series_map:
                series_map[b.code].append((snap.ts_label, round(main_net_ratio(b), 4)))
            row[b.code] = main_net_ratio(b)
        # 热力图仅保留 focus 板块
        heat_boards = [b.code for b in focus]
        heat_values.append([round(row.get(c, 0.0), 4) for c in heat_boards])

    report.heatmap_boards = heat_boards
    report.heatmap_times = heat_times
    # heat_values 目前按时间行存储 -> 转置为 [板块][时间]
    report.heatmap_values = (
        [list(col) for col in zip(*heat_values)] if heat_values else []
    )
    report.trend_boards = focus_codes
    report.trend_series = [
        {
            "board": c,
            "times": [p[0] for p in series_map[c]],
            "values": [p[1] for p in series_map[c]],
        }
        for c in focus_codes
    ]
    # 回填 trend 到板块对象（供接口直接输出）
    for b in focus:
        b.trend = [p[1] for p in series_map.get(b.code, [])]

    # ---------- 4. 切换信号 ----------
    signals: list[RotationSignal] = []
    if history:
        prev = history[-1]
        if prev.boards:
            prev_rank = _rank_map(prev.boards)
            for b in current.boards:
                delta = b.rank_delta
                cur_rk = _rank_map(current.boards).get(b.code, 0)
                prev_rk = prev_rank.get(b.code, 0)
                if delta >= config.ROTATION_RANK_DELTA and b.main_net > 0:
                    sig = "rotate_in"
                    label = "资金轮入"
                    conf = signal_confidence(delta, b.main_net, b.amount)
                elif delta <= -config.ROTATION_RANK_DELTA and b.main_net < 0:
                    sig = "rotate_out"
                    label = "资金轮出"
                    conf = signal_confidence(abs(delta), b.main_net, b.amount)
                elif b.status == STATUS_DIVERGE:
                    sig = "diverge"
                    label = "价升背离"
                    conf = signal_confidence(0, b.main_net, b.amount)
                elif b.status == STATUS_ACCUMULATE:
                    sig = "accumulate"
                    label = "资金吸筹"
                    conf = signal_confidence(0, b.main_net, b.amount)
                else:
                    continue
                signals.append(
                    RotationSignal(
                        board_code=b.code,
                        board_name=b.name,
                        board_type=b.board_type,
                        signal=sig,
                        signal_label=label,
                        change_pct=b.change_pct,
                        main_net=b.main_net,
                        rank_delta=delta,
                        prev_rank=prev_rk,
                        cur_rank=cur_rk,
                        confidence=round(conf, 2),
                    )
                )
    report.signals = sorted(
        signals, key=lambda s: (-s.confidence, -abs(s.main_net))
    )[:12]

    # ---------- 5. 领涨/领跌板块 ----------
    hy = [b for b in current.boards if b.board_type == "HY"]
    report.leader = [
        {
            "code": b.code,
            "name": b.name,
            "change_pct": b.change_pct,
            "main_net": b.main_net,
            "status": b.status,
            "status_label": STATUS_LABEL.get(b.status, ""),
        }
        for b in sorted(
            hy, key=lambda x: (x.change_pct, x.main_net), reverse=True
        )[:6]
    ]
    report.laggard = [
        {
            "code": b.code,
            "name": b.name,
            "change_pct": b.change_pct,
            "main_net": b.main_net,
            "status": b.status,
            "status_label": STATUS_LABEL.get(b.status, ""),
        }
        for b in sorted(hy, key=lambda x: (x.change_pct, x.main_net))[:6]
    ]

    return report


def _focus_boards(boards: list[BoardFlow], n: int | None = None) -> list[BoardFlow]:
    """按资金活跃度（|主力净占比|）取关注板块。"""
    n = n or config.ROTATION_FOCUS_N
    return sorted(
        boards, key=lambda b: abs(main_net_ratio(b)), reverse=True
    )[:n]


def format_signal(sig: RotationSignal) -> str:
    """信号 → 一行文字（用于跑马灯/日志）。"""
    return (
        f"[{sig.signal_label}] {sig.board_name}({sig.board_code}) "
        f"涨跌 {sig.change_pct:+.2f}% 主力净额 {sig.main_net / 1e8:+.2f}亿 "
        f"排名 {sig.prev_rank}→{sig.cur_rank}"
    )
