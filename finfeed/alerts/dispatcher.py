#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""新闻告警调度器 — 把抓取管线与推送渠道接线的中间层。

流程（fire-and-forget，绝不阻塞抓取管线）：
  pipeline 入库 → schedule_dispatch() → dispatch_news_alerts()
    1. 全局开关（alert_settings.enabled）
    2. 逐条匹配：
       - 自选股命中（stock_monitor.stock_watchlist ∩ news.stocks）
         → 按 watchlist_min_importance 过滤（0 = 全推）
       - 主题命中（topics 关键词）
         → 按 base_importance × 市场状态动态倍率过滤
    3. 任一命中且达到阈值的新闻，汇总后按渠道逐个推送：
       - 渠道自身 min_importance 二次过滤
       - 免打扰时段（quiet_start/quiet_end，HH:MM）跳过
       - (news_id, webhook_id) 唯一键幂等去重
       - 单条消息最多 20 条新闻
"""

from __future__ import annotations

import asyncio
import logging
from typing import List, Optional

from finfeed.alerts import store
from finfeed.alerts.subscription import match_topics_news, match_watchlist_news
from finfeed.alerts.webhook import send_webhook_news
from finfeed.storage.models import NewsItem
from finfeed.utils.time_utils import now_bj

logger = logging.getLogger("news_monitor")

# 单条推送消息包含的新闻上限（payload 构建器同样按 20 截断展示）
MAX_NEWS_PER_PUSH = 20

# fire-and-forget 任务集合（防止 Task 被 GC）
_pending_tasks: set = set()


def _in_quiet_hours(cfg: dict, now=None) -> bool:
    """判断当前时间是否处于渠道免打扰时段（支持跨零点区间，如 22:30-08:00）。"""
    start = (cfg.get("quiet_start") or "").strip()
    end = (cfg.get("quiet_end") or "").strip()
    if not start or not end:
        return False
    try:
        now = now or now_bj()
        cur = now.hour * 60 + now.minute
        sh, sm = start.split(":")[:2]
        eh, em = end.split(":")[:2]
        s = int(sh) * 60 + int(sm)
        e = int(eh) * 60 + int(em)
        if s == e:
            return False
        if s < e:
            return s <= cur < e
        return cur >= s or cur < e  # 跨零点
    except (ValueError, TypeError):
        return False


def _evaluate_news(items: List[NewsItem], settings: dict) -> tuple[List[dict], List[dict]]:
    """对一批新闻做匹配与阈值过滤。

    Returns:
        (alert_items, topics_by_id)：alert_items 元素为
        {item, matched_stocks, matched_topics}；topics_by_id 为 id→topic 映射。
    """
    from finfeed.market.alerts import threshold_multiplier

    base_threshold = settings.get("base_importance", 5.0)
    watchlist_min = settings.get("watchlist_min_importance", 0.0)
    use_regime = settings.get("use_regime", True)
    regime_mult = threshold_multiplier() if use_regime else 1.0
    topic_threshold = base_threshold * regime_mult

    topics_by_id: dict = {}
    alert_items: List[dict] = []
    for item in items:
        matched_stocks = match_watchlist_news(item.stocks or [])
        hit_watchlist = bool(matched_stocks) and item.importance >= watchlist_min
        matched_topics = match_topics_news(item.title, item.intro or "")
        hit_topic = bool(matched_topics) and item.importance >= topic_threshold
        if not (hit_watchlist or hit_topic):
            continue
        for t in matched_topics:
            topics_by_id[t["id"]] = t
        alert_items.append({
            "item": item,
            "matched_stocks": matched_stocks,
            "matched_topics": matched_topics,
        })
    return alert_items, topics_by_id


async def dispatch_news_alerts(items: List[NewsItem]) -> Optional[dict]:
    """执行一次告警分发（由 schedule_dispatch 在事件循环中调度）。"""
    if not items:
        return None

    settings = store.get_settings()
    if not settings.get("enabled"):
        return None

    channels = store.list_webhooks(enabled_only=True)
    if not channels:
        return None

    alert_items, topics_by_id = _evaluate_news(items, settings)
    if not alert_items:
        return None

    result = {"evaluated": len(items), "alerted": len(alert_items), "pushed": 0, "failed": 0}
    now = now_bj()

    for cfg in channels:
        try:
            min_importance = float(cfg.get("min_importance") or 0.0)
            candidates = [
                a for a in alert_items
                if a["item"].importance >= min_importance
            ]
            if not candidates:
                continue
            if _in_quiet_hours(cfg, now):
                logger.debug(f"渠道 {cfg['name']} 处于免打扰时段，跳过 {len(candidates)} 条")
                continue

            candidates.sort(key=lambda a: a["item"].id or 0, reverse=True)
            fresh_ids = store.filter_fresh(
                [a["item"].id for a in candidates if a["item"].id], cfg["id"]
            )
            fresh = [a for a in candidates if a["item"].id in set(fresh_ids)]
            if not fresh:
                continue

            news_list = [a["item"] for a in fresh[:MAX_NEWS_PER_PUSH]]
            all_stocks = sorted({c for a in fresh for c in a["matched_stocks"]})
            all_topics = list({t["id"]: t for a in fresh for t in a["matched_topics"]}.values())

            send_res = await send_webhook_news(news_list, [cfg], all_stocks, all_topics)
            if send_res.get("success"):
                store.record_pushed([a["item"].id for a in fresh], cfg["id"])
                result["pushed"] += 1
                logger.info(
                    f"告警推送成功 → {cfg['name']}：{len(news_list)} 条新闻"
                    f"（自选股 {all_stocks or '无'}，主题 {[t['name'] for t in all_topics] or '无'}）"
                )
            if send_res.get("failed"):
                result["failed"] += send_res["failed"]
                for d in send_res.get("details", []):
                    if not d.get("ok"):
                        logger.warning(f"告警推送失败 → {d['name']}: {d.get('error')}")
        except Exception as e:
            logger.error(f"分发到渠道 {cfg.get('name')} 异常: {e}", exc_info=True)
            result["failed"] += 1

    return result


def schedule_dispatch(items: List[NewsItem]) -> None:
    """管线钩子入口：把入库新闻调度为后台分发任务（fire-and-forget）。

    必须在事件循环内调用（pipeline.process_and_store 为 async，天然满足）。
    任何异常只记日志，不影响抓取主流程。
    """
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        logger.debug("无运行中事件循环，跳过告警分发")
        return
    task = loop.create_task(_safe_dispatch(list(items)))
    _pending_tasks.add(task)
    task.add_done_callback(_pending_tasks.discard)


async def _safe_dispatch(items: List[NewsItem]) -> None:
    try:
        await dispatch_news_alerts(items)
    except Exception as e:
        logger.error(f"告警分发任务异常: {e}", exc_info=True)
