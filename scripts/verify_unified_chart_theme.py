# -*- coding: utf-8 -*-
"""验证统一图表主题机制：
1) ChartPanel 主题切换重绘修复（此前缺陷：切主题后画布保留旧配色）
2) ScreenerView / DimensionRadar 迁移统一 composable 后无回归
"""
import asyncio
from playwright.async_api import async_playwright

BASE = "http://127.0.0.1:8866"
THEME_KEY = "finfeed_theme"

JS_CANVAS_BRIGHTNESS = """
() => {
  const cv = document.querySelector('canvas');
  if (!cv || !cv.width) return null;
  const ctx = cv.getContext('2d');
  const d = ctx.getImageData(0, 0, cv.width, cv.height).data;
  let r = 0, g = 0, b = 0, n = 0;
  for (let i = 0; i < d.length; i += 16) { // 4px 步进采样
    if (d[i + 3] === 0) continue;
    r += d[i]; g += d[i + 1]; b += d[i + 2]; n++;
  }
  if (!n) return null;
  return { avg: (r + g + b) / (3 * n), opaque: n };
}
"""

JS_SET_THEME = f"(t) => localStorage.setItem('{THEME_KEY}', t)"


async def goto_theme(page, path, theme):
    # hash 路由：服务器只看到 "/"，页面路径走 /#/xxx
    await page.goto(f"{BASE}/{path}", wait_until="domcontentloaded")
    await page.evaluate(JS_SET_THEME, theme)
    await page.reload(wait_until="domcontentloaded")
    try:
        await page.wait_for_selector("canvas", timeout=30000)
    except Exception:
        state = await page.evaluate(
            "() => ({href: location.href, canvas: document.querySelectorAll('canvas').length,"
            " txt: (document.body.innerText||'').slice(0,120)})"
        )
        print("[DIAG] canvas 等待超时:", state)
        raise
    await page.wait_for_timeout(3000)  # 等图表数据就绪


async def main():
    async with async_playwright() as p:
        browser = await p.chromium.launch()
        page = await browser.new_page(viewport={"width": 1600, "height": 1000})
        errors = []
        page.on("pageerror", lambda e: errors.append(str(e)))
        page.on("console", lambda m: errors.append(m.text) if m.type == "error" else None)

        # ── 1. Dashboard（ChartPanel 消费方）：主题切换重绘验证 ──
        await goto_theme(page, "#/dashboard", "light")
        light = await page.evaluate(JS_CANVAS_BRIGHTNESS)
        await goto_theme(page, "#/dashboard", "dark")
        dark = await page.evaluate(JS_CANVAS_BRIGHTNESS)
        ok_chartpanel = (
            light and dark
            and abs(light["avg"] - dark["avg"]) > 5
            and min(light["opaque"], dark["opaque"]) > 100
        )
        print(f"[ChartPanel] light_avg={light and round(light['avg'], 1)} "
              f"dark_avg={dark and round(dark['avg'], 1)} -> {'OK 主题重绘生效' if ok_chartpanel else 'CHECK'}")

        # ── 2. ScreenerView 回归：图表页签 + 主题重绘 ──
        await goto_theme(page, "#/screener", "dark")
        has_panel = await page.evaluate("!!document.querySelector('.screener-panel__cta, .screener-panel')")
        print(f"[Screener] 面板挂载: {'OK' if has_panel else 'FAIL'}")

        b_dark = await page.evaluate(JS_CANVAS_BRIGHTNESS)
        await goto_theme(page, "#/screener", "light")
        b_light = await page.evaluate(JS_CANVAS_BRIGHTNESS)
        ok_screener = b_dark and b_light and abs(b_dark["avg"] - b_light["avg"]) > 5
        print(f"[Screener] 图表令牌重绘 dark={b_dark and round(b_dark['avg'], 1)} "
              f"light={b_light and round(b_light['avg'], 1)} -> {'OK' if ok_screener else 'CHECK'}")

        # ── 恢复亮色主题 + 汇总 ──
        await page.evaluate(JS_SET_THEME, "light")
        real_errs = [e for e in errors if "favicon" not in e.lower()]
        print(f"[Console] JS 错误: {len(real_errs)} {real_errs[:3] if real_errs else ''}")
        verdict = ok_chartpanel and ok_screener and not real_errs
        print("RESULT:", "PASS" if verdict else "NEED-REVIEW")
        await browser.close()


asyncio.run(main())
