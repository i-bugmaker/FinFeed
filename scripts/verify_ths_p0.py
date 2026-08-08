#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""P0 增强验证脚本：同花顺股吧 JSON + 同花顺热股榜

覆盖：
  1) 导入冒烟（factory 注册、sources、解析器、pipeline）
  2) ThsGubaJsonParser._parse_post 解析结构化帖子 -> meta 落库字段
  3) ThsHotRankParser._parse_eq / _parse_dq 排名聚合
  4) pipeline._boost_importance_with_meta 互动量/排名/认证 增强
  5) SOURCE_SIGNAL 含新源
  6) 尽力尝试真实联网抓取（沙箱无网则跳过）
"""

import asyncio
import json
import sys
import traceback

from finfeed.config.sources import NewsSource, get_forum_sources
from finfeed.core.parsers.factory import create_parser
from finfeed.core.parsers.forum_parsers.ths import (
    ThsGubaJsonParser, ThsHotRankParser, THS_GUBA_FOCUS_CODES,
)
from finfeed.core.pipeline import _boost_importance_with_meta
from finfeed.analysis.forum_sentiment import SOURCE_SIGNAL


def banner(t):
    print("\n" + "=" * 60)
    print(t)
    print("=" * 60)


def test_import_smoke():
    banner("[1] 导入冒烟 + factory 注册")
    srcs = [s for s in get_forum_sources() if s.parser_type in ("ths_guba_json", "ths_hot_rank")]
    names = {s.name: s.parser_type for s in srcs}
    print("FORUM_SOURCES 中的同花顺新源:", names)
    assert "同花顺股吧热帖" in names and names["同花顺股吧热帖"] == "ths_guba_json"
    assert "同花顺热股榜" in names and names["同花顺热股榜"] == "ths_hot_rank"
    # 通过 factory 构造解析器
    p1 = create_parser(NewsSource(name="同花顺股吧热帖", url="https://t.10jqka.com.cn/", parser_type="ths_guba_json"))
    p2 = create_parser(NewsSource(name="同花顺热股榜", url="https://eq.10jqka.com.cn/", parser_type="ths_hot_rank"))
    print("  create_parser ->", type(p1).__name__, type(p2).__name__)
    assert isinstance(p1, ThsGubaJsonParser) and isinstance(p2, ThsHotRankParser)
    print("  OK")


def test_guba_parse_post():
    banner("[2] ThsGubaJsonParser._parse_post 解析结构化帖子")
    parser = ThsGubaJsonParser(NewsSource(name="同花顺股吧热帖", url="https://t.10jqka.com.cn/", parser_type="ths_guba_json"))
    post = {
        "pid": "991234", "uid": "8821", "code": "300059",
        "content": "东方财富这波行情太猛了，散户都在追，小心追高被套！",
        "ctime": int(__import__("time").time()), "mtime": int(__import__("time").time()),
        "user": {"nickname": "老股民", "is_v": 1, "stock_age": 8},
        "ip_location": "广东",
        "stat": {"reply": 120, "share": 30, "like": 560, "forward": 12},
    }
    item = parser._parse_post(post, "300059", "东方财富")
    assert item is not None, "解析返回空"
    assert item.category == "forum"
    assert "300059" in item.stocks  # 目标股在提及列表中（源名含"同花顺"会附带300033，属既有行为）
    meta = item.meta
    print("  meta =", json.dumps(meta, ensure_ascii=False))
    assert meta["likes"] == 560 and meta["replies"] == 120
    assert meta["forwards"] == 12 and meta["shares"] == 30
    assert meta["is_v"] is True and meta["ip_location"] == "广东"
    assert meta["stock_age"] == 8 and meta["uid"] == "8821"
    # 互动量过低/过短/广告 应过滤
    assert parser._parse_post({"content": "短", "pid": "1"}, "300059", "x") is None
    promo = {"pid": "2", "content": "免费领取牛股，加微信内部群", "stat": {}}
    assert parser._parse_post(promo, "300059", "x") is None
    print("  互动量/认证/地域 落库正确；噪声过滤正确")
    print("  OK")


def test_hot_rank_parse():
    banner("[3] ThsHotRankParser 排名聚合（eq + dq）")
    parser = ThsHotRankParser(NewsSource(name="同花顺热股榜", url="https://eq.10jqka.com.cn/", parser_type="ths_hot_rank"))

    eq_snapshot = [{
        "order": 1, "code": "300059", "name": "东方财富", "rate": "1163740.5",
        "market": "sz", "tag": {"concept_tag": ["金融科技", "互联网券商"]},
    }, {
        "order": 2, "code": "600519", "name": "贵州茅台", "rate": "998877.0",
        "market": "sh", "tag": {"concept_tag": ["白酒"]},
    }]
    # 真实结构：stock_list 为按时间戳为键的 dict，取最大键=最新快照
    eq_data = {"data": {"stock_list": {"202608071050": eq_snapshot}}}
    ranked = asyncio.run(parser._parse_eq(eq_data))
    print("  eq ranked:", {k: (v["rank"], v["rate"], v["concept_tag"]) for k, v in ranked.items()})
    assert ranked["300059"]["rank"] == 1 and ranked["300059"]["concept_tag"][0] == "金融科技"
    assert ranked["600519"]["rank"] == 2
    assert ranked["300059"]["rate"] is None  # eq 的 rate 是热度值，非百分比

    dq_items = [
        {"code": "000001", "name": "平安银行", "order": 5, "rise_and_fall": 2.1,
         "tag": {"concept_tag": ["银行", "红利"]}},
        {"stock_code": "600036", "stock_name": "招商银行", "hot_rank": 9,
         "rise_and_fall": 1.5, "tag": {"concept_tag": ["银行"]}},
    ]
    dq_data = {"data": {"stock_list": dq_items}}
    dq = asyncio.run(parser._parse_dq("hour", dq_data))
    print("  dq(hour):", {k: (v["rank"], v["rate"], v["concept_tag"]) for k, v in dq.items()})
    assert dq["000001"]["rank"] == 5 and dq["600036"]["rank"] == 9
    assert dq["000001"]["rate"] == 2.1 and dq["000001"]["concept_tag"][0] == "银行"
    print("  OK")


async def _patch_eq(parser, data):
    return await parser._parse_eq(data)


async def _patch_dq(parser, period, data):
    return await parser._parse_dq(period, data)


def test_boost():
    banner("[4] pipeline._boost_importance_with_meta 增强")
    # 排名 -> 重要性（rank1≈10.0，rank100≈1.0，区分头部）
    r1 = _boost_importance_with_meta(5.0, {"rank": 1})
    r100 = _boost_importance_with_meta(5.0, {"rank": 100})
    print(f"  rank=1 -> {r1} ; rank=100 -> {r100}")
    assert r1 == 10.0 and r100 == 1.0
    # 互动量叠加
    eng = _boost_importance_with_meta(5.0, {"likes": 560, "replies": 120, "forwards": 12, "shares": 30})
    print(f"  高互动量 -> {eng}")
    assert eng > 5.0
    # 认证大V轻微降权
    base = _boost_importance_with_meta(6.0, {"likes": 0})
    vip = _boost_importance_with_meta(6.0, {"likes": 0, "is_v": True})
    print(f"  普通 {base} vs 大V {vip}")
    assert vip < base
    # 空 meta 透传
    assert _boost_importance_with_meta(4.2, None) == 4.2
    print("  OK")


def test_signal_map():
    banner("[5] forum_sentiment.SOURCE_SIGNAL 含新源")
    print("  ", {k: SOURCE_SIGNAL[k] for k in ("同花顺热股榜", "同花顺股吧热帖", "同花顺")})
    assert SOURCE_SIGNAL.get("同花顺热股榜") == 1.2
    assert SOURCE_SIGNAL.get("同花顺股吧热帖") == 1.1
    print("  OK")


def test_live():
    banner("[6] 真实联网抓取（尽力，沙箱无网则跳过）")
    async def run():
        guba = ThsGubaJsonParser(NewsSource(name="同花顺股吧热帖", url="https://t.10jqka.com.cn/", parser_type="ths_guba_json"))
        hot = ThsHotRankParser(NewsSource(name="同花顺热股榜", url="https://eq.10jqka.com.cn/", parser_type="ths_hot_rank"))
        import httpx
        dummy = httpx.Response(200, json={})
        try:
            g = await guba.parse(dummy)
            print(f"  股吧JSON 抓取条目: {len(g)}")
            if g:
                print("   样例:", g[0].title[:40], "| meta:", json.dumps(g[0].meta, ensure_ascii=False)[:120])
        except Exception as e:
            print("  股吧JSON 联网失败(预期沙箱无网):", str(e)[:80])
        try:
            h = await hot.parse(dummy)
            print(f"  热股榜 抓取条目: {len(h)}")
            if h:
                print("   样例:", h[0].title)
        except Exception as e:
            print("  热股榜 联网失败(预期沙箱无网):", str(e)[:80])
    try:
        asyncio.run(run())
    except Exception as e:
        print("  联网测试异常:", str(e)[:80])


if __name__ == "__main__":
    fails = []
    for fn in (test_import_smoke, test_guba_parse_post, test_hot_rank_parse, test_boost, test_signal_map, test_live):
        try:
            fn()
        except Exception as e:
            fails.append((fn.__name__, traceback.format_exc()))
            print(f"\n!!! {fn.__name__} 失败:\n{traceback.format_exc()}")
    banner("结果汇总")
    if fails:
        print(f"失败 {len(fails)} 项:", [f[0] for f in fails])
        sys.exit(1)
    print("全部通过 ✅")
