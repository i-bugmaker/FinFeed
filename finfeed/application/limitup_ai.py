#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""涨跌停结构 AI 分析（用例编排层）

职责边界：
  - 只做「盘面快照采集 -> 结构化摘要 -> 提示词装配」，
    模型调用 / 任务流转在 :mod:`finfeed.llm.insight`，HTTP 在 llm 路由。
  - 数据来自两条互补链路，缺一路不致命：
      · 同花顺涨停聚焦：连板梯队、断板梯队、涨停题材归因（reason）、炸板率
      · 通达信涨跌停池：涨停封单额、开板次数、跌停开板次数、成交额、流通市值

「真跌停」判定口径（本模块的核心设计）：
  通达信 DT 池收录的是**收盘仍封死跌停**的个股，字段 ``open_times``
  记录盘中开板次数：
    · ``open_times == 0`` → 真跌停：全天未开板，卖压最坚决；
    · ``open_times  >  0`` → 撬板后回封：有资金撬板但尾盘仍封死，
      抛压仍占优，但封单已被消耗，次日打开概率高于真跌停。
  口径限制：盘中触及跌停、收盘脱离跌停的个股不在 DT 池中，本模块不覆盖，
  提示词中显式声明，避免模型把「不在名单」误读为「无跌停风险」。
"""

from __future__ import annotations

import logging
import re
from typing import Any, Dict, List, Optional, Set, Tuple

logger = logging.getLogger("news_monitor")

# ---- 提示词体量上限（防止极端行情下超出模型上下文）----
MAX_FIRST_BOARD = 45      # 首板梯队最多展示只数
MAX_BROKEN_LADDER = 30    # 断板梯队最多展示只数
MAX_REAL_DOWN = 40        # 真跌停最多展示只数
MAX_PRIED_DOWN = 25       # 撬板跌停最多展示只数
MAX_BROKEN_POOL = 20      # 炸板池最多展示只数
MAX_THEME_ROWS = 20       # 题材归因行数上限

_NA = "—"

# 题材归因切分与归并（reason 为「A+B+C」形式的自由文本）
_SPLIT_RE = re.compile(r"[+＋、/／,，;；|｜\s]+")
# 去噪词：出现即删除，不影响题材语义
_NOISE_WORDS = ("概念", "板块", "产业链", "龙头", "题材", "订单", "扩产", "背景", "转型")
# 归并时忽略的通用二元组：这些词是「通用后缀/修饰语」，
# 以其为归并键会把军工装备与氢能装备、液冷服务器与油气服务并成一类。
# 宁可少并（召回低）也不错并（精度低）——个股原文始终可供模型回查。
_STOP_BIGRAMS = frozenset(
    {
        "公司", "股份", "集团", "有限", "中标", "项目", "布局", "业务", "产品",
        "市场", "全球", "国内", "高端", "主营", "领域", "预期", "控股", "投资",
        "服务", "装备", "材料", "技术", "智能", "系统", "平台", "设备", "工程",
        "资源", "能源", "科技", "电子", "网络", "信息", "制造", "开发", "建设",
        "发展", "国际", "中国", "器件", "组件", "应用", "器件", "数据", "业务",
    }
)


class SnapshotError(Exception):
    """盘面快照不足以支撑分析（无数据或数据源全部降级）"""


# ============================================================
# 基础工具
# ============================================================
def _num(v: Any, default: float = 0.0) -> float:
    try:
        if v is None or v == "":
            return default
        return float(v)
    except (TypeError, ValueError):
        return default


def _int(v: Any, default: int = 0) -> int:
    try:
        if v is None or v == "":
            return default
        return int(float(v))
    except (TypeError, ValueError):
        return default


def _yi(v: Any, nd: int = 2) -> str:
    """元 → 亿元文本"""
    n = _num(v)
    if n == 0:
        return _NA
    return f"{n / 1e8:.{nd}f}亿"


def _signed_yi(v: Any) -> str:
    n = _num(v)
    if n == 0:
        return _NA
    return ("+" if n > 0 else "") + f"{n / 1e8:.2f}亿"


def _pct(v: Any) -> str:
    n = _num(v)
    return f"{n:.2f}%"


def _price(v: Any) -> str:
    n = _num(v)
    return f"{n:.2f}" if n else _NA


def _safe_pool(store, td: str, direction: str) -> List[Dict[str, Any]]:
    try:
        return list(store.get_limit_pool(td, direction) or [])
    except Exception as e:  # noqa: BLE001
        logger.warning("AI 分析：%s 池读取失败（降级为空）: %s", direction, e)
        return []


# ============================================================
# 采集
# ============================================================
async def collect_snapshot(trade_date: Optional[str] = None) -> Dict[str, Any]:
    """采集分析所需的盘面快照（异步，须在主事件循环内调用）。"""
    from finfeed.market import store, ths_limitup
    from finfeed.utils.time_utils import now_bj

    td = (trade_date or "").strip() or now_bj().strftime("%Y-%m-%d")

    ladder_payload: Dict[str, Any] = {}
    intensity: Dict[str, Any] = {}
    try:
        ladder_payload = await ths_limitup.fetch_board_ladder(td) or {}
    except Exception as e:  # noqa: BLE001
        logger.warning("AI 分析：连板天梯读取失败: %s", e)
        ladder_payload = {"error": str(e)}
    try:
        intensity = await ths_limitup.fetch_limit_up_intensity(td) or {}
    except Exception as e:  # noqa: BLE001
        logger.warning("AI 分析：涨停强度读取失败: %s", e)
        intensity = {"error": str(e)}

    if ladder_payload.get("error") and intensity.get("error"):
        raise SnapshotError(f"{td} 暂无可用的涨跌停数据（数据源不可用）")

    up_rows = _safe_pool(store, td, "up")
    down_rows = _safe_pool(store, td, "down")
    broken_rows = _safe_pool(store, td, "broken")

    ladder = list(ladder_payload.get("ladder") or [])
    broken_ladder = list(ladder_payload.get("broken_ladder") or [])
    ths_up = list(intensity.get("up") or [])
    ths_lower = list(intensity.get("lower") or [])
    ths_open = list(intensity.get("open") or [])

    # 任一链路全空视为无数据（盘前 / 休市 / 未采集）
    if not (ladder or up_rows or ths_up or down_rows or ths_lower):
        raise SnapshotError(f"{td} 暂无涨跌停数据（可能为盘前、休市或未采集）")

    # 通达信口径补充字段（封单额 / 开板次数 / 成交额 / 流通市值）
    tdx_up = {r.get("code"): r for r in up_rows}
    # 同花顺口径补充字段（题材归因 / 主力净额）
    ths_up_map = {r.get("code"): r for r in ths_up}

    # 跌停结构：优先通达信 DT 池（含 open_times），否则退回同花顺跌停池
    if down_rows:
        real_down = [r for r in down_rows if _int(r.get("open_times")) == 0]
        pried_down = [r for r in down_rows if _int(r.get("open_times")) > 0]
        down_source = "tdx"
    else:
        real_down = [dict(r, open_times=0) for r in ths_lower]
        pried_down = []
        down_source = "ths"

    real_down.sort(key=lambda r: -_num(r.get("limit_amount")))
    pried_down.sort(key=lambda r: -_num(r.get("limit_amount")))

    promotion = _calc_promotion(store, ladder_payload.get("prev_date"), ladder)

    # 代码 → 连板高度（同花顺梯队优先，通达信 limit_streak 兜底）
    board_map: Dict[str, int] = {}
    for tier in ladder:
        for s in tier.get("stocks") or []:
            code = s.get("code")
            if not code:
                continue
            h = _int(s.get("continue_num")) or _int(tier.get("height"))
            board_map[code] = max(board_map.get(code, 0), h)
    for code, r in tdx_up.items():
        if code:
            board_map[code] = max(board_map.get(code, 0), _int(r.get("limit_streak")))

    return {
        "date": td,
        "degraded": [
            k for k, v in (("ladder", ladder_payload), ("intensity", intensity)) if v.get("error")
        ],
        "source_tag": ladder_payload.get("source") or intensity.get("source") or "",
        "intensity": {
            "up_total": _int(intensity.get("up_total")),
            "open_total": _int(intensity.get("open_total")),
            "lower_total": _int(intensity.get("lower_total")),
            "metrics": intensity.get("metrics") or {},
        },
        "ladder": ladder,
        "broken_ladder": broken_ladder,
        "max_height": _int(ladder_payload.get("max_height")),
        "first_board_broken_count": _int(ladder_payload.get("first_board_broken_count")),
        "prev_date": ladder_payload.get("prev_date") or "",
        "promotion": promotion,
        "ths_up": ths_up,
        "ths_open": ths_open,
        "tdx_up": tdx_up,
        "ths_up_map": ths_up_map,
        "tdx_up_total": len(up_rows),
        "tdx_broken_total": len(broken_rows),
        "broken_rows": sorted(broken_rows, key=lambda r: -_int(r.get("open_times"))),
        "real_down": real_down,
        "pried_down": pried_down,
        "down_total": len(down_rows) or len(ths_lower),
        "down_source": down_source,
        "tdx_down_total": len(down_rows),
        "themes": _theme_stats(ths_up or _flatten_ladder(ladder), board_map),
    }


def _flatten_ladder(ladder: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """连板梯队打平为个股列表（无同花顺涨停池时的题材归因兜底）。"""
    out: List[Dict[str, Any]] = []
    for tier in ladder:
        for s in tier.get("stocks") or []:
            out.append(
                {
                    "code": s.get("code"),
                    "name": s.get("name"),
                    "reason": s.get("reason") or "",
                    "continue_day_cnt": s.get("continue_num") or tier.get("height") or 0,
                    "main_net_amount": s.get("main_net_amount") or 0,
                }
            )
    return out


def _calc_promotion(store, prev_date: Optional[str], ladder: List[Dict[str, Any]]) -> Dict[str, Any]:
    """昨日连板股（≥2 板）今日晋级率。"""
    if not prev_date:
        return {"prev_boards": 0, "promoted": 0, "rate": None}
    try:
        prev_rows = store.get_ths_limitup_ladder(prev_date) or []
    except Exception as e:  # noqa: BLE001
        logger.warning("AI 分析：昨日天梯读取失败: %s", e)
        return {"prev_boards": 0, "promoted": 0, "rate": None}

    prev_boards = [r for r in prev_rows if _int(r.get("height")) >= 2]
    if not prev_boards:
        return {"prev_boards": 0, "promoted": 0, "rate": None}
    today_codes = {
        s.get("code") for tier in ladder for s in (tier.get("stocks") or [])
    }
    promoted = sum(1 for r in prev_boards if r.get("code") in today_codes)
    return {
        "prev_boards": len(prev_boards),
        "promoted": promoted,
        "rate": round(promoted / len(prev_boards), 4),
    }


def _bigrams(text: str) -> Set[str]:
    s = text or ""
    if len(s) < 2:
        return {s} if s else set()
    return {s[i : i + 2] for i in range(len(s) - 1)}


def _concept_tokens(reason: str) -> List[str]:
    """把「A+B+C」形式的涨停原因切分为题材关键词（个股内去重）。"""
    tokens: List[str] = []
    seen: Set[str] = set()
    for raw in _SPLIT_RE.split(reason or ""):
        t = raw.strip("（）()【】[]· ")
        for w in _NOISE_WORDS:
            t = t.replace(w, "")
        t = t.strip("+＋-— ")
        if len(t) >= 2 and t not in seen:
            seen.add(t)
            tokens.append(t)
    return tokens


def _theme_stats(
    up_items: List[Dict[str, Any]],
    board_map: Optional[Dict[str, int]] = None,
    top: int = MAX_THEME_ROWS,
) -> List[Dict[str, Any]]:
    """题材归因聚合：关键词切分 → 频次统计 → 按共享二元组模糊归并。

    同花顺 reason 是自由文本（如「液冷散热+服务器液冷」），逐字串相等聚合
    会退化成每只股一类；故先切词，再按共享二元组把语义相近的写法并为一类。
    归并属启发式，存在误差，提示词中已要求模型以个股明细为准校验。
    """
    board_map = board_map or {}
    token_stats: Dict[str, Dict[str, Any]] = {}
    for it in up_items or []:
        code = it.get("code") or ""
        reason = str(it.get("reason") or "").strip()
        if not reason:
            continue
        board = _int(it.get("continue_day_cnt")) or _int(board_map.get(code) or 0)
        net = _num(it.get("main_net_amount"))
        lead = f"{it.get('name') or ''}({code})"
        for tok in _concept_tokens(reason):
            g = token_stats.setdefault(
                tok, {"count": 0, "net": 0.0, "best_board": 0, "best_net": -1e18, "lead": ""}
            )
            g["count"] += 1
            g["net"] += net
            if (board, net) > (g["best_board"], g["best_net"]):
                g["best_board"] = board
                g["best_net"] = net
                g["lead"] = lead

    ordered = sorted(
        token_stats.items(), key=lambda kv: (-kv[1]["count"], -kv[1]["best_board"], kv[0])
    )

    clusters: List[Dict[str, Any]] = []
    for tok, g in ordered:
        bg = _bigrams(tok) - _STOP_BIGRAMS
        target = next((c for c in clusters if bg & c["bigrams"]), None)
        if target is None:
            target = {
                "label": tok, "count": 0, "net": 0.0, "max_board": 0,
                "lead": "", "score": (-1, -1e18), "bigrams": bg, "members": set(),
            }
            clusters.append(target)
        target["count"] += g["count"]
        target["net"] += g["net"]
        target["members"].add(tok)
        if (g["best_board"], g["best_net"]) > target["score"]:
            target["score"] = (g["best_board"], g["best_net"])
            target["max_board"] = max(0, g["best_board"])
            target["lead"] = g["lead"]

    clusters.sort(key=lambda c: (-c["count"], -c["max_board"]))
    rows: List[Dict[str, Any]] = []
    for c in clusters[:top]:
        members = sorted(c["members"])
        alias = [m for m in members if m != c["label"]]
        rows.append(
            {
                "theme": c["label"],
                "alias": alias[:4],
                "alias_total": len(alias),
                "count": c["count"],
                "max_board": c["max_board"],
                "net": c["net"],
                "lead": c["lead"],
            }
        )
    return rows


# ============================================================
# 渲染
# ============================================================
def _up_line(s: Dict[str, Any], tdx: Dict[str, Any], board: Any) -> str:
    """涨停/连板个股一行式摘要（信息密度优先，省 token）。"""
    seg: List[str] = []
    name = s.get("name") or ""
    code = s.get("code") or ""
    seg.append(f"{name}({code})")
    seg.append(f"价{_price(s.get('price'))}")
    seg.append(_pct(s.get("change_pct")))
    reason = str(s.get("reason") or "").strip() or _NA
    seg.append(f"题材[{reason}]")
    if board:
        seg.append(f"{board}板")
    time_ = s.get("limit_up_time") or (tdx.get("first_limit_time") if tdx else "")
    if time_:
        seg.append(f"首封{time_}")
    if tdx:
        seal = _num(tdx.get("limit_amount"))
        if seal:
            seg.append(f"封单{seal:.2f}亿")
        amount = _num(tdx.get("amount"))
        if amount:
            seg.append(f"成交{amount:.2f}亿")
        ot = _int(tdx.get("open_times"))
        if ot:
            seg.append(f"开板{ot}次")
    net = _num(s.get("main_net_amount"))
    if abs(net) >= 1e6:  # 低于 100 万不占位，避免出现「主力+0.00亿」
        seg.append(f"主力{_signed_yi(net)}")
    to = _num(s.get("turnover_ratio")) or _num(tdx.get("turnover") if tdx else 0)
    if to:
        seg.append(f"换手{to:.1f}%")
    cmv = _num(s.get("effective_circulation"))
    if not cmv and tdx:
        cmv = _num(tdx.get("circ_mv")) * 1e8  # 通达信口径为亿元
    if cmv:
        seg.append(f"流通{_yi(cmv)}")
    return " | ".join(seg)


def _down_line(r: Dict[str, Any]) -> str:
    seg: List[str] = []
    seg.append(f"{r.get('name') or ''}({r.get('code') or ''})")
    seg.append(f"价{_price(r.get('price') or r.get('p'))}")
    pct = _num(r.get("pct_chg") if r.get("pct_chg") is not None else r.get("change_pct"))
    seg.append(f"{pct:.2f}%")
    streak = _int(r.get("limit_streak")) or 1
    seg.append(f"连跌{streak}天")
    seal = _num(r.get("limit_amount"))
    if seal:
        seg.append(f"封单{seal:.2f}亿")
    amount = _num(r.get("amount"))
    if amount:
        seg.append(f"成交{amount:.2f}亿")
    to = _num(r.get("turnover"))
    if to:
        seg.append(f"换手{to:.1f}%")
    cmv = _num(r.get("circ_mv"))
    if cmv:
        seg.append(f"流通{cmv:.2f}亿")
    ot = _int(r.get("open_times"))
    if ot:
        seg.append(f"撬板{ot}次")
    industry = str(r.get("reason") or "").strip()
    if industry:
        seg.append(f"行业[{industry}]")
    return " | ".join(seg)


def _broken_line(r: Dict[str, Any]) -> str:
    seg: List[str] = []
    seg.append(f"{r.get('name') or ''}({r.get('code') or ''})")
    seg.append(f"价{_price(r.get('price'))}")
    pct = _num(r.get("pct_chg"))
    seg.append(f"{pct:.2f}%" if pct else _NA)
    seg.append(f"炸板{_int(r.get('open_times'))}次")
    if r.get("first_limit_time"):
        seg.append(f"首封{r.get('first_limit_time')}")
    prev = _int(r.get("limit_streak"))
    if prev:
        seg.append(f"此前{prev}连板")
    amount = _num(r.get("amount"))
    if amount:
        seg.append(f"成交{amount:.2f}亿")
    industry = str(r.get("reason") or "").strip()
    if industry:
        seg.append(f"行业[{industry}]")
    return " | ".join(seg)


def _ladder_block(ladder: List[Dict[str, Any]], tdx_up: Dict[str, Any]) -> List[str]:
    lines: List[str] = []
    for tier in ladder:
        height = _int(tier.get("height"))
        stocks = list(tier.get("stocks") or [])
        if not stocks:
            continue
        truncated = 0
        if height <= 1:
            stocks = sorted(stocks, key=lambda s: -_num((tdx_up.get(s.get("code")) or {}).get("limit_amount")))
            if len(stocks) > MAX_FIRST_BOARD:
                truncated = len(stocks) - MAX_FIRST_BOARD
                stocks = stocks[:MAX_FIRST_BOARD]
        lines.append(f"{height}板 · {len(stocks)} 家" + (f"（另有 {truncated} 只未展示）" if truncated else ""))
        for s in stocks:
            lines.append(
                "  - "
                + _up_line(s, tdx_up.get(s.get("code")) or {}, s.get("continue_num") or height)
            )
    return lines


def _broken_block(broken_ladder: List[Dict[str, Any]]) -> List[str]:
    lines: List[str] = []
    shown = 0
    for tier in broken_ladder:
        stocks = list(tier.get("stocks") or [])
        if not stocks:
            continue
        lines.append(f"归入{tier.get('height')}板层级 · {len(stocks)} 家")
        for s in stocks:
            if shown >= MAX_BROKEN_LADDER:
                break
            shown += 1
            seg = [
                f"{s.get('name') or ''}({s.get('code') or ''})",
                f"昨日{_int(s.get('prev_height'))}连板",
            ]
            today_chg = _num(s.get("change_pct"))
            if today_chg:
                seg.append(f"今日{today_chg:+.2f}%")
            net = _num(s.get("main_net_amount"))
            if net:
                seg.append(f"主力{_signed_yi(net)}")
            lines.append("  - " + " | ".join(seg))
    return lines


def render_snapshot(snap: Dict[str, Any]) -> str:
    """把盘面快照渲染为紧凑的分节文本（供模型阅读）。"""
    lines: List[str] = []
    intensity = snap.get("intensity") or {}
    metrics = intensity.get("metrics") or {}
    promo = snap.get("promotion") or {}

    lines.append(
        f"【数据基准】交易日 {snap.get('date')} · 同花顺涨停聚焦 + 通达信涨跌停池"
        + (f" · 数据状态：{snap.get('source_tag')}" if snap.get("source_tag") else "")
        + (f" · 降级模块：{'/'.join(snap.get('degraded') or [])}" if snap.get("degraded") else "")
    )
    lines.append("")

    # 一、市场情绪快照
    lines.append("## 一、市场情绪快照")
    lines.append(
        f"- 涨停 {intensity.get('up_total', 0)} 家 · 炸板 {intensity.get('open_total', 0)} 家"
        f" · 跌停 {intensity.get('lower_total', 0)} 家（同花顺口径）"
    )
    if metrics:
        lines.append(
            f"- 封板率 {_num(metrics.get('seal_rate')) * 100:.1f}%"
            f" · 炸板率 {_num(metrics.get('broken_rate')) * 100:.1f}%"
        )
    lines.append(f"- 最高连板 {snap.get('max_height', 0)} 板")
    tdx_note = (
        f"- 通达信池采集覆盖：涨停 {snap.get('tdx_up_total', 0)}"
        f" / 炸板 {snap.get('tdx_broken_total', 0)}"
        f" / 跌停 {snap.get('tdx_down_total', 0)}"
    )
    if not (
        snap.get("tdx_up_total")
        or snap.get("tdx_broken_total")
        or snap.get("tdx_down_total")
    ):
        tdx_note += "（全为 0 表示当日未采集该池，不代表没有涨跌停）"
    lines.append(tdx_note)
    if promo.get("rate") is not None:
        lines.append(
            f"- 晋级率 {_num(promo.get('rate')) * 100:.1f}%"
            f"（前一交易日 {promo.get('prev_boards')} 家连板股中 {promo.get('promoted')} 家今日继续封板"
            f"，对比日 {snap.get('prev_date') or _NA}）"
        )
    lines.append("")

    # 二、连板梯队
    lines.append("## 二、连板梯队（同花顺，按连板高度降序）")
    block = _ladder_block(snap.get("ladder") or [], snap.get("tdx_up") or {})
    lines.extend(block or ["（今日无连板梯队数据）"])
    lines.append("")

    # 三、断板梯队
    lines.append("## 三、断板梯队（昨日连板今日未封板，按「昨日高度+1」归位）")
    block = _broken_block(snap.get("broken_ladder") or [])
    lines.extend(block or ["（今日无断板梯队数据）"])
    if snap.get("first_board_broken_count"):
        lines.append(f"- 另有首板断板 {snap.get('first_board_broken_count')} 家（信息价值低，仅计数）")
    lines.append("")

    # 四、题材归因分布
    lines.append("## 四、涨停题材归因分布（涨停原因切词聚合，按涉及家次降序）")
    themes = snap.get("themes") or []
    if themes:
        for g in themes:
            alias = ""
            if g.get("alias"):
                more = _int(g.get("alias_total")) - len(g.get("alias") or [])
                alias = "（含 " + "/".join(g["alias"]) + (f" 等 {g['alias_total']} 种写法" if more > 0 else "") + "）"
            lines.append(
                f"- {g['theme']}{alias}：{g['count']} 家次"
                f" · 最高{max(0, _int(g.get('max_board')))}板"
                f" · 主力净额合计{_signed_yi(g.get('net'))} · 代表 {g.get('lead') or _NA}"
            )
        lines.append(
            "- 说明：题材由涨停原因文本自动切词并按关键词相似度归并，存在归并误差；"
            "涉及家次可大于涨停家数（一只股可归属多个题材），请以第二节个股「题材[...]」原文为准校验。"
        )
    else:
        lines.append("（无题材归因数据）")
    lines.append("")

    # 五、跌停结构（核心：真跌停）
    lines.append("## 五、跌停结构（重点）")
    real = snap.get("real_down") or []
    pried = snap.get("pried_down") or []
    src_note = (
        "通达信 DT 池（含盘中开板次数字段）"
        if snap.get("down_source") == "tdx"
        else "同花顺跌停池（无开板次数字段，全部按真跌停处理）"
    )
    lines.append(f"数据源：{src_note} · 合计 {len(real) + len(pried)} 家")
    lines.append("")
    lines.append(f"### 5.1 真跌停（收盘封死且全天未开板，open_times=0）· {len(real)} 家")
    if real:
        for r in real[:MAX_REAL_DOWN]:
            lines.append("  - " + _down_line(r))
        if len(real) > MAX_REAL_DOWN:
            lines.append(f"  （另有 {len(real) - MAX_REAL_DOWN} 只未展示）")
    else:
        lines.append("  （无）")
    lines.append("")
    lines.append(f"### 5.2 撬板后回封（盘中曾打开跌停、尾盘仍封死，open_times>0）· {len(pried)} 家")
    if pried:
        for r in pried[:MAX_PRIED_DOWN]:
            lines.append("  - " + _down_line(r))
        if len(pried) > MAX_PRIED_DOWN:
            lines.append(f"  （另有 {len(pried) - MAX_PRIED_DOWN} 只未展示）")
    else:
        lines.append("  （无）")
    lines.append("")

    # 六、炸板池
    lines.append("## 六、炸板池（盘中触及涨停、收盘未封住，按炸板次数降序）")
    broken_rows = snap.get("broken_rows") or []
    if broken_rows:
        for r in broken_rows[:MAX_BROKEN_POOL]:
            lines.append("  - " + _broken_line(r))
        if len(broken_rows) > MAX_BROKEN_POOL:
            lines.append(f"  （另有 {len(broken_rows) - MAX_BROKEN_POOL} 只未展示）")
    else:
        lines.append("  （无炸板数据）")

    return "\n".join(lines)


# ============================================================
# 提示词
# ============================================================
SYSTEM_PROMPT = """你是一名资深 A 股短线交易员兼情绪周期分析师，擅长从涨跌停结构反推市场情绪位置、识别主线题材与潜在风险。

分析纪律（必须遵守）：
1. 严格基于用户提供的数据，禁止虚构任何个股名称、代码、数值、消息或新闻；数据未覆盖的维度，明确写「数据未覆盖」，不得猜测。
2. 区分事实与推断：事实直接引用数据（家数、封单额、连板高度等），推断必须显式标注「（推断）」并给出推理链条。
3. 结论先行：每个板块先给结论，再给依据，禁止空泛套话与正确的废话。
4. 使用简体中文、Markdown 输出，善用表格与短要点，层次清晰。
5. 严禁承诺收益或给出确定性的买卖指令；只给条件化判断、概率描述与触发条件。
6. 涉及个股时统一使用「名称(代码)」格式，便于核对。"""

USER_TEMPLATE = """# 任务
基于 {date} 的 A 股涨跌停盘面数据，依次完成：情绪周期定位 → 涨停概念分类 → 跌停结构与真跌停专项 → 潜在行情发掘 → 风险提示。

# 数据口径（务必先读，避免误判）
- 连板梯队 / 断板梯队 / 题材归因：同花顺涨停聚焦。「题材」为数据源给出的涨停原因，可能为空或宽泛，需要你归并同类表述。
- 第四节的题材分布由系统对涨停原因做自动切词与模糊归并生成，可能存在归并错误或遗漏；第二节的个股明细是权威来源，归类时须回查原文校验，「涉及家次」大于涨停家数属正常（一只股可同时归属多个题材）。
- 封单额单位为亿元，数值越大代表封板越坚决；「开板 N 次」指盘中打开涨停的次数。
- 跌停结构：通达信 DT 池收录**收盘仍封死跌停**的个股，`open_times` 为盘中开板次数：
  · `open_times = 0` → **真跌停**：全天未开板，卖压最坚决、分歧最小；
  · `open_times > 0` → **撬板后回封**：有资金撬板但尾盘仍封死，抛压仍占优，但封单已被消耗，次日打开概率高于真跌停；
  · **口径限制**：盘中触及跌停但收盘已脱离跌停的个股不在 DT 池中，本数据不覆盖。分析时不得把「未出现在名单」当作「无跌停风险」。
- 若跌停数据源为同花顺跌停池，则无开板次数字段，全部按真跌停处理，且需在结论中说明该精度限制。
- 炸板池：盘中触及涨停但收盘未封住的个股，炸板次数越多说明承接越弱。
- 晋级率 = 前一交易日连板股（≥2 板）中今日继续封板的比例，是判断情绪是否退潮的关键量化指标。

# 盘面数据
{snapshot}

# 输出要求
严格按以下五个部分输出，保留二级标题，不要增删章节、不要输出任何前言或后记。

## 一、情绪周期定位
给出一句话结论（冰点 / 修复 / 发酵 / 高潮 / 退潮 / 衰退 中的哪一档，允许写「X 向 Y 过渡」），随后用 3-5 条要点列出依据，每条依据必须引用具体数据（涨停家数、炸板率、最高连板、晋级率、跌停家数中的至少两项）。

## 二、涨停概念分类
把今日涨停股按概念/题材聚类为 3-6 条主线，用表格输出：

| 主线概念 | 涨停家数 | 梯队结构（最高板 · 龙头） | 中军 / 跟风代表 | 持续性判断 |
| --- | --- | --- | --- | --- |

表格之后补充 2-3 条要点：哪条主线是一枝独秀 / 哪几条存在概念交叉（同一只股归属多个概念）、哪条最可能是「一日游」。

## 三、跌停结构与真跌停专项
1. **结构判断**：真跌停 vs 撬板回封 的家数、占比、封单额量级对比；据此判断今日空头力量的性质——系统性杀跌 / 局部退潮 / 个股利空主导。
2. **真跌停名单解读**：把真跌停个股归类（连续跌停≥2 天的连锁杀跌 / ST 与退市风险 / 题材退潮补跌 / 高位股炸板后跌停 / 其他），每类给出代表个股与判断理由。
3. **多空对冲**：跌停个股所属行业/题材是否与第二节的涨停主线重叠？重叠意味着分化加剧还是主线扩散？请明确表态。
4. **超跌观察**：连续跌停天数≥2 的个股中，是否存在「杀跌末端」特征？给出**条件**而非结论（例如需要看到封单额萎缩至某量级、或出现放量撬板），并说明数据不足时的判断局限。

## 四、潜在行情发掘
给出 3-5 个值得跟踪的方向，每个方向严格使用以下模板：

- **方向名**（关联概念 · 代表股：名称(代码)）
  - 逻辑：一句话说清为什么现在值得跟。
  - 确认信号：需要看到什么才成立（量化到具体条件，如龙头晋级 N 板、概念内涨停家数扩散至 N 家、断板股反包、封单额维持在 X 亿以上等）。
  - 证伪信号：出现什么即放弃。
  - 风险点：与本日数据直接相关的具体风险。

## 五、风险提示
列出 3-5 条与今日数据直接相关的风险，每条必须挂靠具体数据（如「炸板率 X%，超过 30% 意味着承接不足」），禁止写放之四海皆准的套话。"""


def build_messages(snap: Dict[str, Any]) -> List[Dict[str, str]]:
    return [
        {"role": "system", "content": SYSTEM_PROMPT},
        {
            "role": "user",
            "content": USER_TEMPLATE.format(
                date=snap.get("date") or _NA,
                snapshot=render_snapshot(snap),
            ),
        },
    ]


def build_meta(snap: Dict[str, Any]) -> Dict[str, Any]:
    """回传给前端的展示元信息（供结果弹窗提示条使用）。"""
    intensity = snap.get("intensity") or {}
    return {
        "date": snap.get("date") or "",
        "limit_up_total": intensity.get("up_total", 0),
        "broken_total": intensity.get("open_total", 0) or snap.get("tdx_broken_total", 0),
        "down_total": snap.get("down_total", 0) or intensity.get("lower_total", 0),
        "real_down_total": len(snap.get("real_down") or []),
        "pried_down_total": len(snap.get("pried_down") or []),
        "max_height": snap.get("max_height", 0),
        "promotion_rate": (snap.get("promotion") or {}).get("rate"),
        "stocks_sampled": sum(len(t.get("stocks") or []) for t in (snap.get("ladder") or [])),
        "degraded": snap.get("degraded") or [],
    }


async def prepare(
    trade_date: Optional[str] = None,
) -> Tuple[List[Dict[str, str]], Dict[str, Any]]:
    """采集快照并装配提示词。返回 (messages, meta)。"""
    snap = await collect_snapshot(trade_date)
    return build_messages(snap), build_meta(snap)
