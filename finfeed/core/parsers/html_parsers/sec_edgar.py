#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""SEC EDGAR 公告解析器

数据源：
- 主端点：https://www.sec.gov/cgi-bin/browse-edgar?action=getcurrent&output=atom
  （Atom XML，返回最近 N 条指定表单类型申报，含精确美东时间与归档索引链接）
- 补抓端点：https://efts.sec.gov/LATEST/search-index（全文检索 JSON，支持按日期范围过滤）

SEC 为美国证券交易委员会官方披露源，公开数据无版权限制，但要求：
- User-Agent 必须带联系信息（如 "FinFeed research contact@finfeed.example.com"）
- 请求频率不超过 10 req/s，本解析器使用礼貌间隔

- 条目 URL：归档索引 https://www.sec.gov/Archives/edgar/data/{cik}/{accession-no}/
- 时间：feed 中为美东时间（EDT/EST 带时区偏移），解析后转为北京时间
- 保守策略：正常模式单次请求（count 默认 40），补抓按日期范围分页回溯最多 7 天
"""

import asyncio
import logging
import re
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple

import httpx

from finfeed.storage.models import NewsItem
from finfeed.utils.time_utils import TZ_BJ, bj_str_from_ts

from ..base import BaseParser

logger = logging.getLogger("news_monitor")

ATOM_NS = "http://www.w3.org/2005/Atom"

SEC_ATOM_URL = "https://www.sec.gov/cgi-bin/browse-edgar"
SEC_SEARCH_URL = "https://efts.sec.gov/LATEST/search-index"
SEC_ARCHIVE_BASE = "https://www.sec.gov/Archives/edgar/data"

DEFAULT_FORM_TYPE = "8-K"
DEFAULT_COUNT = 40
CATCH_UP_PAGE_SIZE = 100
CATCH_UP_SLEEP = 0.5


def _default_ua() -> str:
    """默认 User-Agent（带联系信息，满足 SEC 要求）"""
    return "FinFeed research contact@finfeed.example.com"


class SecEdgarParser(BaseParser):
    """SEC EDGAR 最新申报解析器（Atom XML）"""

    def __init__(self, source):
        super().__init__(source)
        self._catch_up_mode = False
        self._catch_up_end_ts = 0

    def set_catch_up_mode(self, enabled: bool, end_ts: int = 0) -> None:
        """设置补抓模式"""
        self._catch_up_mode = enabled
        self._catch_up_end_ts = end_ts

    # 参数与解析辅助
    def _headers(self) -> Dict[str, str]:
        """构造请求头：合并 source 配置，确保 UA 带联系信息"""
        headers = dict(self.source.headers or {})
        ua = headers.get("User-Agent") or _default_ua()
        if "contact@" not in ua and "@" not in ua:
            ua = f"{ua} ({_default_ua()})"
        headers["User-Agent"] = ua
        return headers

    def _form_type(self) -> str:
        """读取配置的表单类型（默认 8-K）"""
        params = self.source.params or {}
        return str(params.get("type") or DEFAULT_FORM_TYPE)

    def _build_atom_params(self, count: int) -> Dict[str, str]:
        """构造 getcurrent Atom 订阅请求参数"""
        return {
            "action": "getcurrent",
            "type": self._form_type(),
            "company": "",
            "dateb": "",
            "owner": "include",
            "count": str(count),
            "output": "atom",
        }

    @staticmethod
    def _parse_updated(updated: str) -> Tuple[int, str]:
        """解析 Atom updated 时间（美东带时区偏移）并转北京时间"""
        try:
            dt = datetime.fromisoformat(updated.strip())
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone(timedelta(hours=-5)))
            ts = int(dt.astimezone(TZ_BJ).timestamp())
            return ts, bj_str_from_ts(ts)
        except (ValueError, TypeError):
            return 0, ""

    @staticmethod
    def _extract_company(title: str) -> str:
        """从标题提取公司名：'8-K - Precipio, Inc. (0001043961) (Filer)' -> 'Precipio, Inc.'"""
        m = re.search(r"-\s+(.+?)\s+\(\d{10}\)\s*\(Filer\)", title)
        if m:
            return m.group(1).strip()
        return ""

    @staticmethod
    def _summary_items(summary: str) -> str:
        """从 summary 提取 Item 清单（如 'Item 2.02: Results of Operations...'）"""
        if not summary:
            return ""
        text = re.sub(r"<[^>]+>", "", summary)
        text = text.replace("&nbsp;", " ")
        lines = [ln.strip() for ln in text.split("\n") if ln.strip()]
        items = [ln for ln in lines if ln.startswith("Item ")]
        return " | ".join(items[:3])

    def _entry_to_news(self, entry: ET.Element) -> Optional[NewsItem]:
        """将 Atom 单条 entry 转换为 NewsItem"""
        ns = {"a": ATOM_NS}
        title_el = entry.find("a:title", ns)
        if title_el is None or not (title_el.text or "").strip():
            return None
        title = title_el.text.strip()

        link = None
        for link_el in entry.findall("a:link", ns):
            if link_el.get("rel") == "alternate":
                link = link_el.get("href")
                break
        if not link:
            return None
        url = link if link.startswith("http") else "https://www.sec.gov" + link

        updated_el = entry.find("a:updated", ns)
        ts, pt = self._parse_updated(updated_el.text or "") if updated_el is not None else (0, "")
        if ts <= 0:
            return None
        # 增量过滤：时间戳早于或等于上次更新时间则跳过
        if not self._catch_up_mode and ts and ts <= self.last_ts:
            return None

        summary_el = entry.find("a:summary", ns)
        if summary_el is not None and summary_el.text:
            summary = summary_el.text
        else:
            summary = ""

        company = self._extract_company(title)
        items = self._summary_items(summary)
        intro_parts = []
        if company:
            intro_parts.append(company)
        if self._form_type():
            intro_parts.append(self._form_type())
        if items:
            intro_parts.append(items)
        intro = " | ".join(p for p in intro_parts if p)

        return self._make_news(
            title=title[:80],
            url=url,
            publish_ts=ts,
            publish_time=pt,
            intro=intro[:150],
        )

    # 主解析入口（Atom XML）
    async def fetch_normal(self, http_client) -> list[NewsItem]:
        """正常模式：请求 getcurrent Atom feed，单次获取 DEFAULT_COUNT 条。

        覆盖框架 `_make_request`：SEC 需要 `action=getcurrent` 等专用参数，
        而 `source.params` 仅用于配置表单类型，不能直接作为请求参数。
        """
        try:
            resp = await http_client.get(
                SEC_ATOM_URL,
                headers=self._headers(),
                params=self._build_atom_params(DEFAULT_COUNT),
            )
            if resp.status_code != 200:
                logger.warning(f"SEC EDGAR 正常抓取失败：HTTP {resp.status_code}")
                return []
            return await self.parse(resp)
        except Exception as e:
            logger.warning(f"SEC EDGAR 正常抓取异常：{str(e)[:100]}")
            return []

    async def parse(self, response: httpx.Response) -> list[NewsItem]:
        """解析 EDGAR getcurrent Atom XML 响应"""
        news_list: list[NewsItem] = []
        try:
            root = ET.fromstring(response.content)
        except ET.ParseError as e:
            logger.warning(f"SEC EDGAR Atom 解析失败: {str(e)[:80]}")
            return []

        ns = {"a": ATOM_NS}
        for entry in root.findall("a:entry", ns):
            try:
                news = self._entry_to_news(entry)
            except Exception as e:
                logger.debug(f"SEC EDGAR 单条解析失败: {str(e)[:80]}")
                continue
            if news is not None:
                news_list.append(news)
        return news_list

    # 补抓支持（全文检索 JSON，按日期范围分页）
    def _build_search_params(self, start_date: str, end_date: str, page: int) -> Dict[str, str]:
        """构造全文检索参数（日期格式 YYYY-MM-DD）"""
        return {
            "q": self._form_type(),
            "dateRange": "custom",
            "startdt": start_date,
            "enddt": end_date,
            "forms": self._form_type(),
            "page": str(page),
        }

    def _search_to_news(self, src: Dict[str, Any], form_type: str) -> Optional[NewsItem]:
        """将全文检索单条 _source 记录转换为 NewsItem（仅日期粒度）"""
        adsh = src.get("adsh") or ""
        ciks = src.get("ciks") or []
        file_date = src.get("file_date") or ""
        if not adsh or not ciks or not file_date:
            return None
        cik = str(ciks[0]).lstrip("0") or "0"
        url = f"{SEC_ARCHIVE_BASE}/{cik}/{adsh}/"

        # 仅提供文件日期（无精确时间），取美东当日 12:00 为近似时间
        try:
            dt = datetime.strptime(file_date, "%Y-%m-%d").replace(hour=12)
            dt_et = dt.replace(tzinfo=timezone(timedelta(hours=-5)))
            ts = int(dt_et.astimezone(TZ_BJ).timestamp())
            pt = bj_str_from_ts(ts)
        except (ValueError, TypeError):
            return None

        display_names = src.get("display_names") or []
        company = display_names[0] if display_names else ""
        items = " | ".join(str(i) for i in (src.get("items") or [])[:3])
        intro_parts = []
        if company:
            intro_parts.append(company)
        if form_type:
            intro_parts.append(form_type)
        if items:
            intro_parts.append(f"Item {items}")
        intro = " | ".join(p for p in intro_parts if p)

        title = (company or f"{form_type} - {file_date}")
        return self._make_news(
            title=title[:80],
            url=url,
            publish_ts=ts,
            publish_time=pt,
            intro=intro[:150],
        )

    async def _search_page(self, http_client, start_date: str, end_date: str, page: int) -> Tuple[List[NewsItem], int]:
        """请求单页全文检索结果，返回 (news, total_hits)"""
        resp = await http_client.get(
            SEC_SEARCH_URL,
            headers=self._headers(),
            params=self._build_search_params(start_date, end_date, page),
        )
        if resp.status_code != 200:
            logger.warning(f"SEC EDGAR 补抓请求失败：HTTP {resp.status_code}")
            return [], 0
        try:
            data = resp.json()
        except (ValueError, TypeError):
            return [], 0
        total = int((data.get("hits") or {}).get("total", {}).get("value", 0) or 0)
        hits = (data.get("hits") or {}).get("hits") or []
        news_list: list[NewsItem] = []
        for h in hits:
            src = h.get("_source") or {}
            try:
                news = self._search_to_news(src, self._form_type())
            except Exception as e:
                logger.debug(f"SEC EDGAR 补抓单条解析失败: {str(e)[:80]}")
                continue
            if news is not None:
                news_list.append(news)
        return news_list, total

    async def fetch_with_catch_up(self, http_client) -> list[NewsItem]:
        """补抓模式：按日期范围分页回溯（最多 7 天）"""
        if not self._catch_up_mode or self.last_ts <= 0:
            return []

        catch_up_start_ts = self.get_catch_up_start_ts()
        start_date = datetime.fromtimestamp(catch_up_start_ts, tz=TZ_BJ).date()
        end_date = datetime.now(TZ_BJ).date()

        logger.info(f"SEC EDGAR 补抓模式：{start_date} 至 {end_date}")

        all_news: list[NewsItem] = []
        try:
            page = 1
            while page <= 15:
                news, total = await self._search_page(
                    http_client, start_date.strftime("%Y-%m-%d"), end_date.strftime("%Y-%m-%d"), page
                )
                all_news.extend(news)
                if not news or page * CATCH_UP_PAGE_SIZE >= total:
                    break
                page += 1
                await asyncio.sleep(CATCH_UP_SLEEP)
        except Exception as e:
            logger.warning(f"SEC EDGAR 补抓失败：{str(e)[:80]}")

        all_news = [n for n in all_news if n.publish_ts > catch_up_start_ts]
        # 去重（按 URL）
        seen: set[str] = set()
        deduped: list[NewsItem] = []
        for n in all_news:
            if n.url in seen:
                continue
            seen.add(n.url)
            deduped.append(n)
        deduped.sort(key=lambda x: x.publish_ts, reverse=True)
        if deduped:
            self.last_ts = max(n.publish_ts for n in deduped if n.publish_ts > 0)
        logger.info(f"SEC EDGAR 补抓完成：共获取 {len(deduped)} 条申报")
        return deduped
