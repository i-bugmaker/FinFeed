#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""新闻/热搜舆情 → 个股/板块情绪（方案B，P2）

复用现有 news 表（已含 stocks / sentiment / importance / keywords）：
  - rollup_news_to_stock_sentiment()：按交易日把新闻情绪汇总到个股，
    写入 stock_sentiment(source='news')。因 stock_sentiment 主键含 source，
    与 tdx 源共存；aggregate_sector_from_stocks 不过滤 source，故板块/全市场
    温度会自动融合「新闻舆情 + tdx 听盘」双信号。
  - top_news_themes()：聚合当日热搜主题词（按 importance 加权），供报告「热搜主题」。

数据来源：news 表 publish_time 为北京时间，按 date(publish_time)=trade_date 过滤。
"""

import json
import logging
from typing import Dict, List, Optional, Tuple

from finfeed.analysis.snapshot import get_stock_name
from finfeed.storage import sentiment_store as ss
from finfeed.storage.database import get_db_manager
from finfeed.utils.time_utils import now_bj

logger = logging.getLogger("news_monitor")

NEWS_SOURCE = "news"
_SENT_MAP = {"positive": 1.0, "negative": -1.0, "neutral": 0.0}

# 论坛/聚合帖关键词噪声，主题抽取时剔除（仅影响热搜主题，不影响逐股情绪）
_JUNK_SUBSTR = ["浏览", "评论", "股友", "人气", "向标", "基民", "日电", "散户",
               "洗盘", "回本", "实盘", "炒股", "日记", "感谢", "老欧", "老天",
               "作手", "小芳", "忙忙碌", "买包包", "有希望", "排名稳定", "感觉要",
               "这个月", "盘面", "收盘点评", "股市怎么看", "市场活跃", "操作风格",
               "以下特征", "呈现", "该营业部", "席位", "风向标",
               "财联社", "金十", "东方财富"]


def rollup_news_to_stock_sentiment(trade_date: Optional[str] = None) -> int:
    """把当日新闻/论坛帖情绪汇总为个股情绪，写入 stock_sentiment(source='news')。

    每只被提及股票：sentiment_score = Σ(sentiment×importance) / Σimportance（截断[-1,1]）；
    heat = Σimportance；mention_count = 新闻条数。
    Returns: 写入个股数。
    """
    td = trade_date or now_bj().strftime("%Y-%m-%d")
    db = get_db_manager()
    with db.get_db() as c:
        c.execute(
            "SELECT stocks, sentiment, importance FROM news "
            "WHERE date(publish_time) = ? AND stocks IS NOT NULL AND stocks != '[]'",
            (td,),
        )
        rows = c.fetchall()
    if not rows:
        logger.info(f"{td} 无带 stocks 的新闻，跳过新闻舆情汇总")
        return 0

    acc: Dict[str, List[float]] = {}  # code -> [wsum, wsum_s, pos, neg, cnt]
    for r in rows:
        try:
            codes = json.loads(r["stocks"])
        except Exception:
            continue
        if not codes:
            continue
        s = _SENT_MAP.get((r["sentiment"] or "neutral"), 0.0)
        w = float(r["importance"]) if r["importance"] else 1.0
        for code in codes:
            if code not in acc:
                acc[code] = [0.0, 0.0, 0, 0, 0]
            acc[code][0] += w
            acc[code][1] += s * w
            if s > 0:
                acc[code][2] += 1
            elif s < 0:
                acc[code][3] += 1
            acc[code][4] += 1

    recs = []
    for code, (wsum, wsum_s, pos, neg, cnt) in acc.items():
        score = max(-1.0, min(1.0, wsum_s / wsum)) if wsum else 0.0
        label = "positive" if score > 0.2 else ("negative" if score < -0.2 else "neutral")
        recs.append({
            "code": code, "name": get_stock_name(code), "trade_date": td,
            "sentiment_score": round(score, 4), "sentiment_label": label,
            "heat": round(wsum, 2), "mention_count": cnt,
            "pos_mentions": pos, "neg_mentions": neg, "source": NEWS_SOURCE,
        })
    n = ss.upsert_stock_sentiment(recs)
    logger.info(f"新闻舆情汇总 {td}：写入 {n} 只个股（来源 news）")
    return n


def top_news_themes(trade_date: Optional[str] = None, limit: int = 20) -> List[Tuple[str, float, int]]:
    """当日热搜主题词（按 importance 加权聚合），返回 [(theme, imp_sum, count)] 降序。"""
    td = trade_date or now_bj().strftime("%Y-%m-%d")
    db = get_db_manager()
    with db.get_db() as c:
        # 仅取资讯类来源，剔除股吧/人气榜/热帖等论坛噪声关键词
        c.execute(
            "SELECT keywords, importance FROM news "
            "WHERE date(publish_time) = ? AND keywords IS NOT NULL AND keywords != '[]' "
            "AND source NOT LIKE '%股吧%' AND source NOT LIKE '%人气榜%' "
            "AND source NOT LIKE '%热帖%'",
            (td,),
        )
        rows = c.fetchall()
    agg: Dict[str, List[float]] = {}
    for r in rows:
        try:
            kws = json.loads(r["keywords"])
        except Exception:
            continue
        w = float(r["importance"] or 1.0)
        for kw in kws:
            kw = (kw or "").strip()
            if len(kw) < 2 or len(kw) > 12:  # 过滤噪声极短/极长词
                continue
            if any(j in kw for j in _JUNK_SUBSTR):  # 剔除论坛/聚合噪声词
                continue
            if kw not in agg:
                agg[kw] = [0.0, 0]
            agg[kw][0] += w
            agg[kw][1] += 1
    items = sorted(agg.items(), key=lambda kv: kv[1][0], reverse=True)[:limit]
    return [(k, v[0], int(v[1])) for k, v in items]


if __name__ == "__main__":
    import argparse
    p = argparse.ArgumentParser(description="新闻/热搜舆情汇总")
    p.add_argument("--rollup", action="store_true", help="汇总新闻情绪到 stock_sentiment")
    p.add_argument("--themes", action="store_true", help="输出当日热搜主题")
    p.add_argument("--date", type=str, default="", help="交易日 YYYY-MM-DD")
    p.add_argument("--top", type=int, default=20)
    args = p.parse_args()
    td = args.date or now_bj().strftime("%Y-%m-%d")
    if args.rollup:
        print("写入个股数:", rollup_news_to_stock_sentiment(td))
    elif args.themes:
        for k, imp, cnt in top_news_themes(td, args.top):
            print(f"{k}\timp={imp:.1f}\tcount={cnt}")
    else:
        p.print_help()
