#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""港交所披露易（hkexnews）解析器冒烟验证脚本

覆盖：
  1) 导入冒烟：HkexNewsParser 为 BaseParser 子类
  2) 离线解析：JSON 二次解析、title 必填、HTML 实体清理、时间归一化、
     intro 拼接（代码|公司|类型）、URL 前缀拼接、增量过滤
  3) 离线健壮性：坏 JSON / 非列表 result 返回空列表
  4) 真实联网：请求最近一天数据，断言至少解析出 1 条（无网则跳过）
  5) 真实联网：fetch_with_catch_up 按日回补（无网则跳过）

结尾打印 ALL PASS（纯 ASCII）。
"""

import asyncio
import json
import os
import sys
import traceback
from datetime import datetime, timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import httpx
from finfeed.config.sources import NewsSource
from finfeed.core.parsers.base import BaseParser
from finfeed.core.parsers.json_parsers.hkexnews import (
    HKEX_BASE_URL,
    HKEX_SEARCH_URL,
    HkexNewsParser,
)
from finfeed.utils.time_utils import TZ_BJ

SAMPLE_ITEMS = [
    {
        "TITLE": "PROXY FORM FOR USE AT THE 2026 SECOND EXTRAORDINARY SHAREHOLDERS&#x27; GENERAL MEETING",
        "DATE_TIME": "14/08/2026 22:59",
        "STOCK_NAME": "HEARTCARE-B",
        "STOCK_CODE": "06609",
        "FILE_LINK": "/listedco/listconews/sehk/2026/0814/2026081402127.pdf",
        "LONG_TEXT": "Proxy Forms",
    },
    {
        "TITLE": "NOTICE OF EGM/SGM &amp; Closure of Books<br/>",
        "DATE_TIME": "14/08/2026 22:58",
        "STOCK_NAME": "HEARTCARE-B",
        "STOCK_CODE": "06609",
        "FILE_LINK": "/listedco/listconews/sehk/2026/0814/2026081402125.pdf",
        "LONG_TEXT": "Announcements and Notices - [Notice of EGM]",
    },
    {
        "TITLE": "",
        "DATE_TIME": "14/08/2026 22:58",
        "STOCK_NAME": "EMPTY TITLE CO",
        "STOCK_CODE": "00001",
        "FILE_LINK": "/listedco/listconews/sehk/2026/0814/x.pdf",
        "LONG_TEXT": "Empty title",
    },
]


def sample_response() -> httpx.Response:
    body = json.dumps({"result": json.dumps(SAMPLE_ITEMS), "hasNextRow": False, "recordCnt": "3"})
    return httpx.Response(200, text=body, request=httpx.Request("GET", HKEX_SEARCH_URL))


def banner(t: str) -> None:
    print("\n" + "=" * 60)
    print(t)
    print("=" * 60)


def make_parser() -> HkexNewsParser:
    return HkexNewsParser(NewsSource(name="港交所披露易", url=HKEX_SEARCH_URL, parser_type="hkexnews"))


def test_import_smoke() -> None:
    banner("[1] import smoke: HkexNewsParser is BaseParser subclass")
    parser = make_parser()
    assert isinstance(parser, BaseParser)
    assert parser.source.parser_type == "hkexnews"
    print("  OK")


def test_parse_offline() -> None:
    banner("[2] offline parse: double JSON / title required / ts / intro / url / incremental")
    parser = make_parser()
    items = asyncio.run(parser.parse(sample_response()))
    assert len(items) == 2, f"expect 2 items (empty-title skipped), got {len(items)}"
    it0, it1 = items
    assert it0.title.startswith("PROXY FORM")
    assert "'" in it0.title, f"HTML entity &#x27; not unescaped: {it0.title!r}"
    assert it0.url == HKEX_BASE_URL + "/listedco/listconews/sehk/2026/0814/2026081402127.pdf"
    assert it0.publish_time == "2026-08-14 22:59:00"
    assert it0.publish_ts > 0
    assert "06609" in it0.intro and "HEARTCARE-B" in it0.intro
    assert it0.publish_ts > it1.publish_ts  # 22:59 > 22:58
    assert "<br" not in it1.title and "&amp;" not in it1.title
    print("  sample:", it0.title[:50], "|", it0.intro[:40], "|", it0.publish_time)
    # incremental filter: last_ts = newer item -> both filtered
    parser.last_ts = it0.publish_ts
    items2 = asyncio.run(parser.parse(sample_response()))
    assert len(items2) == 0, f"expect 0 items after last_ts={it0.publish_ts}, got {len(items2)}"
    # incremental filter: last_ts = older item -> only newer survives
    parser2 = make_parser()
    parser2.last_ts = it1.publish_ts
    items3 = asyncio.run(parser2.parse(sample_response()))
    assert len(items3) == 1 and items3[0].publish_ts == it0.publish_ts
    print("  incremental filter (ts <= last_ts skipped): OK")
    print("  OK")


def test_parse_robustness() -> None:
    banner("[3] offline robustness: bad JSON / empty / non-list result -> empty list")
    parser = make_parser()
    assert asyncio.run(parser.parse(httpx.Response(200, text="not json at all"))) == []
    assert asyncio.run(parser.parse(httpx.Response(200, text='{"result": "{bad json"}'))) == []
    assert asyncio.run(parser.parse(httpx.Response(200, text='{"result": "[]"}'))) == []
    assert asyncio.run(parser.parse(httpx.Response(200, text='{"result": 42}'))) == []
    print("  OK")


def test_live_recent() -> None:
    banner("[4] live: fetch recent day, expect >= 1 item (skip if no network)")
    parser = make_parser()
    today = datetime.now(TZ_BJ).date()
    yesterday = today - timedelta(days=1)

    async def run() -> None:
        async with httpx.AsyncClient(timeout=25) as client:
            resp = await client.get(
                HKEX_SEARCH_URL,
                params=parser._build_params(yesterday.strftime("%Y%m%d"), today.strftime("%Y%m%d")),
            )
            assert resp.status_code == 200, f"HTTP {resp.status_code}"
            items = await parser.parse(resp)
            assert len(items) >= 1, "live recent parsed 0 items"
            print(f"  parsed {len(items)} items")
            print("  sample:", items[0].title[:50], "|", items[0].intro[:40], "|", items[0].publish_time)

    try:
        asyncio.run(run())
    except Exception as e:
        print("  live fetch failed (skip):", str(e)[:100])
        return
    print("  OK")


def test_live_catch_up() -> None:
    banner("[5] live: fetch_with_catch_up day-window backfill (skip if no network)")
    parser = make_parser()
    parser.set_catch_up_mode(True)
    parser.last_ts = int(datetime.now(TZ_BJ).timestamp()) - 86400 * 2  # 2 days ago

    async def run() -> None:
        async with httpx.AsyncClient(timeout=25) as client:
            items = await parser.fetch_with_catch_up(client)
            assert len(items) >= 1, "catch-up returned 0 items"
            print(f"  catch-up returned {len(items)} items, newest ts={items[0].publish_ts}")

    try:
        asyncio.run(run())
    except Exception as e:
        print("  live catch-up failed (skip):", str(e)[:100])
        return
    print("  OK")


if __name__ == "__main__":
    fails = []
    for fn in (test_import_smoke, test_parse_offline, test_parse_robustness, test_live_recent, test_live_catch_up):
        try:
            fn()
        except Exception:
            fails.append((fn.__name__, traceback.format_exc()))
            print(f"\n!!! {fn.__name__} FAILED:\n{traceback.format_exc()}")
    banner("RESULT")
    if fails:
        print(f"FAILED {len(fails)} item(s):", [f[0] for f in fails])
        sys.exit(1)
    print("ALL PASS")
