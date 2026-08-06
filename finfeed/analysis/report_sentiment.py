#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""复盘日报·舆情情绪板块渲染器（方案E/D 输出层，P5）

读取聚合表输出 Markdown（A股惯例：红=涨/偏多，绿=跌/偏空）：
  - market_sentiment_daily  → 全市场舆情温度
  - sector_sentiment        → 板块情绪榜
  - stock_sentiment         → 个股热度榜 TopN
供自动化在 15:30 复盘时嵌入报告。
"""

from typing import Optional

from finfeed.storage import sentiment_store as ss
from finfeed.utils.time_utils import now_bj

# A股配色（红涨绿跌）
RED = "#E24B4A"
GREEN = "#3B6D11"
GREY = "#888888"


def _sent_color(score: float) -> str:
    if score > 0.1:
        return RED
    if score < -0.1:
        return GREEN
    return GREY


def _sent_label(score: float) -> str:
    if score > 0.2:
        return "偏多"
    if score < -0.2:
        return "偏空"
    return "中性"


def render_sentiment_section(trade_date: Optional[str] = None,
                             source: str = "tdx_ai_listening",
                             top_n: int = 20) -> str:
    """渲染「舆情情绪」板块 Markdown。无数据返回占位说明。"""
    td = trade_date or now_bj().strftime("%Y-%m-%d")
    out: list[str] = []
    out.append("## 🌡️ 舆情情绪快照")
    out.append(f"> 数据日期：{td} ｜ 来源：{source}（通达信 AI 听盘 多空权重）")
    out.append("")

    # ---- 全市场舆情温度 ----
    m = ss.get_market_sentiment(td)
    if not m:
        out.append("⚠️ 当日暂无 tdx 舆情数据（盘后快照未执行或目标池无资讯）。")
        out.append("")
        return "\n".join(out)

    idx = float(m.get("sentiment_index", 0.0) or 0.0)
    c = _sent_color(idx)
    lbl = _sent_label(idx)
    out.append(f"### 全市场舆情温度：<span style=\"color:{c}\">**{idx:+.3f}**</span> （{lbl}）")
    out.append("")
    out.append(f"- 多空分布：🔴 偏多 **{m.get('up_limit',0)}** 只 ｜ "
               f"🟢 偏空 **{m.get('down_limit',0)}** 只 ｜ 中性 {m.get('breadth',0)} 只")
    out.append(f"- 论坛热度均值：{m.get('forum_heat',0):.2f} ｜ 资讯情绪：{m.get('news_sentiment',0):+.3f}")
    out.append("")

    # ---- 板块情绪榜 ----
    with ss.get_db_manager().get_db() as cur:
        cur.execute(
            "SELECT sector_name, sector_type, sentiment_score, member_count FROM sector_sentiment "
            "WHERE trade_date = ? ORDER BY sentiment_score DESC",
            (td,),
        )
        sectors = [dict(r) for r in cur.fetchall()]
    if sectors:
        out.append("### 🏭 板块情绪榜（按情绪分降序）")
        out.append("")
        out.append("| 板块 | 类型 | 情绪分 | 情绪 | 覆盖样本 |")
        out.append("|------|------|-------:|------|---------:|")
        for s in sectors:
            sc = float(s["sentiment_score"])
            out.append(
                f"| {s['sector_name']} | {s['sector_type']} | "
                f"<span style=\"color:{_sent_color(sc)}\">{sc:+.3f}</span> | "
                f"{_sent_label(sc)} | {s['member_count']} |"
            )
        out.append("")

    # ---- 个股热度榜 ----
    top = ss.get_top_heat_stocks(td, top_n, source=source)
    if top:
        out.append(f"### 🔥 个股热度榜 Top{len(top)}（按多空权重/热度降序）")
        out.append("")
        out.append("| 排名 | 代码 | 名称 | 热度 | 情绪分 | 情绪 |")
        out.append("|-----:|------|------|-----:|-------:|------|")
        for i, r in enumerate(top, 1):
            sc = float(r.get("sentiment_score", 0.0))
            out.append(
                f"| {i} | {r['code']} | {r['name']} | {r.get('heat',0):.0f} | "
                f"<span style=\"color:{_sent_color(sc)}\">{sc:+.3f}</span> | "
                f"{_sent_label(sc)} |"
            )
        out.append("")
        pos = sum(1 for r in top if r.get("sentiment_label") == "positive")
        neg = sum(1 for r in top if r.get("sentiment_label") == "negative")
        out.append(f"**热度榜多空概览**：🔴 偏多 {pos} 只 ｜ 🟢 偏空 {neg} 只 ｜ "
                   f"样本 {len(top)} 只（前 {top_n} 热门标的）。")
        out.append("")

    # ---- 热搜主题（新闻/论坛关键词聚合，方案B） ----
    try:
        from finfeed.analysis.news_sentiment import top_news_themes
        themes = top_news_themes(td, limit=15)
    except Exception:
        themes = []
    if themes:
        out.append("### 🔍 当日热搜主题（按影响力加权）")
        out.append("")
        out.append("| 主题 | 影响力 | 提及次数 |")
        out.append("|------|------:|---------:|")
        for k, imp, cnt in themes:
            out.append(f"| {k} | {imp:.1f} | {cnt} |")
        out.append("")

    out.append("---")
    out.append("*舆情情绪由通达信 AI 听盘「整体权重(0-100)」映射至 [-1,1] 情绪分，"
               "板块由成分股情绪聚合；仅覆盖盘后快照目标池（涨停/跌停/人气榜/热点龙头），"
               "非全市场逐股，宜作情绪温度参考而非择股依据。*")
    return "\n".join(out)


if __name__ == "__main__":
    print(render_sentiment_section())
