# -*- coding: utf-8 -*-
"""
FinFeed 品牌资产生成器
======================

从统一的几何定义生成全部栅格化品牌资产，保证与 `public/logo.svg`、
`public/favicon.svg` 的矢量源在形状上完全一致。

设计约束
--------
* 画布基准：48 x 48 单位坐标系（与 SVG viewBox 一致）
* 圆角比例：11.5 / 48 = 23.96%（squircle 观感）
* 品牌渐变：#4f8dff -> #2563eb -> #1b3fb8，方向 (4,2) -> (44,46)
* 小尺寸（<= 48px）自动切换为简化字形：加粗笔画、去掉基线，保证 16px 可辨识

渲染管线
--------
超采样（8x / 4x）+ LANCZOS 降采样，获得接近矢量的边缘质量。
圆角笔帽与圆角连接通过「线段 + 顶点圆」手动合成实现。

输出目录：web/public/
运行：python web/scripts/gen_brand_assets.py
"""

from __future__ import annotations

import struct
from io import BytesIO
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFont

# --------------------------------------------------------------------------
# 常量
# --------------------------------------------------------------------------

OUT = Path(__file__).resolve().parents[1] / "public"
OUT.mkdir(parents=True, exist_ok=True)

UNIT = 48.0
RADIUS_RATIO = 11.5 / UNIT

GRAD_STOPS = [
    (0.00, (0x4F, 0x8D, 0xFF)),
    (0.55, (0x25, 0x63, 0xEB)),
    (1.00, (0x1B, 0x3F, 0xB8)),
]
GRAD_FROM = (4.0, 2.0)
GRAD_TO = (44.0, 46.0)

# 完整字形（>= 64px）
FULL_TREND = [(11.0, 30.0), (18.5, 22.5), (25.0, 27.5), (34.0, 15.0)]
FULL_TREND_W = 3.8
FULL_NODE = (34.0, 15.0, 3.6)
FULL_BASE = [(11.0, 35.4), (34.0, 35.4)]
FULL_BASE_W = 2.4
FULL_BASE_ALPHA = 102  # 0.40

# 简化字形（<= 48px）
MINI_TREND = [(11.5, 31.0), (19.0, 23.0), (25.5, 28.5), (34.0, 15.5)]
MINI_TREND_W = 4.6
MINI_NODE = (34.0, 15.5, 4.2)

WHITE = (255, 255, 255)


# --------------------------------------------------------------------------
# 绘制原语
# --------------------------------------------------------------------------

def _gradient_rgb(w: int, h: int) -> np.ndarray:
    """按 userSpaceOnUse 方向生成三段式线性渐变。"""
    sx = w / UNIT
    sy = h / UNIT
    x0, y0 = GRAD_FROM[0] * sx, GRAD_FROM[1] * sy
    x1, y1 = GRAD_TO[0] * sx, GRAD_TO[1] * sy

    dx, dy = x1 - x0, y1 - y0
    denom = dx * dx + dy * dy

    yy, xx = np.mgrid[0:h, 0:w].astype(np.float64)
    t = ((xx - x0) * dx + (yy - y0) * dy) / denom
    t = np.clip(t, 0.0, 1.0)

    out = np.zeros((h, w, 3), dtype=np.float64)
    for i in range(len(GRAD_STOPS) - 1):
        p0, c0 = GRAD_STOPS[i]
        p1, c1 = GRAD_STOPS[i + 1]
        seg = (t >= p0) & (t <= p1)
        local = np.zeros_like(t)
        local[seg] = (t[seg] - p0) / (p1 - p0)
        for ch in range(3):
            out[..., ch][seg] = c0[ch] + (c1[ch] - c0[ch]) * local[seg]
    return out.astype(np.uint8)


def _rounded_mask(w: int, h: int, radius: float) -> Image.Image:
    m = Image.new("L", (w, h), 0)
    d = ImageDraw.Draw(m)
    if radius <= 0:
        d.rectangle([0, 0, w - 1, h - 1], fill=255)
    else:
        d.rounded_rectangle([0, 0, w - 1, h - 1], radius=radius, fill=255)
    return m


def _stroke_polyline(draw: ImageDraw.ImageDraw, pts, width: float, fill) -> None:
    """圆角笔帽 + 圆角连接的折线描边（线段 + 顶点圆合成）。"""
    r = width / 2.0
    if len(pts) >= 2:
        draw.line(pts, fill=fill, width=max(1, int(round(width))))
    for (x, y) in pts:
        draw.ellipse([x - r, y - r, x + r, y + r], fill=fill)


def render_mark(
    size: int,
    *,
    rounded: bool = True,
    bleed_scale: float = 1.0,
    supersample: int = 8,
    simplified: bool | None = None,
    background: bool = True,
) -> Image.Image:
    """渲染品牌标记。

    Args:
        size:         输出边长（px）
        rounded:      是否绘制圆角（apple-touch-icon / maskable 需要直角满幅）
        bleed_scale:  字形缩放系数，用于 maskable 安全区（0.8 = 内缩 20%）
        supersample:  超采样倍率
        simplified:   None 时按尺寸自动判定
        background:   是否绘制品牌底色
    """
    if simplified is None:
        simplified = size <= 48

    ss = max(1, min(supersample, max(1, 4096 // max(size, 1))))
    n = size * ss
    scale = n / UNIT

    if background:
        rgb = _gradient_rgb(n, n)
        alpha = _rounded_mask(n, n, RADIUS_RATIO * n if rounded else 0)
        base = Image.fromarray(rgb, "RGB").convert("RGBA")
        base.putalpha(alpha)
    else:
        base = Image.new("RGBA", (n, n), (0, 0, 0, 0))

    def to_px(pts):
        cx = cy = UNIT / 2.0
        return [
            (
                (cx + (x - cx) * bleed_scale) * scale,
                (cy + (y - cy) * bleed_scale) * scale,
            )
            for (x, y) in pts
        ]

    # 基线（半透明，需独立图层做 alpha 混合）
    if not simplified:
        layer = Image.new("RGBA", (n, n), (0, 0, 0, 0))
        d = ImageDraw.Draw(layer)
        _stroke_polyline(
            d, to_px(FULL_BASE), FULL_BASE_W * scale * bleed_scale,
            WHITE + (FULL_BASE_ALPHA,),
        )
        base = Image.alpha_composite(base, layer)

    # 趋势线 + 实时节点
    layer = Image.new("RGBA", (n, n), (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)
    trend = MINI_TREND if simplified else FULL_TREND
    tw = (MINI_TREND_W if simplified else FULL_TREND_W) * scale * bleed_scale
    _stroke_polyline(d, to_px(trend), tw, WHITE + (255,))

    nx, ny, nr = MINI_NODE if simplified else FULL_NODE
    (px, py), = to_px([(nx, ny)])
    pr = nr * scale * bleed_scale
    d.ellipse([px - pr, py - pr, px + pr, py + pr], fill=WHITE + (255,))
    base = Image.alpha_composite(base, layer)

    if ss > 1:
        base = base.resize((size, size), Image.LANCZOS)
    return base


# --------------------------------------------------------------------------
# ICO 容器（PNG 压缩条目，Vista+ / 全部现代浏览器支持）
# --------------------------------------------------------------------------

def write_ico(path: Path, images: list[Image.Image]) -> None:
    blobs = []
    for im in images:
        buf = BytesIO()
        im.save(buf, format="PNG", optimize=True)
        blobs.append(buf.getvalue())

    n = len(images)
    header = struct.pack("<HHH", 0, 1, n)
    offset = 6 + 16 * n
    entries, payload = b"", b""
    for im, blob in zip(images, blobs):
        w = 0 if im.width >= 256 else im.width
        h = 0 if im.height >= 256 else im.height
        entries += struct.pack("<BBBBHHII", w, h, 0, 0, 1, 32, len(blob), offset)
        offset += len(blob)
        payload += blob
    path.write_bytes(header + entries + payload)


# --------------------------------------------------------------------------
# OG / 社交分享图
# --------------------------------------------------------------------------

FONT_CANDIDATES_BOLD = [
    r"C:\Windows\Fonts\seguibl.ttf",
    r"C:\Windows\Fonts\segoeuib.ttf",
    r"C:\Windows\Fonts\arialbd.ttf",
]
FONT_CANDIDATES_REG = [
    r"C:\Windows\Fonts\segoeui.ttf",
    r"C:\Windows\Fonts\msyh.ttc",
    r"C:\Windows\Fonts\arial.ttf",
]


def _font(cands, size):
    for p in cands:
        if Path(p).exists():
            try:
                return ImageFont.truetype(p, size)
            except Exception:
                continue
    return ImageFont.load_default()


def render_og(w: int = 1200, h: int = 630) -> Image.Image:
    bg = Image.new("RGBA", (w, h), (0x0B, 0x12, 0x1E, 255))
    d = ImageDraw.Draw(bg)

    # 背景网格
    step = 48
    for x in range(0, w, step):
        d.line([(x, 0), (x, h)], fill=(255, 255, 255, 8), width=1)
    for y in range(0, h, step):
        d.line([(0, y), (w, y)], fill=(255, 255, 255, 8), width=1)

    # 品牌辉光
    glow = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    gd = ImageDraw.Draw(glow)
    for i in range(28):
        r = 520 - i * 16
        a = int(3 + i * 0.5)
        gd.ellipse([w - 240 - r, -160 - r, w - 240 + r, -160 + r],
                   fill=(0x25, 0x63, 0xEB, a))
    bg = Image.alpha_composite(bg, glow)
    d = ImageDraw.Draw(bg)

    mark = render_mark(140, rounded=True, supersample=6)
    bg.alpha_composite(mark, (88, 150))

    f_title = _font(FONT_CANDIDATES_BOLD, 92)
    f_sub = _font(FONT_CANDIDATES_REG, 34)
    f_meta = _font(FONT_CANDIDATES_REG, 26)

    d.text((88, 316), "FinFeed", font=f_title, fill=(0xF2, 0xF5, 0xFA, 255))
    d.text((88, 428), "实时财经新闻监控与舆情分析平台",
           font=f_sub, fill=(0x9A, 0xA7, 0xBC, 255))
    d.text((88, 486), "多源聚合  ·  情绪量化  ·  事件日历  ·  AI 解读",
           font=f_meta, fill=(0x5F, 0x82, 0xD6, 255))

    d.line([(88, 300), (168, 300)], fill=(0x25, 0x63, 0xEB, 255), width=5)
    return bg.convert("RGB")


# --------------------------------------------------------------------------
# 主流程
# --------------------------------------------------------------------------

def main() -> None:
    generated: list[str] = []

    # 标准 PNG 序列
    for s in (16, 32, 48, 64, 96, 128, 180, 192, 256, 384, 512):
        im = render_mark(s)
        name = f"favicon-{s}.png" if s <= 48 else f"icon-{s}.png"
        im.save(OUT / name, format="PNG", optimize=True)
        generated.append(name)

    # favicon.ico（16/32/48 三分辨率）
    write_ico(OUT / "favicon.ico", [render_mark(s) for s in (16, 32, 48)])
    generated.append("favicon.ico")

    # Apple Touch Icon：满幅直角、系统自行遮罩
    render_mark(180, rounded=False, bleed_scale=0.86, supersample=8) \
        .convert("RGB").save(OUT / "apple-touch-icon.png", format="PNG", optimize=True)
    generated.append("apple-touch-icon.png")

    # PWA maskable：80% 安全区
    for s in (192, 512):
        render_mark(s, rounded=False, bleed_scale=0.72, supersample=6) \
            .save(OUT / f"maskable-{s}.png", format="PNG", optimize=True)
        generated.append(f"maskable-{s}.png")

    # 透明背景标记（用于深色底/文档）
    render_mark(512, background=False, simplified=False, supersample=6) \
        .save(OUT / "brand/logo-glyph-512.png", format="PNG", optimize=True)
    generated.append("brand/logo-glyph-512.png")

    # OG 分享图
    render_og().save(OUT / "og-image.png", format="PNG", optimize=True)
    generated.append("og-image.png")

    print("Generated {} assets in {}".format(len(generated), OUT))
    for g in generated:
        p = OUT / g
        print("  {:<28} {:>8,} bytes".format(g, p.stat().st_size))


if __name__ == "__main__":
    main()
