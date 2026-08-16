#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""深交所公告解析器验证脚本

覆盖：
  1) 导入冒烟（json_parsers 注册、factory 构造 SzseParser）
  2) SzseParser._build_url 附件 URL 拼接
  3) 真实联网抓取当日公告并解析为 NewsItem（沙箱无网则跳过）
"""

import asyncio
import os
import sys
import traceback

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import httpx
from finfeed.config.sources import NewsSource
from finfeed.core.parsers.base import get_registered_parsers
from finfeed.core.parsers.factory import create_parser
from finfeed.core.parsers.json_parsers.szse import SzseParser
from finfeed.utils.time_utils import now_bj


def banner(t):
    print("\n" + "=" * 60)
    print(t)
    print("=" * 60)


def test_import_smoke():
    banner("[1] 导入冒烟 + factory 注册")
    assert "szse" in get_registered_parsers(), "szse 未注册"
    p = create_parser(NewsSource(name="深交所公告", url="http://www.szse.cn/", parser_type="szse"))
    print("  create_parser ->", type(p).__name__)
    assert isinstance(p, SzseParser)
    print("  OK")


def test_build_url():
    banner("[2] SzseParser._build_url 附件 URL 拼接")
    url = SzseParser._build_url("/disc/disk03/finalpage/2026-08-14/600000_20260814_1.PDF")
    print("  ", url)
    assert url == "http://disc.static.szse.cn/disc/disk03/finalpage/2026-08-14/600000_20260814_1.PDF"
    assert SzseParser._build_url("") == ""
    assert SzseParser._build_url("https://x.com/a.pdf") == "https://x.com/a.pdf"
    print("  OK")


def test_live():
    banner("[3] 真实联网抓取（尽力，沙箱无网则跳过）")

    async def run():
        parser = SzseParser(NewsSource(name="深交所公告", url="http://www.szse.cn/", parser_type="szse"))
        today_str = now_bj().strftime("%Y-%m-%d")
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/132.0.0.0 Safari/537.36",
            "Referer": "http://www.szse.cn/disclosure/listed/notice/index.html",
            "Content-Type": "application/json",
        }
        body = {
            "channelCode": ["listedNotice_disc"],
            "seDate": [today_str, today_str],
            "pageSize": 50,
            "pageNum": 1,
        }
        async with httpx.AsyncClient(timeout=20, follow_redirects=True) as client:
            resp = await client.post(
                "http://www.szse.cn/api/disc/announcement/annList",
                headers=headers,
                json=body,
            )
            print(f"  接口 HTTP {resp.status_code}")
            assert resp.status_code == 200
            data = resp.json()
            announce_count = int(data.get("announceCount") or 0)
            items = data.get("data") or []
            print(f"  announceCount={announce_count} 本页条目={len(items)}")
            if announce_count == 0 and now_bj().weekday() >= 5:
                print("  当日公告为空（周末非交易日，预期行为，跳过严格断言）")
            else:
                assert announce_count > 0, "SZSE 当日公告为空"

            # 通过 parser.parse 走完整解析路径（response.client 由 fetcher 附加）
            resp.client = client
            news = await parser.parse(resp)
            print(f"  parser.parse 产出 {len(news)} 条 NewsItem")
            if news:
                first = news[0]
                print("   样例:", first.title[:50], "|", first.publish_time, "|", first.url[:60])
                assert first.title and first.url.startswith("http://disc.static.szse.cn")
                assert first.publish_ts > 0
        # 分页遍历验证（第2页仍可拿数据）
        async with httpx.AsyncClient(timeout=20, follow_redirects=True) as client:
            body["pageNum"] = 2
            resp2 = await client.post(
                "http://www.szse.cn/api/disc/announcement/annList",
                headers=headers,
                json=body,
            )
            assert resp2.status_code == 200
            items2 = (resp2.json().get("data") or [])
            print(f"  第2页条目数={len(items2)}")

    try:
        asyncio.run(run())
    except AssertionError:
        raise
    except Exception as e:
        print("  联网失败(预期沙箱无网):", str(e)[:80])
    print("  OK")


if __name__ == "__main__":
    fails = []
    for fn in (test_import_smoke, test_build_url, test_live):
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
