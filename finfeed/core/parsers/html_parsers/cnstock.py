#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""中国证券网 解析器"""

import logging
from datetime import datetime, timedelta, timezone

import httpx

from finfeed.storage.models import NewsItem
from finfeed.utils.time_utils import bj_str_from_ts

from ..base import BaseParser

logger = logging.getLogger("news_monitor")
class CNStockParser(BaseParser):
    """上海证券报 - 浏览器渲染提取DOM数据"""

    async def _fetch_with_browser(self) -> list:
        """使用浏览器渲染并提取新闻数据"""
        try:
            from playwright.async_api import async_playwright

            async with async_playwright() as p:
                browser = await p.chromium.launch(
                    headless=True,
                    args=["--disable-gpu", "--disable-dev-shm-usage", "--no-sandbox"]
                )
                page = await browser.new_page(
                    user_agent=self.source.headers.get("User-Agent", ""),
                    viewport={"width": 1920, "height": 1080}
                )

                await page.goto(self.source.url, timeout=45000)
                await page.wait_for_load_state("networkidle", timeout=20000)
                await page.wait_for_timeout(3000)

                # 在浏览器中执行JS提取新闻数据
                news_data = await page.evaluate("""
                    () => {
                        const items = document.querySelectorAll('li.ant-timeline-item');
                        const result = [];
                        let currentYear = null;
                        let currentMonth = null;
                        let currentDay = null;

                        for (const item of items) {
                            // 提取日期标签（年月日）
                            const label = item.querySelector('.ant-timeline-item-label');
                            if (label && label.textContent.trim()) {
                                const datePs = label.querySelectorAll('p.font_dina');
                                if (datePs.length >= 2) {
                                    const ym = datePs[0].textContent.trim();
                                    const d = datePs[1].textContent.trim();
                                    const parts = ym.split('.');
                                    if (parts.length >= 2) {
                                        currentYear = parseInt(parts[0]);
                                        currentMonth = parseInt(parts[1]);
                                        currentDay = parseInt(d);
                                    }
                                }
                            }

                            // 提取时间 (HH:MM)
                            let timeText = '';
                            const timeEl = item.querySelector('.ant-timeline-item-content p.font_dina');
                            if (timeEl) {
                                timeText = timeEl.textContent.trim();
                            }

                            // 提取链接和标题内容
                            const linkEl = item.querySelector('a[href*="/commonDetail/"]');
                            let url = '';
                            let title = '';
                            let content = '';

                            if (linkEl) {
                                url = linkEl.href;
                                // 查找标题span（【】包裹的文本）
                                const spans = linkEl.querySelectorAll('span');
                                for (const span of spans) {
                                    const text = span.textContent.trim();
                                    if (text.startsWith('【') && text.endsWith('】')) {
                                        title = text;
                                        // 提取内容：克隆链接元素，移除标题span和详情链接后取文本
                                        const clone = linkEl.cloneNode(true);
                                        const allSpans = clone.querySelectorAll('span');
                                        for (const s of allSpans) {
                                            const st = s.textContent.trim();
                                            if (st === text || st.includes('详情')) {
                                                s.remove();
                                            }
                                        }
                                        content = clone.textContent.trim();
                                        break;
                                    }
                                }
                                if (!title) {
                                    title = linkEl.textContent.trim().substring(0, 80);
                                }
                            }

                            if (title && timeText && url) {
                                result.push({
                                    title: title,
                                    url: url,
                                    year: currentYear,
                                    month: currentMonth,
                                    day: currentDay,
                                    time: timeText,
                                    content: content
                                });
                            }
                        }
                        return result;
                    }
                """)

                await browser.close()
                return news_data
        except Exception as e:
            logger.warning(f"上海证券报浏览器渲染失败: {str(e)[:80]}")
            return []

    async def parse(self, response: httpx.Response) -> list[NewsItem]:
        news_list = []
        bj_tz = timezone(timedelta(hours=8))
        seen_urls = set()

        try:
            items = await self._fetch_with_browser()
            logger.info(f"上海证券报浏览器提取到 {len(items)} 条新闻")

            for item in items:
                if not isinstance(item, dict):
                    continue

                title = (item.get("title") or "").strip()
                url = item.get("url", "")
                if not title or not url:
                    continue

                if url in seen_urls:
                    continue
                seen_urls.add(url)

                # 构建时间戳
                year = item.get("year")
                month = item.get("month")
                day = item.get("day")
                time_str = item.get("time", "")

                ts = 0
                pt = ""
                if year and month and day and time_str:
                    try:
                        dt_str = f"{year}-{month:02d}-{day:02d} {time_str}:00"
                        dt = datetime.strptime(dt_str, "%Y-%m-%d %H:%M:%S")
                        dt = dt.replace(tzinfo=bj_tz)
                        ts = int(dt.timestamp())
                        pt = bj_str_from_ts(ts)
                    except (ValueError, TypeError):
                        pass

                if ts <= 0:
                    continue

                if not self._catch_up_mode and ts and ts <= self.last_ts:
                    continue

                content = (item.get("content") or "").strip()

                news_list.append(self._make_news(
                    title=title[:80],
                    url=url,
                    publish_ts=ts,
                    publish_time=pt,
                    intro=content[:150],
                ))
        except Exception as e:
            logger.warning(f"上海证券报解析失败: {str(e)[:80]}")

        news_list.sort(key=lambda x: x.publish_ts, reverse=True)
        return news_list

    async def fetch_with_catch_up(self, http_client) -> list[NewsItem]:
        """补抓模式：上海证券报页面不支持分页历史，返回空"""
        return []


# 新华财经（中国金融信息网 cnfin.com）多栏目解析器

CNFIN_FLASH_QUERY_IDS = "3618537139,3618537138,3618537137,3618537136,3618537135,3618537134,3618537133,3618537132,3618537130"
CNFIN_FLASH_API = "https://api.cnfin.com/roll/query/getNewsList.htm"
CNFIN_CHANNELS = [
    {"name": "要闻", "path": "news/index.html", "type": "html"},
    {"name": "快讯", "path": "", "type": "api"},
    {"name": "独家", "path": "dj/index.html", "type": "html"},
    {"name": "宏观", "path": "macro/index.html", "type": "html"},
    {"name": "股市", "path": "stock/index.html", "type": "html"},
    {"name": "债市", "path": "bond/index.html", "type": "html"},
    {"name": "汇市", "path": "forex/index.html", "type": "html"},
    {"name": "货币", "path": "currency/index.html", "type": "html"},
    {"name": "大宗", "path": "commodity/index.html", "type": "html"},
    {"name": "丝路", "path": "silu/", "type": "html"},
    {"name": "信用", "path": "xinyong/", "type": "html"},
]
CNFIN_BASE_URL = "https://www.cnfin.com"
