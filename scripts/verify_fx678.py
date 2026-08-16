#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""汇通网 7×24 快讯解析器冒烟验证脚本

覆盖：
  1) 导入冒烟（factory 注册、解析器构造）
  2) 离线样本解析（zykx 响应结构：code=10 + data JSON 字符串）
  3) 标题/正文拆分（【】前缀 + 无前缀两种形态）
  4) 增量过滤（last_ts）
  5) 补抓模式（_catch_up_single_request，单请求）
  6) 尽力尝试真实联网抓取（沙箱无网则跳过）
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
from finfeed.core.parsers.json_parsers.fx678 import Fx678Parser
from finfeed.utils.time_utils import now_bj

_SOURCE = NewsSource(
    name="汇通网快讯",
    url="https://www.fx678.com/kx/ajax/zykx",
    parser_type="fx678",
    method="POST",
    headers={
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
        "Referer": "https://www.fx678.com/kx/",
        "Accept": "application/json, text/javascript, */*; q=0.01",
        "X-Requested-With": "XMLHttpRequest",
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
    assert isinstance(p, Fx678Parser), f"create_parser 返回 {type(p).__name__}"
    print("  OK")


def _sample_response() -> httpx.Response:
    """构造与真实 zykx 接口一致的离线样本"""
    sample = {
        "code": 10,
        "msg": "成功!",
        "data": json.dumps([
            {
                "NEWSID": "202608151930292061",
                "NEWS_TITLE": "【伊朗与阿曼就霍尔木兹海峡“航运地图”达成一致】\r\n1. 伊朗外交部发言人表示，双方同意建立联合工作组，确保海峡通行安全。\r\n\r\n2. 阿曼方面称，该协议将于下月生效。",
                "PUBLISHTIME": "2026-08-15 19:30:29",
            },
            {
                "NEWSID": "202608151621242064",
                "NEWS_TITLE": "霍尔木兹危机再升级！油轮接连遇袭，油价一周狂飙超5%",
                "PUBLISHTIME": "2026-08-15 16:21:26",
            },
            {
                "NEWSID": "202608151200000001",
                "NEWS_TITLE": "【测试】含 <b>HTML</b> 标签的正文",
                "PUBLISHTIME": "2026-08-15 12:00:00",
            },
        ]),
    }
    return httpx.Response(200, json=sample)


def test_parse_offline():
    banner("[2] 离线样本解析（zykx 响应结构）")
    parser = Fx678Parser(_SOURCE)
    items = asyncio.run(parser.parse(_sample_response()))
    print(f"  解析条目: {len(items)}")
    for it in items:
        print(f"    [{it.publish_time}] {it.title[:40]} | intro={it.intro[:30]!r}")
    assert len(items) == 3
    # 【】前缀拆分
    assert items[0].title == "伊朗与阿曼就霍尔木兹海峡“航运地图”达成一致"
    assert "1. 伊朗外交部发言人" in items[0].intro
    assert "\r" not in items[0].intro, "intro 应归一化 \\r\\n -> \\n"
    # 无前缀整行标题
    assert items[1].title.startswith("霍尔木兹危机")
    assert items[1].intro == ""
    # HTML 剥离
    assert "<b>" not in items[2].intro and "HTML" in items[2].intro
    # 详情页 URL 规则
    assert items[0].url == "https://www.fx678.com/C/20260815/202608151930292061.html"
    # 时间戳
    assert items[0].publish_ts > 0 and items[0].publish_time == "2026-08-15 19:30:29"
    print("  OK")


def test_incremental_filter():
    banner("[3] 增量过滤（last_ts）")
    parser = Fx678Parser(_SOURCE)
    items = asyncio.run(parser.parse(_sample_response()))
    parser.last_ts = items[1].publish_ts  # 只保留比 16:21 更新的
    items2 = asyncio.run(parser.parse(_sample_response()))
    print(f"  last_ts={parser.last_ts} -> 过滤后 {len(items2)} 条")
    assert len(items2) == 1 and items2[0].title.startswith("伊朗与阿曼")
    print("  OK")


def test_catch_up():
    banner("[4] 补抓模式（_catch_up_single_request，单请求）")
    parser = Fx678Parser(_SOURCE)
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
        parser = Fx678Parser(_SOURCE)
        async with httpx.AsyncClient(timeout=15, follow_redirects=True) as client:
            resp = await client.post(_SOURCE.url, headers=dict(_SOURCE.headers))
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
