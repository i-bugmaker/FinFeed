#!/usr/bin/env python3
"""FinFeed 设计令牌 WCAG 对比度审计。

只读脚本。从 tokens.css 解析亮/暗主题令牌，计算关键前后景组合的对比度，
判定是否符合 WCAG 2.1 AA（正文 4.5:1，大字/UI 组件 3:1）。
支持 rgba 半透明色在给定底色上的合成计算。

用法: python web/scripts/contrast_audit.py
"""
import os
import re
import sys

AA_TEXT = 4.5    # 正文
AA_LARGE = 3.0   # 大字(>=18.66px bold 或 >=24px) 与 UI 组件/图形

HEX_RE = re.compile(r"^#(?:[0-9a-fA-F]{3}|[0-9a-fA-F]{4}|[0-9a-fA-F]{6}|[0-9a-fA-F]{8})$")
RGBA_RE = re.compile(r"^rgba?\(\s*([\d.]+)\s*,\s*([\d.]+)\s*,\s*([\d.]+)"
                     r"(?:\s*,\s*([\d.]+))?\s*\)$")


# ── 颜色工具 ────────────────────────────────────────────────────────────
def srgb_to_lin(c):
    c /= 255.0
    return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4


def luminance(rgb):
    r, g, b = (srgb_to_lin(v) for v in rgb)
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def contrast_rgb(fg, bg):
    l1, l2 = luminance(fg), luminance(bg)
    hi, lo = max(l1, l2), min(l1, l2)
    return (hi + 0.05) / (lo + 0.05)


def parse_color(val):
    """返回 (r,g,b) 或 (r,g,b,a)；无法解析返回 None。"""
    if not val:
        return None
    v = val.strip()
    if HEX_RE.match(v):
        h = v.lstrip("#")
        if len(h) in (3, 4):
            h = "".join(ch * 2 for ch in h)
        r, g, b = (int(h[i:i + 2], 16) for i in (0, 2, 4))
        a = int(h[6:8], 16) / 255.0 if len(h) == 8 else 1.0
        return (r, g, b, a)
    m = RGBA_RE.match(v)
    if m:
        r, g, b = (float(m.group(i)) for i in (1, 2, 3))
        a = float(m.group(4)) if m.group(4) is not None else 1.0
        return (r, g, b, a)
    return None


def composite(fg, bg):
    """将带 alpha 的 fg 合成到不透明 bg 上。"""
    r, g, b, a = fg
    br, bg_, bb = bg[0], bg[1], bg[2]
    return (r * a + br * (1 - a),
            g * a + bg_ * (1 - a),
            b * a + bb * (1 - a))


# ── CSS 解析 ────────────────────────────────────────────────────────────
def extract_block(text, start_brace):
    """从 '{' 位置起做花括号配对，返回块内部文本。"""
    depth = 0
    i = start_brace
    while i < len(text):
        if text[i] == "{":
            depth += 1
        elif text[i] == "}":
            depth -= 1
            if depth == 0:
                return text[start_brace + 1:i]
        i += 1
    return text[start_brace + 1:]


def declarations(body):
    out = {}
    for name, val in re.findall(r"(--[\w-]+)\s*:\s*([^;{}]+)", body):
        out.setdefault(name, val.strip())
    return out


def parse_theme(path):
    """返回 {'light': {...}, 'dark': {...}}，每个为主题内的令牌 -> 原始值。"""
    text = open(path, encoding="utf-8").read()
    # 去掉注释，避免注释里的示例值干扰
    text = re.sub(r"/\*.*?\*/", "", text, flags=re.S)

    blocks = []   # (selector, body)
    for m in re.finditer(r"([^{}]+)\{", text):
        sel = m.group(1).strip().replace("\n", " ")
        sel = re.sub(r"\s+", " ", sel)
        body = extract_block(text, m.end() - 1)
        blocks.append((sel, body))

    base = {}
    light = {}
    dark = {}
    for sel, body in blocks:
        d = declarations(body)
        if not d:
            continue
        if sel == ":root":
            base.update(d)
        elif "data-theme='light'" in sel:
            light.update(d)
        elif "data-theme='dark'" in sel:
            dark.update(d)

    return {"light": {**base, **light}, "dark": {**base, **dark}}


def resolve(tokens, name, depth=0):
    """解析令牌到 (r,g,b,a)，支持 var() 别名，最多 6 层。"""
    if depth > 6 or name not in tokens:
        return None
    val = tokens[name]
    m = re.match(r"^var\(\s*(--[\w-]+)\s*\)$", val)
    if m:
        return resolve(tokens, m.group(1), depth + 1)
    return parse_color(val)


# ── 测试用例 ────────────────────────────────────────────────────────────
# 以下令牌豁免严格判定，但仍纳入测量供参考：
#   · --ff-text-disabled  WCAG 1.4.3 明确豁免「非活动/禁用组件」
#   · --ff-border/-strong 纯装饰性分隔线/卡片描边。WCAG 1.4.11 的 3:1 只约束
#                         「识别控件所必需」的边界；表单控件已改用
#                         --ff-border-field，本脚本对其单独检查。
EXEMPT = {
    "--ff-text-disabled": "WCAG 1.4.3 豁免禁用态",
    "--ff-border": "装饰性分隔线，表单请用 --ff-border-field",
    "--ff-border-strong": "装饰性描边，表单请用 --ff-border-field",
}

# (前景令牌, 背景令牌, 用途, 阈值)
CASES = [
    ("--ff-text-primary", "--ff-bg-canvas", "主文本 / 页面底色", AA_TEXT),
    ("--ff-text-primary", "--ff-bg-surface", "主文本 / 卡片底", AA_TEXT),
    ("--ff-text-secondary", "--ff-bg-surface", "次级文本 / 卡片底", AA_TEXT),
    ("--ff-text-tertiary", "--ff-bg-surface", "辅助文本 / 卡片底", AA_TEXT),
    ("--ff-text-placeholder", "--ff-bg-surface", "占位符 / 卡片底", AA_TEXT),
    ("--ff-text-disabled", "--ff-bg-surface", "禁用文本 / 卡片底", AA_LARGE),
    ("--ff-text-link", "--ff-bg-surface", "链接 / 卡片底", AA_TEXT),
    ("--ff-brand-text", "--ff-bg-surface", "品牌文字 / 卡片底", AA_TEXT),
    ("--ff-brand-fg", "--ff-brand", "主按钮文字 / 主按钮底", AA_TEXT),
    ("--ff-up-text", "--ff-bg-surface", "涨(红)文字 / 卡片底", AA_TEXT),
    ("--ff-down-text", "--ff-bg-surface", "跌(绿)文字 / 卡片底", AA_TEXT),
    ("--ff-warn-text", "--ff-bg-surface", "警示文字 / 卡片底", AA_TEXT),
    ("--ff-danger-text", "--ff-bg-surface", "危险文字 / 卡片底", AA_TEXT),
    ("--ff-up", "--ff-bg-surface", "涨(红)填充 / 卡片底", AA_LARGE),
    ("--ff-down", "--ff-bg-surface", "跌(绿)填充 / 卡片底", AA_LARGE),
    ("--ff-warn", "--ff-bg-surface", "警示填充 / 卡片底", AA_LARGE),
    ("--ff-brand", "--ff-bg-surface", "品牌色(图标/描边) / 卡片底", AA_LARGE),
    ("--ff-border-strong", "--ff-bg-surface", "强边框（装饰性）/ 卡片底", AA_LARGE),
    ("--ff-border", "--ff-bg-surface", "常规边框（装饰性）/ 卡片底", AA_LARGE),
    ("--ff-border-field", "--ff-bg-surface", "表单控件边框 / 卡片底", AA_LARGE),
    ("--ff-border-field", "--ff-bg-subtle", "表单控件边框 / 浅底", AA_LARGE),
    ("--ff-up-text", "--ff-up-subtle", "涨文字 / 涨浅底", AA_TEXT),
    ("--ff-down-text", "--ff-down-subtle", "跌文字 / 跌浅底", AA_TEXT),
    ("--ff-warn-text", "--ff-warn-subtle", "警示文字 / 警示浅底", AA_TEXT),
    ("--ff-brand-text", "--ff-brand-subtle", "品牌文字 / 品牌浅底", AA_TEXT),
    ("--ff-text-secondary", "--ff-bg-subtle", "次级文本 / 浅底", AA_TEXT),
]


def main():
    here = os.path.dirname(os.path.abspath(__file__))
    tokens_path = os.path.normpath(os.path.join(here, "..", "src", "styles", "tokens.css"))
    if not os.path.exists(tokens_path):
        print(f"[!] 未找到 {tokens_path}", file=sys.stderr)
        return 1

    themes = parse_theme(tokens_path)
    total = fails = 0
    fail_list = []

    for tname, label in (("light", "亮色 Light"), ("dark", "暗色 Dark")):
        tok = themes[tname]
        print("\n" + "=" * 92)
        print(f"主题: {label}   （解析到 {len(tok)} 个令牌）")
        print("=" * 92)
        print(f"{'前景':<24}{'背景':<24}{'对比度':>8}{'要求':>7}  判定  用途")
        print("-" * 92)
        for fg_k, bg_k, usage, need in CASES:
            fg = resolve(tok, fg_k)
            bg = resolve(tok, bg_k)
            if fg is None or bg is None:
                miss = fg_k if fg is None else bg_k
                print(f"{fg_k:<24}{bg_k:<24}{'—':>8}{'—':>7}  跳过  {usage}（{miss} 无法解析）")
                continue
            # 半透明底色需先合成到该主题的画布色上，再计算前景。
            canvas = resolve(tok, "--ff-bg-canvas") or (255, 255, 255, 1)
            bgc = composite(bg, canvas[:3]) if bg[3] < 1 else bg[:3]
            fgc = composite(fg, bgc) if fg[3] < 1 else fg[:3]
            ratio = contrast_rgb(fgc, bgc)
            exempt = fg_k in EXEMPT
            total += 1
            ok = ratio >= need
            if not ok and not exempt:
                fails += 1
                fail_list.append((label, fg_k, bg_k, ratio, need, usage))
            flag = "PASS" if ok else ("豁免" if exempt else "FAIL")
            print(f"{fg_k:<24}{bg_k:<24}{ratio:>8.2f}{need:>6}:1  "
                  f"{flag:<4}  {usage}")

    print("\n" + "=" * 92)
    print(f"合计 {total} 项检查，未达标 {fails} 项")
    print("=" * 92)
    if fail_list:
        print("\n未达标明细（按严重度排序）:")
        for label, fg, bg, ratio, need, usage in sorted(fail_list, key=lambda x: x[3]):
            gap = need - ratio
            print(f"  [{label}] {fg} on {bg}: {ratio:.2f} (需 {need}:1, 差 {gap:.2f}) — {usage}")

    print("\n判定标准: 正文 4.5:1 / 大字与非文本 UI 组件 3:1 (WCAG 2.1 AA)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
