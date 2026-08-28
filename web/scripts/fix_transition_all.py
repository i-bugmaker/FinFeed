#!/usr/bin/env python3
"""将 `transition: all` 替换为显式属性列表，并把字面量时长归一化到设计令牌。

为什么需要：
  `transition: all` 会让浏览器监听元素上所有属性的变化，包含会触发
  重排(reflow)的非合成属性（width/height/top/left 等）。在快讯流这类
  高频重绘的长列表中，这会造成可观测的掉帧。改为只过渡合成友好的属性
  （background-color / border-color / color / box-shadow / transform），
  可让动画完全跑在合成线程上。

规则：
  · 保留原有的缓动函数；未指定缓动时补 --ff-ease-standard。
  · 字面量时长按就近原则映射到令牌：
      <=150ms -> --ff-dur-fast(140)   <=200ms -> --ff-dur-base(200)
      <=280ms -> --ff-dur-slow(280)   其他   -> --ff-dur-slower(400)

用法: python web/scripts/fix_transition_all.py [--apply]   # 默认 dry-run
"""
import os
import re
import sys

PROPS = ["background-color", "border-color", "color", "box-shadow", "transform"]
ROOT = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src"))

# transition: all <rest>;
PAT = re.compile(r"transition:\s*all\s+([^;]+);", re.IGNORECASE)


def normalize(rest):
    """把时长/缓动片段归一化到设计令牌。"""
    text = rest.strip()

    # 提取已有缓动函数
    ease = None
    m_ease = re.search(r"var\(--ff-ease-[\w-]+\)|cubic-bezier\([^)]*\)|ease-in-out|ease-out|ease-in|linear|ease\b", text)
    if m_ease:
        ease = m_ease.group(0)

    # 提取时长并替换
    def repl(m):
        val = m.group(1)
        unit = m.group(2)
        if unit == "s":
            ms = float(val) * 1000
        else:
            ms = float(val)
        if ms <= 150:
            return "var(--ff-dur-fast)"
        if ms <= 200:
            return "var(--ff-dur-base)"
        if ms <= 280:
            return "var(--ff-dur-slow)"
        return "var(--ff-dur-slower)"

    dur = re.sub(r"(\d*\.?\d+)(ms|s)\b", repl, text)
    # 去掉缓动部分，只留时长（可能是 var(...)）
    m_dur = re.search(r"var\(--ff-dur-[\w-]+\)", dur)
    if not m_dur:
        return None
    duration = m_dur.group(0)
    if not ease:
        ease = "var(--ff-ease-standard)"
    return f"{duration} {ease}"


def main():
    apply = "--apply" in sys.argv
    changed = []
    for dirpath, dirnames, filenames in os.walk(ROOT):
        dirnames[:] = [d for d in dirnames if d not in ("node_modules", "dist")]
        for fn in filenames:
            if not fn.endswith((".vue", ".css")):
                continue
            p = os.path.join(dirpath, fn)
            src = open(p, encoding="utf-8").read()
            out = src
            hits = 0

            def sub(m):
                nonlocal hits
                norm = normalize(m.group(1))
                if not norm:
                    return m.group(0)
                hits += 1
                return "transition: " + ", ".join(f"{pr} {norm}" for pr in PROPS) + ";"

            out = PAT.sub(sub, src)
            if hits:
                rel = os.path.relpath(p, ROOT).replace(os.sep, "/")
                changed.append((rel, hits))
                if apply:
                    open(p, "w", encoding="utf-8").write(out)

    total = sum(h for _, h in changed)
    mode = "已写入" if apply else "预演(dry-run)"
    print(f"{mode}: {len(changed)} 个文件 / {total} 处 transition: all")
    for rel, h in sorted(changed, key=lambda x: -x[1]):
        print(f"    {rel:<52} {h} 处")
    if not apply and total:
        print("\n确认无误后加 --apply 执行写入。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
