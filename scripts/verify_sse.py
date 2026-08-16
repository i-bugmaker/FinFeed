#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""上交所公告解析器验证脚本

覆盖：
  1) 导入冒烟（json_parsers 注册、factory 构造 SseParser）
  2) SseParser._synthesize_ts 时间合成逻辑
  3) SseParser._build_url 附件 URL 拼接
  4) 真实联网抓取当日公告并解析为 NewsItem（沙箱无网则跳过）
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
from finfeed.core.parsers.json_parsers.sse import SseParser
from finfeed.utils.time_utils import now_bj


def banner(t):
    print("\n" + "=" * 60)
    print(t)
    print("=" * 60)


def test_import_smoke():
    banner("[1] 导入冒烟 + factory 注册")
    assert "sse" in get_registered_parsers(), "sse 未注册"
    p = create_parser(NewsSource(name="上交所公告", url="http://query.sse.com.cn/", parser_type="sse"))
    print("  create_parser ->", type(p).__name__)
    assert isinstance(p, SseParser)
    print("  OK")


def test_synthesize_ts():
    banner("[2] SseParser._synthesize_ts 时间合成")
    today = now_bj().date()
    today_str = today.strftime("%Y-%m-%d")

    ts_today = SseParser._synthesize_ts(today_str)
    print(f"  当日 {today_str} -> ts={ts_today}，与当前时刻偏差={abs(ts_today - int(__import__('time').time()))}s")
    assert ts_today > 0
    assert abs(ts_today - int(__import__("time").time())) < 3600

    ts_hist = SseParser._synthesize_ts("2026-08-01")
    from datetime import datetime, timedelta, timezone

    expect = int(datetime(2026, 8, 1, 9, 0, 0, tzinfo=timezone(timedelta(hours=8))).timestamp())
    assert ts_hist == expect, f"历史日期应固定 09:00:00，got {ts_hist} expect {expect}"
    print(f"  历史 2026-08-01 -> ts={ts_hist}（09:00:00）")

    assert SseParser._synthesize_ts("") == 0
    assert SseParser._synthesize_ts("bad-date") == 0
    print("  空/非法输入 -> 0")
    print("  OK")


def test_build_url():
    banner("[3] SseParser._build_url 附件 URL 拼接")
    url = SseParser._build_url("/disclosure/listedinfo/announcement/c/new/2026-08-15/600000_20260815_WBJG.pdf")
    print("  ", url)
    assert url == "https://static.sse.com.cn/disclosure/listedinfo/announcement/c/new/2026-08-15/600000_20260815_WBJG.pdf"
    assert SseParser._build_url("") == ""
    assert SseParser._build_url("https://x.com/a.pdf") == "https://x.com/a.pdf"
    print("  OK")


def test_live():
    banner("[4] 真实联网抓取（尽力，沙箱无网则跳过）")

    async def run():
        parser = SseParser(NewsSource(name="上交所公告", url="http://query.sse.com.cn/", parser_type="sse"))
        today_str = now_bj().strftime("%Y-%m-%d")
        async with httpx.AsyncClient(timeout=20, follow_redirects=True) as client:
            # 直接验证接口原始响应（不走 parser，先确认端点可用）
            params = {
                "jsonCallBack": "",
                "isPagination": "true",
                "pageHelp.pageSize": "50",
                "pageHelp.cacheSize": "1",
                "pageHelp.pageNo": "1",
                "START_DATE": today_str,
                "END_DATE": today_str,
                "SECURITY_CODE": "",
                "TITLE": "",
                "BULLETIN_TYPE": "",
                "stockType": "",
            }
            headers = {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/132.0.0.0 Safari/537.36",
                "Referer": "http://www.sse.com.cn/disclosure/listedinfo/announcement/",
            }
            resp = await client.get(
                "http://query.sse.com.cn/security/stock/queryCompanyBulletinNew.do",
                params=params,
                headers=headers,
            )
            print(f"  接口 HTTP {resp.status_code}")
            assert resp.status_code == 200
            data = resp.json()
            page_help = data.get("pageHelp") or {}
            groups = page_help.get("data") or []
            total = page_help.get("total", 0)
            flat = [it for g in groups for it in g]
            print(f"  total={total} pageCount={page_help.get('pageCount')} 扁平条目={len(flat)}")
            if total == 0 and now_bj().weekday() >= 5:
                print("  当日公告为空（周末非交易日，预期行为，跳过严格断言）")
            else:
                assert total > 0, "SSE 当日公告为空"

            # 通过 parser.parse 走完整解析路径（response.client 由 fetcher 附加）
            resp.client = client
            news = await parser.parse(resp)
            print(f"  parser.parse 产出 {len(news)} 条 NewsItem")
            if news:
                first = news[0]
                print("   样例:", first.title[:50], "|", first.publish_time, "|", first.url[:60])
                assert first.title and first.url.startswith("https://static.sse.com.cn")
                assert first.publish_ts > 0
        # 分页遍历验证（第2页仍可拿数据）
        async with httpx.AsyncClient(timeout=20, follow_redirects=True) as client:
            params["pageHelp.pageNo"] = "2"
            resp2 = await client.get(
                "http://query.sse.com.cn/security/stock/queryCompanyBulletinNew.do",
                params=params,
                headers=headers,
            )
            assert resp2.status_code == 200
            g2 = (resp2.json().get("pageHelp") or {}).get("data") or []
            print(f"  第2页分组数={len(g2)}")

    try:
        asyncio.run(run())
    except AssertionError:
        raise
    except Exception as e:
        print("  联网失败(预期沙箱无网):", str(e)[:80])
    print("  OK")


if __name__ == "__main__":
    fails = []
    for fn in (test_import_smoke, test_synthesize_ts, test_build_url, test_live):
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
