#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""涨停归因日报（对应升级方案 场景2）

对当日涨停池，自动 join 三路证据并生成 markdown 归因表：
  - 当日新闻（news_stock_link 关联 + 标题检索）
  - 龙虎榜席位净买（billboard）
  - 个股资金流（money_flow 主力净流入）
直接对齐 USER.md 的「涨跌停全量分析 + 龙虎榜 + 资金流向」日报需求，且全自动。
"""

import logging
import time
from typing import Any, Dict, List, Optional

from finfeed.storage.database import get_db_manager
from finfeed.utils.time_utils import now_bj

from . import store

logger = logging.getLogger("news_monitor")


def _code_names() -> Dict[str, str]:
    db = get_db_manager()
    with db.get_db() as c:
        c.execute("SELECT code, name FROM stock_meta")
        return {r["code"]: r["name"] for r in c.fetchall()}


def _recent_news_for_codes(codes: List[str], since_ts: int) -> Dict[str, List[str]]:
    if not codes:
        return {}
    db = get_db_manager()
    placeholders = ",".join("?" * len(codes))
    with db.get_db() as c:
        c.execute(
            f"""SELECT DISTINCT l.code, n.title
                FROM news_stock_link l JOIN news n ON n.id = l.news_id
                WHERE l.code IN ({placeholders}) AND n.publish_ts >= ?
                ORDER BY n.publish_ts DESC""",
            codes + [since_ts],
        )
        out: Dict[str, List[str]] = {}
        for r in c.fetchall():
            out.setdefault(r["code"], []).append(r["title"])
    return out


def produce_limit_up_report(trade_date: Optional[str] = None, top_n: int = 30) -> str:
    """生成涨停归因 markdown 报告。"""
    td = trade_date or now_bj().strftime("%Y-%m-%d")
    zt = store.get_limit_pool(td, "up")
    if not zt:
        return f"# {td} 涨停归因\n\n当日无涨停池数据（盘后未采集或未到收盘）。"

    codes = [r["code"] for r in zt]
    names = _code_names()
    # 最近 3 天相关新闻
    since_ts = int(time.time()) - 3 * 86400
    news_map = _recent_news_for_codes(codes, since_ts)
    # 龙虎榜 / 资金流
    bb = {r["code"]: r for r in store.get_billboard(td)}
    mf_rows = _money_flow_map(td, codes)

    lines = [f"# {td} 涨停归因分析（共 {len(zt)} 只涨停）", ""]
    lines.append("| # | 代码 | 名称 | 行业 | 连板 | 封单(亿) | 流通市值(亿) | "
                 "龙虎榜净买(万) | 主力净流入(万) | 相关新闻 |")
    lines.append("| - | - | - | - | - | - | - | - | - | - |")
    for i, r in enumerate(zt[:top_n], 1):
        code = r["code"]
        name = names.get(code, r["name"])
        b = bb.get(code)
        mf = mf_rows.get(code)
        news = news_map.get(code, [])
        news_txt = news[0][:24] + ("…" if len(news[0]) > 24 else "") if news else "-"
        news_txt = news_txt.replace("|", "/")
        lines.append(_format_limit_row(i, r, name, b, mf, news_txt))

    if len(zt) > top_n:
        lines.append("")
        lines.append(f"> 仅展示前 {top_n} 只，完整 {len(zt)} 只见 limit_pool 表。")

    # 板块聚合
    lines.append("")
    lines.append("## 涨停行业分布")
    ind = defaultdict_count([r.get("reason", "") for r in zt if r.get("reason")])
    for k, v in sorted(ind.items(), key=lambda x: -x[1])[:15]:
        lines.append(f"- {k or '未分类'}: {v} 只")
    return "\n".join(lines)


def _format_limit_row(
    i: int,
    r: Dict[str, Any],
    name: str,
    b: Optional[Dict[str, Any]],
    mf: Optional[float],
    news_txt: str,
) -> str:
    """渲染单只涨停股的一行 markdown 表格。

    『连板』列固定取 limit_pool.limit_streak（连板数），而非 open_times（开板次数）。
    该约定由 tests/test_report.py 守护，防止回归到误用 open_times 的旧实现。
    """
    bb_net = f"{b['net_amount'] / 1e4:,.0f}" if b else "-"
    mf_net = f"{mf / 1e4:,.0f}" if mf is not None else "-"
    return (
        f"| {i} | {r['code']} | {name} | {r.get('reason', '')} | {r.get('limit_streak', 0)} | "
        f"{r.get('limit_amount', 0):.2f} | {r.get('circ_mv', 0):.1f} | {bb_net} | {mf_net} | {news_txt} |"
    )


def _money_flow_map(trade_date: str, codes: List[str]) -> Dict[str, float]:
    if not codes:
        return {}
    db = get_db_manager()
    placeholders = ",".join("?" * len(codes))
    with db.get_db() as c:
        c.execute(
            f"SELECT code, main_net FROM money_flow WHERE trade_date = ? AND code IN ({placeholders})",
            [trade_date] + codes,
        )
        return {r["code"]: r["main_net"] for r in c.fetchall()}


def defaultdict_count(items):
    from collections import Counter
    return Counter(items)


def run_report(trade_date: Optional[str] = None) -> str:
    return produce_limit_up_report(trade_date)
