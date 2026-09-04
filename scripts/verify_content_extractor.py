#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""统一正文提取器 — 全源样例验证

对每个源取 2 篇样例文章，运行 fetch_article_detail 提取，
输出：源名 / 提取方式 / 中文字数 / 段落数 / 配图数 / 标题命中 / 结论。
"""
from __future__ import annotations

import asyncio
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from finfeed.content_extractor import fetch_article_detail  # noqa: E402

SAMPLES = json.load(open(
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "_probe_samples.json"),
    encoding="utf-8",
))
RE_CJK = __import__("re").compile(r"[\u4e00-\u9fff]")


async def run_one(url: str, title: str) -> dict:
    res = await fetch_article_detail(url, title=title)
    text = res.text
    return {
        "url": url,
        "method": res.method,
        "cjk": len(RE_CJK.findall(text)),
        "paras": len(res.paragraphs),
        "images": len(res.images),
        "title": res.title,
        "head": text[:60].replace("\n", " "),
    }


async def main():
    results = {}
    for src, items in SAMPLES.items():
        if not items:
            results[src] = {"verdict": "无样本"}
            continue
        row = []
        for it in items[:2]:
            try:
                r = await run_one(it["url"], it.get("title", ""))
                db_cjk = len(RE_CJK.findall(it.get("content") or ""))
                r["db_cjk"] = db_cjk
                row.append(r)
            except Exception as e:  # noqa: BLE001
                row.append({"url": it["url"], "error": str(e)[:80]})
        results[src] = row
        # 打印
        for r in row:
            if "error" in r:
                print(f"{src:12s} ERR {r['error']}")
                continue
            flag = "OK " if r["cjk"] >= 50 else ("PART" if r["cjk"] >= 20 else "FAIL")
            print(f"{src:12s} [{flag}] {r['method']:8s} 中文{r['cjk']:5d} "
                  f"(库内{str(r['db_cjk']):>5}) 段{r['paras']:3d} 图{r['images']} "
                  f"标题{('Y' if r['title'] else 'N')} | {r['head'][:42]}")
        print("-" * 100)
    json.dump(results, open(
        os.path.join(os.path.dirname(os.path.abspath(__file__)), "_extract_verify.json"),
        "w", encoding="utf-8"), ensure_ascii=False, indent=1)


if __name__ == "__main__":
    asyncio.run(main())
