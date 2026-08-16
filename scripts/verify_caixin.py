#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""端到端验证：财新网 caixin 数据源（配置 -> 工厂 -> 抓取 -> 解析 -> NewsItem）"""
import asyncio
import sys

import httpx

sys.path.insert(0, r"E:\VibeCoding\FinFeed")

from finfeed.config.sources import get_source_by_name
from finfeed.core.parsers.factory import create_parser


async def main():
    src = get_source_by_name("财新网")
    assert src is not None, "财新网 source not found in config"
    print("source:", src.name, "| parser_type:", src.parser_type, "| url:", src.url)

    parser = create_parser(src)
    print("parser class:", type(parser).__name__)

    async with httpx.AsyncClient(follow_redirects=True, timeout=20, verify=False) as client:
        resp = await client.get(src.url, headers=dict(src.headers), params=dict(src.params))
        print("HTTP:", resp.status_code, "len:", len(resp.content))
        assert resp.status_code == 200

        news = await parser.parse(resp)
        print("parsed items:", len(news))
        assert len(news) > 0, "no items parsed"

        for n in news[:5]:
            print(f"  [{n.publish_time}] {n.title[:60]} | {n.url[:70]} | src={n.source} cat={n.category}")

        # 校验时间戳为北京时间（epoch 秒）
        from finfeed.utils.time_utils import bj_str_from_ts
        print("sample ts -> bj:", bj_str_from_ts(news[0].publish_ts))

        # 补抓模式冒烟：模拟 last_ts 后走分页补抓
        parser.last_ts = news[0].publish_ts - 3600  # 回退1小时
        parser.set_catch_up_mode(True)
        caught = await parser.fetch_with_catch_up(client)
        print("catch-up items:", len(caught))
        assert len(caught) > 0, "catch-up returned nothing"


if __name__ == "__main__":
    asyncio.run(main())
    print("OK")
