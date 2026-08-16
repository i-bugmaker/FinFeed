#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""富途牛牛港美股快讯 解析器

使用富途官网资讯站公开 JSON 接口（news.futunn.com），无需登录。
端点：GET https://news.futunn.com/news-site-api/main/get-flash-list
支持 pageSize 与 seqMark 游标分页；pageSize 实测最大可取 50。
"""

import asyncio
import logging

import httpx

from finfeed.storage.models import NewsItem
from finfeed.utils.time_utils import bj_str_from_ts

from ..base import CATCH_UP_MIN_INTERVAL, BaseParser

logger = logging.getLogger("news_monitor")


def _ts_from_futu_time(value: object) -> int:
    """将富途快讯时间字段转为 Unix 秒级时间戳（容忍毫秒级数值）"""
    if value is None:
        return 0
    try:
        ts = int(value)
    except (TypeError, ValueError):
        return 0
    if ts > 1_000_000_000_000:
        ts //= 1000
    return ts


class FutuParser(BaseParser):
    """富途牛牛快讯 - news.futunn.com 公开 JSON API"""

    async def parse(self, response: httpx.Response) -> list[NewsItem]:
        news_list = []
        try:
            data = response.json()
        except ValueError:
            logger.warning("富途牛牛快讯：响应非 JSON")
            return news_list
        if data.get("code") != 0:
            logger.warning(f"富途牛牛快讯：接口返回 code={data.get('code')}")
            return news_list
        payload = data.get("data") or {}
        inner = payload.get("data") or {}
        items = inner.get("news") or []
        for item in items:
            if not isinstance(item, dict):
                continue
            title_raw = (item.get("title") or "").strip()
            content = (item.get("content") or "").strip()
            title = title_raw or content
            if not title:
                continue
            ts = _ts_from_futu_time(item.get("time"))
            if ts and ts <= self.last_ts:
                continue
            pt = bj_str_from_ts(ts) if ts else ""
            url = item.get("detailUrl") or "#"
            news_list.append(self._make_news(
                title=title[:80],
                url=url,
                publish_ts=ts,
                publish_time=pt,
                intro=content[:150] if title_raw else "",
            ))
        return news_list

    async def fetch_with_catch_up(self, http_client) -> list[NewsItem]:
        """补抓模式：通过 seqMark 游标分页获取历史数据"""
        if not self._catch_up_mode or self.last_ts <= 0:
            return []

        logger.info("富途牛牛快讯补抓模式：开始游标分页补抓")
        all_news = []
        catch_up_start_ts = self.get_catch_up_start_ts()
        seq_mark = ""

        saved_last_ts = self.last_ts
        self.last_ts = 0

        try:
            for _ in range(15):
                try:
                    params = dict(self.source.params)
                    params["pageSize"] = 50
                    if seq_mark:
                        params["seqMark"] = seq_mark

                    resp = await http_client.get(
                        self.source.url,
                        headers=dict(self.source.headers),
                        params=params,
                    )
                    if resp.status_code != 200:
                        logger.warning(f"富途牛牛快讯补抓请求失败：HTTP {resp.status_code}")
                        break

                    news_list = await self.parse(resp)
                    if not news_list:
                        break
                    all_news.extend(news_list)

                    try:
                        body = resp.json()
                        inner = (body.get("data") or {}).get("data") or {}
                        seq_mark = inner.get("seqMark") or ""
                    except ValueError:
                        break
                    if not seq_mark:
                        break

                    oldest_ts = min(
                        (n.publish_ts for n in news_list if n.publish_ts > 0), default=0
                    )
                    if oldest_ts <= catch_up_start_ts:
                        break

                    await asyncio.sleep(CATCH_UP_MIN_INTERVAL)
                except Exception as e:
                    logger.warning(f"富途牛牛快讯补抓失败：{str(e)[:80]}")
                    break
        finally:
            self.last_ts = saved_last_ts

        filtered = [n for n in all_news if n.publish_ts > catch_up_start_ts]
        if filtered:
            self.last_ts = max(n.publish_ts for n in filtered if n.publish_ts > 0)
        filtered.sort(key=lambda x: x.publish_ts, reverse=True)
        logger.info(f"富途牛牛快讯补抓完成：共获取{len(filtered)}条历史新闻")

        return filtered
