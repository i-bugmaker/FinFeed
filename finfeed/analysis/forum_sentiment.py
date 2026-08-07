#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""散户情绪指数（自建·聚合全路 UGC 舆情源）

舆情源在「来源」维度上已由 sources.py 扩充（人气榜 / 股吧 / 热搜 / 社区帖），
本模块在「信号」维度上把它们聚合成一个可量化的全市场散户情绪指数：

  retail_index  ∈ [-1, 1]   散户多空情绪（偏多>0 / 偏空<0），按源信号强度加权
  heat          ∈ [0, 100]  散户讨论热度（条数 + 覆盖个股数，对数压缩）
  top_stocks    舆情热度 Top 个股（加权提及量 × 源信号）
  active_sources 当日产生数据的舆情源（展示名）

数据源：news 表 category='forum' 的记录（入库时已完成 sentiment/importance/stocks 计算）。
写入 forum_sentiment_daily，供复盘日报「散户情绪指数」板块与 CLI 使用。
"""

import json
import logging
from typing import Dict, List, Optional

from finfeed.analysis.snapshot import get_stock_name
from finfeed.storage import sentiment_store as ss
from finfeed.storage.database import get_db_manager
from finfeed.utils.time_utils import now_bj

logger = logging.getLogger("news_monitor")

_SENT_VAL = {"positive": 1.0, "negative": -1.0, "neutral": 0.0}

# 各舆情源（展示名）的信号权重：专业社区/人气榜 > 股吧 > 全网热搜
SOURCE_SIGNAL = {
    "东方财富": 1.2,   # 人气榜 + 热门股吧 + 动态股吧
    "雪球": 1.2,       # 专业投资社区
    "同花顺": 1.0,     # 论股堂 + 同花顺股吧
    "新浪财经": 0.8,   # 新浪股吧
    "知乎": 0.8,       # 讨论社区热榜
    "百度热搜": 0.6,   # 全网注意力（含非投资者，信号偏弱）
}
DEFAULT_SIGNAL = 1.0

# 热度标定基准：volume=300 / coverage=150 视为满热度 100
_HEAT_VOL_BASE = 301
_HEAT_COV_BASE = 151


def _signal(source: str) -> float:
    return SOURCE_SIGNAL.get(source, DEFAULT_SIGNAL)


def _label(idx: float) -> str:
    if idx > 0.2:
        return "偏多"
    if idx < -0.2:
        return "偏空"
    return "中性"


def build_forum_sentiment(trade_date: Optional[str] = None) -> Dict[str, object]:
    """聚合当日论坛舆情 → 散户情绪指数，幂等写入 forum_sentiment_daily。

    Returns:
        计算结果的 dict；无数据时返回 {}。
    """
    td = trade_date or now_bj().strftime("%Y-%m-%d")
    db = get_db_manager()
    with db.get_db() as c:
        c.execute(
            "SELECT title, source, sentiment, importance, stocks FROM news "
            "WHERE category = ? AND date(publish_time) = ?",
            ("forum", td),
        )
        rows = c.fetchall()
    if not rows:
        logger.info(f"{td} 无论坛舆情数据，跳过散户情绪指数")
        return {}

    import math
    wsum = 0.0
    wsum_s = 0.0
    up = down = neutral = 0
    stock_acc: Dict[str, List[float]] = {}   # code -> [wsum, wsum_s, cnt]
    src_set = set()

    for r in rows:
        src = r["source"] or ""
        sent = r["sentiment"] or "neutral"
        imp = float(r["importance"]) if r["importance"] else 1.0
        w = max(imp, 1.0) * _signal(src)
        v = _SENT_VAL.get(sent, 0.0)
        wsum += w
        wsum_s += v * w
        if v > 0:
            up += 1
        elif v < 0:
            down += 1
        else:
            neutral += 1
        src_set.add(src)
        try:
            codes = json.loads(r["stocks"] or "[]")
        except Exception:
            codes = []
        for code in codes:
            if not isinstance(code, str) or len(code) != 6:
                continue
            if code not in stock_acc:
                stock_acc[code] = [0.0, 0.0, 0]
            stock_acc[code][0] += w
            stock_acc[code][1] += v * w
            stock_acc[code][2] += 1

    idx = max(-1.0, min(1.0, wsum_s / wsum)) if wsum else 0.0
    volume = len(rows)
    coverage = len(stock_acc)
    heat = round(
        100.0 * min(
            1.0,
            0.7 * math.log1p(volume) / math.log(_HEAT_VOL_BASE)
            + 0.3 * math.log1p(coverage) / math.log(_HEAT_COV_BASE),
        ),
        1,
    )

    top = []
    for code, (cw, cws, cnt) in stock_acc.items():
        s = max(-1.0, min(1.0, cws / cw)) if cw else 0.0
        top.append({
            "code": code,
            "name": get_stock_name(code),
            "heat": round(cw, 2),
            "sentiment_score": round(s, 4),
            "mention_count": int(cnt),
        })
    top.sort(key=lambda x: x["heat"], reverse=True)
    top = top[:10]

    result = {
        "trade_date": td,
        "retail_index": round(idx, 4),
        "label": _label(idx),
        "heat": heat,
        "up_count": up,
        "down_count": down,
        "neutral_count": neutral,
        "volume": volume,
        "stock_coverage": coverage,
        "active_sources": sorted(src_set),
        "top_stocks": top,
    }
    ss.upsert_forum_sentiment(
        trade_date=td,
        retail_index=result["retail_index"],
        heat=heat,
        up_count=up,
        down_count=down,
        neutral_count=neutral,
        volume=volume,
        stock_coverage=coverage,
        active_sources=sorted(src_set),
        top_stocks=top,
    )
    logger.info(
        f"散户情绪指数 {td}: index={result['retail_index']:+.3f}({result['label']}) "
        f"heat={heat} vol={volume} stocks={coverage} 来源 {len(src_set)} 路"
    )
    return result


if __name__ == "__main__":
    import argparse

    p = argparse.ArgumentParser(description="散户情绪指数聚合（自建·全路UGC源）")
    p.add_argument("--date", type=str, default="", help="交易日 YYYY-MM-DD")
    p.add_argument("--show", action="store_true", help="展示最近一条已入库指数")
    args = p.parse_args()
    td = args.date or now_bj().strftime("%Y-%m-%d")
    if args.show:
        f = ss.get_forum_sentiment(td)
        if not f:
            logger.info("当日无数据；可先运行聚合或传入 --date")
        else:
            logger.info(json.dumps(f, ensure_ascii=False, indent=2))
    else:
        res = build_forum_sentiment(td)
        logger.info(json.dumps(res, ensure_ascii=False, indent=2) if res else "当日无论坛舆情数据")
