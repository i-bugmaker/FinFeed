#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""涨停聚焦：容错链路故障注入验证（Task #6）

用例：
  1. 全部实时正常                     → source=live，四模块有数据
  2. 注入 limit_up_pool 单点失败      → L1：up 池 DB 补位，open/lower 仍实时
  3. 注入三池全失败                   → L2：整模块回退 DB
  4. 注入 get_limit_up_stocks 失败    → L1：天梯骨架保留，仅丢富化字段
  5. 注入 overview 失败               → L1：风向标股仍呈现
  6. 注入全部接口失败                 → L2：DB 回退 / 明确 error
"""
import asyncio
import sys

sys.path.insert(0, ".")

from finfeed.market import store  # noqa: E402
from finfeed.market import ths_limitup as M  # noqa: E402
from finfeed.storage.database import get_db_manager  # noqa: E402

_orig_request = M._request
_FAIL: set = set()


async def _patched_request(path, params=None, mobile=False, timeout=25.0):
    for pat in _FAIL:
        if pat in path:
            raise RuntimeError(f"[注入故障] {path}")
    return await _orig_request(path, params, mobile, timeout)


M._request = _patched_request


def _brief(name, d):
    if "error" in d:
        return f"  {name:10s} ERROR={d['error']} degraded={d.get('degraded')}"
    src = d.get("source")
    fb = d.get("fallback", "-")
    cd = d.get("cached_date", "-")
    dg = d.get("degraded") or []
    if name == "intensity":
        body = (f"up={len(d.get('up', []))}/{d.get('up_total')} "
                f"open={len(d.get('open', []))}/{d.get('open_total')} "
                f"lower={len(d.get('lower', []))}/{d.get('lower_total')} "
                f"封板率={d.get('metrics', {}).get('seal_rate')}")
        rich = sum(1 for x in d.get("up", []) if x.get("limit_up_time"))
        body += f" 富化={rich}"
    elif name == "ladder":
        body = (f"梯队={len(d.get('ladder', []))} 最高={d.get('max_height')} "
                f"股数={sum(len(x['stocks']) for x in d.get('ladder', []))}")
        rich = sum(1 for x in d.get("ladder", []) for s in x["stocks"] if s.get("reason"))
        body += f" 富化={rich}"
    elif name == "wind":
        bl = d.get("blocks", [])
        body = (f"题材={len(bl)} 涨停股={sum(len(b.get('stocks', [])) for b in bl)} "
                f"TOP={'/'.join(b['name'] for b in bl[:3])}")
    else:
        tabs = d.get("wind_vane", {}).get("tabs", [])
        body = (f"涨停={d.get('limit_up', {}).get('now')} "
                f"涨/跌={d.get('rise_fall', {}).get('rise')}/{d.get('rise_fall', {}).get('fall')} "
                f"风向标tab={len(tabs)}({sum(len(t['stocks']) for t in tabs)}股)")
    return f"  {name:10s} src={src:12s} fb={fb:24s} cached={cd} degraded={dg}\n             {body}"


async def case(title, fails):
    global _FAIL
    _FAIL = set(fails)
    M._CACHE.clear()  # 清缓存，确保真的重打接口
    print(f"\n=== {title} ===")
    print(f"    注入失败: {sorted(fails) or '无'}")
    for name, fn in (("intensity", M.fetch_limit_up_intensity),
                     ("ladder", M.fetch_board_ladder),
                     ("wind", M.fetch_strong_wind),
                     ("sentiment", M.fetch_market_sentiment)):
        try:
            print(_brief(name, await fn()))
        except Exception as e:  # noqa: BLE001
            print(f"  {name:10s} !! 未捕获异常 {type(e).__name__}: {e}")


async def main():
    store.ensure_market_tables()
    await case("用例1 全部正常（并落库当日快照）", [])
    await case("用例2 涨停池单点失败 → L1 DB 补位", ["limit_up/limit_up_pool"])
    await case("用例3 三池全失败 → L2 模块回退", [
        "limit_up/limit_up_pool", "limit_up/open_limit_pool", "limit_up/lower_limit_pool"])
    await case("用例4 富化源失败 → L1 保留骨架", ["get_limit_up_stocks"])
    await case("用例5 情绪总览失败 → L1 保留风向标", ["market_state/v1/overview"])
    await case("用例6 全接口失败 → L2 全模块回退", [
        "limit_up/", "stock_pool/", "market_state/"])

    # 落库校验
    print("\n=== DB 快照校验 ===")
    td = M.now_bj().strftime("%Y-%m-%d")
    for pt in ("up", "open", "lower"):
        print(f"  pool[{pt:5s}] {len(store.get_ths_limitup_pool(td, pt))} 行")
    print(f"  ladder      {len(store.get_ths_limitup_ladder(td))} 行")
    print(f"  block_top   {len(store.get_ths_limitup_block_top(td))} 行")
    print(f"  wind        {len(store.get_ths_limitup_wind(td))} 行")
    print(f"  sentiment   {'1 行' if store.get_ths_limitup_sentiment(td) else '0 行'}")
    print(f"  已采日期    {store.get_ths_limitup_dates()['dates'][:5]}")


if __name__ == "__main__":
    get_db_manager()
    asyncio.run(main())
