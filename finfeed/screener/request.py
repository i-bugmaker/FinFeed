#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""ScreenerRequest 结构化输入契约与编排（P3 I/O 重构）。

把设计文档 §4.1 的 JSON 契约映射为后端可执行的 ScreenerConfig，并负责：
- 用户自定义选股规则（股票池 / 策略 / 输出三大块）的合并与校验；
- 模板保存 / 加载 / 列出 / 删除（JSON 落盘 logs/screener_templates/）；
- 策略对比（compare）：同一快照下跑两套规则，输出差异摘要。

设计依据：docs/screener_refactor_design.md §4（I/O Contract）、§7（UI/UX）。
向后兼容：本模块不修改默认配置语义；service 层仍可在无 request 时走 load_config()。
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .config import ScreenerConfig, load_config

# 模板落盘目录（进程级，单例）
_TEMPLATES_DIR = Path(__file__).resolve().parent.parent.parent / "logs" / "screener_templates"

# 维度键（与 config.weights 对齐；growth/reversal 为设计预留维度，本期未实现因子）
_DIMS = ("capital", "momentum", "valuation", "liquidity", "quality", "sentiment", "growth", "reversal")


@dataclass
class ScreenerRequest:
    """结构化选股请求（对应设计文档 §4.1）。

    字段均为可选；未提供的字段回退到默认配置 / 引擎默认值。
    """

    universe: dict[str, Any] = field(default_factory=dict)
    strategy: dict[str, Any] = field(default_factory=dict)
    output: dict[str, Any] = field(default_factory=dict)
    template: str | None = None          # 先应用已存模板（再叠加本次覆盖）
    compare_with: str | None = None      # 对比模板名（service 层用于叠加对比）

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "ScreenerRequest":
        d = d or {}
        # 支持 template 嵌套在 strategy 或顶层
        template = d.get("template") or (d.get("strategy") or {}).get("template")
        return cls(
            universe=d.get("universe") or {},
            strategy=d.get("strategy") or {},
            output=d.get("output") or {},
            template=template,
            compare_with=d.get("compare_with"),
        )


def _deep_merge(base: dict, override: dict) -> dict:
    """浅+一层合并（用于模板叠加用户覆盖）。"""
    out = dict(base)
    for k, v in (override or {}).items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _deep_merge(out[k], v)
        else:
            out[k] = v
    return out


def build_config(req: ScreenerRequest, base: ScreenerConfig | None = None) -> ScreenerConfig:
    """把 ScreenerRequest 合并进 ScreenerConfig（不修改 base，返回新实例）。

    映射规则（设计文档 §4.1）：
    - universe        → filters（板块/ST/停牌/流动性/价格/PE/市值）
    - strategy.mode   → engine.mode（linear→fixed|auto，ml→ml，blend→blend）
    - strategy.auto_weight + dim_weights → 维度权重（任一非 null 覆盖）
    - strategy.orthogonalize / ml / blend_alpha → engine
    - output.tiers    → tiers 阈值；output.top 由调用方读取
    """
    base = base or load_config()
    cfg = ScreenerConfig.from_dict(base.to_dict())  # 深拷贝（含 engine）

    # 若指定模板，先叠加模板再叠加本次 strategy/universe/output
    if req.template:
        tpl = load_template(req.template)
        if tpl:
            req = ScreenerRequest(
                universe=_deep_merge(tpl.get("universe", {}), req.universe),
                strategy=_deep_merge(tpl.get("strategy", {}), req.strategy),
                output=_deep_merge(tpl.get("output", {}), req.output),
            )

    u = req.universe or {}
    f = cfg.filters
    if isinstance(u.get("boards"), dict):
        f["boards"] = {k: bool(v) for k, v in u["boards"].items()}
    if "exclude_st" in u:
        f["exclude_st"] = bool(u["exclude_st"])
    if "exclude_suspended" in u:
        f["exclude_suspended"] = bool(u["exclude_suspended"])
    if "min_amount" in u and u["min_amount"] is not None:
        f["min_amount"] = float(u["min_amount"])
    if "min_turnover" in u and u["min_turnover"] is not None:
        f["min_turnover"] = float(u["min_turnover"])
    if isinstance(u.get("price_range"), (list, tuple)) and len(u["price_range"]) == 2:
        lo, hi = u["price_range"]
        if lo is not None:
            f["min_price"] = float(lo)
        if hi is not None:
            f["max_price"] = float(hi)
    if isinstance(u.get("pe_ttm_range"), (list, tuple)) and len(u["pe_ttm_range"]) == 2:
        lo, hi = u["pe_ttm_range"]
        if lo is not None:
            f["pe_min"] = float(lo)
        if hi is not None:
            f["pe_max"] = float(hi)
    if isinstance(u.get("float_cap_range"), (list, tuple)) and len(u.get("float_cap_range")) == 2:
        lo, hi = u["float_cap_range"]
        if lo is not None:
            f["min_circ_cap"] = float(lo)
    # 注：exclude_new_days（剔除次新）已随 min_listing_days 死配置一并移除
    # —— 数据源无上市日期字段，此前该参数从未生效。

    s = req.strategy or {}
    eng = cfg.engine
    mode = str(s.get("mode", "linear")).lower()
    auto_weight = bool(s.get("auto_weight", False))
    dim_weights = s.get("dim_weights") or {}
    custom = {d: float(v) for d, v in dim_weights.items()
              if d in _DIMS and v is not None}

    if mode == "ml":
        eng["mode"] = "ml"
    elif mode == "blend":
        eng["mode"] = "blend"
    elif mode == "ic":
        eng["mode"] = "ic"
    elif mode == "auto":
        eng["mode"] = "auto"
    elif mode == "linear":
        # 有自定义权重 → 固定；否则按 auto_weight 决定 IC 自动加权或固定
        eng["mode"] = "auto" if (auto_weight and not custom) else "fixed"
    else:
        eng["mode"] = "fixed"

    if custom:
        # 自定义权重：以用户给定值覆盖对应维度后，整体归一化到合计 1.0
        cfg.weights.update(custom)
        tot = sum(cfg.weights.values())
        if tot > 0:
            cfg.weights = {d: v / tot for d, v in cfg.weights.items()}
        eng["mode"] = "fixed"  # 人工干预权重时锁定固定模式

    if "orthogonalize" in s:
        eng["orthogonalize"] = bool(s["orthogonalize"])
    if "blend_alpha" in s and s["blend_alpha"] is not None:
        eng["blend_alpha"] = float(s["blend_alpha"])
    ml = s.get("ml") or {}
    if "horizon" in ml:
        eng["horizon"] = int(ml["horizon"])
    if "top_quantile" in ml:
        eng["top_quantile"] = float(ml["top_quantile"])
    if "min_history_days" in ml:
        eng["min_history_days"] = int(ml["min_history_days"])

    o = req.output or {}
    if isinstance(o.get("tiers"), dict):
        for k in ("strong", "watch", "observe"):
            if k in o["tiers"] and o["tiers"][k] is not None:
                cfg.tiers[k] = float(o["tiers"][k])

    return cfg


# ---------------------------------------------------------------------------
# 模板存储（JSON 落盘）
# ---------------------------------------------------------------------------

def _tpl_path(name: str) -> Path:
    safe = "".join(c for c in name if c.isalnum() or c in ("_", "-", "."))
    return _TEMPLATES_DIR / f"{safe or 'untitled'}.json"


def save_template(name: str, req_dict: dict[str, Any]) -> dict[str, Any]:
    """保存选股请求为模板（含 universe/strategy/output）。"""
    _TEMPLATES_DIR.mkdir(parents=True, exist_ok=True)
    payload = {
        "name": name,
        "saved_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "request": req_dict,
    }
    _tpl_path(name).write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return payload


def load_template(name: str) -> dict[str, Any] | None:
    p = _tpl_path(name)
    if not p.exists():
        return None
    try:
        return json.loads(p.read_text(encoding="utf-8")).get("request")
    except (ValueError, OSError):
        return None


def list_templates() -> list[dict[str, Any]]:
    if not _TEMPLATES_DIR.exists():
        return []
    out = []
    for p in sorted(_TEMPLATES_DIR.glob("*.json")):
        try:
            d = json.loads(p.read_text(encoding="utf-8"))
            out.append({"name": d.get("name", p.stem), "saved_at": d.get("saved_at"),
                        "request": d.get("request", {})})
        except (ValueError, OSError):
            continue
    return out


def delete_template(name: str) -> bool:
    p = _tpl_path(name)
    if p.exists():
        p.unlink()
        return True
    return False


# ---------------------------------------------------------------------------
# 策略对比
# ---------------------------------------------------------------------------

def compare_configs(cfg_a: ScreenerConfig, cfg_b: ScreenerConfig) -> dict[str, Any]:
    """对比两套配置的差异（权重 / 引擎 / 过滤 / 评级）。"""
    diff_weights = {d: [round(cfg_a.weights.get(d, 0.0), 4),
                       round(cfg_b.weights.get(d, 0.0), 4)]
                    for d in _DIMS
                    if abs(cfg_a.weights.get(d, 0.0) - cfg_b.weights.get(d, 0.0)) > 1e-6}
    return {
        "weights": diff_weights,
        "engine_mode": [cfg_a.engine.get("mode"), cfg_b.engine.get("mode")],
        "orthogonalize": [cfg_a.engine.get("orthogonalize"), cfg_b.engine.get("orthogonalize")],
        "filters_delta": {
            "min_amount": [cfg_a.filters.get("min_amount"), cfg_b.filters.get("min_amount")],
            "min_turnover": [cfg_a.filters.get("min_turnover"), cfg_b.filters.get("min_turnover")],
            "boards": [cfg_a.filters.get("boards"), cfg_b.filters.get("boards")],
        },
        "tiers": {
            "strong": [cfg_a.tiers.get("strong"), cfg_b.tiers.get("strong")],
            "watch": [cfg_a.tiers.get("watch"), cfg_b.tiers.get("watch")],
        },
    }


def summarize_result(result: Any) -> dict[str, Any]:
    """把 ScreenerResult 压缩为对比所需的摘要。"""
    scores = getattr(result, "scores", []) or []
    tiers = {"strong": 0, "watch": 0, "observe": 0, "none": 0}
    for s in scores:
        tiers[s.tier] = tiers.get(s.tier, 0) + 1
    avg = (sum(s.total_score for s in scores) / len(scores)) if scores else 0.0
    return {
        "universe_size": result.universe_size,
        "scored_size": result.scored_size,
        "avg_total_score": round(avg, 2),
        "tier_counts": tiers,
        "engine_mode": result.engine_mode,
        "model_status": getattr(result, "model_status", "linear"),
    }
