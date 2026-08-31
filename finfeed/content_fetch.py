#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""原文正文抓取与后台批量补齐

针对部分信息源（如凤凰财经、界面、澎湃、和讯等）在列表接口中未携带正文，
这里提供两个互补通道：

1. 按 URL 实时抓取文章正文（``fetch_article_content``），展开详情时随查随补；
2. 后台周期性任务（``content_backfill_loop``），批量补齐库里缺正文的记录。

抓到的正文统一写入 ``news.content`` 字段，支撑离线复盘。
"""

from __future__ import annotations

import asyncio
import logging
import re

import httpx
from bs4 import BeautifulSoup

from finfeed.storage.database import (
    db_news_without_content,
    db_update_news_content,
)

logger = logging.getLogger("news_monitor")

_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)
_HEADERS = {
    "User-Agent": _UA,
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}

_TIMEOUT = httpx.Timeout(10.0)
# 每分钟后台最多补齐的条数，避免对来源站点造成压力
_BATCH_SIZE = 10
_BATCH_INTERVAL = 300  # 秒

# 常见的正文容器选择器（按优先级尝试命中）
_ARTICLE_SELECTORS = [
    "article div[class*='content']",
    "article div[class*='article']",
    "div[class*='article-content']",
    "div[class*='article_content']",
    "div[class*='content']",
    "div[class*='rich_media_content']",
    "div[class*='post-content']",
]
_RE_BLANK_LINES = re.compile(r"[ \t\u3000]+")
_RE_EMPTY_LINES = re.compile(r"\n{3,}")


def _clean_text(text: str) -> str:
    """折叠空白、去除导航/脚本残留换行，压缩为紧凑段落文本"""
    text = text.replace("\u200b", "").replace("\xa0", " ")
    text = _RE_BLANK_LINES.sub(" ", text)
    text = _RE_EMPTY_LINES.sub("\n\n", text)
    return text.strip()


def extract_readable_text(html: str) -> str:
    """从 HTML 提取可读正文文本（同步纯函数，便于单测）"""
    if not html:
        return ""
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup(["script", "style", "noscript", "iframe", "nav", "header", "footer"]):
        tag.decompose()

    # 优先在常见正文容器里拼接 <p> 文本
    for selector in _ARTICLE_SELECTORS:
        node = soup.select_one(selector)
        if not node:
            continue
        paras = [p.get_text(" ", strip=True) for p in node.find_all("p")]
        text = "\n".join(p for p in paras if p)
        if len(text) >= 30:
            return _clean_text(text)

    # 兜底：直接拼主体 <p>
    paras = [p.get_text(" ", strip=True) for p in soup.find_all("p")]
    text = "\n".join(p for p in paras if p)
    if text:
        return _clean_text(text)

    # 最后兜底：body 全部可见文本
    body = soup.body
    return _clean_text(body.get_text("\n", strip=True)) if body else ""


async def fetch_article_content(url: str, client: httpx.AsyncClient | None = None) -> str:
    """按 URL 抓取文章正文文本，失败返回空串"""
    if not url or url == "#":
        return ""
    owns = client is None
    c = client or httpx.AsyncClient(headers=_HEADERS, timeout=_TIMEOUT, follow_redirects=True)
    try:
        resp = await c.get(url)
        resp.raise_for_status()
        return extract_readable_text(resp.text)
    except Exception as e:  # noqa: BLE001
        logger.debug(f"抓取正文失败 [{url}] : {e}")
        return ""
    finally:
        if owns:
            await c.aclose()


async def backfill_content_batch(limit: int = _BATCH_SIZE, client: httpx.AsyncClient | None = None) -> int:
    """补齐一批缺失正文的记录，返回成功条数"""
    items = db_news_without_content(limit=limit)
    if not items:
        return 0
    owns = client is None
    c = client or httpx.AsyncClient(headers=_HEADERS, timeout=_TIMEOUT, follow_redirects=True)
    filled = 0
    try:
        for i, n in enumerate(items):
            content = await fetch_article_content(n.url, c)
            if content:
                db_update_news_content(n.id, content)
                filled += 1
            if i < len(items) - 1:
                await asyncio.sleep(1.0)
    finally:
        if owns:
            await c.aclose()
    if filled:
        logger.info(f"正文后台补齐：本次处理 {len(items)} 条，成功填充 {filled} 条")
    return filled


async def content_backfill_loop() -> None:
    """后台周期补齐正文（运行期间持续循环，退出后自行结束）"""
    async with httpx.AsyncClient(headers=_HEADERS, timeout=_TIMEOUT, follow_redirects=True) as client:
        while True:
            try:
                await backfill_content_batch(client=client)
            except asyncio.CancelledError:
                break
            except Exception as e:  # noqa: BLE001
                logger.debug(f"正文后台补齐异常: {e}")
            try:
                await asyncio.sleep(_BATCH_INTERVAL)
            except asyncio.CancelledError:
                break