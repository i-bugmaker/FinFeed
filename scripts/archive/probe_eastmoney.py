#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""东方财富接口可用性实测探针

对《东方财富API数据源分析报告》列出的全部端点逐一发起真实请求，
输出三分类结论：AVAILABLE / DEGRADED(限流或空数据) / DEAD。

用法：python scripts/probe_eastmoney.py [--json out.json]
"""

import argparse
import json
import re
import ssl
import sys
import time
import urllib.parse
import urllib.request

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")
CTX = ssl.create_default_context()
CTX.check_hostname = False
CTX.verify_mode = ssl.CERT_NONE

UT_PUSH2 = "fa5fd1943c7b386f172d6893dbfba10b"
UT_KLINE = "7eea3edcaed734bea9cbfc24409ed989"
UT_CLIST = "bd1d9ddb04089700cf9c27f6f7426281"
UT_FUND = "b2884a393a59ad64002292a3e90d46a5"

DATACENTER = "https://datacenter-web.eastmoney.com/api/data/v1/get"

RESULTS = []


def _req(url, referer, method="GET", body=None, cookie=None, timeout=20):
    headers = {"User-Agent": UA, "Referer": referer, "Accept": "*/*"}
    if cookie:
        headers["Cookie"] = cookie
    data = None
    if body is not None:
        data = json.dumps(body).encode("utf-8")
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    with urllib.request.urlopen(req, timeout=timeout, context=CTX) as r:
        return r.status, r.read().decode("utf-8", "replace")


def probe(name, url, referer="https://quote.eastmoney.com/", *, method="GET",
          body=None, cookie=None, check=None, jsonp=False, retries=2):
    """check(payload)->(ok:bool, note:str)"""
    last = ""
    for i in range(retries):
        try:
            status, text = _req(url, referer, method, body, cookie)
            raw = text
            if jsonp:
                m = re.search(r"[\w$.]+\((.*)\)\s*;?\s*$", text.strip(), re.S)
                if m:
                    text = m.group(1)
            try:
                payload = json.loads(text)
            except Exception:
                payload = None
            if check:
                ok, note = check(payload if payload is not None else raw)
            else:
                ok, note = (payload is not None), f"HTTP {status}"
            RESULTS.append({
                "name": name, "status": "AVAILABLE" if ok else "DEGRADED",
                "http": status, "note": note,
                "url": url[:150],
            })
            print(f"{'[OK]  ' if ok else '[WARN]'} {name:38s} | {note}")
            return payload
        except Exception as e:
            last = f"{type(e).__name__}: {str(e)[:120]}"
            if i < retries - 1:
                time.sleep(2.0)
    RESULTS.append({"name": name, "status": "DEAD", "http": 0, "note": last, "url": url[:150]})
    print(f"[FAIL] {name:38s} | {last}")
    return None


def q(base, params):
    return base + "?" + urllib.parse.urlencode(params, safe="(),'\"*:+=<>")


# --------------------------------------------------------------------------
def chk_stock_get(p):
    d = (p or {}).get("data") or {}
    if d.get("f43") is not None:
        return True, f"{d.get('f58')} 价={d.get('f43')} 涨跌幅={d.get('f170')}"
    return False, f"rc={(p or {}).get('rc')} data空"


def chk_ulist(p):
    diff = ((p or {}).get("data") or {}).get("diff") or []
    return (len(diff) > 0), f"{len(diff)} 条"


def chk_klines(p):
    k = ((p or {}).get("data") or {}).get("klines") or []
    return (len(k) > 0), f"{len(k)} 根 K 线, 末根={k[-1][:40] if k else '-'}"


def chk_trends(p):
    t = ((p or {}).get("data") or {}).get("trends") or []
    return (len(t) > 0), f"{len(t)} 个分时点"


def chk_dc(p):
    r = (p or {}).get("result") or {}
    d = r.get("data") or []
    if (p or {}).get("success") is False:
        return False, f"success=false msg={(p or {}).get('message')}"
    return (len(d) > 0), f"count={r.get('count')} 本页={len(d)}"


def chk_ztpool(p):
    d = (p or {}).get("data") or {}
    pool = d.get("pool") or []
    rc = (p or {}).get("rc")
    return (len(pool) > 0), f"rc={rc} tc={d.get('tc')} pool={len(pool)}"


def chk_kamt(p):
    d = (p or {}).get("data") or {}
    s2n = d.get("s2n") or d.get("hk2sh") or []
    return bool(d), f"keys={list(d.keys())[:6]}"


def chk_f10(p):
    if not isinstance(p, dict):
        return False, "非 JSON"
    keys = [k for k in p.keys() if k != "status"]
    return (len(keys) > 0), f"节点={keys[:5]}"


def chk_ann(p):
    d = (p or {}).get("data") or {}
    lst = d.get("list") or []
    return (len(lst) > 0), f"{len(lst)} 条公告"


def chk_report(p):
    d = (p or {}).get("data") or []
    return (len(d) > 0), f"hits={(p or {}).get('hits')} 本页={len(d)}"


def chk_news(p):
    d = (p or {}).get("data") or {}
    lst = d.get("list") or []
    return (len(lst) > 0), f"{len(lst)} 条快讯"


def chk_hotrank(p):
    d = (p or {}).get("data") or []
    return (len(d) > 0), f"{len(d)} 只热股"


def chk_search(p):
    r = (p or {}).get("QuotationCodeTable") or {}
    d = r.get("Data") or []
    return (len(d) > 0), f"{len(d)} 条联想"


def chk_clist(p):
    d = ((p or {}).get("data") or {})
    diff = d.get("diff") or []
    return (len(diff) > 0), f"total={d.get('total')} 本页={len(diff)}"


def chk_newssearch(p):
    if not isinstance(p, dict):
        return False, "非 JSON"
    res = (p.get("result") or {})
    lst = res.get("cmsArticleWebOld") or []
    return (len(lst) > 0), f"hits={p.get('hitsTotal')} 本页={len(lst)}"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", help="结果写入 JSON 文件")
    ap.add_argument("--date", default="", help="交易日 YYYY-MM-DD")
    args = ap.parse_args()

    import datetime
    today = datetime.date.today()
    d = args.date or str(today)
    # 找最近交易日（简单回退到最近工作日）
    dt = datetime.date.fromisoformat(d)
    while dt.weekday() >= 5:
        dt -= datetime.timedelta(days=1)
    trade = dt.isoformat()
    trade_c = trade.replace("-", "")
    prev = dt - datetime.timedelta(days=1)
    while prev.weekday() >= 5:
        prev -= datetime.timedelta(days=1)
    prev_s = prev.isoformat()

    QUOTE = "https://quote.eastmoney.com/"
    DATA = "https://data.eastmoney.com/"

    print(f"=== 东方财富端点实测  交易日={trade} 前一日={prev_s} ===\n")

    print("--- 三、行情类 ---")
    probe("3.1 实时快照 stock/get",
          q("https://push2.eastmoney.com/api/qt/stock/get",
            {"secid": "1.600519", "fltt": 2, "invt": 2,
             "fields": "f43,f44,f45,f46,f47,f48,f57,f58,f60,f169,f170,f171,f162,f167,f116,f117",
             "ut": UT_PUSH2}), QUOTE, check=chk_stock_get)

    probe("3.2 批量行情 ulist.np",
          q("https://push2.eastmoney.com/api/qt/ulist.np/get",
            {"secids": "1.600519,0.000001", "fields": "f2,f3,f12,f14", "fltt": 2,
             "ut": UT_PUSH2}), QUOTE, check=chk_ulist)

    probe("3.2b 市场宽度 ulist f104/105/106",
          q("https://push2.eastmoney.com/api/qt/ulist.np/get",
            {"secids": "1.000001,0.399001,0.399006,1.000688",
             "fields": "f12,f14,f104,f105,f106,f2,f3", "fltt": 2, "ut": UT_PUSH2}),
          QUOTE, check=chk_ulist)

    probe("3.3 日K线 klt=101",
          q("https://push2his.eastmoney.com/api/qt/stock/kline/get",
            {"secid": "1.600519", "klt": 101, "fqt": 1, "lmt": 10, "end": "20500101",
             "fields1": "f1,f2,f3,f4,f5,f6",
             "fields2": "f51,f52,f53,f54,f55,f56,f57,f58,f59,f60,f61",
             "ut": UT_KLINE}), QUOTE, check=chk_klines)

    probe("3.3b 日K线 用 push2 通用 UT",
          q("https://push2his.eastmoney.com/api/qt/stock/kline/get",
            {"secid": "1.600519", "klt": 101, "fqt": 1, "lmt": 5, "end": "20500101",
             "fields1": "f1,f2,f3,f4,f5,f6",
             "fields2": "f51,f52,f53,f54,f55,f56,f57,f58,f59,f60,f61",
             "ut": UT_PUSH2}), QUOTE, check=chk_klines)

    probe("3.3c 日K线 beg/end 区间模式",
          q("https://push2his.eastmoney.com/api/qt/stock/kline/get",
            {"secid": "1.600519", "klt": 101, "fqt": 1, "beg": "20260701", "end": "20500101",
             "fields1": "f1,f2,f3,f4,f5,f6",
             "fields2": "f51,f52,f53,f54,f55,f56,f57,f58,f59,f60,f61",
             "ut": UT_KLINE}), QUOTE, check=chk_klines)

    probe("3.3d 周K线 klt=102",
          q("https://push2his.eastmoney.com/api/qt/stock/kline/get",
            {"secid": "1.600519", "klt": 102, "fqt": 1, "lmt": 5, "end": "20500101",
             "fields1": "f1,f2,f3,f4,f5,f6",
             "fields2": "f51,f52,f53,f54,f55,f56,f57,f58,f59,f60,f61",
             "ut": UT_KLINE}), QUOTE, check=chk_klines)

    probe("3.3e 分钟K线 klt=1",
          q("https://push2his.eastmoney.com/api/qt/stock/kline/get",
            {"secid": "1.600519", "klt": 1, "fqt": 1, "lmt": 10, "end": "20500101",
             "fields1": "f1,f2,f3,f4,f5,f6",
             "fields2": "f51,f52,f53,f54,f55,f56,f57,f58,f59,f60,f61",
             "ut": UT_KLINE}), QUOTE, check=chk_klines)

    probe("3.4 分时 trends2 ndays=1",
          q("https://push2his.eastmoney.com/api/qt/stock/trends2/get",
            {"secid": "1.600519", "fields1": "f1,f2,f3,f4,f5,f6,f7,f8,f9,f10,f11,f12,f13",
             "fields2": "f51,f52,f53,f54,f55,f56,f57,f58", "ndays": 1, "iscr": 0,
             "ut": UT_PUSH2}), QUOTE, check=chk_trends)

    probe("3.5 个股资金流历史 fflow/kline",
          q("https://push2his.eastmoney.com/api/qt/stock/fflow/kline/get",
            {"secid": "1.600519", "fields1": "f1,f2,f3,f7",
             "fields2": "f51,f52,f53,f54,f55,f56,f57,f58,f59,f60,f61,f62,f63,f64,f65",
             "klt": 101, "lmt": 5, "ut": UT_FUND}), QUOTE,
          check=lambda p: (len(((p or {}).get("data") or {}).get("klines") or []) > 0,
                           f"{len((((p or {}).get('data') or {}).get('klines') or []))} 条"))

    probe("3.5b 个股实时资金流字段 stock/get f62",
          q("https://push2.eastmoney.com/api/qt/stock/get",
            {"secid": "1.600519", "fltt": 2, "invt": 2,
             "fields": "f12,f14,f62,f184,f66,f72,f78,f84,f160,f170,f43", "ut": UT_FUND}),
          QUOTE, check=lambda p: (((p or {}).get("data") or {}).get("f62") is not None,
                                  f"f62={((p or {}).get('data') or {}).get('f62')} f184={((p or {}).get('data') or {}).get('f184')}"))

    probe(f"3.6 涨停池 ZTPool {trade_c}",
          q("https://push2ex.eastmoney.com/getTopicZTPool",
            {"cb": "", "dpt": "wz.ztzt", "Pageindex": 0, "pagesize": 200,
             "sort": "fbt:asc", "date": trade_c, "ut": UT_KLINE}),
          "https://quote.eastmoney.com/ztb/detail", check=chk_ztpool)

    probe(f"3.6b 跌停池 DTPool {trade_c}",
          q("https://push2ex.eastmoney.com/getTopicDTPool",
            {"cb": "", "dpt": "wz.ztzt", "Pageindex": 0, "pagesize": 200,
             "sort": "fund:asc", "date": trade_c, "ut": UT_KLINE}),
          "https://quote.eastmoney.com/ztb/detail", check=chk_ztpool)

    probe("3.7 沪深港通实时 kamt.rtmin",
          q("https://push2.eastmoney.com/api/qt/kamt.rtmin/get",
            {"fields1": "f1,f2,f3,f4", "fields2": "f51,f52,f53,f54,f55,f56",
             "ut": UT_FUND}), QUOTE, check=chk_kamt)

    probe("3.8 clist 行业板块",
          q("https://push2.eastmoney.com/api/qt/clist/get",
            {"pn": 1, "pz": 10, "po": 1, "np": 1, "fltt": 2, "invt": 2, "fid": "f3",
             "fs": "m:90+t:3", "fields": "f2,f3,f12,f14", "ut": UT_CLIST}),
          QUOTE, check=chk_clist)

    probe("3.8b clist 沪深A股全量",
          q("https://push2.eastmoney.com/api/qt/clist/get",
            {"pn": 1, "pz": 20, "po": 1, "np": 1, "fltt": 2, "invt": 2, "fid": "f3",
             "fs": "m:0+t:6,m:0+t:80,m:1+t:2,m:1+t:23",
             "fields": "f2,f3,f12,f14,f20,f21,f62", "ut": UT_CLIST}),
          QUOTE, check=chk_clist)

    probe("53 全球指数 ulist 100.*",
          q("https://push2.eastmoney.com/api/qt/ulist.np/get",
            {"secids": "100.NDX,100.DJIA,100.SPX,100.HSI", "fields": "f2,f3,f12,f14",
             "fltt": 2, "ut": UT_PUSH2}), QUOTE, check=chk_ulist)

    print("\n--- 四、F10 基本面 ---")
    EMWEB = "https://emweb.securities.eastmoney.com/"
    for tag, path in [
        ("4.1 公司概况 CompanySurvey", "PC_HSF10/CompanySurvey/PageAjax"),
        ("4.2 经营分析 BusinessAnalysis", "PC_HSF10/BusinessAnalysis/PageAjax"),
        ("4.3 股东研究 ShareholderResearch", "PC_HSF10/ShareholderResearch/PageAjax"),
        ("4.4 核心题材 CoreConception", "PC_HSF10/CoreConception/PageAjax"),
    ]:
        probe(tag, f"https://emweb.securities.eastmoney.com/{path}?code=SH600519",
              EMWEB, check=chk_f10)

    probe("4.5 资产负债表 zcfzbAjaxNew",
          q("https://emweb.securities.eastmoney.com/PC_HSF10/NewFinanceAnalysis/zcfzbAjaxNew",
            {"companyType": 4, "reportDateType": 0, "reportType": 1,
             "dates": "2026-03-31", "code": "SH600519"}), EMWEB, check=chk_f10)

    print("\n--- 五、数据中心 datacenter ---")
    dc_cases = [
        ("5.1 业绩报表 RPT_LICO_FN_CPD", "RPT_LICO_FN_CPD", "(REPORTDATE='2026-03-31')", "REPORTDATE"),
        ("5.2 业绩预告 RPT_PUBLIC_OP_NEWPREDICT", "RPT_PUBLIC_OP_NEWPREDICT", '(SECURITY_CODE="000563")', "NOTICE_DATE"),
        (f"5.3 龙虎榜 RPT_DAILYBILLBOARD [{prev_s}]", "RPT_DAILYBILLBOARD_DETAILSNEW", f"(TRADE_DATE='{prev_s}')", "TRADE_DATE"),
        ("5.4 融资融券 RPTA_WEB_RZRQ_GGMX", "RPTA_WEB_RZRQ_GGMX", '(SECURITY_CODE="600519")', "DATE"),
        (f"5.5 大宗交易 RPT_DATA_BLOCKTRADE", "RPT_DATA_BLOCKTRADE", f"(TRADE_DATE='{prev_s}')", "TRADE_DATE"),
        (f"5.6 沪深港通 RPT_MUTUAL_DEAL_HISTORY", "RPT_MUTUAL_DEAL_HISTORY", "", "TRADE_DATE"),
        ("5.7 可转债 RPT_BOND_CB_LIST", "RPT_BOND_CB_LIST", "", "PUBLIC_START_DATE"),
        ("5.8 限售解禁 RPT_LIFT_STAGE", "RPT_LIFT_STAGE", "", "FREE_DATE"),
        ("5.9 A股名录 RPT_F10_BASIC_ORGINFO", "RPT_F10_BASIC_ORGINFO", "", "SECURITY_CODE"),
        ("5.10 核心题材板块 RPT_F10_CORETHEME_BOARDTYPE", "RPT_F10_CORETHEME_BOARDTYPE", "", "SECURITY_CODE"),
        ("5.11 主力资金流 RPT_MAINFUNDINFLOW", "RPT_MAINFUNDINFLOW", "", "TRADE_DATE"),
        ("5.12 新股申购 RPT_IPO_XGSGLB", "RPT_IPO_XGSGLB", "", "APPLY_DATE"),
    ]
    for tag, rpt, flt, sort in dc_cases:
        params = {"sortColumns": sort, "sortTypes": -1, "pageNumber": 1, "pageSize": 5,
                  "columns": "ALL", "reportName": rpt, "source": "WEB", "client": "WEB"}
        if flt:
            params["filter"] = flt
        probe(tag, q(DATACENTER, params), DATA, check=chk_dc)

    print("\n--- 六、公告 / 研报 ---")
    probe("6.1 公司公告 np-anotice",
          q("https://np-anotice-stock.eastmoney.com/api/security/ann",
            {"sr": -1, "page_size": 10, "page_index": 1, "ann_type": "A",
             "client_source": "web", "stock_list": "600519"}),
          "https://data.eastmoney.com/notices/", check=chk_ann)

    beg = (dt - datetime.timedelta(days=60)).isoformat()
    for tag, qt, extra in [("6.2a 个股研报 qType=0", 0, {"code": "600519"}),
                           ("6.2b 行业研报 qType=1", 1, {}),
                           ("6.2c 策略研报 qType=2", 2, {})]:
        p = {"industryCode": "*", "pageSize": 10, "pageNo": 1, "qType": qt,
             "beginTime": beg, "endTime": trade, "cb": "datatable2359"}
        p.update(extra)
        probe(tag, q("https://reportapi.eastmoney.com/report/list", p),
              "https://data.eastmoney.com/report/", check=chk_report, jsonp=True)

    print("\n--- 七、快讯 / 搜索 ---")
    probe("7.1 7x24 快讯 column=724",
          q("https://np-listapi.eastmoney.com/comm/web/getNewsByColumns",
            {"client": "web", "biz": "web_724", "column": "724", "order": 1,
             "needInteractData": 0, "page_index": 1, "page_size": 10}),
          "https://kuaixun.eastmoney.com/", check=chk_news)

    probe("7.1b 市场资讯 column=350",
          q("https://np-listapi.eastmoney.com/comm/web/getNewsByColumns",
            {"client": "web", "biz": "web_350", "column": "350", "order": 1,
             "needInteractData": 0, "page_index": 1, "page_size": 10}),
          "https://kuaixun.eastmoney.com/", check=chk_news)

    probe("7.2 热搜榜 POST stockrank",
          "https://emappdata.eastmoney.com/stockrank/getAllCurrentList",
          "https://guba.eastmoney.com/", method="POST",
          body={"appId": "appId01", "globalId": "786e4c21-70dc-435a-93bb-38",
                "marketType": "", "pageNo": 1, "pageSize": 20},
          check=chk_hotrank)

    param = json.dumps({"uid": "", "keyword": "贵州茅台", "type": ["cmsArticleWebOld"],
                        "client": "web", "clientType": "web", "clientVersion": "curr",
                        "param": {"cmsArticleWebOld": {"searchScope": "default",
                                                       "sort": "default", "pageIndex": 1,
                                                       "pageSize": 3, "preTag": "<em>",
                                                       "postTag": "</em>"}}},
                       ensure_ascii=False, separators=(",", ":"))
    probe("7.3 新闻全文搜索 JSONP",
          "https://search-api-web.eastmoney.com/search/jsonp?cb=jQuery1&param="
          + urllib.parse.quote(param),
          "https://so.eastmoney.com/", cookie="qgqp_b_id=abc123def456",
          check=chk_newssearch, jsonp=True)

    probe("7.4 搜索联想 suggest",
          q("https://searchapi.eastmoney.com/api/suggest/get",
            {"input": "贵州茅台", "type": 14,
             "token": "D43BF722C8E33BDC906FB84D85E326E8", "count": 5}),
          "https://www.eastmoney.com/", check=chk_search)

    print("\n--- 八、基金 ---")
    probe("8.1 全量基金代码表",
          "https://fund.eastmoney.com/js/fundcode_search.js",
          "https://fund.eastmoney.com/",
          check=lambda t: (isinstance(t, str) and "var r" in t, f"{len(t)//1024}KB" if isinstance(t, str) else "非文本"))

    probe("8.2 基金历史净值 pingzhongdata",
          "https://fund.eastmoney.com/pingzhongdata/110022.js",
          "https://fund.eastmoney.com/",
          check=lambda t: (isinstance(t, str) and "fS_name" in t, f"{len(t)//1024}KB" if isinstance(t, str) else "非文本"))

    probe("8.4 基金盘中估值 fundgz (预期失效)",
          "https://fundgz.1234567.com.cn/js/110022.js",
          "https://fund.eastmoney.com/",
          check=lambda t: (isinstance(t, str) and "jsonpgz" in t, "存活" if isinstance(t, str) and "jsonpgz" in t else "已失效"),
          retries=1)

    # ---- 汇总 ----
    ok = [r for r in RESULTS if r["status"] == "AVAILABLE"]
    warn = [r for r in RESULTS if r["status"] == "DEGRADED"]
    dead = [r for r in RESULTS if r["status"] == "DEAD"]
    print("\n" + "=" * 70)
    print(f"总计 {len(RESULTS)} | 可用 {len(ok)} | 降级/空 {len(warn)} | 失败 {len(dead)}")
    if warn:
        print("\n[降级/空数据]")
        for r in warn:
            print(f"  - {r['name']}: {r['note']}")
    if dead:
        print("\n[失败]")
        for r in dead:
            print(f"  - {r['name']}: {r['note']}")

    if args.json:
        with open(args.json, "w", encoding="utf-8") as f:
            json.dump(RESULTS, f, ensure_ascii=False, indent=2)
        print(f"\n结果已写入 {args.json}")


if __name__ == "__main__":
    main()
