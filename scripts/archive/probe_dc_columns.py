#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""datacenter 报表字段与过滤列勘定（为事实层整合定契约）"""

import json
import ssl
import urllib.parse
import urllib.request

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")
CTX = ssl.create_default_context()
CTX.check_hostname = False
CTX.verify_mode = ssl.CERT_NONE
DC = "https://datacenter-web.eastmoney.com/api/data/v1/get"


def dc(params, referer="https://data.eastmoney.com/"):
    # 关键：不把 " 放进 safe，让其编码为 %22（否则 Tomcat 400）
    url = DC + "?" + urllib.parse.urlencode(params, safe="(),'*:+=<>")
    req = urllib.request.Request(url, headers={
        "User-Agent": UA, "Referer": referer, "Accept": "*/*"})
    try:
        with urllib.request.urlopen(req, timeout=20, context=CTX) as r:
            body = r.read().decode("utf-8", "replace")
        p = json.loads(body)
        if p.get("success") is False:
            return None, p.get("message")
        r_ = p.get("result") or {}
        return r_, f"count={r_.get('count')}"
    except urllib.error.HTTPError as e:
        return None, f"HTTP {e.code}"
    except Exception as e:
        return None, f"{type(e).__name__}: {str(e)[:80]}"


def show(tag, params, keys=None):
    r, note = dc(params)
    if r is None:
        print(f"  [WARN] {tag}: {note}")
        return None
    d = r.get("data") or []
    print(f"  [OK]   {tag}: {note} 本页={len(d)}")
    if d:
        print(f"         全部字段({len(d[0])}): {list(d[0].keys())}")
        if keys:
            print(f"         样例: { {k: d[0].get(k) for k in keys} }")
    return d


print("=== 1. 融资融券个股明细：无 filter 探字段 ===")
d = show("RPTA_WEB_RZRQ_GGMX 无filter",
         {"sortColumns": "DATE", "sortTypes": -1, "pageNumber": 1, "pageSize": 2,
          "columns": "ALL", "reportName": "RPTA_WEB_RZRQ_GGMX",
          "source": "WEB", "client": "WEB"})
if d:
    # 用真实字段名做 filter
    for col in ("SCODE", "SECURITY_CODE", "SECUCODE"):
        if col in d[0]:
            show(f"RPTA_WEB_RZRQ_GGMX filter by {col}",
                 {"sortColumns": "DATE", "sortTypes": -1, "pageNumber": 1, "pageSize": 2,
                  "columns": "ALL", "reportName": "RPTA_WEB_RZRQ_GGMX",
                  "source": "WEB", "client": "WEB",
                  "filter": f'({col}="600519")'})

print("\n=== 2. 个股资金流 RPT_DMSK_TS_STOCKNEW（替代逐只 push2 轮询）===")
d = show("RPT_DMSK_TS_STOCKNEW",
         {"sortColumns": "NETMLJE", "sortTypes": -1, "pageNumber": 1, "pageSize": 3,
          "columns": "ALL", "reportName": "RPT_DMSK_TS_STOCKNEW",
          "source": "WEB", "client": "WEB"})
if not d:
    d = show("RPT_DMSK_TS_STOCKNEW 默认排序",
             {"pageNumber": 1, "pageSize": 3, "columns": "ALL",
              "reportName": "RPT_DMSK_TS_STOCKNEW", "source": "WEB", "client": "WEB"})

print("\n=== 3. 业绩预告 / 业绩快报 过滤能力 ===")
show("RPT_PUBLIC_OP_PREDICT filter 代码",
     {"sortColumns": "NOTICE_DATE", "sortTypes": -1, "pageNumber": 1, "pageSize": 2,
      "columns": "ALL", "reportName": "RPT_PUBLIC_OP_PREDICT", "source": "WEB",
      "client": "WEB", "filter": '(SECURITY_CODE="000563")'},
     keys=["SECURITY_NAME_ABBR", "NOTICE_DATE", "FORECASTTYPE"])

show("RPT_FCI_PERFORMANCEE 业绩快报",
     {"sortColumns": "UPDATE_DATE", "sortTypes": -1, "pageNumber": 1, "pageSize": 2,
      "columns": "ALL", "reportName": "RPT_FCI_PERFORMANCEE", "source": "WEB",
      "client": "WEB"},
     keys=["SECURITY_NAME_ABBR", "REPORT_DATE", "BASIC_EPS"])

print("\n=== 4. 新股申购 RPTA_APP_IPOAPPLY ===")
show("RPTA_APP_IPOAPPLY",
     {"sortColumns": "APPLY_DATE", "sortTypes": -1, "pageNumber": 1, "pageSize": 2,
      "columns": "ALL", "reportName": "RPTA_APP_IPOAPPLY", "source": "WEB", "client": "WEB"},
     keys=["SECURITY_NAME_ABBR", "APPLY_DATE", "LISTING_DATE"])

print("\n=== 5. 沪深港通持股 RPT_MUTUAL_DEAL_HISTORY ===")
show("RPT_MUTUAL_DEAL_HISTORY",
     {"sortColumns": "TRADE_DATE", "sortTypes": -1, "pageNumber": 1, "pageSize": 2,
      "columns": "ALL", "reportName": "RPT_MUTUAL_DEAL_HISTORY", "source": "WEB",
      "client": "WEB"})

print("\n=== 6. 龙虎榜字段确认 ===")
show("RPT_DAILYBILLBOARD_DETAILSNEW",
     {"sortColumns": "TRADE_DATE", "sortTypes": -1, "pageNumber": 1, "pageSize": 2,
      "columns": "ALL", "reportName": "RPT_DAILYBILLBOARD_DETAILSNEW",
      "source": "WEB", "client": "WEB", "filter": "(TRADE_DATE='2026-08-06')"})

print("\n=== 7. A股名录字段确认（stock_meta 依赖）===")
show("RPT_F10_BASIC_ORGINFO",
     {"sortColumns": "SECURITY_CODE", "sortTypes": 1, "pageNumber": 1, "pageSize": 2,
      "columns": "ALL", "reportName": "RPT_F10_BASIC_ORGINFO", "source": "WEB", "client": "WEB"})

print("\n=== 8. 核心题材板块字段确认（sector_members 依赖）===")
show("RPT_F10_CORETHEME_BOARDTYPE",
     {"sortColumns": "SECURITY_CODE", "sortTypes": 1, "pageNumber": 1, "pageSize": 2,
      "columns": "ALL", "reportName": "RPT_F10_CORETHEME_BOARDTYPE",
      "source": "WEB", "client": "WEB"})

print("\n=== 9. 日线替代源探测（datacenter 有无全市场日行情）===")
for name, sort in [("RPT_DMSK_TS_STOCKNEW", "TRADE_DATE"),
                   ("RPT_CUSTOM_STOCK_QUOTE", "TRADE_DATE"),
                   ("RPT_LICO_FN_CPD", "REPORTDATE")]:
    r, note = dc({"sortColumns": sort, "sortTypes": -1, "pageNumber": 1, "pageSize": 1,
                  "columns": "ALL", "reportName": name, "source": "WEB", "client": "WEB"})
    print(f"  {name}: {note if r is None else 'OK ' + note}")
