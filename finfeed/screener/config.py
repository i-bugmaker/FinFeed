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
from dataclasses import dataclass, field, asdict
from typing import Any

from .boards import BOARD_LABELS


# ---------------------------------------------------------------------------
# 默认配置（经验校准；均为可调参数，运行时可由 JSON 覆盖）
# ---------------------------------------------------------------------------

def _default_weights() -> dict[str, float]:
    return {
        "capital": 0.30,     # 资金面
        "momentum": 0.25,    # 动量趋势
        "valuation": 0.20,   # 估值
        "liquidity": 0.15,   # 量价活跃
        "quality": 0.10,     # 质量稳定
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
        # 动量趋势
        "momentum": {
            "mom20_mid": 15.0, "mom20_scale": 20.0,             # 20日动量(%) sigmoid 锚点
            "mom20_overheat": 45.0, "mom20_overheat_floor": 0.6,  # 过热(>45%) 衰减系数下限
            "mom60_mid": 20.0, "mom60_scale": 30.0,             # 60日动量(%) sigmoid 锚点
            "w_mom20": 0.40, "w_mom60": 0.30, "w_align": 0.30,
        },
        # 估值（价值因子）：PE_TTM 钟形 + 股息率钟形 双因子
        "valuation": {
            "pe_mid": 18.0, "pe_width": 18.0,                   # PE_TTM 钟形锚点（合理区约 8~36）
            "loss_penalty": 15.0,                               # 亏损股给低分（通常已被过滤器剔除）
            # 股息率(%) 钟形：高股息代表现金流稳定、估值锚扎实（收入型价值）
            "dy_mid": 2.0, "dy_width": 2.5,                     # 约 2% 最佳，过高(周期顶)或过低皆非优
            "w_pe": 0.70, "w_dy": 0.30,                         # PE 为主、股息率为辅的双价值因子
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
            # 分红稳定性：股息率(%) 钟形，约 2% 代表稳健分红型
            "dy_mid": 2.0, "dy_width": 2.0,
            "w_vol": 0.45, "w_profit": 0.20, "w_size": 0.20, "w_dy": 0.15,
        },
    }


def _default_neutralize() -> dict[str, Any]:
    """板块内相对评分（截面中性化）。

    评分默认用全市场统一锚点，但科创板(高估值/高波动)、创业板与主板
    的系统差异会导致板块间不公平。本开关把各维度子分与其「同板块内
    相对排名(百分位)」做混合，削弱板块系统性偏差，使跨板块可比。

    blend ∈ [0,1]：0=关闭(纯绝对分)，1=完全板块相对分。
    """
    return {
        "blend": 0.30,   # 默认 30% 相对 + 70% 绝对，温和中性化
    }


def _default_tiers() -> dict[str, Any]:
    return {
        # 综合分阈值（0~100）
        # 说明：strong 阈值从 72 下调至 68，guardrails 同步放宽，避免在
        # 市场偏弱/资金维度整体承压时出现「入选=0」而仅留 watch 的情况。
        "strong": 68.0,   # 入选候选
        "watch": 60.0,    # 关注
        "observe": 50.0,  # 观察
        # 入选护栏：综合分达标后，各维度仍需满足下限，否则降级
        "guardrails": {
            "capital_min": 38.0,
            "momentum_min": 40.0,
            "valuation_min": 40.0,
            "quality_min": 35.0,
            # 当日涨跌幅绝对值超过此值（接近涨跌停）则降级，避免追高/无法成交
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
        lines.append("模型对每只股票计算 **5 个维度子分（0~100）**，按权重加权得到综合分（0~100）：")
        lines.append("")
        lines.append("| 维度 | 权重 | 核心含义 | 主要因子 |")
        lines.append("|------|------|----------|----------|")
        lines.append(f"| 资金面 | {w['capital']*100:.0f}% | 主力资金是否持续流入 | 主力净比(今日, %)、5日主力净流入占流通市值(%) |")
        lines.append(f"| 动量趋势 | {w['momentum']*100:.0f}% | 价格是否处于上升结构 | 20日动量、60日动量、5/20/60日动量有序性 |")
        lines.append(f"| 估值 | {w['valuation']*100:.0f}% | 价格是否合理 | 市盈率 TTM + 股息率（双价值因子，钟形） |")
        lines.append(f"| 量价活跃 | {w['liquidity']*100:.0f}% | 是否具备可交易流动性 | 成交额(log)、换手率(%) |")
        lines.append(f"| 质量稳定 | {w['quality']*100:.0f}% | 波动/盈利/规模是否稳健 | 波动率 + 盈利 + 市值规模 + 分红四因子 |")
        lines.append("")
        lines.append("### 维度子分计算")
        lines.append("")
        lines.append(f"- **资金面** = {p['capital']['w_today']:.2f}×今日主力净比分 + "
                     f"{p['capital']['w_5d']:.2f}×5日净流入占流通分")
        lines.append(f"  - 今日主力净比：sigmoid(锚点 {p['capital']['today_ratio_mid']}%, 尺度 {p['capital']['today_ratio_scale']}%)")
        lines.append(f"  - 5日净流入占流通：sigmoid(锚点 {p['capital']['net5d_pct_mid']}%, 尺度 {p['capital']['net5d_pct_scale']}%)")
        lines.append(f"- **动量趋势** = {p['momentum']['w_mom20']:.2f}×20日动量分 + "
                     f"{p['momentum']['w_mom60']:.2f}×60日动量分 + {p['momentum']['w_align']:.2f}×动量有序分")
        lines.append(f"  - 20日动量：sigmoid(锚点 {p['momentum']['mom20_mid']}%)；> {p['momentum']['mom20_overheat']}% 触发过热衰减")
        lines.append(f"  - 60日动量：sigmoid(锚点 {p['momentum']['mom60_mid']}%)")
        lines.append(f"  - 动量有序：满足 5日≥20日≥60日≥0 的程度（每满足一项 +1/3）")
        lines.append(f"- **估值** = {p['valuation']['w_pe']:.2f}×PE_TTM 钟形分 + {p['valuation']['w_dy']:.2f}×股息率钟形分")
        lines.append(f"  - PE_TTM：钟形（峰值 {p['valuation']['pe_mid']}，宽度 {p['valuation']['pe_width']}）；亏损股给 {p['valuation']['loss_penalty']:.0f} 分")
        lines.append(f"  - 股息率：钟形（峰值 {p['valuation']['dy_mid']}%，宽度 {p['valuation']['dy_width']}%）—— 高股息代表现金流稳健、估值锚扎实")
        lines.append(f"- **量价活跃** = {p['liquidity']['w_amount']:.2f}×成交额分 + {p['liquidity']['w_turnover']:.2f}×换手率分")
        lines.append(f"  - 成交额：log10 线性带 [{p['liquidity']['amount_log_lo']}, {p['liquidity']['amount_log_hi']}]")
        lines.append(f"  - 换手率：钟形（峰值 {p['liquidity']['turnover_mid']}%）")
        qp = p['quality']
        lines.append(f"- **质量稳定** = {qp['w_vol']:.2f}×波动率分 + {qp['w_profit']:.2f}×盈利分 + {qp['w_size']:.2f}×市值规模分 + {qp['w_dy']:.2f}×分红分")
        lines.append(f"  - 波动率：钟形（振幅峰值 {qp['amp_mid']}%；技术面启用时改用年化波动峰值 {qp['vol_ann_mid']}%）")
        lines.append(f"  - 盈利：EPS>0 计满分（亏损股已被过滤）")
        lines.append(f"  - 市值规模：log10(总市值) 钟形（峰值 {qp['size_log_mid']}，宽度 {qp['size_log_width']}），过小(壳/妖)或过大(超大盘)均降权")
        lines.append(f"  - 分红：股息率钟形（峰值 {qp['dy_mid']}%），持续分红代表经营稳健")
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
        lines.append("；".join(flt) + "。")
        lines.append("")
        lines.append("### 评级与入选护栏")
        lines.append("")
        lines.append(f"- **入选候选 (Strong)**：综合分 ≥ {t['strong']:.0f}，且资金≥{g['capital_min']:.0f}、"
                     f"动量≥{g['momentum_min']:.0f}、估值≥{g['valuation_min']:.0f}、质量≥{g['quality_min']:.0f}，"
                     f"且当日涨跌幅绝对值 < {g['max_abs_chg_today']:.1f}%（避免追高/无法成交）。")
        lines.append(f"- **关注 (Watch)**：综合分 ≥ {t['watch']:.0f}（或满足综合分但触发护栏降级）。")
        lines.append(f"- **观察 (Observe)**：综合分 ≥ {t['observe']:.0f}。")
        lines.append(f"- **不入选**：综合分 < {t['observe']:.0f}（仅保留在全量快照中）。")
        lines.append("")
        lines.append("### 板块中性化（截面相对评分）")
        lines.append("")
        nb = self.neutralize.get("blend", 0.0)
        if nb > 0:
            lines.append(
                f"为消除科创板/创业板与主板之间估值、波动等系统性差异，每个维度子分会与"
                f"「同板块内百分位排名」按 {nb:.0%} 混合（即 {1-nb:.0%} 绝对分 + {nb:.0%} 板块相对分），"
                "使跨板块的候选可比。可在配置中调整 blend（0=关闭，1=完全相对分）。"
            )
        else:
            lines.append("板块中性化已关闭（blend=0），评分为全市场统一绝对分。")
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
