#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""对首轮实测中「降级/400」的端点做根因定位与参数修正"""

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


def raw(url, referer="https://data.eastmoney.com/"):
    req = urllib.request.Request(url, headers={
        "User-Agent": UA, "Referer": referer, "Accept": "*/*"})
    try:
        with urllib.request.urlopen(req, timeout=20, context=CTX) as r:
            return r.status, r.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8", "replace")[:300]
    except Exception as e:
        return 0, f"{type(e).__name__}: {e}"


def dc(tag, params):
    url = DC + "?" + urllib.parse.urlencode(params, safe="(),'\"*:+=<>&|")
    st, body = raw(url)
    try:
        p = json.loads(body)
        r = p.get("result") or {}
        d = r.get("data") or []
        if p.get("success") is False:
            print(f"  [WARN] {tag}: success=false {p.get('message')}")
            return None
        print(f"  [OK]   {tag}: count={r.get('count')} 本页={len(d)}")
        if d:
            print(f"         字段样例: {list(d[0].keys())[:12]}")
        return d
    except Exception:
        print(f"  [FAIL] {tag}: HTTP {st} {body[:160]}")
        return None


print("=== 1. 业绩预告 —— filter 引号/排序列排查 ===")
dc("A 无 sortColumns", {"pageNumber": 1, "pageSize": 3, "columns": "ALL",
                        "reportName": "RPT_PUBLIC_OP_NEWPREDICT", "source": "WEB",
                        "client": "WEB", "filter": '(SECURITY_CODE="000563")'})
dc("B sortColumns=REPORTDATE", {"sortColumns": "REPORTDATE", "sortTypes": -1,
                                "pageNumber": 1, "pageSize": 3, "columns": "ALL",
                                "reportName": "RPT_PUBLIC_OP_NEWPREDICT",
                                "source": "WEB", "client": "WEB",
                                "filter": '(SECURITY_CODE="000563")'})
dc("C 换报表 RPT_PUBLIC_OP_PREDICT", {"sortColumns": "NOTICE_DATE", "sortTypes": -1,
                                      "pageNumber": 1, "pageSize": 3, "columns": "ALL",
                                      "reportName": "RPT_PUBLIC_OP_PREDICT",
                                      "source": "WEB", "client": "WEB"})
dc("D 业绩快报 RPT_FCI_PERFORMANCEE", {"sortColumns": "UPDATE_DATE", "sortTypes": -1,
                                       "pageNumber": 1, "pageSize": 3, "columns": "ALL",
                                       "reportName": "RPT_FCI_PERFORMANCEE",
                                       "source": "WEB", "client": "WEB"})

print("\n=== 2. 融资融券 —— 报表名/排序列排查 ===")
dc("A 原名无排序", {"pageNumber": 1, "pageSize": 3, "columns": "ALL",
                    "reportName": "RPTA_WEB_RZRQ_GGMX", "source": "WEB", "client": "WEB",
                    "filter": '(SCODE="600519")'})
dc("B sortColumns=DATE", {"sortColumns": "DATE", "sortTypes": -1, "pageNumber": 1,
                          "pageSize": 3, "columns": "ALL", "reportName": "RPTA_WEB_RZRQ_GGMX",
                          "source": "WEB", "client": "WEB", "filter": '(SCODE="600519")'})
dc("C RPT_RZRQ_LSHJ", {"sortColumns": "DIM_DATE", "sortTypes": -1, "pageNumber": 1,
                       "pageSize": 3, "columns": "ALL", "reportName": "RPT_RZRQ_LSHJ",
                       "source": "WEB", "client": "WEB"})

print("\n=== 3. 主力资金流报表名候选 ===")
for name, sort in [("RPT_CUSTOM_STOCK_PANKOU_FUNDFLOW_ALL", "TRADE_DATE"),
                   ("RPT_VALUEANALYSIS_ETFCFLOW", "TRADE_DATE"),
                   ("RPT_MUTUAL_STOCK_NORTHBOUND", "TRADE_DATE"),
                   ("RPT_DMSK_TS_STOCKNEW", "TRADE_DATE")]:
    dc(name, {"sortColumns": sort, "sortTypes": -1, "pageNumber": 1, "pageSize": 2,
              "columns": "ALL", "reportName": name, "source": "WEB", "client": "WEB"})

print("\n=== 4. 新股申购报表名候选 ===")
for name, sort in [("RPT_IPO_INFO", "APPLY_DATE"),
                   ("RPTA_APP_IPOAPPLY", "APPLY_DATE"),
                   ("RPT_IPO_NEWSTOCK", "APPLY_DATE"),
                   ("RPT_NEWSTOCK_ISSUE", "APPLY_DATE")]:
    dc(name, {"sortColumns": sort, "sortTypes": -1, "pageNumber": 1, "pageSize": 2,
              "columns": "ALL", "reportName": name, "source": "WEB", "client": "WEB"})

print("\n=== 5. 7x24 快讯 —— 响应结构剖析 ===")
u = ("https://np-listapi.eastmoney.com/comm/web/getNewsByColumns?client=web"
     "&biz=web_724&column=724&order=1&needInteractData=0&page_index=1&page_size=5")
st, body = raw(u, "https://kuaixun.eastmoney.com/")
print(f"  HTTP {st}, 长度 {len(body)}")
try:
    p = json.loads(body)
    print(f"  顶层键: {list(p.keys())}")
    d = p.get("data")
    if isinstance(d, dict):
        print(f"  data 键: {list(d.keys())}")
        for k, v in d.items():
            if isinstance(v, list):
                print(f"    data.{k}: list[{len(v)}]")
                if v:
                    print(f"      首条键: {list(v[0].keys())[:12]}")
    print(f"  message={p.get('message')} code={p.get('code')}")
except Exception as e:
    print(f"  解析失败: {e}; 原文前 300: {body[:300]}")

print("\n=== 6. F10 经营分析 —— 返回体检查 ===")
st, body = raw("https://emweb.securities.eastmoney.com/PC_HSF10/BusinessAnalysis/PageAjax?code=SH600519",
               "https://emweb.securities.eastmoney.com/")
print(f"  HTTP {st}, 长度 {len(body)}, 前 200 字符: {body[:200]!r}")
st2, body2 = raw("https://emweb.securities.eastmoney.com/PC_HSF10/BusinessAnalysis/PageAjax?code=SZ000001",
                 "https://emweb.securities.eastmoney.com/")
print(f"  SZ000001: HTTP {st2}, 长度 {len(body2)}, 前 200: {body2[:200]!r}")
# 新版 F10 网关
st3, body3 = raw("https://emweb.eastmoney.com/PC_HSF10/BusinessAnalysis/PageAjax?code=SH600519",
                 "https://emweb.eastmoney.com/")
print(f"  emweb.eastmoney.com: HTTP {st3}, 长度 {len(body3)}, 前 200: {body3[:200]!r}")
