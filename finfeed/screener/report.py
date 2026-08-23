#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""选股结果报告生成：Markdown（可读 + 方法论 + 选股逻辑）与 JSON。"""

from __future__ import annotations

import json
import os
from typing import Any

from .config import ScreenerConfig
from .models import ScreenerResult


def _tier_label(tier: str) -> str:
    return {
        "strong": "入选候选",
        "watch": "关注",
        "observe": "观察",
        "none": "不入选",
    }.get(tier, tier)


def render_markdown(
    result: ScreenerResult,
    cfg: ScreenerConfig,
    top_n: int = 40,
) -> str:
    """渲染完整 Markdown 报告。"""
    s = result.scores
    strong = [x for x in s if x.tier == "strong"]
    shown = s[:top_n]

    L: list[str] = []
    L.append("# FinFeed 选股评分报告")
    L.append("")
    L.append(f"- 生成时间：{result.generated_at}")
    L.append(f"- 数据源：{result.data_source}")
    kind_label = {"realtime": "盘中实时", "trade_date": "交易日收盘定格", "local": "本地时间兜底"}.get(
        result.as_of_kind, result.as_of_kind)
    L.append(f"- 行情快照时间：{result.snapshot_time or '—'}（{kind_label}）")
    if result.fallback_chain and len(result.fallback_chain) > 1:
        L.append(f"- 数据回退链：{' → '.join(result.fallback_chain)}")
    L.append(f"- 数据覆盖率：{result.coverage:.1%}")
    L.append(f"- 覆盖样本：全市场 {result.universe_size} 只 → 通过过滤 {result.screened_size} 只 → 实际评分 {result.scored_size} 只")
    L.append(f"- 技术面富化：{'已启用' if result.technical_enabled else '未启用（质量维度回退振幅代理）'}")
    L.append(f"- 入选候选（Strong）：{len(strong)} 只")
    L.append("")

    # 方法论
    L.append(cfg.explain())
    L.append("")

    # 评分结果表
    L.append(f"## 评分结果 Top {len(shown)}")
    L.append("")
    L.append("| 排名 | 代码 | 名称 | 价格 | 涨跌幅% | PE(TTM) | 综合分 | 资金 | 动量 | 估值 | 量价 | 质量 | 情绪 | 评级 |")
    L.append("|------|------|------|------|---------|---------|--------|------|------|------|------|------|------|------|")
    for i, x in enumerate(shown, 1):
        L.append(
            f"| {i} | {x.code} | {x.name} | {x.price:.2f} | {x.change_pct:+.2f} | "
            f"{x.pe_ttm:.1f} | **{x.total_score:.1f}** | {x.capital_score:.0f} | "
            f"{x.momentum_score:.0f} | {x.valuation_score:.0f} | {x.liquidity_score:.0f} | "
            f"{x.quality_score:.0f} | {x.sentiment_score:.0f} | {_tier_label(x.tier)} |"
        )
    L.append("")

    # 入选候选明细
    L.append("## 入选候选（Strong）选股逻辑")
    L.append("")
    if not strong:
        L.append("本轮无满足综合分与护栏要求的入选候选。可放宽阈值、或结合行业/事件进一步研究。")
    else:
        for i, x in enumerate(strong, 1):
            extra = []
            if x.realized_vol_ann is not None:
                extra.append(f"年化波动{x.realized_vol_ann:.0f}%")
            if x.ma_align:
                extra.append("均线多头(价>MA20>MA60)")
            if x.drawdown_from_high is not None:
                extra.append(f"距高点{x.drawdown_from_high:.0f}%")
            L.append(f"### {i}. {x.code} {x.name}（综合 {x.total_score:.1f}）")
            L.append(
                f"- 价格 {x.price:.2f}｜涨跌幅 {x.change_pct:+.2f}%｜PE(TTM) {x.pe_ttm:.1f}｜"
                f"振幅 {x.amplitude:.2f}%"
            )
            L.append(
                f"- 维度分：资金 {x.capital_score:.0f}｜动量 {x.momentum_score:.0f}｜"
                f"估值 {x.valuation_score:.0f}｜量价 {x.liquidity_score:.0f}｜质量 {x.quality_score:.0f}"
            )
            if extra:
                L.append("- 技术面：" + "；".join(extra))
            L.append(f"- **选股逻辑**：{x.rationale}")
            L.append("")

    # 风险提示
    L.append("## 风险提示")
    L.append("")
    L.append("1. 本模型基于历史市场规律（动量、价值、流动性、主力资金）进行系统化量化筛选，"
             "用于缩小研究范围，**不构成任何投资建议**。")
    L.append("2. 因子权重与阈值为经验设定，历史表现不代表未来收益；不同市场环境下需动态校准。")
    L.append("3. 数据来自 easy-tdx 通达信行情，存在时效性与完整性限制；实盘前请以券商终端复核。")
    L.append("4. 评分高不代表无风险，请结合基本面、仓位管理与止损纪律使用。")
    L.append("")
    return "\n".join(L)


def render_json(result: ScreenerResult) -> dict[str, Any]:
    """渲染 JSON（机器可读）。"""
    return result.to_dict()


def write_report(
    result: ScreenerResult,
    cfg: ScreenerConfig,
    md_path: str | None = None,
    json_path: str | None = None,
    top_n: int = 40,
) -> dict[str, str]:
    """写出报告文件，返回实际写出的路径字典。"""
    written: dict[str, str] = {}
    if md_path:
        os.makedirs(os.path.dirname(os.path.abspath(md_path)) or ".", exist_ok=True)
        with open(md_path, "w", encoding="utf-8") as fp:
            fp.write(render_markdown(result, cfg, top_n))
        written["markdown"] = md_path
    if json_path:
        os.makedirs(os.path.dirname(os.path.abspath(json_path)) or ".", exist_ok=True)
        with open(json_path, "w", encoding="utf-8") as fp:
            json.dump(render_json(result), fp, ensure_ascii=False, indent=2)
        written["json"] = json_path
    return written
