#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""火星财经快讯解析器冒烟验证脚本

覆盖：
  1) 导入冒烟（factory 注册 + MarsbitParser 构造）
  2) 离线单测：用样例 JSON 验证 parse() 字段映射 / 毫秒转秒 / 增量过滤
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
from finfeed.core.parsers.json_parsers.marsbit import MarsbitParser
from finfeed.utils.time_utils import bj_str_from_ts

SAMPLE_JSON = {
    "code": 1,
    "msg": "ok",
    "obj": {
        "pageSize": 8,
        "recordCount": 1000,
        "currentPage": 1,
        "pageCount": 125,
        "currentTime": 1787992783741,
        "inforList": [
            {
                "id": "20260829163923805673",
                "content": "<p>【数据：过去 7 天 ETH 供应量增加 20,125 枚 ETH】火星财经消息，据 Cointelegraph 报道，ETH 供应量在过去 7 天内增加了超过 20,125 枚 ETH。</p>",
                "upCounts": 7,
                "downCounts": 3,
                "images": "",
                "imagesRemark": "",
                "url": "",
                "status": 1,
                "createdBy": "fff9d400cb94444fadaefd429516c276",
                "createdTime": 1787992764000,
                "channelId": 21,
                "tag": 1,
                "author": "MarsBit 快讯",
                "audio": "https://hx24-media-prod.marsbit.co/audio/live/20260829163923805673.mp3",
                "align": 0,
            },
            {
                "id": "20260829163215103904",
                "content": "<p>【Codex或再破用户纪录：Tibo暗示明天又要送额度重置】动察 Beating AI 快讯，OpenAI 核心产品负责人 Thibault Sottiaux 暗示，Codex 可能在明天达到新的增长里程碑。</p>",
                "upCounts": 2,
                "downCounts": 0,
                "images": "",
                "imagesRemark": "",
                "url": "",
                "status": 1,
                "createdBy": "abc",
                "createdTime": 1787992335000,
                "channelId": 21,
                "tag": 1,
                "author": "MarsBit 快讯",
                "audio": "",
                "align": 0,
            },
            {
                "id": "20260829120000000000",
                "content": "",
                "status": 1,
                "createdTime": 1787989200000,
                "channelId": 21,
                "tag": 1,
                "author": "MarsBit 快讯",
            },
        ],
    },
}


def banner(t: str) -> None:
    print("\n" + "=" * 60)
    print(t)
    print("=" * 60)


def test_import_smoke() -> None:
    banner("[1] 导入冒烟（类可直接构造，factory 注册由部署方按需添加）")
    from finfeed.core.parsers.base import BaseParser
    from finfeed.core.parsers.factory import create_parser

    src = NewsSource(
        name="火星财经",
        url="https://api.marsbit.co/info/lives/showlives",
        parser_type="marsbit",
        headers={"User-Agent": "Mozilla/5.0", "Referer": "https://news.marsbit.co/flash"},
        params={"currentPage": 1, "pageSize": 50},
    )
    parser = MarsbitParser(src)
    print("  MarsbitParser ->", type(parser).__name__)
    assert isinstance(parser, BaseParser), "MarsbitParser 应为 BaseParser 子类"
    assert parser.source.parser_type == "marsbit"

    created = create_parser(src)
    assert isinstance(created, MarsbitParser), "factory 应能按 parser_type='marsbit' 创建 MarsbitParser"
    print("  create_parser('marsbit') ->", type(created).__name__)
    print("  OK")


def test_parse_offline() -> None:
    banner("[2] 离线单测 parse()")
    parser = MarsbitParser(NewsSource(name="火星财经", url="https://api.marsbit.co/info/lives/showlives", parser_type="marsbit"))
    resp = httpx.Response(200, json=SAMPLE_JSON)
    items = asyncio.run(parser.parse(resp))
    print(f"  解析条目: {len(items)}")
    assert len(items) == 2, "空正文条目应被过滤，仅保留 2 条"
    first = items[0]
    print("  样例1:", first.title[:40], "|", first.publish_time, "|", first.url[:60])
    assert first.title == "数据：过去 7 天 ETH 供应量增加 20,125 枚 ETH"
    assert first.publish_ts == 1787992764, "createdTime 毫秒应转为秒"
    assert first.publish_time == bj_str_from_ts(1787992764)
    assert first.url == "https://news.marsbit.co/flash/20260829163923805673.html"
    assert "火星财经消息" in first.intro, "intro 应包含正文"
    assert first.source == "火星财经"
    second = items[1]
    print("  样例2:", second.title[:40], "| intro:", second.intro[:40])
    assert second.title == "Codex或再破用户纪录：Tibo暗示明天又要送额度重置"
    # 增量过滤：last_ts 设为最新时间后，再次解析应全部跳过
    parser.last_ts = 1787992764
    items2 = asyncio.run(parser.parse(resp))
    assert len(items2) == 0, "增量过滤后应无新条目"
    print("  增量过滤正确")
    print("  OK")


def test_live() -> None:
    banner("[3] 真实联网抓取（尽力，无网则跳过）")
    parser = MarsbitParser(NewsSource(
        name="火星财经",
        url="https://api.marsbit.co/info/lives/showlives",
        parser_type="marsbit",
        headers={
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
            "Referer": "https://news.marsbit.co/flash",
            "Accept": "application/json, text/plain, */*",
        },
        params={"currentPage": 1, "pageSize": 50},
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
    for fn in (test_import_smoke, test_parse_offline, test_live):
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
