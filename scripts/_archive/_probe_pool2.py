#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""dump dataapi 三池完整响应结构（info / page / *_count）。"""
import asyncio
import json
import sys
import time

sys.path.insert(0, ".")

from finfeed.market import ths_limitup as M  # noqa: E402


async def dump(kind):
    ms = int(time.time() * 1000)
    raw = await M._request(f"/limit_up/{kind}", {
        "page": 1, "limit": 200, "field": M._POOL_FIELDS,
        "filter": "HS,GEM2STAR", "order_field": "330324", "order_type": 0, "_": ms,
    }, mobile=False)
    d = M._data_of(raw)
    print(f"\n===== {kind} =====")
    print(f"  外层 keys: {list(raw.keys()) if isinstance(raw, dict) else type(raw)}")
    print(f"  data keys: {list(d.keys())}")
    for k in ("page", "limit_up_count", "limit_down_count", "date", "msg", "trade_status"):
        print(f"    {k:18s} = {json.dumps(d.get(k), ensure_ascii=False)[:200]}")
    info = d.get("info")
    print(f"    info               type={type(info).__name__} "
          f"len={len(info) if hasattr(info, '__len__') else '-'}")
    if isinstance(info, list) and info:
        print(f"      [0] = {json.dumps(info[0], ensure_ascii=False)[:400]}")
        print(f"      [0] keys = {list(info[0].keys()) if isinstance(info[0], dict) else '-'}")
        if len(info) > 1:
            print(f"      [-1]= {json.dumps(info[-1], ensure_ascii=False)[:300]}")
    elif isinstance(info, dict):
        print(f"      keys = {list(info.keys())[:20]}")
        print(f"      dump = {json.dumps(info, ensure_ascii=False)[:600]}")


async def main():
    for k in ("limit_up_pool", "open_limit_pool", "lower_limit_pool"):
        await dump(k)

    print("\n===== 分页探测：limit=20 看 page 结构 =====")
    ms = int(time.time() * 1000)
    raw = await M._request("/limit_up/limit_up_pool", {
        "page": 1, "limit": 20, "field": M._POOL_FIELDS,
        "filter": "HS,GEM2STAR", "order_field": "330324", "order_type": 0, "_": ms,
    }, mobile=False)
    d = M._data_of(raw)
    print(f"  page={json.dumps(d.get('page'), ensure_ascii=False)}  "
          f"info_len={len(d.get('info') or [])}")


if __name__ == "__main__":
    asyncio.run(main())
