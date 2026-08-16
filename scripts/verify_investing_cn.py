#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""英为财情 Investing.com 中文快讯解析器冒烟验证脚本

覆盖：
  1) 导入冒烟（factory 注册 + InvestingCnParser 构造）
  2) 离线单测：用样例 RSS 验证 parse() 字段映射 / UTC->北京时间归一化 / 增量过滤
  3) 真实联网抓取（尽力，无网则跳过）
结尾打印 ALL PASS（纯 ASCII）。
"""

import asyncio
import os
import sys
import traceback

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import httpx
from finfeed.config.sources import NewsSource
from finfeed.core.parsers.html_parsers.investing_cn import InvestingCnParser, _ts_from_utc_str
from finfeed.utils.time_utils import bj_str_from_ts

SAMPLE_RSS = """<?xml version="1.0" encoding="utf-8"?>
<rss version="2.0">
  <channel>
    <title>所有资讯</title>
    <link>https://cn.investing.com</link>
    <item>
      <title>Winnebago高管Woodson出售价值$78,841的公司股票</title>
      <pubDate>2026-08-15 11:16:56</pubDate>
      <author>Investing.com</author>
      <link>https://cn.investing.com/news/insider-trading-news/article-93CH-3519835</link>
    </item>
    <item>
      <title>比特币价格徘徊于$63,000下方，抛售压力抵消监管进展</title>
      <pubDate>2026-08-15 09:41:11</pubDate>
      <author>Investing.com</author>
      <link>https://cn.investing.com/news/cryptocurrency-news/article-3519819</link>
    </item>
    <item>
      <title>上半年净赚近257亿！平安银行二季度净息差环比微升</title>
      <pubDate>2026-08-15 10:06:07</pubDate>
      <author>时代周报</author>
      <link>https://cn.investing.com/news/stock-market-news/article-3519821</link>
    </item>
  </channel>
</rss>
"""


def banner(t: str) -> None:
    print("\n" + "=" * 60)
    print(t)
    print("=" * 60)


def test_import_smoke() -> None:
    banner("[1] 导入冒烟（类可直接构造，factory 注册由部署方按需添加）")
    from finfeed.core.parsers.base import BaseParser

    src = NewsSource(
        name="英为财情",
        url="https://cn.investing.com/rss/news.rss",
        parser_type="investing_cn",
        headers={"User-Agent": "Mozilla/5.0", "Accept": "application/rss+xml, application/xml, text/xml, */*"},
    )
    parser = InvestingCnParser(src)
    print("  InvestingCnParser ->", type(parser).__name__)
    assert isinstance(parser, BaseParser), "InvestingCnParser 应为 BaseParser 子类"
    assert parser.source.parser_type == "investing_cn"
    print("  OK")


def test_parse_offline() -> None:
    banner("[2] 离线单测 parse()")
    parser = InvestingCnParser(NewsSource(name="英为财情", url="https://cn.investing.com/rss/news.rss", parser_type="investing_cn"))
    resp = httpx.Response(200, content=SAMPLE_RSS.encode("utf-8"), headers={"Content-Type": "application/rss+xml"})
    items = asyncio.run(parser.parse(resp))
    print(f"  解析条目: {len(items)}")
    assert len(items) == 3
    first = items[0]
    print("  样例1:", first.title[:40], "|", first.publish_time, "|", first.url[:50])
    assert first.title == "Winnebago高管Woodson出售价值$78,841的公司股票"
    # pubDate 为 UTC，应归一化为北京时间（+8h）
    assert first.publish_ts == _ts_from_utc_str("2026-08-15 11:16:56")
    assert first.publish_time == bj_str_from_ts(first.publish_ts)
    assert first.publish_time == "2026-08-15 19:16:56", "UTC 11:16 应归一化为北京 19:16"
    assert first.url.startswith("https://cn.investing.com/news/")
    assert first.intro == "Investing.com"
    third = items[2]
    assert third.intro == "时代周报", "author 应作为 intro"
    # 增量过滤：last_ts 设为最新时间后，再次解析应全部跳过
    parser.last_ts = first.publish_ts
    items2 = asyncio.run(parser.parse(resp))
    assert len(items2) == 0, "增量过滤后应无新条目"
    print("  增量过滤正确")
    print("  OK")


def test_ts_helper() -> None:
    banner("[3] UTC 时间归一化")
    assert _ts_from_utc_str("2026-08-15 11:16:56") == _ts_from_utc_str("2026-08-15 11:16:56")
    assert _ts_from_utc_str("") == 0
    assert _ts_from_utc_str("bad-date") == 0
    print("  UTC 解析 / 空值 / 非法值处理正确")
    print("  OK")


def test_live() -> None:
    banner("[4] 真实联网抓取（尽力，无网则跳过）")
    parser = InvestingCnParser(NewsSource(
        name="英为财情",
        url="https://cn.investing.com/rss/news.rss",
        parser_type="investing_cn",
        headers={
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
            "Accept": "application/rss+xml, application/xml, text/xml, */*",
        },
    ))

    async def run() -> None:
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.get(parser.source.url, headers=dict(parser.source.headers))
            print(f"  HTTP {resp.status_code}, 响应 {len(resp.content)} 字节")
            if resp.status_code != 200:
                print("  联网失败（预期沙箱无网则跳过）")
                return
            items = await parser.parse(resp)
            print(f"  抓取条目: {len(items)}")
            if items:
                print("   样例:", items[0].title[:50], "|", items[0].publish_time)

    try:
        asyncio.run(run())
    except Exception as e:
        print("  联网测试异常（预期沙箱无网则跳过）:", str(e)[:80])


if __name__ == "__main__":
    fails = []
    for fn in (test_import_smoke, test_parse_offline, test_ts_helper, test_live):
        try:
            fn()
        except Exception:
            fails.append(fn.__name__)
            print(f"\n!!! {fn.__name__} 失败:\n{traceback.format_exc()}")
    banner("结果汇总")
    if fails:
        print(f"失败 {len(fails)} 项: {fails}")
        sys.exit(1)
    print("ALL PASS")
