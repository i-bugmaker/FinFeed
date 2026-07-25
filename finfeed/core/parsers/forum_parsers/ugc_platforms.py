#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""新增舆情UGC平台解析器：同花顺论股堂、微博财经热搜"""

import re
import logging
from typing import Optional
from datetime import datetime
from urllib.parse import quote as urlquote

import httpx
from bs4 import BeautifulSoup, Tag

from .base import BaseHtmlForumParser, BaseJsonForumParser
from finfeed.utils.time_utils import now_bj, TZ_BJ, bj_str_from_ts
from .utils import extract_stocks_from_text, parse_forum_time

logger = logging.getLogger("news_monitor")

FINANCE_KEYWORDS = [
    '股', '基', '基金', 'A股', '沪指', '深成指', '创业板', '科创板', '北证', '北交所',
    '涨', '跌', '牛市', '熊市', '大盘', '板块', '证券', '券商', '银行', '保险',
    '地产', '楼市', '房价', '新能源', '芯片', '半导体', 'AI', '人工智能', '科技', '算力', '光模块',
    '央行', '降息', '加息', '降准', '经济', '贸易', '关税', '人民币', '汇率', '美元',
    '外资', '北向', '南向', '港股', '美股', '纳斯达克', '道琼斯', '标普',
    '黄金', '原油', '期货', '期权', '转债', '打新', '新股', '次新',
    '茅台', '宁德', '比亚迪', '涨停', '跌停', '利好', '利空',
    '抄底', '割肉', '套牢', '踏空', '洗盘', '拉升', '砸盘', '出货',
    '仓位', '满仓', '空仓', '建仓', '加仓', '减仓', '止盈', '止损',
    '业绩', '财报', '分红', '回购', '增持', '减持', '重组', '并购', '借壳',
    'IPO', '注册制', '退市', 'ST', '龙虎榜', '北向资金', '融资融券',
    '光伏', '储能', '锂电池', '医药', '消费', '白酒', '军工', '机器人',
    '石油', '石化', '煤炭', '钢铁', '有色', '电力',
    '两市', '成交额', '成交量', '指数', '上证', '深证',
    '央行', 'MLF', 'LPR', '社融', 'PMI', 'GDP', 'CPI', 'PPI',
    '数字经济', '数据要素', '信创', '国产替代',
    '台风', '灾难', '疫情', '政策', '监管', '证监会', '银保监',
]

PROMO_PATTERNS = [
    '不作为买卖依据', 'VIP', '内部群', '盘中策略', '扫码', '关注公众号',
    '加微信', '加群', '推荐股票', '牛股', '涨停板', '免费领取',
    '公播所', '投资顾问', '投顾', '开户', '佣金',
]


class ThsLoungeParser(BaseHtmlForumParser):
    """同花顺论股堂UGC帖子 - https://t.10jqka.com.cn/
    真正的散户讨论内容，word-content中有用户发言原文"""

    item_selectors = ["li.feed-item"]
    title_selectors = [".word-content"]
    link_selectors = [".feed-item-title a"]
    time_selectors = [".feed-item-timeline-time"]
    intro_selectors = []

    async def parse(self, response: httpx.Response) -> list:
        news_list = []
        self._seen_urls.clear()
        try:
            html_text = response.text
            if not html_text or len(html_text) < 500:
                for enc in ["utf-8", "gb2312", "gbk"]:
                    try:
                        html_text = response.content.decode(enc)
                        break
                    except (UnicodeDecodeError, LookupError):
                        continue
            if self._is_empty_page(html_text, min_links=10):
                logger.info(f"{self.source.name}页面为空，尝试浏览器渲染")
                browser_html = await self._try_browser_render()
                if browser_html:
                    html_text = browser_html
            news_list = self._parse_html(html_text)
        except Exception as e:
            logger.warning(f"{self.source.name}解析失败: {str(e)[:80]}")
        news_list.sort(key=lambda x: x.publish_ts, reverse=True)
        return news_list

    def _parse_html(self, html_text: str) -> list:
        news_list = []
        soup = BeautifulSoup(html_text, "lxml")
        items = soup.select("li.feed-item")
        if not items:
            items = soup.select(".feed-item")
        now_dt = now_bj()
        for item in items:
            try:
                if "hide" in item.get("class", []):
                    continue
                news = self._parse_ths_item(item, now_dt)
                if news:
                    news_list.append(news)
            except Exception:
                continue
        return news_list

    def _is_promo(self, text: str) -> bool:
        for pat in PROMO_PATTERNS:
            if pat in text:
                return True
        return False

    def _parse_ths_item(self, item: Tag, now_dt) -> Optional[object]:
        content_el = item.select_one(".word-content")
        if not content_el:
            return None
        content_text = content_el.get_text(strip=True)
        content_text = re.sub(r'\s+', ' ', content_text).strip()
        if not content_text or len(content_text) < 6:
            return None
        if self._is_promo(content_text):
            return None

        href = ""
        pid = item.get("data-pid", "")
        link_el = item.select_one(".feed-item-title a[href]")
        if link_el:
            href = link_el.get("href", "")
        if not href:
            for a in item.find_all("a", href=True):
                h = a.get("href", "")
                if "circle/" in h or "post/" in h or "topic/" in h:
                    href = h
                    break
        if not href and pid:
            href = f"http://t.10jqka.com.cn/circle/{pid}/"
        if not href or "javascript:" in href:
            if pid:
                href = f"http://t.10jqka.com.cn/circle/{pid}/"
            else:
                return None

        title = content_text[:80]
        intro = content_text[80:200] if len(content_text) > 80 else ""

        ts = 0
        date_str = item.get("data-date", "")
        time_el = item.select_one(".feed-item-timeline-time")
        time_text = time_el.get_text(strip=True) if time_el else ""
        if date_str and time_text and re.match(r'\d{4}', date_str):
            try:
                month = int(date_str[:2])
                day = int(date_str[2:4])
                t_parts = time_text.split(":")
                hour = int(t_parts[0])
                minute = int(t_parts[1]) if len(t_parts) > 1 else 0
                year = now_dt.year
                dt = datetime(year, month, day, hour, minute, tzinfo=TZ_BJ)
                now_ts = now_dt.replace(tzinfo=TZ_BJ).timestamp()
                if dt.timestamp() > now_ts + 3600:
                    dt = dt.replace(year=year - 1)
                ts = int(dt.timestamp())
            except (ValueError, IndexError):
                pass
        if ts <= 0 and time_text:
            ts = parse_forum_time(time_text)
        if ts <= 0:
            ts = int(now_dt.replace(tzinfo=TZ_BJ).timestamp())

        extra_stocks = extract_stocks_from_text(content_text)

        return self._build_news_item(
            title=title,
            url=href,
            publish_ts=ts,
            intro=intro,
            extra_stocks=extra_stocks,
        )

    def _parse_item(self, item: Tag, soup: BeautifulSoup) -> Optional[object]:
        return None


class WeiboFinanceParser(BaseJsonForumParser):
    """微博财经热搜 - https://weibo.com/ajax/side/hotSearch
    筛选财经相关热搜词，反映散户关注焦点"""

    data_path = ["data", "realtime"]
    title_key = "word"
    url_key = "word"
    time_key = ""
    intro_key = "label_name"
    time_is_timestamp = False

    async def parse(self, response: httpx.Response) -> list:
        news_list = []
        self._seen_urls.clear()
        try:
            data = response.json()
            items = data.get("data", {}).get("realtime", [])
            if not isinstance(items, list):
                items = []
            now_ts = int(now_bj().replace(tzinfo=TZ_BJ).timestamp())
            rank = 0
            for item in items:
                try:
                    if not isinstance(item, dict):
                        continue
                    word = item.get("word", "") or item.get("note", "")
                    if not word or len(word) < 2:
                        continue
                    if not self._is_finance_related(word):
                        continue
                    rank += 1
                    label = item.get("label_name", "") or ""
                    num = item.get("num", 0) or item.get("raw_hot", 0)
                    ontop = item.get("is_fei", 0) or item.get("flag", 0) or item.get("is_hot", 0)
                    intro_parts = []
                    if label:
                        intro_parts.append(f"[{label}]")
                    if num:
                        intro_parts.append(f"热度:{num}")
                    if rank <= 3:
                        intro_parts.append("🔥热搜前三")
                    if ontop:
                        intro_parts.append("置顶/热")
                    title = f"[微博热{rank}] {word}"
                    url = f"https://s.weibo.com/weibo?q=%23{urlquote(word)}%23"
                    news = self._build_news_item(
                        title=title,
                        url=url,
                        publish_ts=now_ts - rank * 10,
                        intro=" ".join(intro_parts),
                        extra_stocks=extract_stocks_from_text(word),
                    )
                    if news:
                        news_list.append(news)
                except Exception:
                    continue
        except Exception as e:
            logger.warning(f"微博热搜解析失败: {str(e)[:80]}")
        news_list.sort(key=lambda x: x.publish_ts, reverse=True)
        return news_list

    def _is_finance_related(self, word: str) -> bool:
        for kw in FINANCE_KEYWORDS:
            if kw in word:
                return True
        return False
