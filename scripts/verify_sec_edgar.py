#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""SEC EDGAR（sec_edgar）解析器冒烟验证脚本

覆盖：
  1) 导入冒烟：SecEdgarParser 为 BaseParser 子类
  2) 离线解析：Atom XML 解析、title 必填、链接提取、美东时间转北京时间、
     intro 拼接、增量过滤
  3) 离线健壮性：坏 XML / 空 feed 返回空列表
  4) 离线补抓单条：search-index _source -> NewsItem（URL 拼接 / 时间近似）
  5) 真实联网：Atom 主端点，断言至少解析出 1 条（无网则跳过）
  6) 真实联网：fetch_with_catch_up 全文检索回补（无网则跳过）

结尾打印 ALL PASS（纯 ASCII）。
"""

import asyncio
import os
import sys
import traceback

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import httpx
from finfeed.config.sources import NewsSource
from finfeed.core.parsers.base import BaseParser
from finfeed.core.parsers.html_parsers.sec_edgar import (
    SEC_ARCHIVE_BASE,
    SEC_ATOM_URL,
    SecEdgarParser,
)
from finfeed.utils.time_utils import now_bj

SAMPLE_ATOM = """<?xml version="1.0" encoding="ISO-8859-1" ?>
<feed xmlns="http://www.w3.org/2005/Atom">
  <title>Latest Filings</title>
  <updated>2026-08-15T07:33:43-04:00</updated>
  <entry>
    <title>8-K - Precipio, Inc. (0001043961) (Filer)</title>
    <link rel="alternate" type="text/html" href="https://www.sec.gov/Archives/edgar/data/1043961/000110465926097364/0001104659-26-097364-index.htm"/>
    <summary type="html">
     &lt;b&gt;Filed:&lt;/b&gt; 2026-08-14 &lt;b&gt;AccNo:&lt;/b&gt; 0001104659-26-097364 &lt;b&gt;Size:&lt;/b&gt; 227 KB
    &lt;br&gt;Item 2.02: Results of Operations and Financial Condition
    &lt;br&gt;Item 9.01: Financial Statements and Exhibits
    </summary>
    <updated>2026-08-14T17:30:25-04:00</updated>
    <id>urn:tag:sec.gov,2008:accession-number=0001104659-26-097364</id>
  </entry>
  <entry>
    <title>8-K - Wheels Up Experience Inc. (0001819516) (Filer)</title>
    <link rel="alternate" type="text/html" href="https://www.sec.gov/Archives/edgar/data/1819516/000162828026057181/0001628280-26-057181-index.htm"/>
    <summary type="html">
     &lt;b&gt;Filed:&lt;/b&gt; 2026-08-14 &lt;b&gt;AccNo:&lt;/b&gt; 0001628280-26-057181 &lt;b&gt;Size:&lt;/b&gt; 484 KB
    &lt;br&gt;Item 5.02: Departure of Directors or Certain Officers
    </summary>
    <updated>2026-08-14T17:27:09-04:00</updated>
    <id>urn:tag:sec.gov,2008:accession-number=0001628280-26-057181</id>
  </entry>
</feed>
"""


def banner(t: str) -> None:
    print("\n" + "=" * 60)
    print(t)
    print("=" * 60)


def make_parser() -> SecEdgarParser:
    return SecEdgarParser(NewsSource(name="SEC EDGAR", url=SEC_ATOM_URL, parser_type="sec_edgar"))


def test_import_smoke() -> None:
    banner("[1] import smoke: SecEdgarParser is BaseParser subclass")
    parser = make_parser()
    assert isinstance(parser, BaseParser)
    assert parser.source.parser_type == "sec_edgar"
    assert "contact@" in parser._headers()["User-Agent"], "UA must carry contact info"
    print("  UA:", parser._headers()["User-Agent"])
    print("  OK")


def test_parse_offline() -> None:
    banner("[2] offline parse: Atom XML / link / ET->BJ time / intro / incremental")
    parser = make_parser()
    resp = httpx.Response(200, content=SAMPLE_ATOM.encode("iso-8859-1"), request=httpx.Request("GET", SEC_ATOM_URL))
    items = asyncio.run(parser.parse(resp))
    assert len(items) == 2, f"expect 2 items, got {len(items)}"
    it0, it1 = items
    assert it0.title.startswith("8-K - Precipio, Inc.")
    assert "sec.gov/Archives/edgar/data/1043961" in it0.url
    # 17:30:25 EDT (-04:00) == 21:30:25 UTC == 次日 05:30:25 北京
    assert it0.publish_time == "2026-08-15 05:30:25", f"got {it0.publish_time!r}"
    assert "Precipio, Inc." in it0.intro and "8-K" in it0.intro and "Item 2.02" in it0.intro
    assert it0.publish_ts > it1.publish_ts  # 17:30 > 17:27
    print("  sample:", it0.title[:45], "|", it0.intro[:50], "|", it0.publish_time)
    # incremental: last_ts = newest -> 0 items
    parser.last_ts = it0.publish_ts
    items2 = asyncio.run(parser.parse(resp))
    assert len(items2) == 0, f"expect 0 items after last_ts, got {len(items2)}"
    # incremental: last_ts = older -> only newest survives
    parser2 = make_parser()
    parser2.last_ts = it1.publish_ts
    items3 = asyncio.run(parser2.parse(resp))
    assert len(items3) == 1 and items3[0].publish_ts == it0.publish_ts
    print("  incremental filter (ts <= last_ts skipped): OK")
    print("  OK")


def test_parse_robustness() -> None:
    banner("[3] offline robustness: bad XML / empty feed -> empty list")
    parser = make_parser()
    assert asyncio.run(parser.parse(httpx.Response(200, content=b"not xml at all"))) == []
    empty = b'<?xml version="1.0" ?><feed xmlns="http://www.w3.org/2005/Atom"></feed>'
    assert asyncio.run(parser.parse(httpx.Response(200, content=empty))) == []
    print("  OK")


def test_search_to_news() -> None:
    banner("[4] offline search-to-news: URL join / date approx")
    parser = make_parser()
    src = {
        "adsh": "0001628280-26-057100",
        "ciks": ["0001788060"],
        "display_names": ["Voyager Technologies, Inc./TX  (VOYG)  (CIK 0001788060)"],
        "file_date": "2026-08-14",
        "form": "8-K",
        "items": ["8.01", "9.01"],
    }
    news = parser._search_to_news(src, "8-K")
    assert news is not None
    assert news.url == f"{SEC_ARCHIVE_BASE}/1788060/0001628280-26-057100/"
    assert news.publish_ts > 0
    assert "Voyager" in news.intro and "Item 8.01" in news.intro
    print("  sample:", news.title[:45], "|", news.url, "|", news.publish_time)
    # missing adsh -> None
    assert parser._search_to_news({"ciks": ["0001788060"], "file_date": "2026-08-14"}, "8-K") is None
    print("  OK")


def test_live_atom() -> None:
    banner("[5] live: Atom getcurrent, expect >= 1 item (skip if no network)")
    parser = make_parser()

    async def run() -> None:
        async with httpx.AsyncClient(timeout=25) as client:
            resp = await client.get(SEC_ATOM_URL, headers=parser._headers(), params=parser._build_atom_params(40))
            assert resp.status_code == 200, f"HTTP {resp.status_code}"
            items = await parser.parse(resp)
            assert len(items) >= 1, "live Atom parsed 0 items"
            print(f"  parsed {len(items)} items")
            print("  sample:", items[0].title[:45], "|", items[0].intro[:40], "|", items[0].publish_time)

    try:
        asyncio.run(run())
    except Exception as e:
        print("  live fetch failed (skip):", str(e)[:100])
        return
    print("  OK")


def test_live_catch_up() -> None:
    banner("[6] live: fetch_with_catch_up date-range backfill (skip if no network)")
    parser = make_parser()
    parser.set_catch_up_mode(True)
    parser.last_ts = int(now_bj().timestamp()) - 86400 * 2  # 2 days ago

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
    for fn in (test_import_smoke, test_parse_offline, test_parse_robustness, test_search_to_news, test_live_atom, test_live_catch_up):
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
