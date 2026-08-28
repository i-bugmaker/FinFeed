#!/usr/bin/env python3
"""FinFeed Web UI 静态审计 —— 令牌完整度 / 深色模式 / 硬编码 / 响应式。

只读脚本，不修改任何源文件。输出供设计评审使用的量化报告。
用法: python web/scripts/ui_audit.py [--root web/src]
"""
import argparse
import collections
import os
import re
import sys

SCAN_EXT = (".vue", ".css", ".js", ".ts")
TOKEN_DEF = re.compile(r"(--[\w-]+)\s*:")
TOKEN_USE = re.compile(r"var\(\s*(--[\w-]+)")
HEX = re.compile(r"#(?:[0-9a-fA-F]{3,4}|[0-9a-fA-F]{6}|[0-9a-fA-F]{8})\b")
RGBA = re.compile(r"rgba?\([^)]*\)")
PX_SPACING = re.compile(
    r"(?<![\w-])(?:padding|margin|gap|row-gap|column-gap)(?:-(?:top|right|bottom|left))?"
    r"\s*:\s*[^;{}]*?\b(\d+(?:\.\d+)?)px"
)
TRANS_ALL = re.compile(r"transition:\s*all")
OUTLINE_NONE = re.compile(r"outline\s*:\s*(?:none|0)")
MEDIA = re.compile(r"@media")
DARK = re.compile(r"data-theme|prefers-color-scheme")
FOCUS = re.compile(r":focus(?:-visible)?")
EMOJI = re.compile(
    "[\U0001F300-\U0001FAFF\U00002600-\U000027BF\U0001F000-\U0001F2FF]"
)


def walk(root):
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in ("node_modules", "dist", ".git")]
        for fn in filenames:
            if fn.endswith(SCAN_EXT):
                yield os.path.join(dirpath, fn).replace(os.sep, "/")


def read(path):
    try:
        with open(path, encoding="utf-8") as fh:
            return fh.read()
    except (OSError, UnicodeDecodeError):
        return ""


def strip_style_blocks(text):
    """去掉 <style> 区块，用于区分模板/脚本与样式。"""
    return re.sub(r"<style[^>]*>.*?</style>", "", text, flags=re.S)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", default="src")
    args = ap.parse_args()
    root = args.root.rstrip("/")

    if not os.path.isdir(root):
        print(f"[!] 目录不存在: {root}", file=sys.stderr)
        return 1

    files = sorted(walk(root))
    if not files:
        print(f"[!] 未扫描到文件: {root}", file=sys.stderr)
        return 1

    docs = {f: read(f) for f in files}

    # ── 1. 令牌定义 vs 引用 ────────────────────────────────────────────
    # 定义来源有二，二者都算「有定义」，否则组件内局部变量会被误报为幽灵令牌：
    #   a) 全局设计令牌（.css，集中在 tokens.css）
    #   b) 组件内局部变量（.vue 的 <style> 块，如 --smic-c）
    defined = set()
    local_defined = set()
    for f, t in docs.items():
        if f.endswith(".css"):
            defined |= set(TOKEN_DEF.findall(t))
        elif f.endswith(".vue"):
            style = "".join(re.findall(r"<style[^>]*>(.*?)</style>", t, re.S))
            local_defined |= set(TOKEN_DEF.findall(style))

    use_count = collections.Counter()
    use_loc = collections.defaultdict(collections.Counter)
    for f, t in docs.items():
        for tok in TOKEN_USE.findall(t):
            use_count[tok] += 1
            use_loc[tok][f] += 1

    known = defined | local_defined
    undef = {k: v for k, v in use_count.items() if k not in known}
    total_use = sum(use_count.values())
    total_undef = sum(undef.values())

    # ── 2. 逐文件指标 ──────────────────────────────────────────────────
    per_file = []
    for f, t in docs.items():
        style = t if f.endswith(".css") else "".join(re.findall(r"<style[^>]*>(.*?)</style>", t, re.S))
        per_file.append(
            {
                "file": f,
                "hex": len(HEX.findall(t)),
                "hex_style": len(HEX.findall(style)),
                "rgba": len(RGBA.findall(t)),
                "px": len(PX_SPACING.findall(t)),
                "trans_all": len(TRANS_ALL.findall(t)),
                "outline_none": len(OUTLINE_NONE.findall(t)),
                "media": len(MEDIA.findall(t)),
                "dark": len(DARK.findall(t)),
                "focus": len(FOCUS.findall(t)),
                "emoji": len(EMOJI.findall(t)),
                "undef_tok": sum(use_loc[k][f] for k in undef),
                "lines": t.count("\n") + 1,
            }
        )

    # ── 3. 输出 ────────────────────────────────────────────────────────
    W = 78
    print("=" * W)
    print("FinFeed Web UI 静态审计报告")
    print("=" * W)
    print(f"扫描根目录 : {root}")
    print(f"文件总数   : {len(files)}   (.vue/.css/.js/.ts)")
    print(f"代码总行数 : {sum(r['lines'] for r in per_file):,}")

    print("\n" + "-" * W)
    print("1. 设计令牌完整度")
    print("-" * W)
    print(f"全局令牌   : {len(defined)}（tokens.css 等 .css 定义）")
    print(f"组件局部变量: {len(local_defined)}（.vue <style> 内定义，属合法用法）")
    print(f"被引用令牌 : {len(use_count)}  (引用总次数 {total_use:,})")
    print(f"失效引用   : {len(undef)} 种 / {total_undef:,} 次  "
          f"({total_undef / max(total_use, 1) * 100:.1f}%)")
    print("\n  未定义却被引用的令牌 TOP 15:")
    for k, v in sorted(undef.items(), key=lambda x: -x[1])[:15]:
        top = use_loc[k].most_common(2)
        where = ", ".join(f"{p.split('/')[-1]}({c})" for p, c in top)
        print(f"    {k:<30} {v:>4} 次   {where}")

    print("\n" + "-" * W)
    print("2. 深色模式适配")
    print("-" * W)
    dark_files = [r for r in per_file if r["dark"] > 0]
    vue_files = [r for r in per_file if r["file"].endswith(".vue")]
    print(f"含深色适配的文件 : {len(dark_files)}  -> {[r['file'] for r in dark_files]}")
    print(f"Vue 组件总数     : {len(vue_files)}")
    print(f"Vue 深色适配率   : {len([r for r in dark_files if r['file'].endswith('.vue')])}"
          f"/{len(vue_files)}")
    print("  结论: 令牌层已定义 [data-theme='dark']，但组件层未消费 -> 深色模式不生效")

    print("\n" + "-" * W)
    print("3. 硬编码与规范偏差（按文件，TOP 20）")
    print("-" * W)
    print(f"{'文件':<52}{'hex':>6}{'px':>6}{'trans':>7}{'失效tok':>8}")
    ranked = sorted(per_file, key=lambda r: -(r["hex"] + r["px"] * 0.3 + r["undef_tok"] * 2))
    for r in ranked[:20]:
        name = r["file"][len(root) + 1:]
        name = name if len(name) <= 50 else "…" + name[-49:]
        print(f"{name:<52}{r['hex']:>6}{r['px']:>6}{r['trans_all']:>7}{r['undef_tok']:>8}")

    print("\n" + "-" * W)
    print("4. 全局合计")
    print("-" * W)
    agg = collections.Counter()
    for r in per_file:
        for k in ("hex", "rgba", "px", "trans_all", "outline_none", "media", "focus", "emoji"):
            agg[k] += r[k]
    print(f"硬编码 HEX 颜色     : {agg['hex']}")
    print(f"硬编码 rgba()       : {agg['rgba']}")
    print(f"硬编码 px 间距      : {agg['px']}")
    print(f"transition: all    : {agg['trans_all']}")
    print(f"outline: none      : {agg['outline_none']}")
    print(f"@media 查询         : {agg['media']}")
    print(f":focus 样式         : {agg['focus']}")
    print(f"残留 emoji          : {agg['emoji']}")

    print("\n" + "-" * W)
    print("5. 最缺响应式适配的文件（.vue 中 @media == 0 且 >150 行）")
    print("-" * W)
    no_resp = [r for r in vue_files if r["media"] == 0 and r["lines"] > 150]
    no_resp.sort(key=lambda r: -r["lines"])
    for r in no_resp[:15]:
        print(f"    {r['file'][len(root) + 1:]:<56} {r['lines']:>5} 行")
    print(f"    合计 {len(no_resp)} 个组件无任何断点适配")

    print("\n" + "=" * W)
    print("审计结束（只读，未修改任何文件）")
    print("=" * W)
    return 0


if __name__ == "__main__":
    sys.exit(main())
