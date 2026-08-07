#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""契约验证探针：锁定拟整合端点的真实字段名与返回规模。

只访问 datacenter-web（无限流）与 push2ex（单次），避开仍处惩罚期的 push2 集群。
"""
import json
import sys
import time

import httpx

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")
DC = "https://datacenter-web.eastmoney.com/api/data/v1/get"

client = httpx.Client(timeout=25.0, follow_redirects=True,
                      headers={"User-Agent": UA, "Referer": "https://data.eastmoney.com/"})


def dc(name, report, sort_col, filt="", page_size=3, extra=None):
    params = {
        "pageNumber": 1, "pageSize": page_size, "columns": "ALL",
        "reportName": report, "source": "WEB", "client": "WEB",
    }
    if sort_col:
        params["sortColumns"] = sort_col
        params["sortTypes"] = -1
    if filt:
        params["filter"] = filt
    if extra:
        params.update(extra)
    try:
        r = client.get(DC, params=params)
        d = r.json()
        ok = d.get("success")
        res = d.get("result") or {}
        rows = res.get("data") or []
        print(f"\n=== {name} [{report}] HTTP {r.status_code} success={ok} count={res.get('count')} ===")
        if not ok:
            print("   msg:", d.get("message"))
            return None
        if rows:
            print("   字段:", ", ".join(sorted(rows[0].keys())))
            print("   样本:", json.dumps(rows[0], ensure_ascii=False)[:600])
        else:
            print("   空数据集")
        return rows
    except Exception as e:
        print(f"\n=== {name} [{report}] 异常: {type(e).__name__}: {e}")
        return None


def push2ex_zt(ut, date):
    url = "https://push2ex.eastmoney.com/getTopicZTPool"
    params = {"dpt": "wz.ztzt", "Pageindex": 0, "pagesize": 5,
              "sort": "fbt:asc", "date": date, "ut": ut}
    try:
        r = client.get(url, params=params,
                       headers={"Referer": "https://quote.eastmoney.com/ztb/detail"})
        d = r.json()
        pool = (d.get("data") or {}).get("pool") or []
        print(f"\n=== push2ex ZTPool ut={ut[:12]}...({len(ut)}位) date={date} "
              f"rc={d.get('rc')} tc={(d.get('data') or {}).get('tc')} pool={len(pool)} ===")
        if pool:
            print("   字段:", ", ".join(sorted(pool[0].keys())))
            print("   样本:", json.dumps(pool[0], ensure_ascii=False)[:400])
        return pool
    except Exception as e:
        print(f"\n=== push2ex ZTPool 异常: {type(e).__name__}: {e}")
        return None


if __name__ == "__main__":
    td_dash = sys.argv[1] if len(sys.argv) > 1 else "2026-08-06"
    td_compact = td_dash.replace("-", "")

    # 1. 个股资金流（替代 5000 次 push2 逐只请求）
    dc("个股资金流全市场", "RPT_DMSK_TS_STOCKNEW", "NET_MAIN_FORCE_IN", page_size=3)

    # 2. 融资融券个股明细
    dc("融资融券个股明细", "RPTA_WEB_RZRQ_GGMX", "DATE", page_size=3)

    # 3. 业绩预告
    dc("业绩预告", "RPT_PUBLIC_OP_PREDICT", "NOTICE_DATE", page_size=3)

    # 4. 新股申购日历
    dc("新股申购日历", "RPTA_APP_IPOAPPLY", "APPLY_DATE", page_size=3)

    # 5. 龙虎榜回归
    dc("龙虎榜明细", "RPT_DAILYBILLBOARD_DETAILSNEW", "TRADE_DATE",
       filt=f"(TRADE_DATE='{td_dash}')", page_size=2)

    # 6. 涨停池：正确 ut vs 截断 ut
    push2ex_zt("7eea3edcaed734bea9cbfc24409ed989", td_compact)
    time.sleep(1.0)
    push2ex_zt("7eea3edcaed734bea9cbfba10b", td_compact)

    client.close()
