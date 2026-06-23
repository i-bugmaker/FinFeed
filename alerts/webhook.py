#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Webhook 告警推送

支持钉钉、企业微信、飞书等平台的 Webhook 推送。
"""

import json
import logging
import httpx
from typing import Optional

from storage.models import NewsItem

logger = logging.getLogger("news_monitor")

# Webhook 配置（后续可移到配置文件）
_webhook_configs: list[dict] = []


def add_webhook(webhook_type: str, url: str, name: str = "") -> None:
    """添加 Webhook 配置

    Args:
        webhook_type: 类型 (dingtalk/wecom/feishu)
        url: Webhook URL
        name: 配置名称
    """
    _webhook_configs.append({
        "type": webhook_type.lower(),
        "url": url,
        "name": name or f"{webhook_type}-{len(_webhook_configs)+1}",
        "enabled": True,
    })


def clear_webhooks() -> None:
    """清空所有 Webhook 配置"""
    global _webhook_configs
    _webhook_configs = []


def get_webhooks() -> list[dict]:
    """获取所有 Webhook 配置"""
    return list(_webhook_configs)


async def send_webhook_news(news_list: list[NewsItem], matched_stocks: list[str] = None,
                             matched_topics: list[dict] = None) -> dict:
    """批量推送新闻到所有已配置的 Webhook

    Args:
        news_list: 新闻列表
        matched_stocks: 匹配的自选股（可选）
        matched_topics: 匹配的主题（可选）

    Returns:
        推送结果统计 {成功数, 失败数}
    """
    if not news_list or not _webhook_configs:
        return {"success": 0, "failed": 0}

    success = 0
    failed = 0

    for config in _webhook_configs:
        if not config.get("enabled", True):
            continue
        try:
            ok = await _send_to_webhook(config, news_list, matched_stocks, matched_topics)
            if ok:
                success += 1
            else:
                failed += 1
        except Exception as e:
            logger.warning(f"Webhook 推送失败 [{config['name']}]: {e}")
            failed += 1

    return {"success": success, "failed": failed}


async def _send_to_webhook(config: dict, news_list: list[NewsItem],
                            matched_stocks: list[str] = None,
                            matched_topics: list[dict] = None) -> bool:
    """发送到单个 Webhook"""
    webhook_type = config["type"]
    url = config["url"]

    if webhook_type == "dingtalk":
        payload = _build_dingtalk_payload(news_list, matched_stocks, matched_topics)
    elif webhook_type == "wecom":
        payload = _build_wecom_payload(news_list, matched_stocks, matched_topics)
    elif webhook_type == "feishu":
        payload = _build_feishu_payload(news_list, matched_stocks, matched_topics)
    else:
        logger.warning(f"不支持的 Webhook 类型: {webhook_type}")
        return False

    async with httpx.AsyncClient(timeout=10.0) as client:
        resp = await client.post(url, json=payload)
        return resp.status_code == 200


def _build_dingtalk_payload(news_list: list[NewsItem],
                             matched_stocks: list[str] = None,
                             matched_topics: list[dict] = None) -> dict:
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


def _build_wecom_payload(news_list: list[NewsItem],
                          matched_stocks: list[str] = None,
                          matched_topics: list[dict] = None) -> dict:
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


def _build_feishu_payload(news_list: list[NewsItem],
                           matched_stocks: list[str] = None,
                           matched_topics: list[dict] = None) -> dict:
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
