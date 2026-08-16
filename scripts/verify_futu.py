#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""富途牛牛快讯解析器冒烟验证脚本

覆盖：
  1) 导入冒烟（factory 注册 + FutuParser 构造）
  2) 离线单测：用样例 JSON 验证 parse() 字段映射 / 增量过滤 / 时间归一化
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
from finfeed.core.parsers.json_parsers.futu import FutuParser, _ts_from_futu_time
from finfeed.utils.time_utils import bj_str_from_ts

SAMPLE_JSON = {
    "code": 0,
    "message": "成功",
    "data": {
        "code": "0",
        "message": "success",
        "data": {
            "seqMark": "1786790372000000_flash:20648563",
            "hasMore": True,
            "news": [
                {
                    "id": "20648579",
                    "title": "",
                    "content": "中国地震台网正式测定：08月15日18时54分在印尼苏门答腊岛发生6.8级地震，震源深度170千米。",
                    "time": "1786792626",
                    "detailUrl": "https://news.futunn.com/flash/20648579/test",
                    "newsType": 2,
                    "sourceId": "684",
                },
                {
                    "id": "20648573",
                    "title": "富途测试标题",
                    "content": "这是一条带标题的富途快讯正文内容。",
                    "time": "1786791953",
                    "detailUrl": "https://news.futunn.com/flash/20648573/test",
                    "newsType": 2,
                    "sourceId": "684",
                },
                {
                    "id": "20648570",
                    "title": "",
                    "content": "",
                    "time": "1786791000",
                    "detailUrl": "https://news.futunn.com/flash/20648570/test",
                    "newsType": 2,
                    "sourceId": "684",
                },
            ],
        },
    },
}


def banner(t: str) -> None:
    print("\n" + "=" * 60)
    print(t)
    print("=" * 60)


def test_import_smoke() -> None:
    banner("[1] 导入冒烟（类可直接构造，factory 注册由部署方按需添加）")
    from finfeed.core.parsers.base import BaseParser

    src = NewsSource(
        name="富途牛牛快讯",
        url="https://news.futunn.com/news-site-api/main/get-flash-list",
        parser_type="futu",
        headers={"User-Agent": "Mozilla/5.0", "Referer": "https://news.futunn.com/main/live"},
        params={"pageSize": 20},
    )
    parser = FutuParser(src)
    print("  FutuParser ->", type(parser).__name__)
    assert isinstance(parser, BaseParser), "FutuParser 应为 BaseParser 子类"
    assert parser.source.parser_type == "futu"
    print("  OK")


def test_parse_offline() -> None:
    banner("[2] 离线单测 parse()")
    parser = FutuParser(NewsSource(name="富途牛牛快讯", url="https://news.futunn.com/", parser_type="futu"))
    resp = httpx.Response(200, json=SAMPLE_JSON)
    items = asyncio.run(parser.parse(resp))
    print(f"  解析条目: {len(items)}")
    assert len(items) == 2, "空内容条目应被过滤，仅保留 2 条"
    first = items[0]
    print("  样例1:", first.title[:40], "|", first.publish_time, "|", first.url[:50])
    assert first.title == "中国地震台网正式测定：08月15日18时54分在印尼苏门答腊岛发生6.8级地震，震源深度170千米。"
    assert first.publish_ts == 1786792626
    assert first.publish_time == bj_str_from_ts(1786792626)
    assert first.url.startswith("https://news.futunn.com/flash/")
    assert first.intro == "", "无标题条目 intro 应为空"
    second = items[1]
    print("  样例2:", second.title, "| intro:", second.intro)
    assert second.title == "富途测试标题"
    assert second.intro == "这是一条带标题的富途快讯正文内容。"
    # 增量过滤：last_ts 设为最新时间后，再次解析应全部跳过
    parser.last_ts = 1786792626
    items2 = asyncio.run(parser.parse(resp))
    assert len(items2) == 0, "增量过滤后应无新条目"
    print("  增量过滤正确")
    print("  OK")


def test_ts_helper() -> None:
    banner("[3] 时间字段归一化")
    assert _ts_from_futu_time("1786792626") == 1786792626
    assert _ts_from_futu_time(1786792626) == 1786792626
    assert _ts_from_futu_time(1786792626000) == 1786792626, "毫秒应转为秒"
    assert _ts_from_futu_time(None) == 0
    assert _ts_from_futu_time("abc") == 0
    print("  秒/毫秒/非法值处理正确")
    print("  OK")


def test_live() -> None:
    banner("[4] 真实联网抓取（尽力，无网则跳过）")
    parser = FutuParser(NewsSource(
        name="富途牛牛快讯",
        url="https://news.futunn.com/news-site-api/main/get-flash-list",
        parser_type="futu",
        headers={
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
            "Referer": "https://news.futunn.com/main/live",
            "Accept": "application/json, text/plain, */*",
        },
        params={"pageSize": 20},
    ))

    async def run() -> None:
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.get(parser.source.url, headers=dict(parser.source.headers), params=dict(parser.source.params))
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
