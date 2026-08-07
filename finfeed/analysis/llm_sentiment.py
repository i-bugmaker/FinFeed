#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""LLM 情感增强（方案D，P4）

post-market 对当日高影响力新闻做一次 LLM 多空情感精修，写入 stock_sentiment(source='llm')，
经现有聚合与 tdx(方案E)/新闻(方案B) 融合为板块/全市场情绪。

设计：
  - 实时流水线仍用词典法（analysis/sentiment.py）保证盘中低延迟；
  - 盘后由 agent 批量调用 LLM（单次）对 Top-K 新闻判分，得到更准的个股情感；
  - 单只股票可能被多条新闻提及，按新闻得分均值聚合。
  - LLM 调用由 agent 在盘后快照层执行（进程内调不到 LLM API，且需理解语义）。
"""

import json
import logging
from typing import Dict, List, Optional

from finfeed.analysis.snapshot import get_stock_name
from finfeed.storage import sentiment_store as ss
from finfeed.storage.database import get_db_manager
from finfeed.utils.time_utils import now_bj

logger = logging.getLogger("news_monitor")

LLM_SOURCE = "llm"


def select_top_news_for_llm(trade_date: Optional[str] = None, k: int = 50,
                            min_importance: float = 0.0) -> List[Dict]:
    """取当日影响力 Top-K 且带个股的新闻，供 agent 批量送 LLM 判分。

    Returns: [{id, title, intro, stocks, importance}]
    """
    td = trade_date or now_bj().strftime("%Y-%m-%d")
    db = get_db_manager()
    with db.get_db() as c:
        c.execute(
            "SELECT id, title, intro, stocks, importance FROM news "
            "WHERE date(publish_time) = ? AND stocks IS NOT NULL AND stocks != '[]' "
            "AND importance >= ? ORDER BY importance DESC LIMIT ?",
            (td, min_importance, k),
        )
        return [dict(r) for r in c.fetchall()]


def apply_llm_news_scores(news_score_map: Dict[int, float],
                          trade_date: Optional[str] = None) -> int:
    """把 LLM 返回的 {news_id: 情感分(-1..1)} 聚合到个股，写入 stock_sentiment(source='llm')。

    每只被提及股票：sentiment_score = 其相关新闻得分均值（截断[-1,1]）。
    Returns: 写入个股数。
    """
    td = trade_date or now_bj().strftime("%Y-%m-%d")
    if not news_score_map:
        return 0
    ids = list(news_score_map.keys())
    placeholders = ",".join("?" * len(ids))
    db = get_db_manager()
    with db.get_db() as c:
        c.execute(
            f"SELECT id, stocks FROM news WHERE id IN ({placeholders})", ids
        )
        rows = c.fetchall()
    if not rows:
        logger.warning("LLM 新闻分映射不到任何新闻，跳过")
        return 0
    acc: Dict[str, List[float]] = {}
    for r in rows:
        s = float(news_score_map.get(r["id"], 0.0))
        try:
            codes = json.loads(r["stocks"])
        except Exception:
            continue
        for code in codes:
            if code not in acc:
                acc[code] = [0.0, 0]
            acc[code][0] += s
            acc[code][1] += 1
    recs = []
    for code, (ssum, cnt) in acc.items():
        score = max(-1.0, min(1.0, ssum / cnt)) if cnt else 0.0
        label = "positive" if score > 0.2 else ("negative" if score < -0.2 else "neutral")
        recs.append({
            "code": code, "name": get_stock_name(code), "trade_date": td,
            "sentiment_score": round(score, 4), "sentiment_label": label,
            "heat": round(cnt, 2), "mention_count": cnt,
            "pos_mentions": int(ssum > 0), "neg_mentions": int(ssum < 0),
            "source": LLM_SOURCE,
        })
    n = ss.upsert_stock_sentiment(recs)
    logger.info(f"LLM 情感精修 {td}：写入 {n} 只个股（source=llm）")
    return n


if __name__ == "__main__":
    import argparse
    p = argparse.ArgumentParser(description="LLM 情感增强（方案D）")
    p.add_argument("--select", action="store_true", help="输出待 LLM 判分的 Top 新闻 JSON")
    p.add_argument("--apply", type=str, default="", help="读取 {id:score} JSON 落库")
    p.add_argument("--date", type=str, default="")
    p.add_argument("--top", type=int, default=50)
    args = p.parse_args()
    td = args.date or now_bj().strftime("%Y-%m-%d")
    if args.select:
        items = select_top_news_for_llm(td, k=args.top)
        logger.info(json.dumps(items, ensure_ascii=False, indent=2))
    elif args.apply:
        with open(args.apply, "r", encoding="utf-8") as f:
            m = {int(k): float(v) for k, v in json.load(f).items()}
        logger.info(f"写入个股数: {apply_llm_news_scores(m, td)}")
    else:
        p.print_help()
