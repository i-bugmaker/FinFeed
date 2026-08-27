#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""正确解析下对比 filter 变体，确认抓取范围完整性（是否漏北交所等）。"""
import asyncio
import sys
import time
from collections import Counter

sys.path.insert(0, ".")

from finfeed.market import ths_limitup as M  # noqa: E402


async def pull(kind, extra):
    ms = int(time.time() * 1000)
    params = {"page": 1, "limit": 200, "_": ms}
    params.update(extra)
    d = M._data_of(await M._request(f"/limit_up/{kind}", params, mobile=False))
    info = d.get("info") or []
    page = d.get("page") or {}
    return info, page, d


async def main():
    variants = {
        "filter=HS,GEM2STAR (现网)": {"filter": "HS,GEM2STAR"},
        "filter=HS": {"filter": "HS"},
        "无 filter": {},
        "filter=HS,GEM2STAR,BJ": {"filter": "HS,GEM2STAR,BJ"},
    }
    for tag, extra in variants.items():
        try:
            info, page, _ = await pull("limit_up_pool", extra)
            mt = Counter(x.get("market_type") for x in info)
            mid = Counter(x.get("market_id") for x in info)
            print(f"  {tag:26s} total={page.get('total'):>4} count={page.get('count')} "
                  f"len={len(info):>4} market_type={dict(mt)} market_id={dict(mid)}")
        except Exception as e:  # noqa: BLE001
            print(f"  {tag:26s} EXC {e}")

    print("\n--- change_tag / is_again_limit 分布（现网 filter） ---")
    for kind in ("limit_up_pool", "open_limit_pool", "lower_limit_pool"):
        info, page, d = await pull(kind, {"filter": "HS,GEM2STAR"})
        print(f"  {kind:18s} total={page.get('total')} "
              f"change_tag={dict(Counter(x.get('change_tag') for x in info))} "
              f"again={dict(Counter(x.get('is_again_limit') for x in info))} "
              f"high_days={dict(Counter(x.get('high_days_value') for x in info))}")

    print("\n--- 分页完整性：limit=20 循环拉全 ---")
    all_codes, pg = [], 1
    while pg <= 10:
        ms = int(time.time() * 1000)
        d = M._data_of(await M._request("/limit_up/limit_up_pool", {
            "page": pg, "limit": 20, "filter": "HS,GEM2STAR", "_": ms}, mobile=False))
        info = d.get("info") or []
        page = d.get("page") or {}
        all_codes += [x.get("code") for x in info]
        print(f"    page={pg} len={len(info)} total={page.get('total')} count={page.get('count')}")
        if pg >= int(page.get("count") or 1):
            break
        pg += 1
    print(f"    合计={len(all_codes)} 去重={len(set(all_codes))}")

    print("\n--- 与 mobileapi 富化源交叉验证 ---")
    td = M.now_bj().strftime("%Y-%m-%d")
    rich = await M._get_limit_up_stocks("limit_up_all", td)
    info, page, _ = await pull("limit_up_pool", {"filter": "HS,GEM2STAR"})
    a = {x.get("code") for x in info}
    b = {x.get("code") for x in rich}
    print(f"    dataapi={len(a)} mobileapi={len(b)} 交集={len(a & b)} "
          f"仅dataapi={sorted(a - b)} 仅mobileapi={sorted(b - a)}")


if __name__ == "__main__":
    asyncio.run(main())
