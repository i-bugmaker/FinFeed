#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""push2 主机族可用性 / 限流特征探测

东财 push2 集群对外暴露多个编号镜像主机（0~99.push2 / push2his / push2delay）。
本脚本用于确认：
  1) 编号主机是否可用（绕开单主机 IP 级限流）；
  2) 连续请求的成功率与恢复窗口；
  3) HTTP/1.1 keep-alive 复用 vs 每次新建连接的差异。
"""

import concurrent.futures as cf
import json
import ssl
import time
import urllib.error
import urllib.request

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")
CTX = ssl.create_default_context()
CTX.check_hostname = False
CTX.verify_mode = ssl.CERT_NONE

UT = "fa5fd1943c7b386f172d6893dbfba10b"
UTK = "7eea3edcaed734bea9cbfc24409ed989"


def hit(url, referer="https://quote.eastmoney.com/", timeout=8):
    req = urllib.request.Request(url, headers={
        "User-Agent": UA, "Referer": referer, "Accept": "*/*",
        "Accept-Language": "zh-CN,zh;q=0.9",
        "Connection": "close",
    })
    t0 = time.time()
    try:
        with urllib.request.urlopen(req, timeout=timeout, context=CTX) as r:
            body = r.read().decode("utf-8", "replace")
        dt = (time.time() - t0) * 1000
        try:
            p = json.loads(body)
        except Exception:
            return False, f"非JSON {len(body)}B", dt
        d = p.get("data")
        if d is None:
            return False, f"rc={p.get('rc')} data=None", dt
        return True, "ok", dt
    except Exception as e:
        return False, f"{type(e).__name__}", (time.time() - t0) * 1000


QUOTE_PATH = ("/api/qt/stock/get?secid=1.600519&fltt=2&invt=2"
              "&fields=f43,f57,f58,f170&ut=" + UT)
KLINE_PATH = ("/api/qt/stock/kline/get?secid=1.600519&klt=101&fqt=1&lmt=5"
              "&end=20500101&fields1=f1,f2,f3,f4,f5,f6"
              "&fields2=f51,f52,f53,f54,f55,f56,f57,f58,f59,f60,f61&ut=" + UTK)


def main():
    print("=== A. push2 编号主机（实时快照 stock/get）===")
    hosts = ["push2.eastmoney.com", "push2delay.eastmoney.com"] + \
            [f"{i}.push2.eastmoney.com" for i in (1, 7, 21, 32, 44, 48, 57, 61, 76, 82, 91, 95, 99)]
    good_push2 = []
    for h in hosts:
        ok, note, dt = hit(f"https://{h}{QUOTE_PATH}")
        print(f"  {'OK  ' if ok else 'FAIL'} {h:32s} {note:22s} {dt:6.0f}ms")
        if ok:
            good_push2.append(h)

    print("\n=== B. push2his 编号主机（日 K 线）===")
    hosts2 = ["push2his.eastmoney.com"] + \
             [f"{i}.push2his.eastmoney.com" for i in (1, 7, 21, 32, 44, 48, 57, 61, 76, 82, 91, 95, 99)]
    good_his = []
    for h in hosts2:
        ok, note, dt = hit(f"https://{h}{KLINE_PATH}")
        print(f"  {'OK  ' if ok else 'FAIL'} {h:32s} {note:22s} {dt:6.0f}ms")
        if ok:
            good_his.append(h)

    print(f"\n可用 push2 主机 {len(good_push2)}/{len(hosts)}；"
          f"可用 push2his 主机 {len(good_his)}/{len(hosts2)}")

    print("\n=== C. 单主机连续 12 次（间隔 0.5s）成功率 ===")
    okc = 0
    for i in range(12):
        ok, note, dt = hit(f"https://push2.eastmoney.com{QUOTE_PATH}")
        okc += ok
        print(f"  #{i+1:02d} {'OK' if ok else 'FAIL':4s} {note:22s} {dt:6.0f}ms")
        time.sleep(0.5)
    print(f"  单主机成功率 {okc}/12")

    print("\n=== D. 主机轮换 12 次（间隔 0.5s）成功率 ===")
    pool = good_push2 or hosts
    okr = 0
    for i in range(12):
        h = pool[i % len(pool)]
        ok, note, dt = hit(f"https://{h}{QUOTE_PATH}")
        okr += ok
        print(f"  #{i+1:02d} {'OK' if ok else 'FAIL':4s} {h:28s} {note:20s} {dt:6.0f}ms")
        time.sleep(0.5)
    print(f"  轮换成功率 {okr}/12")

    print("\n=== E. 失败后重试恢复窗口 ===")
    for wait in (0, 1, 3, 6):
        time.sleep(wait)
        ok, note, dt = hit(f"https://push2.eastmoney.com{QUOTE_PATH}")
        print(f"  等待 {wait}s -> {'OK' if ok else 'FAIL'} ({note})")


if __name__ == "__main__":
    main()
