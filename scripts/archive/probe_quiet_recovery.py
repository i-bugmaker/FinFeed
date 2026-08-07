#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""静默恢复验证：不打扰式探测

假设：push2 的 IP 惩罚窗口是「滑动」的——惩罚期内的任何请求都会重置计时器，
因此高频重试反而永远无法恢复。本脚本用长静默 + 单次探测验证该假设。
"""
import time
import urllib.request
import ssl
import json

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")
CTX = ssl.create_default_context()
CTX.check_hostname = False
CTX.verify_mode = ssl.CERT_NONE
URL = ("https://push2.eastmoney.com/api/qt/stock/get?secid=1.600519&fltt=2&invt=2"
       "&fields=f43,f57,f58,f170&ut=fa5fd1943c7b386f172d6893dbfba10b")


def once():
    req = urllib.request.Request(URL, headers={
        "User-Agent": UA, "Referer": "https://quote.eastmoney.com/", "Accept": "*/*"})
    try:
        with urllib.request.urlopen(req, timeout=10, context=CTX) as r:
            p = json.loads(r.read().decode("utf-8", "replace"))
        return p.get("data") is not None
    except Exception as e:
        return False


t0 = time.time()
for quiet in (120, 120, 120, 180, 180, 300):
    print(f"[{time.time()-t0:6.0f}s] 静默 {quiet}s ...", flush=True)
    time.sleep(quiet)
    ok = once()
    print(f"[{time.time()-t0:6.0f}s] 静默 {quiet}s 后单次探测 -> "
          f"{'*** 已恢复 ***' if ok else '仍限流'}", flush=True)
    if ok:
        print(f">>> 结论：静默 {quiet}s 后恢复，累计静默 {time.time()-t0:.0f}s", flush=True)
        break
