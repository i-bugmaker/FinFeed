#!/usr/bin/env python3
"""对 FinFeed Web 前端做真实渲染截图，用于可视化 UI 审查。

用项目自带的 Playwright Chromium（无需额外下载）。
分别采集亮色与暗色主题，用于验证深色模式落地情况。

用法: python web/scripts/shoot_ui.py [--base http://127.0.0.1:5199]
输出: web/../docs/shots/*.png
"""
import argparse
import os
import sys

PAGES = [
    ("flash", "#/flash", "快讯"),
    ("market", "#/market", "全景行情"),
    ("ai", "#/ai", "AI 投研工作台"),
    ("dashboard", "#/dashboard", "仪表盘"),
    ("styleguide", "#/styleguide", "设计规范"),
]

THEMES = [("light", "亮色"), ("dark", "暗色")]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="http://127.0.0.1:5199")
    ap.add_argument("--width", type=int, default=1440)
    ap.add_argument("--height", type=int, default=900)
    ap.add_argument("--only", default="", help="仅采集指定主题 light|dark")
    args = ap.parse_args()

    here = os.path.dirname(os.path.abspath(__file__))
    outdir = os.path.normpath(os.path.join(here, "..", "..", "docs", "shots"))
    os.makedirs(outdir, exist_ok=True)

    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print("[!] 未安装 playwright，跳过可视化采集", file=sys.stderr)
        return 1

    shots = []
    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        for theme, tlabel in THEMES:
            if args.only and theme != args.only:
                continue
            ctx = browser.new_context(
                viewport={"width": args.width, "height": args.height},
                device_scale_factor=1,
            )
            # 通过 localStorage 预置主题，与 store/app.js 的 THEME_KEY 保持一致
            ctx.add_init_script(
                f"try{{localStorage.setItem('finfeed_theme','{theme}')}}catch(e){{}}"
            )
            page = ctx.new_page()
            for slug, route, label in PAGES:
                url = f"{args.base}/{route}"
                try:
                    page.goto(url, wait_until="domcontentloaded", timeout=20000)
                    page.wait_for_timeout(2500)  # 等 Vue 挂载与骨架屏切换
                    name = f"{slug}-{theme}.png"
                    path = os.path.join(outdir, name)
                    page.screenshot(path=path)
                    shots.append((name, f"{label} · {tlabel}"))
                    print(f"  ✓ {name:<28} {label} · {tlabel}")
                except Exception as e:
                    print(f"  ✗ {slug}-{theme}: {type(e).__name__} {str(e)[:80]}")
            ctx.close()
        browser.close()

    print(f"\n共 {len(shots)} 张，输出目录: {outdir}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
