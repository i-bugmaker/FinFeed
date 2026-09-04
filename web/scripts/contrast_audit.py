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
    ("--ff-hot-text", "--ff-bg-surface", "热度文字 / 卡片底", AA_TEXT),
    ("--ff-hot-text", "--ff-hot-subtle", "热度文字 / 热度浅底", AA_TEXT),
    ("--ff-hot-fg", "--ff-hot-strong", "热度徽章白字 / 热度实底", AA_TEXT),
    ("--ff-hot", "--ff-bg-surface", "热度(图标/描边) / 卡片底", AA_LARGE),
]


# ── 组件硬编码颜色扫描 ──────────────────────────────────────────────────
# 令牌审计只能覆盖 var(--ff-*) 组合；组件里绕过令牌的硬编码颜色（如曾出现的
# 白字黄底徽章 1.58:1）是审计盲区。此处按「声明块」提取 color 与 background
# 的字面量配对计算对比度：
#   · color + background 同块    → 按块内字号判 4.5（正文）或 3.0（大字）
#   · 仅 color（无同块背景）      → 对白底/画布/浅底取最差值：
#                                    <3.0 记 FAIL（按图形/图标下限），
#                                    3.0~4.5 记 WARN（疑似小号正文）
# 仅覆盖亮色假设；令牌层暗色已单独成套审计。
COMPONENT_ALLOW = {
    "ui/AppLogo.vue",  # 品牌标志（装饰性，非正文）
}
NAMED = {"white": (255, 255, 255, 1), "black": (0, 0, 0, 1)}
SKIP_VAL = re.compile(r"^\s*(var\(|color-mix\(|transparent|inherit|currentcolor|none)",
                      re.I)
GRAD_STOP = re.compile(r"(#[0-9a-fA-F]{3,8}|rgba?\([^)]*\))")
COLORMIX = re.compile(
    r"color-mix\(\s*in\s+srgb\s*,\s*(#[0-9a-fA-F]{3,8}|rgba?\([^)]*\))\s+"
    r"([\d.]+)%\s*,", re.I)
DECL = re.compile(r"(?<![\w-])(color|background(?:-color)?)\s*:\s*([^;{}]+)")
FS_DECL = re.compile(r"font-size\s*:\s*([\d.]+)px")
FW_DECL = re.compile(r"font-weight\s*:\s*(\d{3})")


def _lit_color(val):
    """字面量颜色 → (r,g,b,a)；var()/color-mix() 等返回 None（另有处理）。"""
    v = val.strip()
    if SKIP_VAL.match(v):
        return None
    low = v.lower()
    if low in NAMED:
        return NAMED[low]
    return parse_color(v)


def _bg_candidates(val):
    """背景值 → 候选 (r,g,b,a) 列表（渐变取全部色标；color-mix 按比例混白）。"""
    v = val.strip()
    out = []
    if SKIP_VAL.match(v):
        return out
    cm = COLORMIX.match(v)
    if cm:
        c = parse_color(cm.group(1))
        if c:
            out.append((c[0], c[1], c[2], c[3] * float(cm.group(2)) / 100.0))
        return out
    if "gradient(" in v:
        for stop in GRAD_STOP.findall(v):
            c = _lit_color(stop)
            if c:
                out.append(c)
        return out
    c = _lit_color(v)
    return [c] if c else []


def scan_components(src_root):
    """扫描组件/样式文件中的硬编码颜色对，返回 (fails, warns) 明细列表。"""
    fails, warns = [], []
    seen = set()
    for dirpath, dirnames, filenames in os.walk(src_root):
        dirnames[:] = [d for d in dirnames if d not in ("node_modules", "dist")]
        for fn in filenames:
            if not fn.endswith((".vue", ".css")):
                continue
            path = os.path.join(dirpath, fn)
            rel = os.path.relpath(path, src_root).replace(os.sep, "/")
            if rel in COMPONENT_ALLOW or rel == "styles/tokens.css":
                continue
            text = open(path, encoding="utf-8").read()
            if fn.endswith(".vue"):
                styles = re.findall(r"<style[^>]*>(.*?)</style>", text, re.S)
                chunks = []
                for st in styles:
                    start = text.find(st) if st else -1
                    chunks.append((st, text.count("\n", 0, max(start, 0))))
                    break  # 组件内至多一个 style 块，行号按首个块算
                if not chunks:
                    continue
                body_all, line0 = chunks[0]
            else:
                body_all, line0 = text, 0
            body_all = re.sub(r"/\*.*?\*/", "", body_all, flags=re.S)
            for m in re.finditer(r"([^{}]+)\{", body_all):
                blk = extract_block(body_all, m.end() - 1)
                # 截断嵌套块污染（@media 场景），只看本层声明
                blk = blk.split("{")[0]
                props = {}
                for name, val in DECL.findall(blk):
                    props.setdefault(name, val)
                if "color" not in props:
                    continue
                fg = _lit_color(props["color"])
                if fg is None:
                    continue
                fgs = composite(fg, (255, 255, 255)) if fg[3] < 1 else fg[:3]
                fs_m = FS_DECL.search(blk)
                fw_m = FW_DECL.search(blk)
                fs = float(fs_m.group(1)) if fs_m else None
                fw = int(fw_m.group(1)) if fw_m else 400
                large = fs is not None and (fs >= 24 or (fs >= 18.66 and fw >= 600))
                need = AA_LARGE if large else AA_TEXT
                line = line0 + body_all.count("\n", 0, m.start()) + 1
                fg_str = props["color"].strip()
                bgs = []
                bg_str = ""
                for key in ("background", "background-color"):
                    if key in props:
                        bgs = _bg_candidates(props[key])
                        if bgs:
                            bg_str = props[key].strip()
                            break
                if bgs:
                    worst = None
                    for bg in bgs:
                        bgc = composite(bg, (255, 255, 255)) if bg[3] < 1 else bg[:3]
                        r = contrast_rgb(fgs, bgc)
                        if worst is None or r < worst[0]:
                            worst = (r, bg_str)
                    if worst is None:
                        continue
                    r, bg_disp = worst
                    key_id = (rel, line, fg_str, bg_str)
                    if key_id in seen:
                        continue
                    seen.add(key_id)
                    if r < need:
                        fails.append((rel, line, fg_str, bg_disp, r, need))
                else:
                    # 白/黑文字的底色必然来自外部（彩色面/反色面），静态不可判定，跳过；
                    # 其余无同块背景的前景色对三种常见亮底取最差值。
                    if fg_str.lower().lstrip("#") in ("fff", "ffffff", "white") \
                            or fgs[:3] == (255, 255, 255) or fgs[:3] == (0, 0, 0):
                        continue
                    r = min(contrast_rgb(fgs, b) for b in ((255, 255, 255), (248, 250, 252), (241, 245, 249)))
                    key_id = (rel, line, fg_str, "<无同块背景>")
                    if key_id in seen:
                        continue
                    seen.add(key_id)
                    if r < AA_LARGE:
                        fails.append((rel, line, fg_str, "亮底(假设)", r, AA_LARGE))
                    elif r < AA_TEXT:
                        warns.append((rel, line, fg_str, "亮底(假设)", r, AA_TEXT))
    return fails, warns


def main():
    import argparse

    ap = argparse.ArgumentParser()
    ap.add_argument(
        "--fail",
        action="store_true",
        help="存在对比度未达标项时以非零码退出（供 CI 设阈值失败）",
    )
    args = ap.parse_args()

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

    # ── 组件硬编码颜色扫描 ──────────────────────────────────────────────
    src_root = os.path.normpath(os.path.join(here, "..", "src"))
    c_fails, c_warns = scan_components(src_root)
    print("\n" + "=" * 92)
    print("组件硬编码颜色对比度扫描（亮色假设；var()/color-mix 前景走令牌审计）")
    print("=" * 92)
    if c_fails or c_warns:
        print(f"{'位置':<44}{'前景':<22}{'背景':<16}{'对比度':>7}{'要求':>7}  判定")
        print("-" * 92)
        for rel, line, fg, bg, r, need in sorted(c_fails, key=lambda x: x[4]):
            print(f"{rel + ':' + str(line):<44}{fg:<22}{bg:<16}{r:>7.2f}{need:>6}:1  FAIL")
        for rel, line, fg, bg, r, need in sorted(c_warns, key=lambda x: x[4]):
            print(f"{rel + ':' + str(line):<44}{fg:<22}{bg:<16}{r:>7.2f}{need:>6}:1  WARN")
        print(f"\n合计 FAIL {len(c_fails)} 项 / WARN {len(c_warns)} 项"
              f"（WARN = 仅前景色无同块背景，3.0~4.5:1，建议核对实际底色）")
    else:
        print("✔ 未发现硬编码颜色对比度问题")

    if args.fail and fails > 0:
        print(f"[FAIL] 存在 {fails} 项令牌对比度未达标，CI 门槛未通过", file=sys.stderr)
        return 1
    if args.fail and c_fails:
        print(f"[FAIL] 组件内存在 {len(c_fails)} 处硬编码颜色对比度不足，CI 门槛未通过",
              file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
