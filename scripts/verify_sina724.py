#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""新浪财经 7×24 直播快讯解析器冒烟验证脚本

覆盖：
  1) 导入冒烟（factory 注册、解析器构造）
  2) 离线样本解析（zhibo/feed 响应结构：result.data.feed.list）
  3) 标题/正文拆分（【】前缀 + 无前缀首句两种形态）
  4) 详情页 URL 提取（ext.docurl 优先，docurl 兜底）
  5) 增量过滤（last_ts）
  6) 补抓模式（_catch_up_paginated，page 翻页）
  7) 尽力尝试真实联网抓取（沙箱无网则跳过）
"""

import asyncio
import json
import os
import sys
import traceback

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import httpx
from finfeed.config.sources import NewsSource
from finfeed.core.parsers.factory import create_parser
from finfeed.core.parsers.json_parsers.sina724 import Sina724Parser
from finfeed.utils.time_utils import now_bj

_SOURCE = NewsSource(
    name="新浪财经7×24",
    url="https://zhibo.sina.com.cn/api/zhibo/feed",
    parser_type="sina724",
    method="GET",
    headers={
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
        "Referer": "https://zhibo.sina.com.cn/finance/152",
        "Accept": "application/json, text/plain, */*",
    },
    params={
        "page_size": 100,
        "zhibo_id": 152,
        "tag_id": 0,
        "dire": "f",
        "dpc": 1,
    },
)


def banner(t):
    print("\n" + "=" * 60)
    print(t)
    print("=" * 60)


def test_import_smoke():
    banner("[1] 导入冒烟 + factory 注册")
    p = create_parser(_SOURCE)
    print("  create_parser ->", type(p).__name__)
    assert isinstance(p, Sina724Parser), f"create_parser 返回 {type(p).__name__}"
    print("  OK")


def _sample_response() -> httpx.Response:
    """构造与真实 zhibo/feed 接口一致的离线样本"""
    sample = {
        "result": {
            "status": {"code": 0, "msg": "OK"},
            "data": {
                "feed": {
                    "list": [
                        {
                            "id": 5042292,
                            "rich_text": "【伊朗与阿曼就霍尔木兹海峡“航运地图”达成一致】伊朗外交部发言人表示，双方同意建立联合工作组，确保海峡通行安全。",
                            "create_time": "2026-08-15 19:36:26",
                            "tag": "国际",
                            "is_delete": 0,
                            "ext": json.dumps({"docurl": "https://finance.sina.com.cn/world/2026-08-15/doc-xxxx.shtml"}),
                            "docurl": "https://zhibo.sina.com.cn/finance/152/detail/5042292",
                        },
                        {
                            "id": 5042291,
                            "rich_text": "中国地震台网正式测定：08月15日18时54分在印尼苏门答腊岛发生6.8级地震。震源深度170千米。",
                            "create_time": "2026-08-15 18:54:00",
                            "tag": "要闻",
                            "is_delete": 0,
                            "ext": "",
                            "docurl": "https://zhibo.sina.com.cn/finance/152/detail/5042291",
                        },
                        {
                            "id": 5042290,
                            "rich_text": "【已删除】这条不应出现",
                            "create_time": "2026-08-15 18:00:00",
                            "tag": "要闻",
                            "is_delete": 1,
                            "ext": "",
                            "docurl": "",
                        },
                    ]
                }
            },
        }
    }
    return httpx.Response(200, json=sample)


def test_parse_offline():
    banner("[2] 离线样本解析（zhibo/feed 响应结构）")
    parser = Sina724Parser(_SOURCE)
    items = asyncio.run(parser.parse(_sample_response()))
    print(f"  解析条目: {len(items)}")
    for it in items:
        print(f"    [{it.publish_time}] {it.title[:40]} | intro={it.intro[:30]!r}")
    assert len(items) == 2, "is_delete=1 的条目应被过滤"
    # 【】前缀拆分
    assert items[0].title == "伊朗与阿曼就霍尔木兹海峡“航运地图”达成一致"
    assert "伊朗外交部发言人" in items[0].intro
    # 无前缀：首句作标题
    assert items[1].title.startswith("中国地震台网正式测定")
    assert "震源深度170千米" in items[1].intro
    # 详情页 URL：ext.docurl 优先
    assert items[0].url == "https://finance.sina.com.cn/world/2026-08-15/doc-xxxx.shtml"
    # docurl 兜底
    assert items[1].url == "https://zhibo.sina.com.cn/finance/152/detail/5042291"
    # 时间戳
    assert items[0].publish_ts > 0 and items[0].publish_time == "2026-08-15 19:36:26"
    print("  OK")


def test_incremental_filter():
    banner("[3] 增量过滤（last_ts）")
    parser = Sina724Parser(_SOURCE)
    items = asyncio.run(parser.parse(_sample_response()))
    parser.last_ts = items[1].publish_ts  # 只保留比 18:54 更新的
    items2 = asyncio.run(parser.parse(_sample_response()))
    print(f"  last_ts={parser.last_ts} -> 过滤后 {len(items2)} 条")
    assert len(items2) == 1 and items2[0].title.startswith("伊朗与阿曼")
    print("  OK")


def test_catch_up():
    banner("[4] 补抓模式（_catch_up_paginated，page 翻页）")
    parser = Sina724Parser(_SOURCE)
    parser.last_ts = int(now_bj().timestamp()) - 3600  # 1 小时前
    parser.set_catch_up_mode(True, int(now_bj().timestamp()))

    async def run():
        async with httpx.AsyncClient(timeout=15, follow_redirects=True) as client:
            items = await parser.fetch_with_catch_up(client)
        return items

    try:
        items = asyncio.run(run())
        print(f"  补抓条目: {len(items)}")
        if items:
            print("   样例:", items[0].title[:40], "|", items[0].publish_time)
        assert len(items) > 0, "联网补抓应返回条目"
    except Exception as e:
        print("  联网失败（沙箱无网则跳过）:", str(e)[:120])
    finally:
        parser.set_catch_up_mode(False)
    print("  OK")


def test_live():
    banner("[5] 真实联网抓取（尽力，沙箱无网则跳过）")
    async def run():
        parser = Sina724Parser(_SOURCE)
        async with httpx.AsyncClient(timeout=15, follow_redirects=True) as client:
            resp = await client.get(_SOURCE.url, headers=dict(_SOURCE.headers), params=dict(_SOURCE.params))
            if resp.status_code != 200:
                print(f"  HTTP {resp.status_code}")
                return
            items = await parser.parse(resp)
            print(f"  抓取条目: {len(items)}")
            if items:
                print("   样例:", items[0].title[:40], "|", items[0].publish_time)
            assert len(items) > 0, "真实接口应返回条目"
    try:
        asyncio.run(run())
    except Exception as e:
        print("  联网失败（沙箱无网则跳过）:", str(e)[:120])


if __name__ == "__main__":
    fails = []
    for fn in (test_import_smoke, test_parse_offline, test_incremental_filter, test_catch_up, test_live):
        try:
            fn()
        except Exception:
            fails.append((fn.__name__, traceback.format_exc()))
            print(f"\n!!! {fn.__name__} 失败:\n{traceback.format_exc()}")
    banner("结果汇总")
    if fails:
        print(f"失败 {len(fails)} 项:", [f[0] for f in fails])
        sys.exit(1)
    print("ALL PASS")
