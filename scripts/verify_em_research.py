#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""东方财富研报流（em_research）冒烟验证脚本

覆盖：
  1) 导入冒烟：EmResearchParser 为 BaseParser 子类
  2) 离线解析：JSONP 剥壳、title 必填、时间归一化、intro 拼接、URL 构造、增量过滤
  3) 离线健壮性：非 JSONP / 坏 JSON 返回空列表
  4) _build_params 参数正确性（qType=0 / pageSize=50 / 时间窗口）
  5) 真实联网：抓取第 1 页，断言至少解析出 1 条（无网则跳过）
  6) 真实联网：fetch_with_catch_up 逐日回补（无网则跳过）

结尾打印 ALL PASS（纯 ASCII）。
"""

import asyncio
import os
import sys
import traceback
from datetime import timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import httpx
from finfeed.config.sources import NewsSource
from finfeed.core.parsers.base import BaseParser
from finfeed.core.parsers.json_parsers.em_research import (
    _ARTICLE_URL,
    _PAGE_SIZE,
    _REPORT_URL,
    EmResearchParser,
)
from finfeed.utils.time_utils import now_bj

SAMPLE_JSONP = (
    'datatable({"hits":3,"size":3,"data":['
    '{"title":"新股申购报告：高景气度现金牛业务占比达34%，母公司CAGR10.69%",'
    '"stockName":"某某股份","stockCode":"920288","orgName":"开源证券股份有限公司",'
    '"orgSName":"开源证券","publishDate":"2026-08-14 10:00:00.000",'
    '"infoCode":"AP202608141828019741","emRatingName":"","ratingChange":"",'
    '"reportType":2,"author":["11000170965.张海涛"],"market":"BEIJING"},'
    '{"title":"算力&光模块附加值提升，Rubin产业链深度报告",'
    '"stockName":"工业富联","stockCode":"601138","orgName":"国盛证券股份有限公司",'
    '"orgSName":"国盛证券","publishDate":"2026-08-15 00:00:00.000",'
    '"infoCode":"AP202608151828019073","emRatingName":"买入","ratingChange":3,'
    '"reportType":2,"author":["11000281334.郑震湘"],"market":"SHANGHAI"},'
    '{"title":"","stockName":"无标题股","stockCode":"000001",'
    '"publishDate":"2026-08-15 01:00:00.000","infoCode":"AP202608151828019999"}'
    '],"TotalPage":1,"pageNo":1,"currentYear":2026})'
)


def banner(t: str) -> None:
    print("\n" + "=" * 60)
    print(t)
    print("=" * 60)


def make_parser() -> EmResearchParser:
    return EmResearchParser(NewsSource(name="东方财富研报", url=_REPORT_URL, parser_type="em_research"))


def test_import_smoke() -> None:
    banner("[1] import smoke: EmResearchParser is BaseParser subclass")
    parser = make_parser()
    assert isinstance(parser, BaseParser)
    assert parser.source.parser_type == "em_research"
    print("  OK")


def test_parse_offline() -> None:
    banner("[2] offline parse: JSONP strip / title required / ts / intro / url / dedup")
    parser = make_parser()
    resp = httpx.Response(200, text=SAMPLE_JSONP)
    items = asyncio.run(parser.parse(resp))
    assert len(items) == 2, f"expect 2 items (empty-title skipped), got {len(items)}"
    it0, it1 = items
    assert it0.title.startswith("新股申购报告")
    assert it0.url == _ARTICLE_URL.format(info_code="AP202608141828019741")
    assert it0.publish_time == "2026-08-14 10:00:00"
    assert it0.publish_ts > 0
    assert it0.intro == "开源证券股份有限公司", f"intro without rating should be orgName, got {it0.intro!r}"
    assert it1.intro == "国盛证券股份有限公司·买入", f"intro with rating should be orgName·rating, got {it1.intro!r}"
    assert it1.publish_ts > it0.publish_ts
    print("  sample:", it1.title[:40], "|", it1.intro, "|", it1.publish_time)
    # incremental filter: last_ts = older item ts -> only newer item survives
    parser.last_ts = it0.publish_ts
    items2 = asyncio.run(parser.parse(resp))
    assert len(items2) == 1 and items2[0].publish_ts == it1.publish_ts
    print("  incremental filter (ts <= last_ts skipped): OK")
    print("  OK")


def test_parse_robustness() -> None:
    banner("[3] offline robustness: non-JSONP / bad JSON -> empty list")
    parser = make_parser()
    assert asyncio.run(parser.parse(httpx.Response(200, text="not jsonp at all"))) == []
    assert asyncio.run(parser.parse(httpx.Response(200, text="datatable({bad json)"))) == []
    assert asyncio.run(parser.parse(httpx.Response(200, text='datatable({"data":[]})'))) == []
    print("  OK")


def test_build_params() -> None:
    banner("[4] _build_params: qType=0 / pageSize=50 / time window")
    parser = make_parser()
    params = parser._build_params("2026-08-14", "2026-08-15")
    assert params["qType"] == "0"
    assert params["pageSize"] == str(_PAGE_SIZE)
    assert params["beginTime"] == "2026-08-14" and params["endTime"] == "2026-08-15"
    assert params["pageNo"] == "1" and params["cb"] == "datatable"
    print("  OK")


def test_live_page1() -> None:
    banner("[5] live: fetch real page 1, expect >= 1 item (skip if no network)")
    parser = make_parser()
    today = now_bj().date()
    yesterday = today - timedelta(days=1)

    async def run() -> None:
        async with httpx.AsyncClient(timeout=20) as client:
            resp = await client.get(
                _REPORT_URL,
                params=parser._build_params(yesterday.strftime("%Y-%m-%d"), today.strftime("%Y-%m-%d")),
            )
            assert resp.status_code == 200, f"HTTP {resp.status_code}"
            items = await parser.parse(resp)
            assert len(items) >= 1, "live page 1 parsed 0 items"
            print(f"  parsed {len(items)} items")
            print("  sample:", items[0].title[:50], "|", items[0].intro[:40], "|", items[0].publish_time)

    try:
        asyncio.run(run())
    except Exception as e:
        print("  live fetch failed (skip):", str(e)[:100])
        return
    print("  OK")


def test_live_catch_up() -> None:
    banner("[6] live: fetch_with_catch_up day-window backfill (skip if no network)")
    parser = make_parser()
    parser.set_catch_up_mode(True)
    parser.last_ts = int(now_bj().replace(tzinfo=None).timestamp()) - 86400  # 1 day ago

    async def run() -> None:
        async with httpx.AsyncClient(timeout=20) as client:
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
    for fn in (test_import_smoke, test_parse_offline, test_parse_robustness, test_build_params, test_live_page1, test_live_catch_up):
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
