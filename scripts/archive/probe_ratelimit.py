#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""push2 限流模型标定

目标：确定可持续调用参数（恢复窗口 / 稳态 QPS / keep-alive 影响），
为事实层限速器提供实证依据，而非拍脑袋配置。
"""

import time
import httpx

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")
UT = "fa5fd1943c7b386f172d6893dbfba10b"
URL = ("https://push2.eastmoney.com/api/qt/stock/get?secid=1.600519&fltt=2&invt=2"
       "&fields=f43,f57,f58,f170&ut=" + UT)
HDR = {"User-Agent": UA, "Referer": "https://quote.eastmoney.com/",
       "Accept": "*/*", "Accept-Language": "zh-CN,zh;q=0.9"}


def try_once(client):
    try:
        r = client.get(URL, headers=HDR, timeout=8)
        p = r.json()
        return p.get("data") is not None
    except Exception:
        return False


print("=== 1. 恢复窗口标定（持续探测直到恢复）===")
with httpx.Client(http2=False, verify=False) as c:
    t0 = time.time()
    for i in range(40):
        ok = try_once(c)
        el = time.time() - t0
        print(f"  t={el:5.1f}s -> {'OK 已恢复' if ok else 'FAIL 仍限流'}")
        if ok:
            print(f"  >> 恢复耗时约 {el:.1f}s")
            break
        time.sleep(5)

print("\n=== 2. keep-alive 长连接稳态测试（间隔 1.0s × 15）===")
with httpx.Client(http2=False, verify=False, limits=httpx.Limits(max_keepalive_connections=1)) as c:
    ok = 0
    for i in range(15):
        r = try_once(c)
        ok += r
        print(f"  #{i+1:02d} {'OK' if r else 'FAIL'}")
        time.sleep(1.0)
    print(f"  keep-alive 成功率 {ok}/15")

print("\n=== 3. 慢速稳态（间隔 3.0s × 10）===")
time.sleep(20)
with httpx.Client(http2=False, verify=False) as c:
    ok = 0
    for i in range(10):
        r = try_once(c)
        ok += r
        print(f"  #{i+1:02d} {'OK' if r else 'FAIL'}")
        time.sleep(3.0)
    print(f"  3s 间隔成功率 {ok}/10")
