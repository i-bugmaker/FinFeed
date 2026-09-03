#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""东方财富研报流 解析器

数据源：https://reportapi.eastmoney.com/report/list（JSONP 分页接口，qType=0 个股研报）。

- 响应为 JSONP 包装（datatable({...})），需剥壳后 json.loads；
- 研报列表位于顶层 data 字段（list[dict]），字段含 title / stockName / stockCode /
  orgName / orgSName / publishDate / infoCode / emRatingName / ratingChange /
  reportType / author / market；
- 文章落地页：https://data.eastmoney.com/report/zw_stock.jshtml?infocode={infoCode}；
- 增量策略：beginTime/endTime 取昨天与今天（东财时间），补抓时按天窗口逐日回补，
  每个窗口内以 pageNo 翻页抓最近研报。
"""

import json
import logging
import re
from datetime import datetime, timedelta

import httpx

from finfeed.storage.models import NewsItem
from finfeed.utils.time_utils import TZ_BJ, bj_str_from_ts, now_bj, ts_from_bj_str

from ..base import BaseParser

logger = logging.getLogger("news_monitor")

_RE_JSONP = re.compile(r"^\w+\((.*)\)$", re.DOTALL)

_REPORT_URL = "https://reportapi.eastmoney.com/report/list"
_ARTICLE_URL = "https://data.eastmoney.com/report/zw_stock.jshtml?infocode={info_code}"

_PAGE_SIZE = 50
_MAX_PAGES = 5


class EmResearchParser(BaseParser):
    """东方财富研报流 - JSONP 分页接口（qType=0 个股研报）"""

    def _build_params(self, begin_time: str, end_time: str) -> dict:
        """构造研报列表请求参数（beginTime/endTime 为东财时间 YYYY-MM-DD）"""
        return {
            "cb": "datatable",
            "industryCode": "*",
            "pageSize": str(_PAGE_SIZE),
            "industry": "*",
            "rating": "*",
            "ratingChange": "*",
            "beginTime": begin_time,
            "endTime": end_time,
            "pageNo": "1",
            "fields": "",
            "qType": "0",
            "orgCode": "",
            "code": "*",
            "rcode": "",
        }

    async def fetch_normal(self, http_client) -> list[NewsItem]:
        """正常模式：抓昨天至今天的个股研报（单页 pageNo=1）。

        覆盖框架 `_make_request`：接口需 beginTime/endTime/qType 等动态参数，
        `source.params` 为空，无参 GET 会触发 HTTP 400。
        """
        end = now_bj().date()
        begin = end - timedelta(days=1)
        try:
            resp = await http_client.get(
                _REPORT_URL,
                headers=dict(self.source.headers),
                params=self._build_params(begin.strftime("%Y-%m-%d"), end.strftime("%Y-%m-%d")),
            )
            if resp.status_code != 200:
                logger.warning(f"{self.source.name} 正常抓取失败：HTTP {resp.status_code}")
                return []
            return await self.parse(resp)
        except Exception as e:
            logger.warning(f"{self.source.name} 正常抓取异常：{str(e)[:100]}")
            return []

    async def parse(self, response: httpx.Response) -> list[NewsItem]:
        """解析 JSONP 响应，返回研报新闻列表"""
        news_list = []
        m = _RE_JSONP.match(response.text)
        if not m:
            logger.warning(f"{self.source.name} 响应不是 JSONP 格式，跳过")
            return news_list
        try:
            data = json.loads(m.group(1))
        except json.JSONDecodeError as e:
            logger.warning(f"{self.source.name} JSON 解析失败：{str(e)[:80]}")
            return news_list
        for a in data.get("data") or []:
            title = (a.get("title") or "").strip()
            if not title:
                continue
            ts = ts_from_bj_str(a.get("publishDate", ""))
            if ts and ts <= self.last_ts:
                continue
            pt = bj_str_from_ts(ts) if ts else ""
            info_code = a.get("infoCode", "")
            url = _ARTICLE_URL.format(info_code=info_code) if info_code else "#"
            org_name = (a.get("orgName") or a.get("orgSName") or "").strip()
            rating = (a.get("emRatingName") or "").strip()
            if org_name and rating:
                intro = f"{org_name}·{rating}"
            elif org_name:
                intro = org_name
            else:
                intro = rating
            news_list.append(self._make_news(
                title=title[:80],
                url=url,
                publish_ts=ts,
                publish_time=pt,
                intro=intro[:150],
            ))
        return news_list

    async def fetch_with_catch_up(self, http_client) -> list[NewsItem]:
        """补抓模式：按天窗口逐日回补（beginTime/endTime 递增回补），窗口内 pageNo 翻页"""
        if not self._catch_up_mode or self.last_ts <= 0:
            return []

        all_news = []
        catch_up_start_ts = self.get_catch_up_start_ts()
        start_date = datetime.fromtimestamp(catch_up_start_ts, tz=TZ_BJ).date()
        day = now_bj().date()
        while day >= start_date:
            begin = day - timedelta(days=1)
            params = self._build_params(begin.strftime("%Y-%m-%d"), day.strftime("%Y-%m-%d"))
            news = await self._catch_up_paginated(
                http_client,
                _REPORT_URL,
                params,
                page_param="pageNo",
                max_pages=_MAX_PAGES,
                items_per_page=_PAGE_SIZE,
            )
            all_news.extend(news)
            day = begin

        all_news.sort(key=lambda x: x.publish_ts, reverse=True)
        logger.info(f"{self.source.name}补抓完成：共获取{len(all_news)}条历史研报")
        return all_news
