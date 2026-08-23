#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""因子注册表（声明式元数据层）。

用途：
- 以配置驱动的方式声明五维模型下的全部因子（来源 / 归一化方式 / 权重引用），
  新增因子 = 注册表加一项 + config.params 加锚点，**无需改动评分执行代码**；
- 为 explain() / 前端方法论展示 / 未来回测框架提供统一元数据入口。

注意：本模块是元数据声明，不参与评分执行（执行走 factors.py 标量路径
与 vector.py 向量路径，两者读取同一 config.params）。
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class FactorSpec:
    """单个因子的声明式定义。"""

    key: str                    # 因子键（全局唯一）
    dim: str                    # 所属维度：capital / momentum / valuation / liquidity / quality
    label: str                  # 中文名
    source: str                 # 数据来源：quote=行情快照 / kline=K线 / fundamental=基本面快照
    normalize: str              # 归一化方式：sigmoid / bell / band / rule
    params_ref: str             # 锚点参数在 config.params[dim] 下的键
    weight_ref: str | None = None  # 子权重在 config.params[dim] 下的键（None=无子权重）
    desc: str = ""              # 说明

    def to_dict(self) -> dict:
        return {
            "key": self.key,
            "dim": self.dim,
            "label": self.label,
            "source": self.source,
            "normalize": self.normalize,
            "params_ref": self.params_ref,
            "weight_ref": self.weight_ref,
            "desc": self.desc,
        }


FACTORS: dict[str, FactorSpec] = {
    # ---- 资金面 ----
    "capital_today_ratio": FactorSpec(
        "capital_today_ratio", "capital", "今日主力净比", "quote", "sigmoid",
        "today_ratio_mid", "w_today", "主力资金当日净流入占比（%），越高越强",
    ),
    "capital_net5d_pct": FactorSpec(
        "capital_net5d_pct", "capital", "5日主力净流入占流通市值", "quote", "sigmoid",
        "net5d_pct_mid", "w_5d", "近 5 日主力净流入 / 流通市值（%），衡量资金持续性",
    ),
    # ---- 动量趋势 ----
    "momentum_20d": FactorSpec(
        "momentum_20d", "momentum", "20日动量", "quote", "sigmoid",
        "mom20_mid", "w_mom20", "20 日区间涨跌幅（%），>overheat 触发过热衰减（回测校准 35%）",
    ),
    "momentum_60d": FactorSpec(
        "momentum_60d", "momentum", "60日动量", "quote", "sigmoid",
        "mom60_mid", "w_mom60", "60 日区间涨跌幅（%）",
    ),
    "momentum_align": FactorSpec(
        "momentum_align", "momentum", "多周期动量有序度", "quote", "rule",
        "w_align", None, "5日≥20日≥60日≥0 每满足一项 +1/3，衡量趋势结构",
    ),
    "momentum_accel": FactorSpec(
        "momentum_accel", "momentum", "动量加速度", "quote", "sigmoid",
        "accel_mid", "w_accel", "20日动量 - 10日动量（时序因子），趋势加速>0 更优",
    ),
    # ---- 估值 ----
    "valuation_pe": FactorSpec(
        "valuation_pe", "valuation", "PE_TTM", "fundamental", "bell",
        "pe_mid", "w_pe", "市盈率 TTM 钟形，合理区约 8~36；亏损给惩罚分、缺失给中性分",
    ),
    # 注：股息率因子已从估值维度移除（共线性治理）——避免与 quality_dy 重复计分
    # ---- 量价活跃 ----
    "liquidity_amount": FactorSpec(
        "liquidity_amount", "liquidity", "成交额(log)", "quote", "band",
        "amount_log_lo", "w_amount", "log10 成交额线性带，衡量可交易性",
    ),
    "liquidity_turnover": FactorSpec(
        "liquidity_turnover", "liquidity", "换手率", "quote", "bell",
        "turnover_mid", "w_turnover", "换手率（%）钟形，活跃但不疯狂",
    ),
    # ---- 质量稳定 ----
    "quality_vol": FactorSpec(
        "quality_vol", "quality", "波动率(年化/振幅)", "kline", "bell",
        "vol_ann_mid", "w_vol", "年化已实现波动率（K线富化）优先，回退当日振幅",
    ),
    "quality_profit": FactorSpec(
        "quality_profit", "quality", "盈利为正", "fundamental", "rule",
        "w_profit", None, "EPS>0 计满分，亏损计 0",
    ),
    "quality_size": FactorSpec(
        "quality_size", "quality", "市值规模", "fundamental", "bell",
        "size_log_mid", "w_size", "log10 总市值钟形，规避壳/妖股与超大盘极端",
    ),
    "quality_dy": FactorSpec(
        "quality_dy", "quality", "持续分红", "fundamental", "bell",
        "dy_mid", "w_dy", "股息率钟形，持续分红代表经营稳健",
    ),
    # ---- 情绪/事件（easy-tdx 快照源）----
    "sentiment_limitup": FactorSpec(
        "sentiment_limitup", "sentiment", "年内涨停天数", "quote", "bell",
        "limitup_mid", "w_limitup", "涨停基因：年内涨停次数钟形（峰值约 6 次），过高=妖股风险",
    ),
    "sentiment_streak": FactorSpec(
        "sentiment_streak", "sentiment", "连涨天数", "quote", "bell",
        "streak_mid", "w_streak", "短线动能：连涨天数钟形（峰值 3 天），连跌自然低分",
    ),
    "sentiment_ddx": FactorSpec(
        "sentiment_ddx", "sentiment", "DDX 大单动向", "quote", "sigmoid",
        "ddx_mid", "w_ddx", "大单净量比：>0 净流入更好（逐单统计，区别于主力净流入）",
    ),
    "sentiment_volspeed": FactorSpec(
        "sentiment_volspeed", "sentiment", "量速", "quote", "bell",
        "volspeed_mid", "w_volspeed", "量能变化：适度放量最优，爆量警惕出货",
    ),
}

# 维度 -> 中文标签（与 config 说明保持一致）
DIM_LABELS = {
    "capital": "资金面",
    "momentum": "动量趋势",
    "valuation": "估值",
    "liquidity": "量价活跃",
    "quality": "质量稳定",
    "sentiment": "情绪/事件",
}


def factors_of_dim(dim: str) -> list[FactorSpec]:
    """返回指定维度下的因子列表（按注册顺序）。"""
    return [f for f in FACTORS.values() if f.dim == dim]


def describe() -> str:
    """渲染因子注册表的 Markdown 说明（供方法论/前端展示）。"""
    lines = ["## 因子注册表", ""]
    for dim, label in DIM_LABELS.items():
        lines.append(f"### {label}")
        lines.append("")
        lines.append("| 因子 | 来源 | 归一化 | 权重 | 说明 |")
        lines.append("|------|------|--------|------|------|")
        for f in factors_of_dim(dim):
            lines.append(
                f"| {f.label} | {f.source} | {f.normalize} | "
                f"{f.weight_ref or '—'} | {f.desc} |"
            )
        lines.append("")
    return "\n".join(lines)
