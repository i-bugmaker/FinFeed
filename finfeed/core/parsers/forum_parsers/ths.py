#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""同花顺舆情增强解析器

A. ThsGubaJsonParser —— 同花顺股吧 JSON 接口
   (t.10jqka.com.cn/lgt/post/open/api/forum/post/v2/recent)
   替换原有 HTML 爬虫，获取结构化帖子：互动量(like/reply/share/forward)、
   认证标识(is_v)、股龄(stock_age)、地域(ip_location)、用户 uid。
   互动量经 pipeline 的 meta 增强写入 importance，并落库到 news.meta，
   用于散户情绪强度与可信度加权。支持按焦点股列表定向抓取。

B. ThsHotRankParser —— 同花顺热股榜
   (eq.10jqka hot_list history + dq.10jqka fuyao hot_list)
   作为东财人气榜之外的第二条散户热度腿，feed 进 forum_sentiment 的
   heat 与 top_stocks。排名/涨跌幅/题材标签写入 meta，由 pipeline 映射为 importance。

反爬：均为 UA/Referer 级别，无需 hexin-v 或登录
（详见《同花顺10jqka数据源全面分析报告》第4、5、7节）。
"""

import asyncio
import logging
import random
from typing import Optional, List, Dict

import httpx

from .base import BaseForumParser
from finfeed.utils.time_utils import now_bj, TZ_BJ
from .utils import STOCK_NAME_MAP
from .ugc_platforms import PROMO_PATTERNS

logger = logging.getLogger("news_monitor")

# 焦点股（高讨论度 A 股，用于股吧 JSON 定向抓取；可在 sources.py 的 params.codes 覆盖）
THS_GUBA_FOCUS_CODES = [
    "600519", "300059", "300750", "002594", "601318", "600036", "600030",
    "000858", "000333", "601012", "002230", "300124", "002475", "600900",
    "601899", "000001", "600276", "002415", "300760", "688981",
    "601138", "000725", "002241", "600585", "601166", "000651", "600887",
    "002714", "601888", "300015",
]

_MOBILE_UA = ("Mozilla/5.0 (iPhone; CPU iPhone OS 16_0 like Mac OS X) "
              "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.0 Mobile/15E148 Safari/604.1")
_PC_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
          "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36")


def _market_of(code: str) -> str:
    return "sh" if code.startswith(("60", "688", "9")) else "sz"


def _is_promo(text: str) -> bool:
    return any(p in text for p in PROMO_PATTERNS)


def _to_float(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _pick(d: Dict, keys):
    for k in keys:
        if k in d and d[k] not in (None, ""):
            return d[k]
    return None


def _pick_int(d: Dict, keys):
    v = _pick(d, keys)
    try:
        return int(v)
    except (TypeError, ValueError):
        return None


def _rand_falcon_uid() -> int:
    return random.randint(710000000, 712680385)


class ThsGubaJsonParser(BaseForumParser):
    """同花顺股吧 JSON 接口解析器（v2/recent）

    遍历焦点股列表，逐股拉取最新论坛帖，输出带互动量/认证/地域元数据的 forum 条目。
    """

    PAGE_SIZE = 15
    PER_CODE = 8
    SORT = "reply"          # reply=按互动量排序，突出高情绪强度帖
    MARKET_ID = 17          # 17 = A 股
    MAX_ITEMS = 200

    def _get_stocks_from_source(self) -> list:
        # 每只帖已在 _parse_post 中通过 extra_stocks 携带其真实焦点股代码；
        # 源级归因（URL/源名匹配）会把单一代码污染到全部帖子，故显式返回空。
        # 即便源名含“同花顺”或 URL 带 code= 参数，也不会误挂 300033 等无关标的。
        return []

    async def parse(self, response: httpx.Response) -> List:
        news_list = []
        self._seen_urls.clear()
        codes = list(self.source.params.get("codes") or THS_GUBA_FOCUS_CODES)
        if not codes:
            return news_list
        headers = {
            "User-Agent": _MOBILE_UA,
            "Referer": "https://t.10jqka.com.cn/",
            "Accept": "application/json, text/plain, */*",
        }
        async with httpx.AsyncClient(timeout=15, follow_redirects=True, headers=headers) as client:
            for code in codes:
                try:
                    url = (
                        "https://t.10jqka.com.cn/lgt/post/open/api/forum/post/v2/recent"
                        f"?page=1&page_size={self.PAGE_SIZE}&pid=0&time=0&sort={self.SORT}"
                        f"&code={code}&market_id={self.MARKET_ID}"
                    )
                    r = await client.get(url)
                    if r.status_code != 200:
                        continue
                    data = r.json()
                    feed = (data.get("data") or {}).get("feed") or []
                    name = STOCK_NAME_MAP.get(code, code)
                    count = 0
                    for post in feed:
                        item = self._parse_post(post, code, name)
                        if item:
                            news_list.append(item)
                            count += 1
                        if count >= self.PER_CODE:
                            break
                    await asyncio.sleep(0.2)
                except Exception as e:
                    logger.debug(f"同花顺股吧JSON抓取 {code} 失败: {str(e)[:60]}")
                    continue
        news_list.sort(key=lambda x: x.publish_ts, reverse=True)
        return news_list[: self.MAX_ITEMS]

    def _parse_post(self, post: Dict, code: str, name: str) -> Optional[object]:
        content = (post.get("content") or "").strip()
        if len(content) < 6:
            return None
        if _is_promo(content):
            return None
        pid = post.get("pid") or post.get("id") or ""
        ctime = post.get("ctime") or post.get("mtime") or 0
        try:
            ctime = int(ctime)
        except (TypeError, ValueError):
            ctime = 0
        stat = post.get("stat") or {}
        try:
            likes = int(stat.get("like", 0) or 0)
            replies = int(stat.get("reply", 0) or 0)
            forwards = int(stat.get("forward", 0) or 0)
            shares = int(stat.get("share", 0) or 0)
        except (TypeError, ValueError):
            likes = replies = forwards = shares = 0
        user = post.get("user") or {}
        is_v = bool(user.get("is_v") or False)
        stock_age = user.get("stock_age")
        ip_location = (post.get("ip_location") or "").strip()
        uid = str(post.get("uid") or "")
        meta = {
            "likes": likes,
            "replies": replies,
            "forwards": forwards,
            "shares": shares,
            "is_v": is_v,
            "ip_location": ip_location,
            "stock_age": stock_age if isinstance(stock_age, int) else None,
            "uid": uid,
            "source_code": code,
        }
        url = (f"https://t.10jqka.com.cn/circle/{pid}/"
               if pid else f"https://t.10jqka.com.cn/?code={code}")
        extra_stocks = [{"code": code, "name": name, "market": _market_of(code)}]
        return self._build_news_item(
            title=content[:100],
            url=url,
            publish_ts=ctime,
            intro=content[100:200] if len(content) > 100 else "",
            extra_stocks=extra_stocks,
            meta=meta,
        )


class ThsHotRankParser(BaseForumParser):
    """同花顺热股榜解析器（eq.10jqka + dq.10jqka fuyao）

    聚合同花顺热股榜（5 分钟粒度历史 + 移动 fuyao 小时/日榜），输出带排名/涨跌幅/题材
    标签的 forum 条目，作为东财人气榜之外的第二条散户热度腿。
    """

    MAX_ITEMS = 120

    def _get_stocks_from_source(self) -> list:
        # 每条热股榜已通过 extra_stocks 携带其对应个股代码，源级归因无意义，
        # 且可避免源名含“同花顺”时误挂 300033。
        return []

    async def parse(self, response: httpx.Response) -> List:
        news_list = []
        self._seen_urls.clear()
        ranked: Dict[str, Dict] = {}
        # 1) eq.10jqka 历史热股榜（5 分钟粒度，取最新快照，字段权威）
        try:
            ranked.update(await self._parse_eq())
        except Exception as e:
            logger.debug(f"同花顺热股榜 eq 失败: {str(e)[:60]}")
        # 2) dq.10jqka fuyao 小时/日热股榜（仅在 eq 缺失时补充）
        try:
            self._merge_dq(ranked, await self._parse_dq("hour"))
        except Exception as e:
            logger.debug(f"同花顺热股榜 dq(hour) 失败: {str(e)[:60]}")
        try:
            self._merge_dq(ranked, await self._parse_dq("day"))
        except Exception as e:
            logger.debug(f"同花顺热股榜 dq(day) 失败: {str(e)[:60]}")

        today = now_bj().strftime("%Y-%m-%d")
        for code, info in ranked.items():
            name = info.get("name") or STOCK_NAME_MAP.get(code, code)
            rank = info.get("rank") or 0
            rate = info.get("rate")
            concept = info.get("concept_tag") or []
            title = f"[热股{rank}] {name}({code})"
            if rate is not None:
                title += f" {rate:+.2f}%"
            # url 含日期 => 每日快照独立入库，使热度腿按交易日贡献 forum_sentiment
            url = (f"https://eq.10jqka.com.cn/frontend/thsTopRank/index.html"
                   f"?code={code}&date={today}")
            meta = {"rank": rank, "rate": rate, "concept_tag": concept}
            item = self._build_news_item(
                title=title,
                url=url,
                publish_ts=int(now_bj().replace(tzinfo=TZ_BJ).timestamp()),
                intro=(f"同花顺热股榜第{rank}位"
                       + (f" | 题材:{'/'.join(concept)}" if concept else "")),
                extra_stocks=[{"code": code, "name": name, "market": _market_of(code)}],
                meta=meta,
            )
            if item:
                news_list.append(item)
        news_list.sort(key=lambda x: x.publish_ts, reverse=True)
        return news_list[: self.MAX_ITEMS]

    @staticmethod
    def _merge_dq(ranked: Dict[str, Dict], incoming: Dict[str, Dict]) -> None:
        for code, info in incoming.items():
            ranked.setdefault(code, info)

    async def _parse_eq(self, data: Optional[Dict] = None) -> Dict[str, Dict]:
        date_str = now_bj().strftime("%Y%m%d")
        url = (f"https://eq.10jqka.com.cn/open/api/hot_list/history/v1/rank"
               f"?type=stock&date={date_str}")
        headers = {
            "User-Agent": _MOBILE_UA,
            "Referer": "https://eq.10jqka.com.cn/",
            "Accept": "application/json, text/plain, */*",
        }
        out: Dict[str, Dict] = {}
        if data is None:
            async with httpx.AsyncClient(timeout=15, follow_redirects=True, headers=headers) as client:
                r = await client.get(url)
                if r.status_code != 200:
                    return out
                data = r.json()
        # 真实结构：stock_list 是按 5 分钟时间戳为键的 dict；取最大键=最新快照
        sl = (data.get("data") or {}).get("stock_list") or {}
        if isinstance(sl, dict):
            if not sl:
                return out
            latest_key = max(sl.keys())
            items = sl[latest_key]
        elif isinstance(sl, list):
            items = sl[-1] if sl and isinstance(sl[-1], list) else sl
        else:
            return out
        if not isinstance(items, list):
            return out
        for it in items:
            code = str(it.get("code") or "")
            if not code.startswith(("60", "688", "00", "30")):
                continue
            # eq 的 rate 为热度值（非百分比），且无题材标签，仅取排名/代码/名称
            tag = it.get("tag") or {}
            concept = tag.get("concept_tag") or []
            out[code] = {
                "name": it.get("name") or STOCK_NAME_MAP.get(code, code),
                "rank": int(it.get("order") or 0),
                "rate": None,
                "concept_tag": [c for c in concept[:3] if c],
            }
        return out

    async def _parse_dq(self, period: str, data: Optional[Dict] = None) -> Dict[str, Dict]:
        url = (f"https://dq.10jqka.com.cn/fuyao/hot_list_data/out/hot_list/v1/stock"
               f"?stock_type=a&type={period}&list_type=normal")
        # Fuyao 网关使用 Falcon UA（见报告第5节）
        headers = {
            "User-Agent": f"Falcon/0.3.29 userid/{_rand_falcon_uid()}",
            "Referer": "https://localhost:8088/",
            "Origin": "https://localhost:8088/",
            "Accept": "application/json, text/plain, */*",
        }
        out: Dict[str, Dict] = {}
        if data is None:
            async with httpx.AsyncClient(timeout=15, follow_redirects=True, headers=headers) as client:
                r = await client.get(url)
                if r.status_code != 200:
                    return out
                data = r.json()
        # 真实结构：stock_list 为 list（100 条），百分比在 rise_and_fall，题材在 tag.concept_tag
        items = (data.get("data") or {}).get("stock_list") or data.get("data") or []
        if not isinstance(items, list):
            return out
        for idx, it in enumerate(items):
            code = _pick(it, ["code", "stock_code", "thscode", "secid"])
            if not code or not str(code).startswith(("60", "688", "00", "30")):
                continue
            code = str(code)
            rank = _pick_int(it, ["order", "rank", "hot_rank", "index", "no"]) or (idx + 1)
            tag = it.get("tag") or {}
            concept = tag.get("concept_tag") or []
            out[code] = {
                "name": _pick(it, ["name", "stock_name"]) or STOCK_NAME_MAP.get(code, code),
                "rank": int(rank),
                "rate": _to_float(it.get("rise_and_fall")),
                "concept_tag": [c for c in concept[:3] if c],
            }
        return out
