#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""新闻处理管道

处理流程: 解析 -> 字段清洗 -> 股票格式验证 -> 情感分析 -> 重要性评分 -> 多级去重 -> 入库/合并
"""

import logging
import math
import re
import time
from typing import List, Optional

from finfeed.analysis.importance import compute_importance
from finfeed.analysis.sentiment import analyze_sentiment_async
from finfeed.analysis.text_analyzer import extract_keywords_simple
from finfeed.config.sources import get_article_display_names, get_flash_display_names
from finfeed.core.dedup import deduplicate, get_dedup_engine
from finfeed.core.parsers.forum_parsers.utils import extract_stocks_from_text
from finfeed.storage.database import db_insert_news, db_merge_duplicate, db_update_stock_meta
from finfeed.storage.models import NewsItem
from finfeed.utils.hash_utils import compute_normalized_title_hash, compute_simhash, simhash_to_hex

logger = logging.getLogger("news_monitor")

_dedup_initialized = False

STOCK_CODE_PATTERN = re.compile(r'^(?:SH|SZ|BJ)?[036][0-9]{5}$|^[48][0-9]{5}$')
STOCK_CODE_RAW_PATTERN = re.compile(r'\b(60\d{4}|688\d{3}|00\d{4}|30\d{4})\b')


def _clean_title(title: str) -> str:
    if not title:
        return ""
    title = re.sub(r'\s+', ' ', title).strip()
    return title


def _clean_intro(intro: str) -> str:
    if not intro:
        return ""
    intro = re.sub(r'<[^>]+>', '', intro)
    intro = re.sub(r'\s+', ' ', intro).strip()
    if len(intro) > 500:
        intro = intro[:500] + "..."
    return intro


def _boost_importance_with_meta(imp: float, meta: Optional[dict]) -> float:
    """解析器侧 meta 信号增强重要性评分（0-10）。

    用于同花顺股吧 JSON（互动量）与同花顺热股榜（排名）等扩展字段：
      - rank 存在时：以排名直接映射重要性（覆盖文本特征分，热股榜无正文语义）
      - 互动量(likes/replies/forwards/shares)：log 压缩后叠加，体现散户情绪强度
      - is_v（认证大V）：轻微降权，抑制投顾/带节奏噪声
    结果截断到 [0, 10]。meta 为空时透传原分。
    """
    if not meta:
        return imp
    try:
        # 1) 热股榜排名信号：rank1≈10.0，rank100≈1.0（线性区分头部）
        rank = meta.get("rank")
        if isinstance(rank, int) and rank > 0:
            imp = max(1.0, 10.0 - (rank - 1) * 0.1)
        # 2) 股吧互动量信号：叠加情绪强度
        eng = sum(int(meta.get(k, 0) or 0) for k in ("likes", "replies", "forwards", "shares"))
        if eng > 0:
            imp += min(4.0, math.log1p(eng) * 0.8)
        # 3) 认证大V：轻微降权
        if meta.get("is_v"):
            imp *= 0.9
        return round(max(0.0, min(10.0, imp)), 1)
    except Exception:
        return imp


def _validate_stocks(raw_stocks: List[str]) -> List[str]:
    if not raw_stocks:
        return []
    valid_stocks = []
    seen = set()
    for s in raw_stocks:
        if not s:
            continue
        s = s.strip()
        if s in seen:
            continue
        if STOCK_CODE_PATTERN.match(s) or STOCK_CODE_RAW_PATTERN.match(s):
            valid_stocks.append(s)
            seen.add(s)
    return valid_stocks


def _validate_timestamp(ts: int, source: str = "") -> int:
    now_ts = int(time.time())
    if ts <= 0:
        return now_ts
    if ts > now_ts + 86400:
        return now_ts
    if ts < 946656000:
        return now_ts
    return ts


async def process_news_items(raw_items: List[NewsItem], source_name: str = "") -> List[NewsItem]:
    if not raw_items:
        return []

    processed: List[NewsItem] = []

    for item in raw_items:
        try:
            if not item.title:
                continue
            item.title = _clean_title(item.title)
            if not item.title:
                continue

            if not item.url:
                item.url = "#"

            if item.intro:
                item.intro = _clean_intro(item.intro)

            if not item.source:
                item.source = source_name

            if not item.category:
                # 兜底：解析器未打标时，按来源展示名归属分类。
                # 快讯展示名（财联社/金十数据/东方财富/…）→ "flash"；
                # 文章展示名（新浪财经/华尔街见闻/巨潮公告/…）→ "article"；
                # 其余（含 UGC 论坛源）→ "forum"。
                if item.source in get_flash_display_names():
                    item.category = "flash"
                elif item.source in get_article_display_names():
                    item.category = "article"
                else:
                    item.category = "forum"

            item.publish_ts = _validate_timestamp(item.publish_ts, item.source)

            if item.stocks:
                item.stocks = _validate_stocks(item.stocks)
                if item.stocks and (item.category == "forum" or source_name == "xueqiu"):
                    extracted = extract_stocks_from_text(f"{item.title} {item.intro}", max_count=5)
                    stock_name_map = {s["code"]: s["name"] for s in extracted if s.get("name")}
                    if stock_name_map:
                        db_update_stock_meta(stock_name_map)

            if not item.keywords:
                try:
                    item.keywords = extract_keywords_simple(f"{item.title} {item.intro}", top_n=8)
                except Exception as e:
                    logger.debug(f"关键词提取失败 [{item.source}]: {e}")
                    item.keywords = []

            if item.sentiment == "neutral" or not item.sentiment:
                try:
                    item.sentiment = await analyze_sentiment_async(item)
                except Exception as e:
                    logger.debug(f"情感分析失败 [{item.source}]: {e}")
                    item.sentiment = "neutral"

            try:
                item.importance = compute_importance(
                    title=item.title,
                    intro=item.intro or "",
                    source=item.source or "",
                    stocks_count=len(item.stocks) if item.stocks else 0
                )
            except Exception as e:
                logger.debug(f"重要性评分失败 [{item.source}]: {e}")
                item.importance = 5.0

            # 解析器侧 meta 信号增强（同花顺股吧互动量 / 热股榜排名）
            try:
                item.importance = _boost_importance_with_meta(item.importance, item.meta)
            except Exception:
                pass

            # 计算去重用哈希
            item.title_hash = compute_normalized_title_hash(item.title)
            content_for_hash = f"{item.title} {item.intro[:200]}" if item.intro else item.title
            item.content_simhash = simhash_to_hex(compute_simhash(content_for_hash))

            processed.append(item)
        except Exception as e:
            logger.debug(f"处理新闻条目异常 [{source_name}]: {e}")
            continue

    return processed


def _init_dedup_engine():
    """初始化去重引擎（启动时从数据库加载历史数据预热）"""
    global _dedup_initialized
    if _dedup_initialized:
        return
    _dedup_initialized = True
    # 依赖倒置：core 层把 analysis 的打分实现注入 storage（见 storage/ports.py），
    # storage 自身不感知 analysis 包，消除 storage -> analysis 反向依赖。
    try:
        from finfeed.analysis.importance import compute_importance
        from finfeed.storage.database import get_db_manager
        get_db_manager().set_importance_scorer(compute_importance)
    except Exception as e:
        logger.warning(f"重要性打分器注入失败（存储侧将使用兜底逻辑）: {e}")
    try:
        from finfeed.storage.database import db_get_recent_for_dedup
        recent_news = db_get_recent_for_dedup(limit=5000)
        engine = get_dedup_engine()
        engine.load_from_db(recent_news)
        logger.info(f"多级去重引擎初始化完成，已加载 {len(recent_news)} 条历史新闻")
    except Exception as e:
        logger.warning(f"去重引擎预热失败（不影响运行）: {e}")


async def process_and_store(raw_items: List[NewsItem], source_name: str = "") -> int:
    """处理新闻并存储（含多级去重）

    Returns:
        新增新闻数量（合并重复的不计入，但会更新主记录）
    """
    processed = await process_news_items(raw_items, source_name)
    if not processed:
        return 0

    # 同批次内简单去重
    processed = deduplicate(processed)
    if not processed:
        return 0

    # 初始化去重引擎（首次调用时预热）
    _init_dedup_engine()

    # 使用多级去重引擎
    engine = get_dedup_engine()
    new_items, merge_pairs, stats = engine.deduplicate_batch(processed)

    # 合并重复项到数据库主记录
    merged_count = 0
    for dup_item, primary in merge_pairs:
        if primary.id and primary.id > 0:
            if db_merge_duplicate(dup_item, primary.id):
                merged_count += 1

    # 插入新条目
    inserted, count = db_insert_news(new_items)

    # 更新去重引擎中的news_id
    if inserted:
        engine.update_after_insert(inserted)
        # 告警分发（fire-and-forget）：自选股/主题订阅命中 → webhook 推送
        try:
            from finfeed.alerts.dispatcher import schedule_dispatch
            schedule_dispatch(inserted)
        except Exception as e:
            logger.debug(f"告警分发调度失败（不影响入库）: {e}")

    if count > 0 or merged_count > 0:
        logger.debug(
            f"[{source_name}] 处理完成: 新增 {count} 条, 合并重复 {merged_count} 条 "
            f"(L1={stats['l1']} L2={stats['l2']} L3={stats['l3']} L4={stats['l4']})"
        )

    return count
