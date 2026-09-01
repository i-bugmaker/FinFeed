#!/usr/bin/env python3
"""快讯展开面板可视化校验：点击标题 → 截图展开态（亮/暗）。

用法: python web/scripts/shoot_flash_expand.py [--base http://127.0.0.1:5199]
"""
import argparse
import os
import sys

BASE_DEFAULT = "http://127.0.0.1:5199"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default=BASE_DEFAULT)
    args = ap.parse_args()

    here = os.path.dirname(os.path.abspath(__file__))
    outdir = os.path.normpath(os.path.join(here, "..", "..", "docs", "shots"))
    os.makedirs(outdir, exist_ok=True)

    from playwright.sync_api import sync_playwright

    errors = []
    with sync_playwright() as p:
        browser = p.chromium.launch()
        for theme in ("light", "dark"):
            page = browser.new_page(viewport={"width": 1440, "height": 1000})
            page.on("console", lambda m: errors.append(f"[console.{m.type}] {m.text}")
                    if m.type == "error" else None)
            page.on("pageerror", lambda e: errors.append(f"[pageerror] {e}"))

            # SSE 长连接会让 networkidle 永不触发，改用 domcontentloaded + 选择器等待
            page.goto(f"{args.base}/#/flash", wait_until="domcontentloaded")
            page.wait_for_selector(".ff-newsrow__headbtn", timeout=30000)
            page.wait_for_timeout(1200)

            # 切换主题
            page.evaluate(
                "t => document.documentElement.setAttribute('data-theme', t)", theme
            )
            page.wait_for_timeout(300)

            # 展开前两条，并等待各自正文加载完成（骨架屏消失）
            btns = page.locator(".ff-newsrow__headbtn")
            n = min(btns.count(), 2)
            for i in range(n):
                btns.nth(i).click()
                try:
                    page.wait_for_selector(".nr-panel__text", timeout=6000)
                except Exception:
                    pass
                page.wait_for_timeout(400)

            page.wait_for_timeout(500)

            # 面板存在性与几何校验
            panels = page.locator(".nr-panel")
            print(f"[{theme}] 展开面板数 = {panels.count()}")
            if panels.count():
                box = panels.first.bounding_box()
                title = page.locator(".ff-newsrow__row").first.bounding_box()
                print(f"[{theme}] 面板 box = {box}")
                print(f"[{theme}] 首行 box = {title}")
                left_delta = (box or {}).get("x", 0) - (title or {}).get("x", 0)
                print(f"[{theme}] 面板相对行左侧偏移 = {left_delta:.1f}px")

            out = os.path.join(outdir, f"flash_expand_{theme}.png")
            page.screenshot(path=out, full_page=False)
            print(f"[{theme}] 截图 -> {out}")
            page.close()
        browser.close()

    if errors:
        print("\n[!] 控制台错误:")
        for e in errors[:20]:
            print("   ", e)
        sys.exit(1)
    print("\n[ok] 无控制台错误")


if __name__ == "__main__":
    main()
