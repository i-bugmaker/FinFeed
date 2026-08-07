#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""金融界 解析器"""

import logging
import asyncio
import httpx
from ..base import BaseParser, CATCH_UP_MIN_INTERVAL
from finfeed.storage.models import NewsItem
from finfeed.utils.time_utils import ts_from_bj_str
logger = logging.getLogger("news_monitor")
class JrjParser(BaseParser):
    """金融界（jrj.com.cn）7×24小时快讯 - JSON API

    数据源页面: https://24h.jrj.com.cn/newsFlash?jrjbq
    后端接口(POST): https://gateway.jrj.com/jrj-news/news/queryNewsFlash
    必需请求头: Content-Type=application/json, productId=6000021, Referer=https://24h.jrj.com.cn/
    请求体: {} 取最新20条；翻页传 {"makeDate": "<上一批最后一条的 makeDate>"}
    响应结构: {"code":20000,"data":{"total":N,"data":[{iiId,title,makeDate,pcInfoUrl,detail,summary,paperMediaSource,stockList,...}]}}
    说明: 金融界快讯 title 字段常为空，改用 detail 正文作为标题；paperMediaSource 标注原始来源（如"金十数据"）。
    """

    async def parse(self, response: httpx.Response) -> list[NewsItem]:
        news_list: list[NewsItem] = []
        try:
            data = response.json()
        except Exception:
            return []
        payload = data.get("data") or {}
        items = payload.get("data") or []
        for a in items:
            make_date = (a.get("makeDate") or "").strip()
            ts = ts_from_bj_str(make_date) if make_date else 0
            if ts and ts <= self.last_ts:
                continue
            detail = (a.get("detail") or "").strip()
            title = (a.get("title") or "").strip()
            if not title:
                title = detail  # 标题常为空，回退到正文首句
            if not title:
                continue
            url = (a.get("pcInfoUrl") or a.get("infoUrl") or a.get("minfoUrl") or "#").strip()
            paper = (a.get("paperMediaSource") or "").strip()
            intro = detail[:150]
            if paper and paper not in title:
                intro = f"[{paper}] {detail}"[:150]
            news_list.append(self._make_news(
                title=title[:80],
                url=url,
                publish_ts=ts,
                publish_time=make_date,
                intro=intro,
            ))
        return news_list

    async def fetch_with_catch_up(self, http_client) -> list[NewsItem]:
        """补抓模式：金融界接口基于 makeDate 游标分页（后端无 page 参数）

        每页返回 20 条（最新在前），翻页时携带上一页最后一条的 makeDate 即可回溯，
        天然契合 7 天补抓窗口。
        """
        if not self._catch_up_mode or self.last_ts <= 0:
            return []
        logger = self._get_logger()
        logger.info(f"{self.source.name}补抓模式：开始游标分页补抓")
        all_news: list[NewsItem] = []
        seen: set = set()
        make_date_cursor = ""
        catch_up_start_ts = self.get_catch_up_start_ts()
        saved_last_ts = self.last_ts
        self.last_ts = 0  # 临时清零，避免 parse 增量过滤把历史条目误删
        try:
            for _ in range(20):
                body = {"makeDate": make_date_cursor} if make_date_cursor else {"makeDate": ""}
                try:
                    resp = await http_client.post(
                        self.source.url,
                        headers=dict(self.source.headers),
                        json=body,
                    )
                except Exception as e:
                    logger.warning(f"{self.source.name}补抓请求失败：{str(e)[:80]}")
                    break
                if resp.status_code != 200:
                    break
                news_list = await self.parse(resp)
                if not news_list:
                    break
                for n in news_list:
                    if n.publish_ts <= catch_up_start_ts:
                        continue
                    if n.publish_time in seen:
                        continue
                    seen.add(n.publish_time)
                    all_news.append(n)
                last = news_list[-1]
                if last.publish_time and last.publish_time != make_date_cursor:
                    make_date_cursor = last.publish_time
                else:
                    break  # 游标无进展，避免死循环
                if len(news_list) < 20:
                    break  # 已到末页
                await asyncio.sleep(CATCH_UP_MIN_INTERVAL)
        finally:
            self.last_ts = saved_last_ts
        all_news.sort(key=lambda x: x.publish_ts, reverse=True)
        if all_news:
            self.last_ts = max(n.publish_ts for n in all_news if n.publish_ts > 0)
        logger.info(f"{self.source.name}补抓完成：共获取{len(all_news)}条历史新闻")
        return all_news
