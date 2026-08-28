#!/usr/bin/env python3
"""AI / Screener / easytdx 三模块的语义令牌迁移。

按以下顺序处理（顺序敏感）：
1. 特定语义反转：AI 模块用 var(--ff-up, #12a150) 表示"好=绿"，
   与 tokens.css 的 --ff-up=红 冲突。批量替换为 var(--ff-down)（=绿）
2. 清理 var() 兜底：移除所有 var(--token, #fallback) 中的 fallback
3. 裸 HEX 批量替换为 var() 语义令牌

用法: python web/scripts/migrate_modules.py [--apply]   # 默认 dry-run
"""
import os
import re
import sys

ROOT = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src"))

# 颜色 → 语义令牌映射（v4.3 品牌色定蓝后）
HEX_MAP = {
    # 品牌色（绿 → 蓝，与 DESIGN_SYSTEM.md §3.1 / §10-D1 决策一致）
    "#2f7d5b": "var(--ff-brand)",
    "#1d4e39": "var(--ff-brand-active)",
    "#4f9e76": "var(--ff-brand-hover)",
    "#9fc3b1": "var(--ff-brand-border)",
    "#bfd9cc": "var(--ff-brand-subtle-hover)",
    "#eaf4ef": "var(--ff-brand-subtle)",
    # 文本 / 边框（Tailwind 灰阶 → 语义令牌）
    "#1f2937": "var(--ff-text-primary)",
    "#6b7280": "var(--ff-text-secondary)",
    "#9ca3af": "var(--ff-text-tertiary)",
    "#e5e7eb": "var(--ff-border)",
    "#8aa096": "var(--ff-text-3)",
    # 背景
    "#fff":    "var(--ff-bg-surface)",
    "#ffffff": "var(--ff-bg-surface)",
    "#f3f6f4": "var(--ff-bg-subtle)",
    "#f1f4f2": "var(--ff-bg-subtle)",
    "#f9fafb": "var(--ff-bg-subtle)",
    "#f3f4f6": "var(--ff-bg-subtle)",
    "#f0f3f7": "var(--ff-bg-subtle)",
    "#e3e8ef": "var(--ff-border)",
    # 旧涨红 → token 实际值
    "#e5484d": "var(--ff-up)",
    "#fdecec": "var(--ff-up-subtle)",
    "#f5c6c8": "var(--ff-up-border)",
    # 状态绿（Web 习惯"涨=绿=好"与 A 股"涨=红"相反；
    # tokens 无 --ff-success，故复用 --ff-down 的绿色）
    "#12a150": "var(--ff-down)",
    "#0d8a43": "var(--ff-down)",
    "#2bb763": "var(--ff-down)",
    "#15803d": "var(--ff-down)",
    # 状态红 → --ff-up（token 里是红色）
    "#f0575c": "var(--ff-up)",
    "#d02b31": "var(--ff-up)",
    "#ff6b6b": "var(--ff-up)",
    "#fbcdcf": "var(--ff-up-border)",
    "#fde4e5": "var(--ff-up-subtle)",
    # easytdx 残留
    "#c0392b": "var(--ff-up)",
    "#b7791f": "var(--ff-warn)",
    "#f59e0b": "var(--ff-warn)",
    "#0f766e": "var(--ff-info)",
    "#9aa4b2": "var(--ff-text-3)",
    "#fdecea": "var(--ff-up-subtle)",
}

# Pass 1a：特定语义反转（必须在通用清理之前）
SEMANTIC_FIXES = [
    (r"var\(--ff-up,\s*#12a150\)", "var(--ff-down)"),
    (r"var\(--ff-up,\s*#0d8a43\)",  "var(--ff-down)"),
    (r"var\(--ff-up,\s*#2bb763\)",  "var(--ff-down)"),
    (r"var\(--ff-up,\s*#15803d\)",  "var(--ff-down)"),
    (r"var\(--ff-down,\s*#e5484d\)", "var(--ff-up)"),
    (r"var\(--ff-up,\s*#e5484d\)",   "var(--ff-up)"),
    (r"var\(--ff-down,\s*#12a150\)", "var(--ff-down)"),
]


def collect_files(roots):
    out = []
    for r in roots:
        path = os.path.join(ROOT, r)
        if os.path.isfile(path):
            out.append(path)
            continue
        for dp, dn, fn in os.walk(path):
            dn[:] = [d for d in dn if d not in ("node_modules", "dist")]
            for f in fn:
                if f.endswith((".vue", ".css")):
                    out.append(os.path.join(dp, f))
    return sorted(out)


def migrate(text):
    for pat, rep in SEMANTIC_FIXES:
        text = re.sub(pat, rep, text, flags=re.I)
    text = re.sub(
        r"var\(\s*(--[\w-]+)\s*,\s*#[0-9a-fA-F]{3,8}\s*\)",
        r"var(\1)",
        text,
    )
    for hex_, var in HEX_MAP.items():
        text = re.sub(
            r"(?<![\w#])" + re.escape(hex_) + r"(?!\w)",
            var,
            text,
            flags=re.I,
        )
    return text


def main():
    apply = "--apply" in sys.argv
    files = collect_files([
        "views/ai", "components/ai",
        "views/ScreenerView.vue",
        "components/easytdx",
    ])

    changed = []
    for f in files:
        src = open(f, encoding="utf-8").read()
        out = migrate(src)
        if out != src:
            rel = os.path.relpath(f, ROOT).replace(os.sep, "/")
            n = sum(1 for a, b in zip(src.splitlines(), out.splitlines()) if a != b)
            changed.append((rel, n, out))
            if apply:
                open(f, "w", encoding="utf-8").write(out)

    mode = "已写入" if apply else "预演(dry-run)"
    print(f"{mode}: {len(changed)} 个文件")
    for rel, n, _ in sorted(changed, key=lambda x: -x[1]):
        print(f"    {rel:<48} ~{n} 行")
    if not apply and changed:
        print("\n确认无误后加 --apply 执行写入。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
