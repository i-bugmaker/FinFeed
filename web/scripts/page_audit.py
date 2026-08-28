#!/usr/bin/env python3
"""页面结构审计：页面骨架、信息层级、状态覆盖、组件复用与导航一致性。

只读脚本。输出供设计评审使用。
用法: python web/scripts/page_audit.py [--root web/src]
"""
import os
import re
import sys

TEMPLATE = re.compile(r"<template[^>]*>(.*)</template>", re.S)
SCRIPT = re.compile(r"<script[^>]*>(.*?)</script>", re.S)


def read(p):
    try:
        with open(p, encoding="utf-8") as fh:
            return fh.read()
    except (OSError, UnicodeDecodeError):
        return ""


def walk(root, exts):
    for dp, dn, fn in os.walk(root):
        dn[:] = [d for d in dn if d not in ("node_modules", "dist", ".git")]
        for f in sorted(fn):
            if f.endswith(exts):
                yield os.path.join(dp, f).replace(os.sep, "/")


def has(tpl, pat):
    return bool(re.search(pat, tpl, re.I))


def analyze(path, root):
    src = read(path)
    m = TEMPLATE.search(src)
    tpl = m.group(1) if m else ""
    rel = os.path.relpath(path, root).replace(os.sep, "/")

    # 页面骨架
    skeleton = {
        "page_cls": has(tpl, r'class="[^"]*\bff-page\b'),
        "page_header": has(tpl, r"ff-page__header"),
        "grid": has(tpl, r"\bff-grid\b"),
        "autogrid": has(tpl, r"\bff-autogrid\b"),
        "card": has(tpl, r"\bAppCard\b|\bff-card\b"),
    }

    # 标题层级：模板中出现的 h1~h4 与排版类
    heads = re.findall(r"<(h[1-4])\b", tpl, re.I)
    typo = re.findall(r'class="[^"]*\bff-(h1|h2|h3|h4|display|lede)\b', tpl)

    # 状态覆盖
    # 注意：本项目除 AppEmpty 外还有一层包装组件 EmptyState（内部即 AppEmpty）。
    # 只匹配 AppEmpty 会产生假阴性——早期版本因此把「缺空状态」的视图数
    # 从实际 11 个高估为 17 个。error 同理，需匹配模板中的渲染分支而非脚本变量。
    states = {
        "loading": has(tpl, r"ff-skeleton|AppSkeleton|is-loading|ff-btn--loading|:loading"),
        "empty": has(tpl, r"AppEmpty|ff-empty|is-empty|<EmptyState"),
        "error": has(
            tpl,
            r'v-if="(?:err|error|hasError|loadError)"'
            r'|v-else-if="(?:err|error|hasError|loadError)"'
            r"|is-error|ff-alert|--danger",
        ),
    }

    # 组件复用（是否使用统一 UI 组件）
    ui = sorted(set(re.findall(r"<(App[A-Z]\w+)", tpl)))
    # 自写按钮（未走 AppButton）
    raw_btn = len(re.findall(r"<button\b", tpl, re.I))
    # 自写图标（绕过 AppIcon）
    raw_svg = len(re.findall(r"<svg\b", tpl, re.I))

    lines = src.count("\n") + 1

    return {
        "file": rel,
        "lines": lines,
        "skeleton": skeleton,
        "heads": heads,
        "typo": typo,
        "states": states,
        "ui": ui,
        "raw_btn": raw_btn,
        "raw_svg": raw_svg,
    }


def main():
    root = "src"
    if not os.path.isdir(root):
        print(f"[!] 未找到 {root}", file=sys.stderr)
        return 1

    views = [p for p in walk(root, (".vue",)) if "/views/" in p]
    comps = [p for p in walk(root, (".vue",)) if "/components/" in p or "/features/" in p]
    uikit = [p for p in walk(root, (".vue",)) if "/ui/" in p]
    # 应用外壳（src/App.vue 等）：不属于 views/components，但会消费 UI 组件，
    # 漏掉它会误报「UI 组件无人引用」。
    shell = [p for p in walk(root, (".vue",))
             if "/views/" not in p and "/components/" not in p
             and "/features/" not in p and "/ui/" not in p]

    rows = [analyze(p, root) for p in views]

    W = 96
    print("=" * W)
    print("页面结构审计报告")
    print("=" * W)
    print(f"视图总数 : {len(views)}    业务组件 {len(comps)}    UI 组件 {len(uikit)}")

    # ── 1. 页面骨架一致性 ──────────────────────────────────────────────
    print("\n" + "-" * W)
    print("1. 页面骨架（.ff-page / .ff-page__header / .ff-grid）")
    print("-" * W)
    print(f"{'视图':<34}{'行数':>6}{'page':>6}{'header':>8}{'grid':>6}{'card':>6}{'标题标签':>12}")
    for r in sorted(rows, key=lambda x: -x["lines"]):
        name = r["file"].replace("src/views/", "")
        s = r["skeleton"]
        print(f"{name:<34}{r['lines']:>6}"
              f"{'✓' if s['page_cls'] else '·':>6}"
              f"{'✓' if s['page_header'] else '·':>8}"
              f"{'✓' if s['grid'] else '·':>6}"
              f"{'✓' if s['card'] else '·':>6}"
              f"{','.join(sorted(set(r['heads']))) or '—':>12}")

    n_page = sum(1 for r in rows if r["skeleton"]["page_cls"])
    n_hdr = sum(1 for r in rows if r["skeleton"]["page_header"])
    n_grid = sum(1 for r in rows if r["skeleton"]["grid"])
    print(f"\n  采用 .ff-page      : {n_page}/{len(rows)}")
    print(f"  采用 .ff-page__header: {n_hdr}/{len(rows)}")
    print(f"  采用 .ff-grid      : {n_grid}/{len(rows)}")

    # ── 2. 信息层级 ────────────────────────────────────────────────────
    print("\n" + "-" * W)
    print("2. 信息层级（页面标题来源）")
    print("-" * W)
    no_head = [r for r in rows if not r["heads"] and not r["typo"]]
    raw_head = [r for r in rows if r["heads"] and not r["typo"]]
    typo_only = [r for r in rows if r["typo"]]
    print(f"  用原生 h1~h4 且未用排版类 : {len(raw_head)} 个视图")
    for r in raw_head:
        print(f"      {r['file'].replace('src/views/',''):<40} {','.join(sorted(set(r['heads'])))}")
    print(f"  用 .ff-h* 排版类          : {len(typo_only)} 个视图")
    for r in typo_only:
        print(f"      {r['file'].replace('src/views/',''):<40} {','.join(sorted(set(r['typo'])))}")
    print(f"  无显式标题                : {len(no_head)} 个视图")
    for r in no_head:
        print(f"      {r['file'].replace('src/views/','')}")

    # ── 3. 状态覆盖 ────────────────────────────────────────────────────
    print("\n" + "-" * W)
    print("3. 异步状态覆盖（loading / empty / error）")
    print("-" * W)
    print(f"{'视图':<34}{'loading':>9}{'empty':>8}{'error':>8}   缺口")
    gaps = []
    for r in sorted(rows, key=lambda x: -x["lines"]):
        st = r["states"]
        miss = [k for k, v in st.items() if not v]
        if miss:
            gaps.append((r["file"], miss))
        print(f"{r['file'].replace('src/views/',''):<34}"
              f"{'✓' if st['loading'] else '✗':>9}"
              f"{'✓' if st['empty'] else '✗':>8}"
              f"{'✓' if st['error'] else '✗':>8}   {','.join(miss) or '—'}")
    print(f"\n  存在状态缺口的视图: {len(gaps)}/{len(rows)}")

    # ── 4. 组件复用 ────────────────────────────────────────────────────
    print("\n" + "-" * W)
    print("4. 组件复用：自写 <button> / <svg> 绕统一组件的情况")
    print("-" * W)
    allc = [analyze(p, root) for p in views + comps + shell]
    rawbtn = [(r["file"], r["raw_btn"]) for r in allc if r["raw_btn"] > 0]
    rawsvg = [(r["file"], r["raw_svg"]) for r in allc if r["raw_svg"] > 0]
    print(f"  含自写 <button> 的文件: {len(rawbtn)}（合计 {sum(n for _, n in rawbtn)} 处）")
    for f, n in sorted(rawbtn, key=lambda x: -x[1])[:12]:
        print(f"      {f:<56} {n} 处")
    print(f"\n  含自写 <svg> 的文件: {len(rawsvg)}（合计 {sum(n for _, n in rawsvg)} 处）")
    for f, n in sorted(rawsvg, key=lambda x: -x[1])[:12]:
        print(f"      {f:<56} {n} 处")

    # ── 5. UI 组件被引用情况 ───────────────────────────────────────────
    print("\n" + "-" * W)
    print("5. UI 组件引用热度（识别「造了却没人用」的组件）")
    print("-" * W)
    usage = {}
    for r in allc:
        for c in r["ui"]:
            usage[c] = usage.get(c, 0) + 1
    names = sorted(
        os.path.basename(p)[:-4] for p in uikit if os.path.basename(p)[0] == "A"
    )
    for n in names:
        c = usage.get(n, 0)
        flag = "  ← 未被任何业务组件引用" if c == 0 else ""
        print(f"      {n:<20} 被 {c:>3} 个文件引用{flag}")

    print("\n" + "=" * W)
    return 0


if __name__ == "__main__":
    sys.exit(main())
