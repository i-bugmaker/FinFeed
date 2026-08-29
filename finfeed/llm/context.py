#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""事实包组装器 —— 把市场事实层 / 舆情层 / 财经日历收口成 AI 可引用的结构化上下文

设计原则：
  1. 所有数字由程序从库内事实表读取，模型只负责归因与叙述，不负责计数；
  2. 每个区块独立容错：某张事实表缺失/为空时降级为空段落，绝不拖垮整个分析；
  3. 输出统一为「文本块 + 结构化 dict」双形态：dict 供前端展示，文本供 prompt 注入。
"""

import logging
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

from finfeed.storage.database import get_db_manager

logger = logging.getLogger("news_monitor")

try:  # 事实层可选依赖：表未建/未采集时全部降级
    from finfeed.market import store as market_store
except Exception:  # noqa: BLE001
    market_store = None  # type: ignore[assignment]

try:
    from finfeed.storage import sentiment_store
except Exception:  # noqa: BLE001
    sentiment_store = None  # type: ignore[assignment]


def _safe(fn, default, *args, **kwargs):
    """调用事实层查询函数，任何异常都降级为 default。"""
    if fn is None:
        return default
    try:
        return fn(*args, **kwargs)
    except Exception as e:  # noqa: BLE001 —— 单区块失败不拖垮事实包
        logger.debug(f"事实包区块查询失败: {getattr(fn, '__name__', fn)}: {e}")
        return default


def _yi(v: Any) -> str:
    """金额（元）格式化为亿元可读字符串。"""
    try:
        f = float(v)
    except (TypeError, ValueError):
        return "-"
    return f"{f / 1e8:.2f}亿"


def _pct(v: Any) -> str:
    try:
        return f"{float(v):+.2f}%"
    except (TypeError, ValueError):
        return "-"


def latest_trade_date() -> Optional[str]:
    """事实层最近一个有数据的交易日。"""
    if market_store is None:
        return None
    d = _safe(market_store.get_latest_ths_limitup_date, None)
    if not d:
        d = _safe(market_store.latest_date, None, "money_flow")
    return d


# ============================================================
# 大盘事实包（复盘简报用）
# ============================================================
def market_fact_pack() -> Dict[str, Any]:
    """聚合最近一个交易日的大盘事实：涨跌停、连板天梯、题材风口、资金流、板块、龙虎榜、两融、未来日历。"""
    facts: Dict[str, Any] = {"trade_date": None}
    if market_store is None:
        return facts

    td = latest_trade_date()
    facts["trade_date"] = td
    if not td:
        return facts

    facts["sentiment"] = _safe(market_store.get_ths_limitup_sentiment, None, td) or {}
    ladder = _safe(market_store.get_ths_limitup_ladder, [], td) or []
    facts["ladder_top"] = ladder[:12]
    facts["limit_up_count"] = sum(int(r.get("number") or 0) for r in ladder) or None
    facts["topics_top"] = (_safe(market_store.get_ths_limitup_block_top, [], td) or [])[:10]
    facts["flow_summary"] = _safe(market_store.get_money_flow_summary, {}, td) or {}
    facts["flow_in_top"] = (_safe(market_store.get_money_flow, [], td, "in", "main_net", 10) or [])[:10]
    facts["flow_out_top"] = (_safe(market_store.get_money_flow, [], td, "out", "main_net", 8) or [])[:8]
    facts["sector_heat_top"] = (_safe(market_store.get_sector_heat, [], td, "industry", 5, "main_net", 10) or [])[:10]
    bb = _safe(market_store.get_billboard, [], td) or []
    facts["billboard_top"] = sorted(
        bb, key=lambda r: abs(float(r.get("net_amount") or 0)), reverse=True
    )[:8]
    facts["margin_summary"] = _safe(market_store.get_margin_summary, {}, td) or {}
    facts["upcoming_events"] = _upcoming_events(5)

    codes = [r.get("code") for r in facts["flow_in_top"] + facts["flow_out_top"] if r.get("code")]
    facts["name_map"] = _stock_names(codes)
    return facts


def _stock_names(codes: List[str]) -> Dict[str, str]:
    if not codes:
        return {}
    out: Dict[str, str] = {}
    try:
        db = get_db_manager()
        with db.get_db() as c:
            for i in range(0, len(codes), 400):
                batch = [x for x in codes[i : i + 400] if x]
                if not batch:
                    continue
                ph = ",".join("?" * len(batch))
                c.execute(f"SELECT code, name FROM stock_meta WHERE code IN ({ph})", batch)
                for r in c.fetchall():
                    out[r["code"]] = r["name"]
    except Exception as e:  # noqa: BLE001
        logger.debug(f"股票名映射查询失败: {e}")
    return out


def _upcoming_events(days: int = 5) -> List[Dict[str, Any]]:
    """未来 N 天财经日历要点（直接读库，日历模块未同步时静默为空）。"""
    try:
        start = datetime.now().strftime("%Y-%m-%d")
        end = (datetime.now() + timedelta(days=days)).strftime("%Y-%m-%d")
        db = get_db_manager()
        with db.get_db() as c:
            c.execute(
                "SELECT event_date, title, importance, region FROM calendar_events "
                "WHERE event_date >= ? AND event_date <= ? "
                "ORDER BY event_date ASC, importance DESC LIMIT 12",
                (start, end),
            )
            return [dict(r) for r in c.fetchall()]
    except Exception as e:  # noqa: BLE001
        logger.debug(f"日历事实查询失败: {e}")
        return []


def _sentiment_line(s: Dict[str, Any]) -> str:
    if not s:
        return ""
    parts = []
    if s.get("rise") is not None:
        parts.append(f"上涨 {s.get('rise')} / 下跌 {s.get('fall')}")
    if s.get("limit_up_now") is not None:
        parts.append(f"实时涨停 {s.get('limit_up_now')}")
    if s.get("north_flow"):
        parts.append(f"北向 {_yi(s.get('north_flow'))}")
    if s.get("turnover_now"):
        parts.append(f"成交额 {_yi(s.get('turnover_now'))}")
    return "，".join(parts)


def market_fact_to_text(facts: Dict[str, Any]) -> str:
    """把大盘事实包压成 prompt 注入文本（确定性数据，模型可直接引用）。"""
    if not facts or not facts.get("trade_date"):
        return ""
    td = facts["trade_date"]
    lines = [f"【市场事实包（程序采集于 {td} 交易日，数字真实可直接引用，不要改动）】"]

    sent = _sentiment_line(facts.get("sentiment") or {})
    if sent:
        lines.append(f"- 市场概览：{sent}")

    ladder = facts.get("ladder_top") or []
    if ladder:
        segs = []
        for r in ladder[:8]:
            name = r.get("name") or r.get("code") or ""
            h = r.get("height") or r.get("continue_num") or ""
            if name:
                segs.append(f"{name}{'（' + str(h) + '连板）' if h and str(h) not in ('0', '1') else ''}")
        lines.append(f"- 连板天梯（高度降序）：{'、'.join(segs)}")
    if facts.get("limit_up_count"):
        lines.append(f"- 当日连板股合计约 {facts['limit_up_count']} 只")

    topics = facts.get("topics_top") or []
    if topics:
        segs = [
            f"{r.get('topic_name')}（涨停 {r.get('limit_up_num')} 只，{_pct(r.get('change'))}）"
            for r in topics[:6]
            if r.get("topic_name")
        ]
        lines.append(f"- 最强风口题材：{'；'.join(segs)}")

    fs = facts.get("flow_summary") or {}
    if fs.get("total"):
        lines.append(
            f"- 资金面：全市场净流入 {fs.get('in_cnt') or 0} 家 / 净流出 {fs.get('out_cnt') or 0} 家，"
            f"主力净额合计 {_yi(fs.get('main_sum'))}，机构参与度均值 "
            f"{round(float(fs.get('org_avg') or 0), 1)}%"
        )

    name_map = facts.get("name_map") or {}
    fin = facts.get("flow_in_top") or []
    if fin:
        segs = [
            f"{name_map.get(r.get('code'), r.get('code'))} {_yi(r.get('main_net'))}"
            for r in fin[:6]
        ]
        lines.append(f"- 主力净流入 Top：{'、'.join(segs)}")
    fout = facts.get("flow_out_top") or []
    if fout:
        segs = [
            f"{name_map.get(r.get('code'), r.get('code'))} {_yi(r.get('main_net'))}"
            for r in fout[:5]
        ]
        lines.append(f"- 主力净流出 Top：{'、'.join(segs)}")

    sectors = facts.get("sector_heat_top") or []
    if sectors:
        segs = [
            f"{r.get('sector_name')}（均值 {_pct(r.get('avg_pct'))}，主力 {_yi(r.get('main_net'))}）"
            for r in sectors[:6]
        ]
        lines.append(f"- 行业热度（按主力净额）：{'；'.join(segs)}")

    bb = facts.get("billboard_top") or []
    if bb:
        segs = [
            f"{name_map.get(r.get('code'), r.get('code'))}（{r.get('reason') or '龙虎榜'}，"
            f"净买 {_yi(r.get('net_amount'))}）"
            for r in bb[:5]
        ]
        lines.append(f"- 龙虎榜要点：{'；'.join(segs)}")

    ms = facts.get("margin_summary") or {}
    if ms.get("total"):
        lines.append(
            f"- 两融：融资余额 {_yi(ms.get('fin_balance_sum'))}，当日融资净买入 {_yi(ms.get('fin_net_sum'))}"
        )

    events = facts.get("upcoming_events") or []
    if events:
        segs = [f"{r.get('event_date')} {r.get('title')}" for r in events[:6] if r.get("title")]
        lines.append(f"- 未来数日重要日程：{'；'.join(segs)}")

    return "\n".join(lines) + "\n"


# ============================================================
# 个股事实包（个股深度报告 / @标的对话用）
# ============================================================
def stock_fact_pack(code: str) -> Dict[str, Any]:
    """聚合单只标的的事实档案：行情、资金、两融、涨跌停记录、龙虎榜、板块、关联新闻。"""
    code = (code or "").strip()
    out: Dict[str, Any] = {"code": code, "found": False}
    if not code:
        return out
    if market_store is None:
        return out
    profile = _safe(market_store.get_stock_profile, {}, code) or {}
    if not profile:
        return out
    out["found"] = True
    out["meta"] = profile.get("meta") or {}
    out["money_flow"] = profile.get("money_flow") or {}
    out["margin"] = profile.get("margin") or {}
    out["limit_records"] = (profile.get("limit_records") or [])[:5]
    out["billboard"] = (profile.get("billboard") or [])[:5]
    out["sectors"] = profile.get("sectors") or []
    out["news"] = (profile.get("news") or [])[:12]
    bars = profile.get("bars") or []
    out["bars_recent"] = bars[-10:]
    # 近期个股舆情热度
    if sentiment_store is not None:
        out["sentiment"] = _safe(
            sentiment_store.get_stock_sentiment, [], code
        ) or []
    return out


def stock_fact_to_text(facts: Dict[str, Any]) -> str:
    if not facts or not facts.get("found"):
        return ""
    meta = facts.get("meta") or {}
    name = meta.get("name") or facts.get("code", "")
    code = facts.get("code", "")
    lines = [f"【个股事实包（程序采集，数字真实可直接引用，不要改动）】{name}（{code}）"]

    mf = facts.get("money_flow") or {}
    if mf:
        lines.append(
            f"- 最新行情（{mf.get('trade_date') or '-'}）：收盘 {mf.get('close_price') or '-'}，"
            f"涨跌幅 {_pct(mf.get('pct_chg'))}，换手率 {mf.get('turnover') or '-'}%，"
            f"主力净流入 {_yi(mf.get('main_net'))}，机构参与度 {mf.get('org_participate') or '-'}%"
        )
    margin = facts.get("margin") or {}
    if margin:
        lines.append(
            f"- 两融（{margin.get('trade_date') or '-'}）：融资余额 {_yi(margin.get('fin_balance'))}，"
            f"融资净买入 {_yi(margin.get('fin_net'))}"
        )
    sectors = facts.get("sectors") or []
    if sectors:
        names = [s.get("sector_name") for s in sectors if s.get("sector_name")][:8]
        if names:
            lines.append(f"- 所属板块：{'、'.join(names)}")
    limits = facts.get("limit_records") or []
    if limits:
        segs = [
            f"{r.get('trade_date')}{'涨停' if r.get('direction') == 'up' else '跌停'}"
            f"{('（' + str(r.get('reason') or '') + '）') if r.get('reason') else ''}"
            for r in limits
        ]
        lines.append(f"- 近期涨跌停记录：{'；'.join(segs)}")
    bb = facts.get("billboard") or []
    if bb:
        segs = [f"{r.get('trade_date')} {r.get('reason') or ''}净买 {_yi(r.get('net_amount'))}" for r in bb[:3]]
        lines.append(f"- 龙虎榜记录：{'；'.join(segs)}")
    bars = facts.get("bars_recent") or []
    if len(bars) >= 2:
        last = bars[-1]
        closes = [float(b.get("close") or 0) for b in bars if b.get("close")]
        if closes:
            chg = (closes[-1] / closes[0] - 1) * 100 if closes[0] else 0
            lines.append(
                f"- 近 {len(closes)} 个交易日：区间涨跌 {_pct(chg)}，最新收盘 {last.get('close')}（{last.get('trade_date')}）"
            )
    sent = facts.get("sentiment") or []
    if sent:
        latest = sent[0] if isinstance(sent[0], dict) else None
        if latest:
            lines.append(
                f"- 个股舆情：热度 {latest.get('heat') or '-'}，提及 {latest.get('mention_count') or '-'} 次，"
                f"情绪 {latest.get('label') or latest.get('sentiment_score') or '-'}"
            )
    news = facts.get("news") or []
    if news:
        lines.append("- 近期关联新闻（标题）：")
        for n in news[:8]:
            lines.append(f"  · [{n.get('publish_time') or ''}] {n.get('title')}")
    return "\n".join(lines) + "\n"


# ============================================================
# 舆情事实包（舆情研判报告用）
# ============================================================
def sentiment_fact_pack() -> Dict[str, Any]:
    """聚合舆情层数据：市场情绪、个股热度榜、板块情绪、论坛情绪。"""
    out: Dict[str, Any] = {}
    if sentiment_store is None:
        return out
    out["market"] = _safe(sentiment_store.get_market_sentiment, None) or {}
    heat_date = None
    if market_store is not None:
        heat_date = _safe(market_store.latest_date, None, "stock_sentiment")
    if heat_date:
        out["top_heat"] = (_safe(sentiment_store.get_top_heat_stocks, [], heat_date, limit=15) or [])[:15]
    else:
        out["top_heat"] = []
    out["forum"] = _safe(sentiment_store.get_forum_sentiment, None) or {}
    try:
        db = get_db_manager()
        with db.get_db() as c:
            c.execute(
                "SELECT sector_name, sentiment_score, heat FROM sector_sentiment "
                "ORDER BY heat DESC LIMIT 8"
            )
            out["sectors"] = [dict(r) for r in c.fetchall()]
    except Exception as e:  # noqa: BLE001
        out["sectors"] = []
        logger.debug(f"板块情绪查询失败: {e}")
    codes = [r.get("code") for r in out["top_heat"] if r.get("code")]
    out["name_map"] = _stock_names(codes)
    return out


def sentiment_fact_to_text(facts: Dict[str, Any]) -> str:
    if not facts:
        return ""
    lines = ["【舆情事实包（程序采集，数字真实可直接引用，不要改动）】"]
    m = facts.get("market") or {}
    if m:
        lines.append(
            f"- 市场情绪指数：{m.get('sentiment_index') or '-'}（{m.get('trade_date') or ''}），"
            f"新闻情绪 {m.get('news_sentiment') or '-'}，市场宽度 {m.get('breadth') or '-'}"
        )
    heat = facts.get("top_heat") or []
    if heat:
        name_map = facts.get("name_map") or {}
        segs = [
            f"{name_map.get(r.get('code'), r.get('code'))}（热度 {r.get('heat') or '-'}，"
            f"{r.get('label') or r.get('sentiment_score') or '-'}，提及 {r.get('mention_count') or '-'}）"
            for r in heat[:10]
        ]
        lines.append(f"- 舆情热度个股 Top：{'、'.join(segs)}")
    sectors = facts.get("sectors") or []
    if sectors:
        segs = [f"{r.get('sector_name')}（{r.get('label') or r.get('sentiment_score') or '-'}）" for r in sectors[:6]]
        lines.append(f"- 板块情绪：{'、'.join(segs)}")
    forum = facts.get("forum") or {}
    if forum:
        lines.append(
            f"- 论坛情绪（{forum.get('trade_date') or ''}）："
            f"正面 {forum.get('positive') or 0} / 中性 {forum.get('neutral') or 0} / "
            f"负面 {forum.get('negative') or 0}"
        )
    return "\n".join(lines) + "\n"
