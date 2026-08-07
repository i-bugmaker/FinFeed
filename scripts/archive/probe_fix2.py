#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""第二轮：验证根因假设与修正方案"""

import json
import ssl
import urllib.parse
import urllib.request
import uuid

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
        return e.code, e.read().decode("utf-8", "replace")[:200]
    except Exception as e:
        return 0, f"{type(e).__name__}: {e}"


print("=== 假设 1：filter 中的裸双引号触发 Tomcat 400，改单引号/百分号编码即可 ===")
cases = [
    ("裸双引号 (safe 不编码)",
     DC + "?" + urllib.parse.urlencode(
         {"sortColumns": "NOTICE_DATE", "sortTypes": -1, "pageNumber": 1, "pageSize": 2,
          "columns": "ALL", "reportName": "RPT_PUBLIC_OP_PREDICT", "source": "WEB",
          "client": "WEB", "filter": '(SECURITY_CODE="000563")'}, safe="(),'\"*:+=<>")),
    ("双引号百分号编码 %22",
     DC + "?" + urllib.parse.urlencode(
         {"sortColumns": "NOTICE_DATE", "sortTypes": -1, "pageNumber": 1, "pageSize": 2,
          "columns": "ALL", "reportName": "RPT_PUBLIC_OP_PREDICT", "source": "WEB",
          "client": "WEB", "filter": '(SECURITY_CODE="000563")'}, safe="(),'*:+=<>")),
    ("改用单引号",
     DC + "?" + urllib.parse.urlencode(
         {"sortColumns": "NOTICE_DATE", "sortTypes": -1, "pageNumber": 1, "pageSize": 2,
          "columns": "ALL", "reportName": "RPT_PUBLIC_OP_PREDICT", "source": "WEB",
          "client": "WEB", "filter": "(SECURITY_CODE='000563')"}, safe="(),'*:+=<>")),
]
for tag, url in cases:
    st, body = raw(url)
    try:
        p = json.loads(body)
        r = p.get("result") or {}
        print(f"  [{'OK' if p.get('success') else 'WARN'}] {tag}: count={r.get('count')} "
              f"本页={len(r.get('data') or [])}")
    except Exception:
        print(f"  [FAIL] {tag}: HTTP {st} (Tomcat 拒绝)")

print("\n=== 假设 2：融资融券报表名正确性（用单引号 filter 重试）===")
for name, sort, flt in [
    ("RPTA_WEB_RZRQ_GGMX", "date", "(scode='600519')"),
    ("RPTA_WEB_RZRQ_GGMX", "DATE", "(SCODE='600519')"),
    ("RPT_RZRQ_DETAIL", "DATE1", "(SCODE='600519')"),
    ("RPTA_WEB_RZRQ_LSHJ", "DIM_DATE", ""),
]:
    params = {"sortColumns": sort, "sortTypes": -1, "pageNumber": 1, "pageSize": 2,
              "columns": "ALL", "reportName": name, "source": "WEB", "client": "WEB"}
    if flt:
        params["filter"] = flt
    url = DC + "?" + urllib.parse.urlencode(params, safe="(),'*:+=<>")
    st, body = raw(url)
    try:
        p = json.loads(body)
        r = p.get("result") or {}
        if p.get("success") is False:
            print(f"  [WARN] {name}/{sort}: {p.get('message')}")
        else:
            d = r.get("data") or []
            print(f"  [OK]   {name}/{sort}: count={r.get('count')} 本页={len(d)}")
            if d:
                print(f"         字段: {list(d[0].keys())[:10]}")
    except Exception:
        print(f"  [FAIL] {name}/{sort}: HTTP {st}")

print("\n=== 假设 3：7x24 快讯缺 req_trace 参数 ===")
for tag, extra in [("补 req_trace", {"req_trace": uuid.uuid4().hex}),
                   ("补 req_trace + fields", {"req_trace": uuid.uuid4().hex,
                                              "fields": "code,showTime,title,summary,url,image"})]:
    p_ = {"client": "web", "biz": "web_724", "column": "724", "order": 1,
          "needInteractData": 0, "page_index": 1, "page_size": 5}
    p_.update(extra)
    url = ("https://np-listapi.eastmoney.com/comm/web/getNewsByColumns?"
           + urllib.parse.urlencode(p_))
    st, body = raw(url, "https://kuaixun.eastmoney.com/")
    try:
        p = json.loads(body)
        d = p.get("data") or {}
        lst = d.get("list") if isinstance(d, dict) else None
        print(f"  [{'OK' if lst else 'WARN'}] {tag}: message={p.get('message')} "
              f"list={len(lst or [])}")
        if lst:
            print(f"         首条键: {list(lst[0].keys())[:10]}")
            print(f"         首条: {str(lst[0].get('title') or lst[0].get('summary'))[:60]}")
    except Exception as e:
        print(f"  [FAIL] {tag}: {e} {body[:150]}")

print("\n=== 假设 4：F10 经营分析 JSON 解析失败原因 ===")
st, body = raw("https://emweb.securities.eastmoney.com/PC_HSF10/BusinessAnalysis/PageAjax?code=SH600519",
               "https://emweb.securities.eastmoney.com/")
print(f"  HTTP {st} 长度 {len(body)}")
try:
    p = json.loads(body)
    print(f"  [OK] 解析成功，顶层键: {list(p.keys())}")
except json.JSONDecodeError as e:
    print(f"  [FAIL] JSONDecodeError: {e}")
    pos = e.pos
    print(f"  出错位置附近: {body[max(0,pos-120):pos+120]!r}")

print("\n=== 假设 5：涨停池 ut —— 报告值 vs 项目中被截断的值 ===")
UT_OK = "7eea3edcaed734bea9cbfc24409ed989"
UT_BAD = "7eea3edcaed734bea9cbfba10b"          # 项目 endpoints.py 中的值（长度不足 32）
for tag, ut in [("报告正确 ut", UT_OK), ("项目当前 ut(截断)", UT_BAD)]:
    url = ("https://push2ex.eastmoney.com/getTopicZTPool?cb=&dpt=wz.ztzt&Pageindex=0"
           f"&pagesize=5&sort=fbt%3Aasc&date=20260806&ut={ut}")
    st, body = raw(url, "https://quote.eastmoney.com/ztb/detail")
    try:
        p = json.loads(body)
        d = p.get("data") or {}
        print(f"  [{'OK' if d.get('pool') else 'WARN'}] {tag} (len={len(ut)}): "
              f"rc={p.get('rc')} tc={d.get('tc')} pool={len(d.get('pool') or [])}")
    except Exception as e:
        print(f"  [FAIL] {tag}: {e}")
