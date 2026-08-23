#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""探测 dataapi 三池为空的原因：逐参数组合试打。"""
import asyncio
import json
import sys
import time

sys.path.insert(0, ".")

from finfeed.market import ths_limitup as M  # noqa: E402


async def probe(path, params, tag):
    try:
        raw = await M._request(path, params, mobile=False)
        d = M._data_of(raw)
        if isinstance(d, dict):
            lst = d.get("list") or d.get("data") or []
            print(f"  [{tag:42s}] keys={list(d.keys())[:8]} total={d.get('total')} "
                  f"count={d.get('count')} len={len(lst)}")
            if lst:
                print(f"       sample={json.dumps(lst[0], ensure_ascii=False)[:220]}")
        elif isinstance(d, list):
            print(f"  [{tag:42s}] list len={len(d)}")
            if d:
                print(f"       sample={json.dumps(d[0], ensure_ascii=False)[:220]}")
        else:
            print(f"  [{tag:42s}] type={type(d).__name__} val={str(d)[:120]}")
    except Exception as e:  # noqa: BLE001
        print(f"  [{tag:42s}] EXC {type(e).__name__}: {e}")


async def main():
    td = M.now_bj().strftime("%Y-%m-%d")
    ymd = M._ymd(td)
    ms = int(time.time() * 1000)
    F = M._POOL_FIELDS

    print(f"\n--- 当前参数（现网实现） date={td} ---")
    await probe("/limit_up/limit_up_pool",
                {"page": 1, "limit": 200, "field": F, "filter": "HS,GEM2STAR",
                 "order_field": "330324", "order_type": 0, "_": ms}, "现网参数 filter=HS,GEM2STAR")

    print("\n--- 变体测试 ---")
    await probe("/limit_up/limit_up_pool",
                {"page": 1, "limit": 200, "field": F, "_": ms}, "去掉 filter/order")
    await probe("/limit_up/limit_up_pool",
                {"page": 1, "limit": 200, "field": F, "filter": "HS,GEM2STAR",
                 "date": ymd, "order_field": "330324", "order_type": 0, "_": ms}, "加 date")
    await probe("/limit_up/limit_up_pool", {}, "无参数")
    await probe("/limit_up/limit_up_pool", {"page": 1, "limit": 200}, "仅分页（无 field）")
    await probe("/limit_up/limit_up_pool",
                {"page": 1, "limit": 200, "field": F, "filter": "HS",
                 "order_field": "330324", "order_type": 0, "_": ms}, "filter=HS")
    await probe("/limit_up/limit_up_pool",
                {"page": 1, "limit": 200, "field": F, "filter": "HS,GEM2STAR",
                 "order_field": "199112", "order_type": 0, "_": ms}, "order_field=199112")

    print("\n--- 炸板 / 跌停池 ---")
    for k in ("open_limit_pool", "lower_limit_pool"):
        await probe(f"/limit_up/{k}",
                    {"page": 1, "limit": 200, "field": F, "filter": "HS,GEM2STAR",
                     "order_field": "330324", "order_type": 0, "_": ms}, f"{k} 现网参数")
        await probe(f"/limit_up/{k}", {"page": 1, "limit": 200, "field": F}, f"{k} 去 filter")

    print("\n--- mobileapi 分层涨停池（富化源，作为交叉验证） ---")
    for cate in ("limit_up_all", "limit_up", "continuous_limit_up", "open_limit_up"):
        try:
            lst = await M._get_limit_up_stocks(cate, td)
            print(f"  [cate={cate:20s}] {len(lst)} 只"
                  f"{'  head=' + str([x['name'] for x in lst[:5]]) if lst else ''}")
        except Exception as e:  # noqa: BLE001
            print(f"  [cate={cate:20s}] EXC {e}")

    print("\n--- 涨停简图涨停股总数（交叉验证真实涨停家数） ---")
    blocks = await M._get_block_top(td)
    codes = {s.get("code") for b in blocks for s in (b.get("stock_list") or [])}
    print(f"  题材数={len(blocks)} 去重涨停股={len(codes)}")
    print("\n--- 情绪总览 limit_up 字段 ---")
    ov = await M._get_overview(td)
    print(f"  limit_up={ov.get('limit_up')}  rise_fall={ov.get('rise_fall')}")
    print(f"  trade_status={await M._get_trade_status()}")


if __name__ == "__main__":
    asyncio.run(main())
