#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""契约验证探针 2：资金流报表排序列 / 跌停池 / 市场宽度替代源。"""
import json
import sys
import time

import httpx

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")
DC = "https://datacenter-web.eastmoney.com/api/data/v1/get"

client = httpx.Client(timeout=25.0, follow_redirects=True,
                      headers={"User-Agent": UA, "Referer": "https://data.eastmoney.com/"})


def dc(name, report, sort_col="", filt="", page_size=2, extra=None, show_fields=True):
    params = {"pageNumber": 1, "pageSize": page_size, "columns": "ALL",
              "reportName": report, "source": "WEB", "client": "WEB"}
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
        print(f"\n=== {name} [{report}] HTTP {r.status_code} success={ok} count={res.get('count')} rows={len(rows)}")
        if not ok:
            print("   msg:", d.get("message"))
            return None
        if rows and show_fields:
            print("   字段:", ", ".join(sorted(rows[0].keys())))
            print("   样本:", json.dumps(rows[0], ensure_ascii=False)[:700])
        return rows
    except Exception as e:
        print(f"\n=== {name} [{report}] 异常: {type(e).__name__}: {e}")
        return None


def push2ex(endpoint, sort, date, ut="7eea3edcaed734bea9cbfc24409ed989"):
    url = f"https://push2ex.eastmoney.com/{endpoint}"
    params = {"dpt": "wz.ztzt", "Pageindex": 0, "pagesize": 5,
              "sort": sort, "date": date, "ut": ut}
    try:
        r = client.get(url, params=params,
                       headers={"Referer": "https://quote.eastmoney.com/ztb/detail"})
        d = r.json()
        data = d.get("data") or {}
        pool = data.get("pool") or []
        print(f"\n=== push2ex {endpoint} sort={sort} rc={d.get('rc')} tc={data.get('tc')} pool={len(pool)}")
        if pool:
            print("   字段:", ", ".join(sorted(pool[0].keys())))
            print("   样本:", json.dumps(pool[0], ensure_ascii=False)[:400])
        return pool
    except Exception as e:
        print(f"\n=== push2ex {endpoint} 异常: {type(e).__name__}: {e}")
        return None


if __name__ == "__main__":
    td_dash = sys.argv[1] if len(sys.argv) > 1 else "2026-08-06"
    td_compact = td_dash.replace("-", "")

    # A. 资金流报表：不带排序，取真实字段名
    rows = dc("个股资金流(无排序)", "RPT_DMSK_TS_STOCKNEW", page_size=2)

    # B. 备选资金流报表名
    for rp, sc in [("RPT_CUSTOM_STOCK_PANKOUFUND_NEW_SUM", ""),
                   ("RPT_VALUEANALYSIS_DET", ""),
                   ("RPT_DMSK_TS_STOCKNEW", "CHANGE_RATE")]:
        dc(f"备选 {rp}", rp, sort_col=sc, page_size=1, show_fields=(rp != "RPT_DMSK_TS_STOCKNEW"))

    # C. 跌停池
    time.sleep(1.0)
    push2ex("getTopicDTPool", "fund:asc", td_compact)
    time.sleep(1.0)
    # D. 炸板池
    push2ex("getTopicZBPool", "fbt:asc", td_compact)

    client.close()
