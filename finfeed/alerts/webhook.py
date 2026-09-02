#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Webhook 告警推送

支持钉钉、企业微信、飞书、Telegram、Server酱 五种渠道的推送。
渠道配置来自 ``finfeed.alerts.store``（SQLite 持久化），本模块只负责发送。
"""

import logging
from typing import Dict, List, Optional

import httpx

from finfeed.storage.models import NewsItem

logger = logging.getLogger("news_monitor")

# 各渠道类型 -> 展示名
CHANNEL_LABELS: Dict[str, str] = {
    "dingtalk": "钉钉",
    "wecom": "企业微信",
    "feishu": "飞书",
    "telegram": "Telegram",
    "serverchan": "Server酱",
}


async def send_webhook_news(news_list: List[NewsItem], configs: List[dict],
                             matched_stocks: Optional[List[str]] = None,
                             matched_topics: Optional[List[dict]] = None) -> dict:
    """批量推送新闻到指定的渠道配置列表。

    Args:
        news_list: 新闻列表（单条消息最多展示 20 条）
        configs: 渠道配置列表（store.list_webhooks(enabled_only=True) 的返回值）
        matched_stocks: 匹配的自选股（可选）
        matched_topics: 匹配的主题（可选）

    Returns:
        推送结果统计 {success, failed, details: [{name, ok, error}]}
    """
    if not news_list or not configs:
        return {"success": 0, "failed": 0, "details": []}

    success = 0
    failed = 0
    details = []

    for config in configs:
        name = config.get("name") or f"{config.get('type')}-{config.get('id', '?')}"
        try:
            ok = await _send_to_webhook(config, news_list, matched_stocks, matched_topics)
            if ok:
                success += 1
            else:
                failed += 1
            details.append({"name": name, "ok": ok, "error": "" if ok else "非 200 响应"})
        except Exception as e:
            logger.warning(f"Webhook 推送失败 [{name}]: {e}")
            failed += 1
            details.append({"name": name, "ok": False, "error": str(e)})

    return {"success": success, "failed": failed, "details": details}


async def _send_to_webhook(config: dict, news_list: List[NewsItem],
                            matched_stocks: Optional[List[str]] = None,
                            matched_topics: Optional[List[dict]] = None) -> bool:
    """发送到单个渠道。"""
    webhook_type = config["type"]
    url = config["url"]

    if webhook_type == "dingtalk":
        payload = _build_dingtalk_payload(news_list, matched_stocks, matched_topics)
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(url, json=payload)
            return resp.status_code == 200
    if webhook_type == "wecom":
        payload = _build_wecom_payload(news_list, matched_stocks, matched_topics)
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(url, json=payload)
            return resp.status_code == 200
    if webhook_type == "feishu":
        payload = _build_feishu_payload(news_list, matched_stocks, matched_topics)
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(url, json=payload)
            return resp.status_code == 200
    if webhook_type == "telegram":
        return await _send_telegram(url, config.get("extra") or "", news_list,
                                     matched_stocks, matched_topics)
    if webhook_type == "serverchan":
        return await _send_serverchan(url, news_list, matched_stocks, matched_topics)

    logger.warning(f"不支持的 Webhook 类型: {webhook_type}")
    return False


async def _send_telegram(base_url: str, chat_id: str, news_list: List[NewsItem],
                          matched_stocks: Optional[List[str]],
                          matched_topics: Optional[List[dict]]) -> bool:
    """Telegram Bot API。base_url 形如 https://api.telegram.org/bot<TOKEN>，chat_id 存 extra。"""
    if not chat_id:
        logger.warning("Telegram 渠道缺少 chat_id（extra 字段）")
        return False
    lines = ["📰 *财经新闻速递*"]
    if matched_stocks:
        lines.append(f"🔔 自选股关注: {', '.join(matched_stocks)}")
    if matched_topics:
        topic_names = [t["name"] for t in matched_topics]
        lines.append(f"📌 主题命中: {', '.join(topic_names)}")
    for i, news in enumerate(news_list[:20], 1):
        lines.append(f"{i}. [{_md_escape(news.title)}]({news.url})")
        lines.append(f"   来源: {news.source} | {news.publish_time}")
    if len(news_list) > 20:
        lines.append(f"... 还有 {len(news_list) - 20} 条")
    text = "\n".join(lines)
    async with httpx.AsyncClient(timeout=10.0) as client:
        resp = await client.post(
            f"{base_url.rstrip('/')}/sendMessage",
            json={"chat_id": chat_id, "text": text, "parse_mode": "Markdown",
                  "disable_web_page_preview": True},
        )
        return resp.status_code == 200


async def _send_serverchan(url: str, news_list: List[NewsItem],
                            matched_stocks: Optional[List[str]],
                            matched_topics: Optional[List[dict]]) -> bool:
    """Server酱（sctapi.ftqq.com/<SENDKEY>.send），form 编码 title + desp(markdown)。"""
    title = f"财经新闻速递（{len(news_list)}条）"
    lines = []
    if matched_stocks:
        lines.append(f"🔔 自选股关注: {', '.join(matched_stocks)}")
    if matched_topics:
        topic_names = [t["name"] for t in matched_topics]
        lines.append(f"📌 主题命中: {', '.join(topic_names)}")
    for i, news in enumerate(news_list[:20], 1):
        lines.append(f"**{i}. [{news.title}]({news.url})**")
        lines.append(f"> 来源: {news.source} | {news.publish_time}\n")
    if len(news_list) > 20:
        lines.append(f"\n... 还有 {len(news_list) - 20} 条")
    desp = "\n".join(lines)
    async with httpx.AsyncClient(timeout=10.0) as client:
        resp = await client.post(url, data={"title": title, "desp": desp})
        return resp.status_code == 200


def _md_escape(text: str) -> str:
    """Telegram Markdown 转义（仅标题文本中易出现的字符）。"""
    for ch in ("*", "_", "[", "]", "(", ")", "`", "~"):
        text = text.replace(ch, f"\\{ch}")
    return text


# Payload 构建器

def make_test_news() -> NewsItem:
    """构造测试消息条目（供 API 层「测试发送」使用）。"""
    return NewsItem(
        title="【测试】FinFeed 告警推送连通性测试",
        url="#",
        source="FinFeed",
        publish_time="",
        intro="如果你看到这条消息，说明该渠道配置正确。",
    )

def _build_dingtalk_payload(news_list: List[NewsItem],
                             matched_stocks: Optional[List[str]] = None,
                             matched_topics: Optional[List[dict]] = None) -> dict:
    """构建钉钉 Markdown 消息"""
    title = f"📰 财经新闻速递 ({len(news_list)}条)"
    lines = [f"### {title}\n"]

    if matched_stocks:
        lines.append(f"🔔 **自选股关注**: {', '.join(matched_stocks)}\n")
    if matched_topics:
        topic_names = [t["name"] for t in matched_topics]
        lines.append(f"📌 **主题命中**: {', '.join(topic_names)}\n")

    for i, news in enumerate(news_list[:20], 1):
        lines.append(f"**{i}. [{news.title}]({news.url})**")
        lines.append(f"> 来源: {news.source} | {news.publish_time}\n")

    if len(news_list) > 20:
        lines.append(f"\n... 还有 {len(news_list) - 20} 条新闻")

    text = "\n".join(lines)

    return {
        "msgtype": "markdown",
        "markdown": {
            "title": title,
            "text": text,
        }
    }


def _build_wecom_payload(news_list: List[NewsItem],
                          matched_stocks: Optional[List[str]] = None,
                          matched_topics: Optional[List[dict]] = None) -> dict:
    """构建企业微信 Markdown 消息"""
    lines = [f"## 📰 财经新闻速递（{len(news_list)}条）\n"]

    if matched_stocks:
        lines.append(f"> 🔔 自选股关注：<font color=\"warning\">{', '.join(matched_stocks)}</font>\n")
    if matched_topics:
        topic_names = [t["name"] for t in matched_topics]
        lines.append(f"> 📌 主题命中：<font color=\"info\">{', '.join(topic_names)}</font>\n")

    for i, news in enumerate(news_list[:20], 1):
        lines.append(f"**{i}. [{news.title}]({news.url})**")
        lines.append(f"> 来源：{news.source} | {news.publish_time}\n")

    if len(news_list) > 20:
        lines.append(f"\n... 还有 {len(news_list) - 20} 条新闻")

    content = "\n".join(lines)

    return {
        "msgtype": "markdown",
        "markdown": {
            "content": content,
        }
    }


def _build_feishu_payload(news_list: List[NewsItem],
                           matched_stocks: Optional[List[str]] = None,
                           matched_topics: Optional[List[dict]] = None) -> dict:
    """构建飞书富文本消息"""
    title = f"📰 财经新闻速递（{len(news_list)}条）"

    content = []

    if matched_stocks:
        content.append([
            {"tag": "text", "text": f"🔔 自选股关注：{', '.join(matched_stocks)}\n"}
        ])
    if matched_topics:
        topic_names = [t["name"] for t in matched_topics]
        content.append([
            {"tag": "text", "text": f"📌 主题命中：{', '.join(topic_names)}\n"}
        ])

    for i, news in enumerate(news_list[:20], 1):
        content.append([
            {"tag": "text", "text": f"{i}. "},
            {"tag": "a", "text": news.title, "href": news.url},
        ])
        content.append([
            {"tag": "text", "text": f"   来源：{news.source} | {news.publish_time}\n"}
        ])

    if len(news_list) > 20:
        content.append([
            {"tag": "text", "text": f"\n... 还有 {len(news_list) - 20} 条新闻"}
        ])

    return {
        "msg_type": "post",
        "content": {
            "post": {
                "zh_cn": {
                    "title": title,
                    "content": content,
                }
            }
        }
    }
