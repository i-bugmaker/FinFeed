#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""选股评分框架配置（唯一真相源）。

本模块集中定义五维加权评分模型的全部参数：维度权重、硬性过滤阈值、
各类因子的归一化锚点、评级分层与入选护栏。所有取值均经过经验校准，
并附带说明，保证「权重与阈值合理、可解释」。

评分维度与默认权重（合计 100）：
    资金面 Capital Flow      30%  —— 主力资金净流入（短+中周期），A 股最可靠的短期 alpha 之一
    动量趋势 Momentum/Trend  25%  —— 中期动量 + 多周期动量有序（上升趋势结构）
    估值 Valuation          20%  —— 市盈率 TTM 落在合理区间（规避高估值与亏损陷阱）
    量价活跃 Liquidity       15%  —— 成交额与换手率处于「活跃但不疯狂」的健康带
    质量稳定 Quality/Stab.   10%  —— 波动率（振幅/已实现波动）适中，非妖股、非僵尸

权重设定逻辑：资金面与动量趋势对短期收益的解释力最强（学术与实战均支持），
故合计 55%；估值提供安全边际，量价保证可交易性，质量稳定控制回撤风险。
各维度内部子因子的相对重要性亦在本文件声明。
"""

from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass, field
from typing import Any

from .boards import BOARD_LABELS

# ---------------------------------------------------------------------------
# 默认配置（经验校准；均为可调参数，运行时可由 JSON 覆盖）
# ---------------------------------------------------------------------------

def _default_weights() -> dict[str, float]:
    # 权重实证校准（2026-08 回测驱动 + 维度扩展）：
    # - 新增情绪/事件维度 10%（easy-tdx 快照：涨停基因/连涨/大单动向/量速）
    # - 资金面 25%→20%：主力净流入为估算值且无历史数据可回测验证，继续让渡
    # - 估值 20%→18%、质量 15%→12%：为情绪维度腾出权重
    return {
        "capital": 0.20,     # 资金面（原 0.30→0.25→0.20，数据可信度存疑持续让渡）
        "momentum": 0.25,    # 动量趋势
        "valuation": 0.18,   # 估值（原 0.20）
        "liquidity": 0.15,   # 量价活跃
        "quality": 0.12,     # 质量稳定（原 0.15）
        "sentiment": 0.10,   # 情绪/事件（新增：A 股短线 alpha，easy-tdx 快照源）
    }


def _default_filters() -> dict[str, Any]:
    return {
        # 剔除 ST / *ST / 退市 / 退（名称含此类字样）
        "exclude_st": True,
        # 剔除停牌（无成交）
        "exclude_suspended": True,
        # 剔除北交所（规则/流动性差异大，默认不参与 A 股主模型）
        # 注：boards["bj"]=False 已覆盖此逻辑；exclude_bj 保留为兼容开关。
        "exclude_bj": True,
        # 板块过滤：仅纳入开启的板块，其余剔除。
        # 键名对应 boards.classify_board 的返回值。
        "boards": {
            "main": True,   # 主板（沪 600/601/603/605，深 000/001/002/003）
            "kcb": True,    # 科创板（688/689）
            "cyb": True,    # 创业板（300/301）
            "bj": False,    # 北交所（8/4/920 开头）
        },
        # 价格区间（元）：过滤仙股与极端高价
        "min_price": 3.0,
        "max_price": 300.0,
        # 市盈率 TTM：剔除亏损(<=0)与高估值(>pe_max)
        "exclude_loss": True,
        "pe_min": 0.0,
        "pe_max": 100.0,
        # 流通市值下限（元）：剔除小市值壳/妖股（默认 30 亿）
        "min_circ_cap": 3.0e9,
        # 换手率下限（%）：剔除流动性枯竭标的
        "min_turnover": 0.3,
        # 成交额下限（元，默认 1 亿）：可交易性护栏，仅排除僵尸/极度缩量标的
        "min_amount": 1.0e8,
        # 上市天数下限（天）：剔除次新（需技术面阶段提供，可选）
        "min_listing_days": 0,
    }


def _default_params() -> dict[str, Any]:
    """各因子归一化的锚点参数。

    归一化函数见 factors.py：
        score_sigmoid(x, mid, scale)  -> 0..100，越高越好（higher_better）
        score_bell(x, mid, width)     -> 0..100，x 越接近 mid 越高
        score_band(x, lo, hi)         -> lo 以下=0，hi 以上=100，之间线性
    """
    return {
        # 资金面
        "capital": {
            "today_ratio_mid": 1.5, "today_ratio_scale": 3.0,   # 主力净比(%) sigmoid 锚点
            "net5d_pct_mid": 0.8, "net5d_pct_scale": 1.5,       # 5日主力净流入占流通市值(%) sigmoid 锚点
            "w_today": 0.55, "w_5d": 0.45,
        },
        # 动量趋势（含时序因子：动量加速度）
        "momentum": {
            "mom20_mid": 15.0, "mom20_scale": 20.0,             # 20日动量(%) sigmoid 锚点
            # 过热衰减（回测校准：原 45%/斜率1/80 偏缓，追高在 T+20 负收益，
            # 下探至 35%/下限 0.5/斜率 1/60，加速衰减防追高）
            "mom20_overheat": 35.0, "mom20_overheat_floor": 0.5,
            "mom20_decay_denom": 60.0,
            "mom60_mid": 20.0, "mom60_scale": 30.0,             # 60日动量(%) sigmoid 锚点
            # 动量加速度：20日动量 - 10日动量（K 线阶段计算），衡量趋势加速/减速
            "accel_mid": 0.0, "accel_scale": 10.0,              # 加速>0 更好，sigmoid
            "w_mom20": 0.35, "w_mom60": 0.25, "w_align": 0.20, "w_accel": 0.20,
        },
        # 估值（共线性治理：剔除股息率重复计分——股息率保留在质量维度，
        # 避免与 quality.dy 双重加分；估值维度仅保留 PE_TTM，w_dy=0）
        "valuation": {
            "pe_mid": 18.0, "pe_width": 12.0,                   # PE_TTM 钟形（校准：宽度 18→12 提升区分度）
            "loss_penalty": 15.0,                               # 亏损股给低分（通常已被过滤器剔除）
            "missing_score": 50.0,                              # PE 缺失给中性分（不误判亏损）
            "dy_mid": 2.0, "dy_width": 2.5,                     # 保留参数（w_dy=0 不使用，兼容性）
            "w_pe": 1.0, "w_dy": 0.0,                           # 仅 PE；股息率由质量维度承担（去重）
        },
        # 量价活跃
        "liquidity": {
            # amount 取 log10(元)：log10(5e8)=8.7, log10(1e9)=9, log10(5e9)=9.7, log10(2e10)=10.3
            "amount_log_lo": 8.3, "amount_log_hi": 10.0,        # band：低于 5e8 偏弱，高于 2e10 充裕
            "turnover_mid": 3.0, "turnover_width": 3.0,          # 换手率(%) 钟形，约 3% 最佳
            "w_amount": 0.5, "w_turnover": 0.5,
        },
        # 质量稳定（默认用当日振幅作波动率代理；技术面阶段可替换为已实现波动）
        # 四因子：波动率适中 + 盈利为正 + 市值规模稳健 + 持续分红
        "quality": {
            "amp_mid": 2.5, "amp_width": 2.5,                   # 振幅(%) 钟形，约 2.5% 最稳
            "vol_ann_mid": 40.0, "vol_ann_width": 35.0,         # 已实现年化波动(%) 钟形（技术面覆盖时）
            # 市值规模（log10 元）：约 10.6（≈400 亿）最稳，过小(壳/妖)或过大(超大盘)均降权
            "size_log_mid": 10.6, "size_log_width": 1.3,
            # 分红稳定性：股息率(%) 钟形，约 2% 代表稳健分红型（估值维度已去重，此处唯一计分）
            "dy_mid": 2.0, "dy_width": 2.0,
            "w_vol": 0.45, "w_profit": 0.20, "w_size": 0.20, "w_dy": 0.15,
        },
        # 情绪/事件（新增维度，easy-tdx 快照源）：
        # 涨停基因 + 连涨动能 + 大单动向 + 量能变化——A 股短线 alpha 的微观结构信号
        "sentiment": {
            # 年内涨停天数：钟形（峰值约 6 次最优），过高=妖股风险衰减
            "limitup_mid": 6.0, "limitup_width": 6.0,
            # 连涨天数：钟形（峰值 3 天），连涨过高=追高风险；负数（连跌）自然低分
            "streak_mid": 3.0, "streak_width": 3.0,
            # DDX 大单净量比：sigmoid（>0 净流入更好）
            "ddx_mid": 0.05, "ddx_scale": 0.30,
            # 量速：钟形（峰值 1.8 适度放量最优），爆量（>4）警惕出货
            "volspeed_mid": 1.8, "volspeed_width": 1.2,
            "w_limitup": 0.25, "w_streak": 0.20, "w_ddx": 0.30, "w_volspeed": 0.25,
        },
    }


def _default_neutralize() -> dict[str, Any]:
    """截面中性化（板块 + 行业 + 市值分层）。

    评分默认用全市场统一锚点，但板块/行业/市值体量的系统性差异会导致
    跨组比较失真。本开关把各维度子分与其「同组内相对排名(百分位)」做
    混合，削弱系统性偏差。

    blend ∈ [0,1]：0=关闭(纯绝对分)，1=完全组内相对分。
    by_industry：True 时分组键含申万行业（无行业字段的标的回退板块分组）。
    by_size：True 时按总市值三分位分层（缺失市值回退板块分组）。
    """
    return {
        "blend": 0.35,         # 默认 35% 相对 + 65% 绝对（较原 0.30 上调：行业差异更需中性化）
        "by_industry": True,   # 行业中性化（需 easy-tdx INDUSTRY 字段）
        "by_size": True,       # 市值分层中性化（三分位）
        "size_quantiles": 3,
    }


def _default_tiers() -> dict[str, Any]:
    return {
        # 综合分阈值（0~100）
        # 说明：strong 阈值从 72 下调至 68，guardrails 同步放宽，避免在
        # 市场偏弱/资金维度整体承压时出现「入选=0」而仅留 watch 的情况。
        "strong": 68.0,   # 入选候选
        "watch": 60.0,    # 关注
        "observe": 50.0,  # 观察
        # 动态评级（fixme 2026-08 方法论改进）：固定绝对阈值在牛熊切换时
        # 系统性失配（弱市入选≈0、强市泛滥）。启用后评级取「绝对阈值达标」
        # 与「截面综合分前 N% 分位」的较强者——保证任何市场环境下入选池
        # 规模稳定，且相对排名剔除市场系统性涨跌影响。
        "dynamic": {
            "enabled": True,
            # 绝对阈值优先；绝对达标者少于下限时，用截面分位兜底放宽（弱市防入选=0）
            "min_strong_floor": 10,
            "rank_top_strong": 0.08,   # 兜底：截面综合分前 8% 可入选
            "rank_top_watch": 0.25,    # 兜底：前 25% 可关注
            "rank_top_observe": 0.50,  # 兜底：前 50% 可观察
        },
        # 入选护栏：综合分达标后，各维度仍需满足下限，否则降级
        "guardrails": {
            "capital_min": 38.0,
            "momentum_min": 40.0,
            "valuation_min": 40.0,
            "quality_min": 35.0,
            # 当日涨跌幅绝对值超过此值（接近涨跌停）则降级，避免追高/无法成交
            # 实际判定由 scoring._limit_pct 按板块动态计算，此值仅作兜底
            "max_abs_chg_today": 9.5,
        },
    }


@dataclass
class ScreenerConfig:
    """选股模型完整配置。"""

    weights: dict[str, float] = field(default_factory=_default_weights)
    filters: dict[str, Any] = field(default_factory=_default_filters)
    params: dict[str, Any] = field(default_factory=_default_params)
    tiers: dict[str, Any] = field(default_factory=_default_tiers)
    neutralize: dict[str, Any] = field(default_factory=_default_neutralize)

    # ---- 序列化 ----
    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "ScreenerConfig":
        # 深合并默认值，保证新增字段有兜底
        cfg = cls()
        if isinstance(d.get("weights"), dict):
            cfg.weights.update(d["weights"])
        if isinstance(d.get("filters"), dict):
            cfg.filters.update(d["filters"])
        if isinstance(d.get("params"), dict):
            for k, v in d["params"].items():
                if isinstance(v, dict) and k in cfg.params:
                    cfg.params[k].update(v)
                else:
                    cfg.params[k] = v
        if isinstance(d.get("tiers"), dict):
            cfg.tiers.update(d["tiers"])
            if isinstance(d["tiers"].get("guardrails"), dict):
                cfg.tiers["guardrails"].update(d["tiers"]["guardrails"])
        if isinstance(d.get("neutralize"), dict):
            cfg.neutralize.update(d["neutralize"])
        return cfg

    @classmethod
    def load(cls, path: str) -> "ScreenerConfig":
        with open(path, "r", encoding="utf-8") as fp:
            return cls.from_dict(json.load(fp))

    def save(self, path: str) -> None:
        with open(path, "w", encoding="utf-8") as fp:
            json.dump(self.to_dict(), fp, ensure_ascii=False, indent=2)

    # ---- 说明 ----
    def explain(self) -> str:
        """返回人类可读的方法论说明（Markdown）。"""
        w = self.weights
        p = self.params
        f = self.filters
        t = self.tiers
        g = t["guardrails"]
        lines = []
        lines.append("## 选股评分方法论")
        lines.append("")
        lines.append("模型对每只股票计算 **6 个维度子分（0~100）**，按权重加权得到综合分（0~100）：")
        lines.append("")
        lines.append("| 维度 | 权重 | 核心含义 | 主要因子 |")
        lines.append("|------|------|----------|----------|")
        lines.append(f"| 资金面 | {w['capital']*100:.0f}% | 主力资金是否持续流入 | 主力净比(今日, %)、5日主力净流入占流通市值(%) |")
        lines.append(f"| 动量趋势 | {w['momentum']*100:.0f}% | 价格是否处于上升结构 | 20日动量、60日动量、动量有序性、动量加速度 |")
        lines.append(f"| 估值 | {w['valuation']*100:.0f}% | 价格是否合理 | 市盈率 TTM（钟形，合理区；亏损/缺失语义） |")
        lines.append(f"| 量价活跃 | {w['liquidity']*100:.0f}% | 是否具备可交易流动性 | 成交额(log)、换手率(%) |")
        lines.append(f"| 质量稳定 | {w['quality']*100:.0f}% | 波动/盈利/规模是否稳健 | 波动率 + 盈利 + 市值规模 + 分红四因子 |")
        lines.append(f"| 情绪/事件 | {w.get('sentiment', 0.0)*100:.0f}% | A 股短线情绪信号 | 年内涨停天数、连涨天数、DDX大单动向、量速 |")
        lines.append("")
        lines.append("### 维度子分计算")
        lines.append("")
        lines.append(f"- **资金面** = {p['capital']['w_today']:.2f}×今日主力净比分 + "
                     f"{p['capital']['w_5d']:.2f}×5日净流入占流通分")
        lines.append(f"  - 今日主力净比：sigmoid(锚点 {p['capital']['today_ratio_mid']}%, 尺度 {p['capital']['today_ratio_scale']}%)")
        lines.append(f"  - 5日净流入占流通：sigmoid(锚点 {p['capital']['net5d_pct_mid']}%, 尺度 {p['capital']['net5d_pct_scale']}%)")
        lines.append(f"- **动量趋势** = {p['momentum']['w_mom20']:.2f}×20日动量分 + "
                     f"{p['momentum']['w_mom60']:.2f}×60日动量分 + {p['momentum']['w_align']:.2f}×动量有序分"
                     f" + {p['momentum']['w_accel']:.2f}×动量加速度分")
        lines.append(f"  - 20日动量：sigmoid(锚点 {p['momentum']['mom20_mid']}%)；> {p['momentum']['mom20_overheat']}% 触发过热衰减（回测校准）")
        lines.append(f"  - 60日动量：sigmoid(锚点 {p['momentum']['mom60_mid']}%)")
        lines.append("  - 动量有序：满足 5日≥20日≥60日≥0 的程度（每满足一项 +1/3）")
        lines.append(f"  - 动量加速度：20日动量−10日动量（sigmoid 锚点 {p['momentum']['accel_mid']}%），趋势加速>0 更优（时序因子）")
        lines.append(f"- **估值** = {p['valuation']['w_pe']:.2f}×PE_TTM 钟形分（股息率已移至质量维度，消除重复计分）")
        lines.append(f"  - PE_TTM：钟形（峰值 {p['valuation']['pe_mid']}，宽度 {p['valuation']['pe_width']}）；亏损股给 {p['valuation']['loss_penalty']:.0f} 分、缺失给中性分")
        lines.append(f"- **量价活跃** = {p['liquidity']['w_amount']:.2f}×成交额分 + {p['liquidity']['w_turnover']:.2f}×换手率分")
        lines.append(f"  - 成交额：log10 线性带 [{p['liquidity']['amount_log_lo']}, {p['liquidity']['amount_log_hi']}]")
        lines.append(f"  - 换手率：钟形（峰值 {p['liquidity']['turnover_mid']}%）")
        qp = p['quality']
        lines.append(f"- **质量稳定** = {qp['w_vol']:.2f}×波动率分 + {qp['w_profit']:.2f}×盈利分 + {qp['w_size']:.2f}×市值规模分 + {qp['w_dy']:.2f}×分红分")
        lines.append(f"  - 波动率：钟形（振幅峰值 {qp['amp_mid']}%；技术面启用时改用年化波动峰值 {qp['vol_ann_mid']}%）")
        lines.append("  - 盈利：EPS>0 计满分（亏损股已被过滤）")
        lines.append(f"  - 市值规模：log10(总市值) 钟形（峰值 {qp['size_log_mid']}，宽度 {qp['size_log_width']}），过小(壳/妖)或过大(超大盘)均降权")
        lines.append(f"  - 分红：股息率钟形（峰值 {qp['dy_mid']}%），持续分红代表经营稳健")
        sp = p['sentiment']
        lines.append(f"- **情绪/事件** = {sp['w_limitup']:.2f}×涨停基因分 + {sp['w_streak']:.2f}×连涨动能分 + "
                     f"{sp['w_ddx']:.2f}×DDX大单动向分 + {sp['w_volspeed']:.2f}×量速分")
        lines.append(f"  - 年内涨停天数：钟形（峰值 {sp['limitup_mid']:.0f} 次），过高=妖股风险衰减")
        lines.append(f"  - 连涨天数：钟形（峰值 {sp['streak_mid']:.0f} 天），连涨过高=追高风险")
        lines.append(f"  - DDX 大单净量比：sigmoid（锚点 {sp['ddx_mid']}，尺度 {sp['ddx_scale']}），>0 净流入更好")
        lines.append(f"  - 量速：钟形（峰值 {sp['volspeed_mid']}），适度放量最优，爆量警惕出货")
        lines.append("")
        lines.append("### 硬性过滤（评分前剔除）")
        lines.append("")
        flt = []
        if f["exclude_st"]:
            flt.append("剔除 ST / *ST / 退市 标的")
        if f["exclude_suspended"]:
            flt.append("剔除停牌（无成交）标的")
        boards = f.get("boards") or {}
        enabled = [BOARD_LABELS.get(k, k) for k, v in boards.items() if v]
        disabled = [BOARD_LABELS.get(k, k) for k, v in boards.items() if not v]
        if disabled:
            flt.append(f"仅纳入板块：{'、'.join(enabled)}（剔除 {'、'.join(disabled)}）")
        else:
            flt.append(f"纳入全部板块：{'、'.join(enabled)}")
        flt.append(f"价格区间 {f['min_price']:.0f} ~ {f['max_price']:.0f} 元")
        if f["exclude_loss"]:
            flt.append(f"剔除亏损(PE_TTM≤0)与 PE_TTM>{f['pe_max']:.0f} 的标的")
        flt.append(f"流通市值 ≥ {f['min_circ_cap']/1e9:.0f} 亿元")
        flt.append(f"换手率 ≥ {f['min_turnover']:.1f}%")
        if f.get("min_amount"):
            flt.append(f"成交额 ≥ {f['min_amount']/1e8:.0f} 亿元（可交易性护栏）")
        lines.append("；".join(flt) + "。")
        lines.append("")
        lines.append("### 评级与入选护栏")
        lines.append("")
        dyn = t.get("dynamic") or {}
        lines.append(f"- **入选候选 (Strong)**：综合分 ≥ {t['strong']:.0f}（或截面前 {dyn.get('rank_top_strong', 0.15):.0%} 分位）"
                     f"，且资金≥{g['capital_min']:.0f}、"
                     f"动量≥{g['momentum_min']:.0f}、估值≥{g['valuation_min']:.0f}、质量≥{g['quality_min']:.0f}，"
                     f"且当日涨跌幅绝对值 < 板块涨跌停×95%（避免追高/无法成交）。")
        if dyn.get("enabled"):
            lines.append("  - 动态评级已启用：评级取「绝对阈值」与「截面综合分前 N% 分位」的较强者，"
                         "弱市不出现入选=0、强市不过度泛滥。")
        lines.append(f"- **关注 (Watch)**：综合分 ≥ {t['watch']:.0f}（或满足综合分但触发护栏降级）。")
        lines.append(f"- **观察 (Observe)**：综合分 ≥ {t['observe']:.0f}。")
        lines.append(f"- **不入选**：综合分 < {t['observe']:.0f} 且未进入截面前 {dyn.get('rank_top_observe', 0.60):.0%}（仅保留在全量快照中）。")
        lines.append("")
        lines.append("### 截面中性化（板块 + 行业 + 市值分层）")
        lines.append("")
        nb = self.neutralize.get("blend", 0.0)
        if nb > 0:
            parts = []
            parts.append(f"按 {nb:.0%} 混合（即 {1-nb:.0%} 绝对分 + {nb:.0%} 组内相对分）")
            keys = []
            keys.append("板块")
            if self.neutralize.get("by_industry", True):
                keys.append("申万行业")
            if self.neutralize.get("by_size", True):
                keys.append(f"市值{self.neutralize.get('size_quantiles', 3)}分位")
            lines.append(
                f"为消除板块/行业/市值体量的系统性差异，每个维度子分会与「{'、'.join(keys)}"
                f"组内百分位排名」{parts[0]}，使跨组候选可比。"
                "可在配置中调整 blend（0=关闭，1=完全相对分）。"
            )
        else:
            lines.append("截面中性化已关闭（blend=0），评分为全市场统一绝对分。")
        lines.append("")
        lines.append("> 说明：本模型为系统化量化筛选工具，因子基于公开市场微观结构规律"
                     "（动量、价值、流动性、聪明钱）设计，用于缩小研究范围，不构成投资建议。"
                     "历史规律不代表未来收益，实盘前请结合基本面与风控。")
        return "\n".join(lines)


# 默认配置单例（模块级，便于直接引用）
DEFAULT_CONFIG = ScreenerConfig()


def load_config(path: str | None = None) -> ScreenerConfig:
    """加载配置：优先 path，其次环境变量 FINFEED_SCREENER_CONFIG 指向的文件。"""
    if path is None:
        path = os.environ.get("FINFEED_SCREENER_CONFIG")
    if path and os.path.exists(path):
        return ScreenerConfig.load(path)
    return ScreenerConfig()
