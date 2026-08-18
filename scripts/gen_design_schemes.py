# -*- coding: utf-8 -*-
"""
FinFeed 视觉参考方案生成器
为 FinFeed 仪表盘生成 10 套风格迥异、可直接在浏览器预览的独立 HTML 设计方案，
每套包含：统一仪表盘样机 + 四要素设计说明（布局 / 外观 / 字体 / 组件）。
同时生成 index.html 对比画廊。
"""

import os

OUT_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "design-schemes")
os.makedirs(OUT_DIR, exist_ok=True)

# ---------------------------------------------------------------------------
# 图标（24x24 描边 path，复用 FinFeed 设计系统的矢量图标理念）
# ---------------------------------------------------------------------------
ICONS = {
    "dashboard": "M4 4h7v7H4zM13 4h7v7h-7zM4 13h7v7H4zM13 13h7v7h-7z",
    "flash": "M13 2 4 14h6l-1 8 9-12h-6z",
    "articles": "M6 2h9l5 5v15H6zM14 2v6h6",
    "market": "M3 3v18h18 M7 14l4-4 3 3 5-6",
    "sentiment": "M3 12h4l3 8 4-16 3 8h4",
    "calendar": "M4 5h16v16H4zM4 9h16M8 3v4M16 3v4",
    "favorites": "M12 3l2.9 6 6.6.9-4.8 4.6 1.2 6.5L12 18l-5.9 3 1.2-6.5L2.5 9.9 9.1 9z",
    "ai": "M12 2l2 6 6 2-6 2-2 6-2-6-6-2 6-2z",
    "search": "M11 4a7 7 0 1 0 0 14 7 7 0 0 0 0-14zM21 21l-5-5",
    "bell": "M18 8a6 6 0 1 0-12 0c0 7-3 9-3 9h18s-3-2-3-9zM13.7 21a2 2 0 0 1-3.4 0",
}
NAV = [
    ("dashboard", "仪表盘", True),
    ("flash", "快讯", False),
    ("articles", "财经", False),
    ("market", "市场", False),
    ("sentiment", "舆情", False),
    ("calendar", "日历", False),
    ("favorites", "收藏", False),
    ("ai", "AI 分析", False),
]

# ---------------------------------------------------------------------------
# 共享组件样式（使用 CSS 变量，自动随主题变化）
# ---------------------------------------------------------------------------
SHARED_CSS = """
*{box-sizing:border-box;margin:0;padding:0}
html,body{height:100%}
body{
  font-family:var(--font-body);
  background:var(--bg-canvas);
  color:var(--text-primary);
  -webkit-font-smoothing:antialiased;
  font-synthesis:none;
  line-height:1.5;
}
a{color:inherit}
.ff-app{display:flex;min-height:100vh}
/* 侧边栏 */
.ff-sidebar{width:250px;flex:0 0 250px;background:var(--bg-sidebar,var(--bg-surface));
  border-right:1px solid var(--border);padding:22px 15px;display:flex;flex-direction:column;
  position:sticky;top:0;height:100vh}
.ff-brand{display:flex;align-items:center;gap:11px;padding:4px 9px 18px}
.ff-logo{width:38px;height:38px;border-radius:11px;background:var(--brand);display:grid;
  place-items:center;color:#fff;flex:0 0 auto}
.ff-logo svg{width:22px;height:22px}
.ff-word{font-family:var(--font-display);font-weight:700;font-size:18px;letter-spacing:-.02em;line-height:1.05}
.ff-word small{display:block;font-family:var(--font-body);font-weight:600;font-size:10px;
  letter-spacing:.16em;text-transform:uppercase;color:var(--text-tertiary);margin-top:3px}
.ff-nav{display:flex;flex-direction:column;gap:3px;margin-top:4px}
.ff-nav a{display:flex;align-items:center;gap:11px;padding:10px 12px;border-radius:var(--radius);
  color:var(--text-secondary);text-decoration:none;font-size:14px;font-weight:500;transition:.16s}
.ff-nav a svg{width:19px;height:19px;opacity:.85;flex:0 0 auto}
.ff-nav a:hover{background:var(--brand-soft);color:var(--text-primary)}
.ff-nav a.active{background:var(--brand-soft);color:var(--brand-strong);font-weight:600}
.ff-nav a.active svg{opacity:1;color:var(--brand)}
.ff-side-foot{margin-top:auto;font-size:11.5px;color:var(--text-tertiary);padding:12px;
  line-height:1.6;border-top:1px solid var(--border)}
/* 顶栏 */
.ff-main{flex:1;min-width:0;display:flex;flex-direction:column}
.ff-topbar{position:sticky;top:0;z-index:5;display:flex;align-items:center;gap:16px;
  padding:14px 26px;background:var(--bg-topbar,var(--bg-surface));border-bottom:1px solid var(--border)}
.ff-search{flex:1;max-width:440px;display:flex;align-items:center;gap:9px;background:var(--bg-canvas);
  border:1px solid var(--border);border-radius:10px;padding:9px 13px;color:var(--text-tertiary)}
.ff-search input{border:none;background:none;outline:none;flex:1;font-size:14px;
  color:var(--text-primary);font-family:var(--font-body)}
.ff-search svg{width:17px;height:17px;flex:0 0 auto}
.ff-top-meta{margin-left:auto;display:flex;align-items:center;gap:14px}
.ff-live{display:flex;align-items:center;gap:7px;font-size:12.5px;font-weight:700;color:var(--up);
  background:var(--brand-soft);padding:7px 13px;border-radius:999px}
.ff-live .dot{width:8px;height:8px;border-radius:50%;background:var(--up);
  animation:pulse 1.8s infinite}
.ff-avatar{width:34px;height:34px;border-radius:50%;background:var(--brand);color:#fff;
  display:grid;place-items:center;font-weight:700;font-size:13px}
.ff-date{font-size:12.5px;color:var(--text-secondary);font-family:var(--font-mono)}
/* 内容 */
.ff-content{padding:26px;display:flex;flex-direction:column;gap:22px;max-width:1280px;
  width:100%;margin:0 auto}
.ff-hero{display:flex;align-items:flex-end;justify-content:space-between;gap:20px;flex-wrap:wrap}
.ff-hero h1{font-family:var(--font-display);font-size:28px;font-weight:700;letter-spacing:-.02em}
.ff-hero p{color:var(--text-secondary);font-size:14px;margin-top:6px;max-width:560px}
.ff-chips{display:flex;gap:8px;flex-wrap:wrap}
.ff-chip{font-size:12px;font-weight:600;padding:6px 12px;border-radius:999px;
  background:var(--brand-soft);color:var(--brand-strong)}
/* 指标卡 */
.ff-stats{display:grid;grid-template-columns:repeat(5,1fr);gap:14px}
.ff-stat{background:var(--bg-surface);border:1px solid var(--border);border-radius:var(--radius-lg);
  padding:16px 17px;transition:.18s}
.ff-stat:hover{transform:translateY(-2px);box-shadow:var(--shadow-md)}
.ff-stat .lbl{font-size:12px;color:var(--text-tertiary);font-weight:600;letter-spacing:.02em}
.ff-stat .val{font-family:var(--font-mono);font-size:23px;font-weight:600;margin-top:8px;
  letter-spacing:-.01em;font-variant-numeric:tabular-nums}
.ff-stat .chg{font-family:var(--font-mono);font-size:13px;font-weight:600;margin-top:5px}
.up{color:var(--up)} .down{color:var(--down)} .neu{color:var(--neutral)}
/* 双列 */
.ff-cols{display:grid;grid-template-columns:1.45fr 1fr;gap:18px}
.ff-card{background:var(--bg-surface);border:1px solid var(--border);border-radius:var(--radius-lg);
  padding:18px 20px}
.ff-card h2{font-family:var(--font-display);font-size:16px;font-weight:700;display:flex;
  align-items:center;gap:9px;margin-bottom:14px}
.ff-card h2 .sub{font-family:var(--font-body);font-weight:500;font-size:12px;
  color:var(--text-tertiary);margin-left:auto}
/* 快讯 */
.ff-news{display:flex;flex-direction:column}
.ff-news-item{display:flex;gap:13px;padding:13px 4px;border-bottom:1px solid var(--border)}
.ff-news-item:last-child{border-bottom:none}
.ff-time{font-family:var(--font-mono);font-size:12px;color:var(--text-tertiary);flex:0 0 46px;padding-top:1px}
.ff-news-body{flex:1;min-width:0}
.ff-news-src{font-size:12px;font-weight:600;color:var(--brand-strong);display:flex;align-items:center;gap:7px}
.ff-news-txt{font-size:14px;color:var(--text-primary);margin-top:4px;line-height:1.55}
.ff-news-txt b{font-weight:700}
.ff-tag{font-size:11px;font-weight:700;padding:3px 9px;border-radius:6px;flex:0 0 auto;
  align-self:flex-start;margin-top:2px}
.ff-tag.up{background:color-mix(in srgb,var(--up) 15%,transparent);color:var(--up)}
.ff-tag.down{background:color-mix(in srgb,var(--down) 15%,transparent);color:var(--down)}
.ff-tag.neu{background:color-mix(in srgb,var(--neutral) 16%,transparent);color:var(--neutral)}
/* 涨停板 */
.ff-limit{display:flex;flex-direction:column}
.ff-limit-row{display:flex;align-items:center;gap:10px;padding:9px 4px;border-bottom:1px solid var(--border)}
.ff-limit-row:last-child{border-bottom:none}
.ff-limit-name{font-size:14px;font-weight:600;flex:0 0 86px}
.ff-limit-name small{display:block;font-family:var(--font-mono);font-size:11px;
  color:var(--text-tertiary);font-weight:500}
.ff-limit-reason{font-size:12.5px;color:var(--text-secondary);flex:1;line-height:1.4}
.ff-limit-px{font-family:var(--font-mono);font-size:13px;font-weight:600;color:var(--up)}
.ff-badge{font-size:10.5px;font-weight:700;padding:2px 7px;border-radius:5px;
  background:var(--brand-soft);color:var(--brand-strong);white-space:nowrap}
.ff-badge.weak{background:color-mix(in srgb,var(--down) 15%,transparent);color:var(--down)}
/* 图表 */
.ff-chart svg{width:100%;height:178px;display:block}
.ff-legend{display:flex;gap:18px;font-size:12px;color:var(--text-secondary);margin-top:10px}
.ff-legend i{display:inline-block;width:10px;height:10px;border-radius:3px;margin-right:6px;vertical-align:-1px}
/* 设计说明 */
.ff-spec{margin-top:6px}
.ff-spec > h3{font-family:var(--font-display);font-size:18px;font-weight:700;margin-bottom:14px;
  display:flex;align-items:center;gap:9px}
.ff-spec-grid{display:grid;grid-template-columns:repeat(2,1fr);gap:14px}
.ff-spec-card{background:var(--bg-surface);border:1px solid var(--border);border-radius:var(--radius-lg);
  padding:16px 18px}
.ff-spec-card .k{font-size:11.5px;font-weight:700;letter-spacing:.06em;text-transform:uppercase;
  color:var(--brand-strong);display:flex;align-items:center;gap:8px;margin-bottom:9px}
.ff-spec-card p{font-size:13.5px;color:var(--text-secondary);line-height:1.68}
.ff-spec-card p+p{margin-top:8px}
@keyframes pulse{0%{box-shadow:0 0 0 0 color-mix(in srgb,var(--up) 55%,transparent)}
  70%{box-shadow:0 0 0 7px transparent}100%{box-shadow:0 0 0 0 transparent}}
@media(max-width:980px){.ff-stats{grid-template-columns:repeat(2,1fr)}
  .ff-cols{grid-template-columns:1fr}.ff-sidebar{display:none}}
@media(max-width:780px){.ff-spec-grid{grid-template-columns:1fr}}
"""

# ---------------------------------------------------------------------------
# 10 套方案定义
# ---------------------------------------------------------------------------
SCHEMES = [
    {
        "id": "01-minimal-pro",
        "cn": "极简专业", "en": "Minimal Pro", "tag": "克制留白 · 数据优先 · 类 Linear / Vercel",
        "fonts": ["Inter", "JetBrains Mono"],
        "tokens": {
            "--bg-canvas": "#f7f8fa", "--bg-surface": "#ffffff", "--bg-sidebar": "#ffffff",
            "--bg-topbar": "#ffffff",
            "--text-primary": "#0f172a", "--text-secondary": "#475569", "--text-tertiary": "#94a3b8",
            "--border": "#e6e8ec",
            "--brand": "#2563eb", "--brand-strong": "#1d4ed8", "--brand-soft": "#eff4ff",
            "--up": "#e5484d", "--down": "#12a150", "--neutral": "#94a3b8", "--accent": "#2563eb",
            "--radius": "10px", "--radius-lg": "14px",
            "--shadow-md": "0 6px 20px -10px rgba(15,23,42,.18)",
            "--font-display": "'Inter',sans-serif",
            "--font-body": "'Inter',-apple-system,'PingFang SC','Microsoft YaHei',sans-serif",
            "--font-mono": "'JetBrains Mono',ui-monospace,monospace",
        },
        "css": "",
        "desc": {
            "layout": "桌面端固定 250px 左侧导航 + 顶部全局搜索栏，主体采用 1280px 居中内容流。信息层级为：指标卡一行（5 列）→ 快讯/涨停板双列（1.45:1）→ 情绪趋势图 → 设计说明。严格遵循 8pt 栅格，组件间距统一 14–22px。",
            "look": "浅灰画布 + 纯白卡片，cobalt 蓝作为唯一品牌色，红涨绿跌语义色严格遵循 A 股惯例。阴影克制（单层柔光），无渐变、无装饰，依靠间距与字重建立层级，整体冷静、专业、可信。",
            "type": "西文 Inter（含 JetBrains Mono 等宽数字），CJK 回退苹方/雅黑。数字统一 tabular-nums 对齐，字号 1.2 模数刻度，标题 700、正文 400，对比清晰。",
            "comp": "按钮/输入/标签全自绘，4 态齐全；指标卡 hover 微抬升；快讯用时间轴 + 来源徽标；标签用 15% 透明度语义底色。整体组件密度偏高但以留白缓冲，适合长时间盯盘。",
        },
    },
    {
        "id": "02-midnight-terminal",
        "cn": "深空终端", "en": "Midnight Terminal", "tag": "近黑底色 · 霓虹青绿 · 高密度数据终端",
        "fonts": ["Inter", "JetBrains Mono"],
        "tokens": {
            "--bg-canvas": "#0b0e14", "--bg-surface": "#121722", "--bg-sidebar": "#0e131c",
            "--bg-topbar": "#0e131c",
            "--text-primary": "#e6edf3", "--text-secondary": "#9aa7b8", "--text-tertiary": "#5b6675",
            "--border": "#232b3a",
            "--brand": "#2dd4bf", "--brand-strong": "#14b8a6", "--brand-soft": "#0e2a28",
            "--up": "#ff5c63", "--down": "#2ee6a0", "--neutral": "#5b6675", "--accent": "#2dd4bf",
            "--radius": "6px", "--radius-lg": "9px",
            "--shadow-md": "0 8px 24px -10px rgba(0,0,0,.6)",
            "--font-display": "'JetBrains Mono',monospace",
            "--font-body": "'Inter',-apple-system,'PingFang SC',sans-serif",
            "--font-mono": "'JetBrains Mono',ui-monospace,monospace",
        },
        "css": """
.ff-logo{box-shadow:0 0 18px color-mix(in srgb,var(--brand) 55%,transparent)}
.ff-nav a{font-family:var(--font-mono);font-size:13px}
.ff-stat .val{font-size:22px}
.ff-live{color:var(--up)}
.ff-word{letter-spacing:.01em}
body{font-feature-settings:"tnum"}
.ff-card h2,.ff-hero h1,.ff-spec h3{color:#fff}
""",
        "desc": {
            "layout": "固定左侧导航 + 顶栏与极简专业一致，但信息密度更高：指标卡 5 列紧凑排布，快讯/涨停板双列，情绪图占满整行。面向「一屏看全市场」的盯盘场景，滚动更少、读数更快。",
            "look": "近黑 #0b0e14 画布，表面微提亮形成层次；teal 青绿为品牌与强调色，叠加红色上涨荧光。数字发光、细描边、低饱和背景，营造 Bloomberg / TradingView 暗色终端的精密感。",
            "type": "以 JetBrains Mono 等宽字体主导（导航、数字、标签），正文用 Inter 保证可读性。等宽确保列对齐，配合 tabular-nums，价格与涨跌幅呈严格网格。",
            "comp": "组件去装饰化：卡片仅细边框 + 微阴影；live 状态点带脉冲；标签用透明度底色。hover 不位移、仅亮度变化，避免暗色下抖动。整体为「信息即界面」的硬核数据风。",
        },
    },
    {
        "id": "03-private-wealth",
        "cn": "奢华私行", "en": "Private Wealth", "tag": "墨绿金箔 · 衬线标题 · 高端私人银行",
        "fonts": ["Playfair Display", "Noto Serif SC", "Inter", "JetBrains Mono"],
        "tokens": {
            "--bg-canvas": "#0c1a16", "--bg-surface": "#0f241d", "--bg-sidebar": "#0a1712",
            "--bg-topbar": "#0a1712",
            "--text-primary": "#f3ede0", "--text-secondary": "#b9c4b6", "--text-tertiary": "#7d8a7f",
            "--border": "#1f3a30",
            "--brand": "#c9a24b", "--brand-strong": "#d8b35e", "--brand-soft": "#1c3329",
            "--up": "#e35d5b", "--down": "#3fb27f", "--neutral": "#7d8a7f", "--accent": "#c9a24b",
            "--radius": "8px", "--radius-lg": "11px",
            "--shadow-md": "0 10px 30px -12px rgba(0,0,0,.5)",
            "--font-display": "'Playfair Display',serif",
            "--font-body": "'Noto Serif SC','Songti SC','SimSun','Inter',serif",
            "--font-mono": "'JetBrains Mono',ui-monospace,monospace",
        },
        "css": """
.ff-card,.ff-sidebar,.ff-stat{border:1px solid color-mix(in srgb,var(--brand) 28%,var(--border))}
.ff-topbar,.ff-sidebar{border-color:color-mix(in srgb,var(--brand) 22%,transparent)}
.ff-card h2,.ff-hero h1,.ff-spec h3,.ff-word{font-family:var(--font-display)}
.ff-logo{border-radius:9px}
.ff-word{font-weight:700}
""",
        "desc": {
            "layout": "固定左侧导航 + 顶栏，主体居中 1180px 以更大留白凸显尊贵感。指标卡 5 列、双列内容、图表，结构与极简专业一致，但内边距更大、节奏更舒缓，强调「少而精」。",
            "look": "墨绿 #0c1a16 画布配金箔 #c9a24b 品牌色，红涨绿跌略降饱和以契合暗调；金色仅作发丝级描边与强调，营造私人银行 / 家族办公室的低调奢华。大留白 + 衬线营造编辑级质感。",
            "type": "标题与品牌用 Playfair Display 衬线，CJK 用思源宋体回退；正文宋体增强书卷气，数字仍用 JetBrains Mono 保证精确。衬线 + 等宽的混排制造「古典权威 + 现代精确」反差。",
            "comp": "卡片以金色细描边替代阴影，按钮描边金边；标签用低透明语义色。组件克制、无圆角夸张，hover 仅金边微亮。整体沉稳、权威，适合高净值客户终端。",
        },
    },
    {
        "id": "04-organic-calm",
        "cn": "清新自然", "en": "Organic Calm", "tag": "暖白森林绿 · 大圆角 · 柔和亲和",
        "fonts": ["Quicksand", "Noto Sans SC", "JetBrains Mono"],
        "tokens": {
            "--bg-canvas": "#fbfaf7", "--bg-surface": "#ffffff", "--bg-sidebar": "#ffffff",
            "--bg-topbar": "#ffffff",
            "--text-primary": "#23332b", "--text-secondary": "#5c6b60", "--text-tertiary": "#9aa89c",
            "--border": "#ece8df",
            "--brand": "#2f7d5b", "--brand-strong": "#245f46", "--brand-soft": "#e7f1eb",
            "--up": "#e2605c", "--down": "#16a36a", "--neutral": "#9aa89c", "--accent": "#2f7d5b",
            "--radius": "13px", "--radius-lg": "24px",
            "--shadow-md": "0 16px 36px -20px rgba(35,51,43,.22)",
            "--font-display": "'Quicksand',sans-serif",
            "--font-body": "'Noto Sans SC','PingFang SC','Microsoft YaHei',sans-serif",
            "--font-mono": "'JetBrains Mono',ui-monospace,monospace",
        },
        "css": """
.ff-stat:hover,.ff-card{box-shadow:0 18px 40px -22px color-mix(in srgb,var(--brand) 42%,transparent)}
.ff-logo{border-radius:13px}
.ff-tag.up,.ff-tag.down,.ff-tag.neu{border-radius:8px}
.ff-word{font-weight:700}
""",
        "desc": {
            "layout": "固定左侧导航 + 顶栏，主体居中 1280px。结构同极简专业，但卡片圆角放大至 24px、留白更松，整体呼吸感强，降低盯盘疲劳。指标卡 5 列 → 双列 → 图表。",
            "look": "暖白 #fbfaf7 画布 + 纯白卡片，森林绿为品牌色，红涨绿跌自然调和。大圆角 + 长投影（低透明）带来柔软、有机的触感，亲和而不失专业，适合大众投资者与长时阅读。",
            "type": "标题 Quicksand 圆体、CJK 思源黑体，数字 JetBrains Mono。圆体字形 + 大圆角形成统一的柔和语言，字重对比温和（600/400）。",
            "comp": "组件以圆角与柔影定义，无硬边；标签圆角胶囊；按钮品牌绿填充、hover 微抬升。整体像「有温度的金融工具」，弱化交易紧张感。",
        },
    },
    {
        "id": "05-apple-frost",
        "cn": "苹果磨砂", "en": "Apple Frost", "tag": "iOS 灰白 · 毛玻璃 · 系统级质感",
        "fonts": ["Inter", "JetBrains Mono"],
        "tokens": {
            "--bg-canvas": "#f2f2f7", "--bg-surface": "#ffffff", "--bg-sidebar": "rgba(255,255,255,.72)",
            "--bg-topbar": "rgba(255,255,255,.72)",
            "--text-primary": "#1c1c1e", "--text-secondary": "#6b6b70", "--text-tertiary": "#aeaeb2",
            "--border": "rgba(0,0,0,.08)",
            "--brand": "#007aff", "--brand-strong": "#0062cc", "--brand-soft": "#e8f1ff",
            "--up": "#ff3b30", "--down": "#34c759", "--neutral": "#8e8e93", "--accent": "#ff9500",
            "--radius": "14px", "--radius-lg": "18px",
            "--shadow-md": "0 10px 30px -16px rgba(0,0,0,.12)",
            "--font-display": "'Inter',-apple-system,sans-serif",
            "--font-body": "-apple-system,'PingFang SC','Microsoft YaHei','Inter',sans-serif",
            "--font-mono": "'JetBrains Mono','SF Mono',ui-monospace,monospace",
        },
        "css": """
body{background:linear-gradient(180deg,#f2f2f7,#eef0f5)}
.ff-sidebar,.ff-topbar{backdrop-filter:blur(20px);-webkit-backdrop-filter:blur(20px)}
.ff-card,.ff-stat{background:rgba(255,255,255,.8);backdrop-filter:blur(14px);
  -webkit-backdrop-filter:blur(14px);border:1px solid rgba(0,0,0,.06)}
.ff-search{background:rgba(120,120,128,.10);border-color:transparent}
.ff-logo{border-radius:13px}
""",
        "desc": {
            "layout": "结构同极简专业，但侧栏与顶栏采用磨砂玻璃浮层，主体居中 1280px。iOS 风格分段与卡片节奏，强调系统一致性，适合以 Safari / App 形态嵌入。",
            "look": "浅灰白 #f2f2f7 渐变画布，表面以 80% 白 + 毛玻璃模糊呈现；蓝 #007aff、绿 #34c759、橙 #ff9500 为系统语义色，红涨 #ff3b30 绿跌 #34c759 遵循 A 股。细腻、克制、像原生系统。",
            "type": "优先系统字体（-apple-system / 苹方），西文 Inter 兜底，数字 JetBrains Mono。与 iOS 排版一致，字距微调、行高舒适。",
            "comp": "组件即 iOS 控件：圆角 14–18px、半透明磨砂、细描边。按钮填充蓝、标签语义色胶囊。整体「无需学习」的系统级熟悉感。",
        },
    },
    {
        "id": "06-lavender-creative",
        "cn": "薰衣草创想", "en": "Lavender Creative", "tag": "紫调渐变 · 年轻 SaaS · 创意工具感",
        "fonts": ["Space Grotesk", "Inter", "JetBrains Mono"],
        "tokens": {
            "--bg-canvas": "#f6f5ff", "--bg-surface": "#ffffff", "--bg-sidebar": "#ffffff",
            "--bg-topbar": "#ffffff",
            "--text-primary": "#1d1b2e", "--text-secondary": "#55506e", "--text-tertiary": "#9b95b5",
            "--border": "#ece9f7",
            "--brand": "#7b61ff", "--brand-strong": "#5b3fe0", "--brand-soft": "#efeaff",
            "--up": "#e5484d", "--down": "#16a36a", "--neutral": "#9b95b5", "--accent": "#7b61ff",
            "--radius": "16px", "--radius-lg": "18px",
            "--shadow-md": "0 10px 26px -12px rgba(43,33,90,.20)",
            "--font-display": "'Space Grotesk',sans-serif",
            "--font-body": "'Inter',-apple-system,'PingFang SC',sans-serif",
            "--font-mono": "'JetBrains Mono',ui-monospace,monospace",
        },
        "css": """
.ff-logo{background:linear-gradient(135deg,var(--brand),#a78bfa)}
.ff-chip{background:linear-gradient(135deg,var(--brand-soft),#f3eaff)}
.ff-nav a.active{background:linear-gradient(135deg,var(--brand-soft),#efeaff)}
.ff-word{font-weight:700}
""",
        "desc": {
            "layout": "结构同极简专业，指标卡 5 列 → 双列 → 图表。圆角放大、间距轻快，配合渐变强调，整体节奏偏向创意协作工具（Notion / Framer）。",
            "look": "浅薰衣草 #f6f5ff 画布，品牌紫 #7b61ff 配青色辅色；logo 与激活态用紫调渐变，红涨绿跌保持。年轻、活力、有想象力，弱化金融的冷硬。",
            "type": "标题 Space Grotesk（几何感强），正文 Inter，数字 JetBrains Mono。几何无衬线 + 等宽形成现代创意产品的标识性排版。",
            "comp": "logo/激活态/标签用渐变填充；按钮主操作为紫渐变；卡片白底柔阴影。组件轻量、圆润，hover 微动效，传递「好用又好看」的产品气质。",
        },
    },
    {
        "id": "07-coral-energy",
        "cn": "珊瑚活力", "en": "Coral Energy", "tag": "珊瑚红 · 奶油暖底 · 编辑型活力",
        "fonts": ["Outfit", "Inter", "JetBrains Mono"],
        "tokens": {
            "--bg-canvas": "#fff8f3", "--bg-surface": "#ffffff", "--bg-sidebar": "#ffffff",
            "--bg-topbar": "#ffffff",
            "--text-primary": "#2a1d18", "--text-secondary": "#7a6458", "--text-tertiary": "#b39c8f",
            "--border": "#f3e3d8",
            "--brand": "#ff5a5f", "--brand-strong": "#e84347", "--brand-soft": "#ffe9e7",
            "--up": "#ff5a5f", "--down": "#2bb673", "--neutral": "#b39c8f", "--accent": "#ff9f43",
            "--radius": "14px", "--radius-lg": "18px",
            "--shadow-md": "0 12px 28px -14px rgba(122,60,40,.20)",
            "--font-display": "'Outfit',sans-serif",
            "--font-body": "'Inter',-apple-system,'PingFang SC',sans-serif",
            "--font-mono": "'JetBrains Mono',ui-monospace,monospace",
        },
        "css": """
.ff-logo{background:linear-gradient(135deg,var(--brand),#ff8a5b)}
.ff-chip{background:var(--brand-soft)}
.ff-word{font-weight:700}
.ff-stat .chg.up{color:var(--up)}
""",
        "desc": {
            "layout": "结构同极简专业，奶油暖底 + 大圆角，信息密度适中。指标卡 5 列 → 双列 → 图表，节奏明快，适合面向个人投资者的轻财经媒体形态。",
            "look": "奶油 #fff8f3 画布，珊瑚红 #ff5a5f 品牌色配暖橙辅色；红涨绿跌中上涨用品牌珊瑚红，下跌用自然绿。温暖、有能量、低距离感，类似 Robinhood 的亲和金融。",
            "type": "标题 Outfit（圆润几何无衬线），正文 Inter，数字 JetBrains Mono。圆润字形呼应暖色调，整体轻快易读。",
            "comp": "logo/主按钮珊瑚渐变；标签语义色胶囊；卡片白底暖阴影。hover 微抬升，动效活泼。传达「理财也可以很轻松」的情绪价值。",
        },
    },
    {
        "id": "08-soft-neumorphism",
        "cn": "新拟态", "en": "Soft Neumorphism", "tag": "浅灰同色 · 凹凸柔影 · 硬件仪表板",
        "fonts": ["Poppins", "Inter", "JetBrains Mono"],
        "tokens": {
            "--bg-canvas": "#e8ebf0", "--bg-surface": "#e8ebf0", "--bg-sidebar": "#e8ebf0",
            "--bg-topbar": "#e8ebf0",
            "--text-primary": "#41464f", "--text-secondary": "#6b7280", "--text-tertiary": "#9aa1ac",
            "--border": "transparent",
            "--brand": "#5b8def", "--brand-strong": "#3f6fd1", "--brand-soft": "#dde6f7",
            "--up": "#e06a6a", "--down": "#3fae7a", "--neutral": "#9aa1ac", "--accent": "#5b8def",
            "--radius": "16px", "--radius-lg": "22px",
            "--shadow-md": "none",
            "--font-display": "'Poppins',sans-serif",
            "--font-body": "'Inter',-apple-system,'PingFang SC',sans-serif",
            "--font-mono": "'JetBrains Mono',ui-monospace,monospace",
        },
        "css": """
body{background:var(--bg-canvas)}
.ff-sidebar,.ff-topbar,.ff-card,.ff-stat{background:var(--bg-surface);border:none;
  box-shadow:8px 8px 18px #c9cdd6,-8px -8px 18px #ffffff}
.ff-nav a:hover,.ff-nav a.active{box-shadow:inset 4px 4px 9px #c9cdd6,inset -4px -4px 9px #ffffff;background:var(--bg-surface)}
.ff-search{box-shadow:inset 3px 3px 7px #c9cdd6,inset -3px -3px 7px #ffffff;border:none;background:var(--bg-surface)}
.ff-stat:hover{transform:none}
.ff-word{font-weight:600}
""",
        "desc": {
            "layout": "结构同极简专业，但因新拟态依赖同色凹凸，侧栏/卡片/画布同色，仅靠光影区分。指标卡 5 列 → 双列 → 图表，留白偏大以容纳柔影。",
            "look": "浅灰 #e8ebf0 单一画布，所有表面同色；通过双向柔影（亮上左、暗下右）制造凸起/凹陷。无边框、低饱和，像实体硬件仪表盘，温润不刺眼。",
            "type": "标题 Poppins（圆润几何），正文 Inter，数字 JetBrains Mono。字形圆润与新拟态的柔软语言一致。",
            "comp": "组件即「光影雕刻」：卡片凸起、输入框凹陷、激活导航内凹。hover 不位移改内凹态。需保证对比度，语义色用于标签与数字而非结构。",
        },
    },
    {
        "id": "09-editorial-mono",
        "cn": "编辑粗野", "en": "Editorial Mono", "tag": "黑白高反差 · 等宽网格 · 财经媒体感",
        "fonts": ["Space Grotesk", "Space Mono", "Inter"],
        "tokens": {
            "--bg-canvas": "#fafafa", "--bg-surface": "#ffffff", "--bg-sidebar": "#ffffff",
            "--bg-topbar": "#ffffff",
            "--text-primary": "#0a0a0a", "--text-secondary": "#444444", "--text-tertiary": "#888888",
            "--border": "#0a0a0a",
            "--brand": "#0a0a0a", "--brand-strong": "#0a0a0a", "--brand-soft": "#efefef",
            "--up": "#e5484d", "--down": "#12a150", "--neutral": "#888888", "--accent": "#1a1aff",
            "--radius": "3px", "--radius-lg": "3px",
            "--shadow-md": "6px 6px 0 #0a0a0a",
            "--font-display": "'Space Grotesk',sans-serif",
            "--font-body": "'Space Mono','Inter',-apple-system,'PingFang SC',monospace",
            "--font-mono": "'Space Mono',ui-monospace,monospace",
        },
        "css": """
.ff-sidebar{border-right:2px solid #0a0a0a}
.ff-topbar{border-bottom:2px solid #0a0a0a}
.ff-card,.ff-stat{border:2px solid #0a0a0a;border-radius:3px;box-shadow:6px 6px 0 #0a0a0a}
.ff-stat:hover{transform:translate(-2px,-2px);box-shadow:9px 9px 0 #0a0a0a}
.ff-nav a{border:2px solid transparent}
.ff-nav a:hover,.ff-nav a.active{border:2px solid #0a0a0a;background:#fff;color:#0a0a0a;box-shadow:3px 3px 0 var(--accent)}
.ff-nav a.active svg{color:var(--accent)}
.ff-logo{border:2px solid #0a0a0a;background:#0a0a0a;border-radius:3px}
.ff-live{border:2px solid #0a0a0a;box-shadow:3px 3px 0 #0a0a0a;color:#0a0a0a;background:#fff}
.ff-live .dot{background:var(--accent)}
.ff-tag.up,.ff-tag.down,.ff-tag.neu{border:1.5px solid currentColor;border-radius:3px}
.ff-chip{border:2px solid #0a0a0a}
.ff-word{font-family:var(--font-display);font-weight:700}
.ff-hero h1{font-weight:700}
""",
        "desc": {
            "layout": "结构同极简专业，但用 2px 硬黑边 + 实色偏移投影（Brutalist）划分区块，网格线外露。指标卡 5 列 → 双列 → 图表，强对齐、强秩序，像财经报纸数字版。",
            "look": "近白 #fafafa 画布 + 纯黑硬边，单一强调色（电光蓝）点缀交互；红涨绿跌保持。高反差、零圆角、可见结构线，粗野主义 + 编辑排版，冷静而具态度。",
            "type": "标题 Space Grotesk（粗）、正文与数字 Space Mono 等宽，CJK 雅黑兜底。等宽网格 + 大写眉题营造「数据新闻」的编辑气质。",
            "comp": "组件即「带黑边的盒子」：卡片/标签硬边 + 偏移投影；激活态黑边 + 蓝影；hover 左移加深投影。极简组件语言，强调内容而非装饰。",
        },
    },
    {
        "id": "10-aurora-glass",
        "cn": "极光玻璃", "en": "Aurora Glass", "tag": "深蓝紫渐变 · 毛玻璃 · 现代 AI 产品",
        "fonts": ["Sora", "Space Grotesk", "JetBrains Mono"],
        "tokens": {
            "--bg-canvas": "#0a0a1f", "--bg-surface": "rgba(255,255,255,.06)", "--bg-sidebar": "rgba(255,255,255,.05)",
            "--bg-topbar": "rgba(255,255,255,.05)",
            "--text-primary": "#eef0ff", "--text-secondary": "#aab0d6", "--text-tertiary": "#6f76a8",
            "--border": "rgba(255,255,255,.12)",
            "--brand": "#8b7bff", "--brand-strong": "#a99bff", "--brand-soft": "rgba(139,123,255,.16)",
            "--up": "#ff6b8b", "--down": "#4be3a8", "--neutral": "#6f76a8", "--accent": "#46d6ff",
            "--radius": "16px", "--radius-lg": "20px",
            "--shadow-md": "0 18px 50px -28px rgba(139,123,255,.5)",
            "--font-display": "'Sora','Space Grotesk',sans-serif",
            "--font-body": "'Inter',-apple-system,'PingFang SC',sans-serif",
            "--font-mono": "'JetBrains Mono',ui-monospace,monospace",
        },
        "css": """
body{background:radial-gradient(1200px 600px at 12% -8%,rgba(139,123,255,.22),transparent 60%),
  radial-gradient(900px 500px at 100% 0%,rgba(70,214,255,.16),transparent 55%),
  linear-gradient(180deg,#0a0a1f,#0d0d22)}
.ff-sidebar,.ff-topbar{backdrop-filter:blur(22px);-webkit-backdrop-filter:blur(22px);
  border-color:rgba(255,255,255,.10)}
.ff-card,.ff-stat{background:rgba(255,255,255,.06);backdrop-filter:blur(16px);
  -webkit-backdrop-filter:blur(16px);border:1px solid rgba(255,255,255,.10);
  box-shadow:0 18px 50px -28px rgba(139,123,255,.5)}
.ff-logo{background:linear-gradient(135deg,var(--brand),#46d6ff);box-shadow:0 0 22px rgba(139,123,255,.5)}
.ff-live{color:var(--up)}
.ff-word{font-weight:700}
.ff-card h2,.ff-hero h1,.ff-spec h3{color:#fff}
""",
        "desc": {
            "layout": "固定左侧玻璃导航 + 玻璃顶栏，主体居中 1280px。指标卡 5 列 → 双列 → 图表，结构同极简专业，但浮层卡片叠于极光渐变背景之上，层次由模糊与光晕建立。",
            "look": "深蓝紫渐变画布（双径向光晕：紫 + 青），卡片为半透明毛玻璃，品牌紫 #8b7bff 配青色辅色；红涨绿跌提亮以适配暗底。现代 AI 产品（Linear 暗色 / Vercel AI）的科技梦幻感。",
            "type": "标题 Sora（几何现代），正文 Inter，数字 JetBrains Mono。几何无衬线 + 等宽，配合发光强调，呈现未来感。",
            "comp": "组件为毛玻璃浮层：logo/主按钮紫青渐变 + 外发光；标签透明度语义色；hover 微抬升 + 光晕增强。整体「界面即光」，强调沉浸与高级感。",
        },
    },
]

# ---------------------------------------------------------------------------
# 数据（统一样机内容，便于跨方案对比）
# ---------------------------------------------------------------------------
STATS = [
    ("上证指数", "3287.45", "+0.82%", "up"),
    ("深证成指", "10654.30", "+1.15%", "up"),
    ("创业板指", "2189.67", "-0.34%", "down"),
    ("涨停 / 跌停", "73 / 12", "宽度偏暖", "neu"),
    ("北向资金", "+42.6亿", "净流入", "up"),
]
NEWS = [
    ("14:32", "财联社", "央行公开市场净投放 <b>2000亿元</b>，资金面边际转松，短端利率下行", "up", "利好"),
    ("13:58", "巨潮公告", "科技龙头发布中报：营收同比 <b>+38%</b>，净利超机构预期", "up", "利好"),
    ("11:20", "金十数据", "美联储释放鸽派信号，离岸人民币升破 <b>7.15</b>", "neu", "中性偏多"),
    ("09:45", "同花顺", "新能源车企 7 月交付环比下滑，机构观点分歧加大", "down", "利空"),
    ("09:31", "新浪财经", "三大指数集体高开，半导体板块领涨", "up", "利好"),
]
LIMIT = [
    ("xx股份", "600519", "题材共振 · 资金抢筹", "+10.0%", "涨停", False),
    ("yy科技", "002415", "业绩超预期 + 机构买入", "+10.0%", "涨停", False),
    ("zz新能", "300750", "炸板回封 · 换手充分", "+9.8%", "炸板", True),
    ("aa制药", "688981", "重磅临床数据积极", "+20.0%", "涨停(科)", False),
]
CHIPS = ["交易日 2026-08-17", "沪深成交额 1.18万亿", "上涨 3120 · 下跌 1680"]


def svg_icon(name):
    return ('<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" '
            'stroke-linecap="round" stroke-linejoin="round"><path d="%s"/></svg>' % ICONS[name])


def build_nav():
    out = []
    for icon, label, active in NAV:
        cls = " active" if active else ""
        out.append('<a class="%s" href="#">%s<span>%s</span></a>' % (cls, svg_icon(icon), label))
    return "\n".join(out)


def build_stats():
    out = []
    for lbl, val, chg, tone in STATS:
        out.append(
            '<div class="ff-stat"><div class="lbl">%s</div>'
            '<div class="val">%s</div>'
            '<div class="chg %s">%s</div></div>' % (lbl, val, tone, chg))
    return "\n".join(out)


def build_news():
    out = []
    for t, src, txt, tone, tag in NEWS:
        out.append(
            '<div class="ff-news-item"><div class="ff-time">%s</div>'
            '<div class="ff-news-body"><div class="ff-news-src">%s · 快讯</div>'
            '<div class="ff-news-txt">%s</div></div>'
            '<div class="ff-tag %s">%s</div></div>' % (t, src, txt, tone, tag))
    return "\n".join(out)


def build_market():
    out = []
    for name, code, reason, px, badge, weak in LIMIT:
        bw = " weak" if weak else ""
        out.append(
            '<div class="ff-limit-row"><div class="ff-limit-name">%s<small>%s</small></div>'
            '<div class="ff-limit-reason">%s</div>'
            '<div class="ff-limit-px">%s</div>'
            '<div class="ff-badge%s">%s</div></div>' % (name, code, reason, px, bw, badge))
    return "\n".join(out)


def build_chart():
    # 静态情绪趋势（利好/利空双线）+ 网格，使用 CSS 变量自适应配色
    return """
<svg viewBox="0 0 600 178" preserveAspectRatio="none" role="img" aria-label="情绪趋势图">
  <defs>
    <linearGradient id="gUp" x1="0" y1="0" x2="0" y2="1">
      <stop offset="0" stop-color="var(--up)" stop-opacity=".22"/>
      <stop offset="1" stop-color="var(--up)" stop-opacity="0"/>
    </linearGradient>
  </defs>
  <line x1="0" y1="44" x2="600" y2="44" stroke="var(--border)" stroke-width="1"/>
  <line x1="0" y1="89" x2="600" y2="89" stroke="var(--border)" stroke-width="1"/>
  <line x1="0" y1="134" x2="600" y2="134" stroke="var(--border)" stroke-width="1"/>
  <path d="M0,120 C60,110 90,70 150,72 C220,74 250,40 320,46 C390,52 420,30 490,38 C540,43 570,34 600,40 L600,178 L0,178 Z"
        fill="url(#gUp)" stroke="none"/>
  <path d="M0,118 C60,108 90,68 150,70 C220,72 250,38 320,44 C390,50 420,28 490,36 C540,41 570,32 600,38"
        fill="none" stroke="var(--up)" stroke-width="2.5" stroke-linecap="round"/>
  <path d="M0,96 C60,92 100,104 160,100 C230,95 260,112 330,108 C400,104 430,118 500,114 C545,111 575,116 600,112"
        fill="none" stroke="var(--down)" stroke-width="2.5" stroke-linecap="round" stroke-dasharray="1 0"/>
  <circle cx="600" cy="38" r="3.5" fill="var(--up)"/>
  <circle cx="600" cy="112" r="3.5" fill="var(--down)"/>
</svg>
<div class="ff-legend">
  <span><i style="background:var(--up)"></i>利好情绪</span>
  <span><i style="background:var(--down)"></i>利空情绪</span>
  <span style="margin-left:auto;color:var(--text-tertiary)">近 20 交易日 · 来源 舆情分析</span>
</div>"""


def build_spec(desc):
    items = [
        ("布局方式", "dashboard", desc["layout"]),
        ("视觉外观", "flash", desc["look"]),
        ("字体选择", "articles", desc["type"]),
        ("组件设计", "market", desc["comp"]),
    ]
    out = []
    for k, ic, txt in items:
        out.append('<div class="ff-spec-card"><div class="k">%s %s</div><p>%s</p></div>'
                   % (svg_icon(ic), k, txt))
    return "\n".join(out)


def build_tokens(tk):
    return "\n".join("  %s: %s;" % (k, v) for k, v in tk.items())


def build_fonts(families):
    fam = "&".join("family=%s:wght@400;500;600;700" % f.replace(" ", "+") for f in families)
    return ('<link rel="preconnect" href="https://fonts.googleapis.com">'
            '<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>'
            '<link href="https://fonts.googleapis.com/css2?%s&display=swap" rel="stylesheet">' % fam)


def build_html(s):
    title = "FinFeed 视觉方案 %s · %s / %s" % (s["id"].split("-")[0], s["cn"], s["en"])
    style = ("<style>\n:root{\n%s\n}\n%s\n%s\n</style>"
             % (build_tokens(s["tokens"]), SHARED_CSS, s["css"]))
    html = """<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>__TITLE__</title>
__FONTS__
__STYLE__
</head>
<body>
<div class="ff-app">
  <aside class="ff-sidebar">
    <div class="ff-brand">
      <div class="ff-logo">__LOGO__</div>
      <div class="ff-word">FinFeed<small>实时金融监控</small></div>
    </div>
    <nav class="ff-nav">__NAV__</nav>
    <div class="ff-side-foot">v2.1.0 · 本地自托管<br>数据每 5s 增量同步</div>
  </aside>
  <div class="ff-main">
    <header class="ff-topbar">
      <div class="ff-search">__SEARCH__<input placeholder="搜索股票、公告、快讯…"></div>
      <div class="ff-top-meta">
        <span class="ff-date">2026-08-17 周一</span>
        <span class="ff-live"><span class="dot"></span>LIVE 实时</span>
        <div class="ff-avatar">A</div>
      </div>
    </header>
    <main class="ff-content">
      <section class="ff-hero">
        <div>
          <h1>收盘复盘 · 全市场快照</h1>
          <p>实时金融新闻与 A 股市场监控系统 — 覆盖快讯、财经、市场事实、舆情与财经日历。</p>
        </div>
        <div class="ff-chips">__CHIPS__</div>
      </section>
      <section class="ff-stats">__STATS__</section>
      <div class="ff-cols">
        <section class="ff-card">
          <h2>__IC_FLASH__ 实时快讯<span class="sub">最近 5 条</span></h2>
          <div class="ff-news">__NEWS__</div>
        </section>
        <section class="ff-card">
          <h2>__IC_MARKET__ 涨停板 / 龙虎榜<span class="sub">今日</span></h2>
          <div class="ff-limit">__LIMIT__</div>
        </section>
      </div>
      <section class="ff-card ff-chart">
        <h2>__IC_SENT__ 舆情情绪趋势<span class="sub">利好 vs 利空</span></h2>
        __CHART__
      </section>
      <section class="ff-spec">
        <h3>__IC_AI__ 本方案设计说明（布局 / 外观 / 字体 / 组件）</h3>
        <div class="ff-spec-grid">__SPEC__</div>
      </section>
    </main>
  </div>
</div>
</body>
</html>"""
    repl = {
        "__TITLE__": title,
        "__FONTS__": build_fonts(s["fonts"]),
        "__STYLE__": style,
        "__LOGO__": svg_icon("ai"),
        "__NAV__": build_nav(),
        "__SEARCH__": svg_icon("search"),
        "__CHIPS__": "".join('<span class="ff-chip">%s</span>' % c for c in CHIPS),
        "__STATS__": build_stats(),
        "__NEWS__": build_news(),
        "__LIMIT__": build_market(),
        "__CHART__": build_chart(),
        "__SPEC__": build_spec(s["desc"]),
        "__IC_FLASH__": svg_icon("flash"),
        "__IC_MARKET__": svg_icon("market"),
        "__IC_SENT__": svg_icon("sentiment"),
        "__IC_AI__": svg_icon("ai"),
    }
    for k, v in repl.items():
        html = html.replace(k, v)
    return html


def build_index():
    cards = []
    for s in SCHEMES:
        t = s["tokens"]
        swatch = ('<span class="sw" style="background:%s"></span>'
                  '<span class="sw" style="background:%s"></span>'
                  '<span class="sw" style="background:%s"></span>'
                  % (t["--brand"], t["--up"], t["--down"]))
        cards.append(
            '<a class="g-card" href="%s.html">'
            '<div class="g-num">%s</div>'
            '<div class="g-name">%s <span>%s</span></div>'
            '<div class="g-tag">%s</div>'
            '<div class="g-sw">%s</div>'
            '<div class="g-go">查看方案 →</div>'
            '</a>' % (s["id"], s["id"].split("-")[0], s["cn"], s["en"], s["tag"], swatch))
    css = """
*{box-sizing:border-box;margin:0;padding:0}
body{font-family:'Inter',-apple-system,'PingFang SC','Microsoft YaHei',sans-serif;
  background:#0f1117;color:#e8eaf0;min-height:100vh;padding:48px 28px}
.wrap{max-width:1180px;margin:0 auto}
header{max-width:1180px;margin:0 auto 30px}
h1{font-family:'Space Grotesk','Inter',sans-serif;font-size:30px;font-weight:700;letter-spacing:-.02em}
.sub{color:#9aa3b2;font-size:14px;margin-top:8px;line-height:1.6;max-width:680px}
.grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(260px,1fr));gap:16px;max-width:1180px;margin:0 auto}
.g-card{display:block;text-decoration:none;color:inherit;background:#181b24;border:1px solid #262b38;
  border-radius:16px;padding:18px 18px 16px;transition:.18s;position:relative;overflow:hidden}
.g-card:hover{transform:translateY(-3px);box-shadow:0 16px 40px -20px rgba(0,0,0,.7);border-color:#465}
.g-num{font-family:'JetBrains Mono',monospace;font-size:12px;color:#6f7891;font-weight:600;letter-spacing:.08em}
.g-name{font-size:18px;font-weight:700;margin-top:6px;font-family:'Space Grotesk','Inter',sans-serif}
.g-name span{font-size:12px;font-weight:500;color:#8b93a7;margin-left:6px}
.g-tag{font-size:12.5px;color:#aab2c5;margin-top:8px;line-height:1.5;min-height:38px}
.g-sw{display:flex;gap:7px;margin-top:12px}
.sw{width:26px;height:26px;border-radius:8px;display:inline-block}
.g-go{margin-top:14px;font-size:13px;font-weight:600;color:#8b7bff}
footer{max-width:1180px;margin:34px auto 0;color:#6f7891;font-size:12.5px;line-height:1.7}
"""
    html = """<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>FinFeed 视觉方案对比画廊</title>
<style>%s</style>
</head>
<body>
<header>
  <h1>FinFeed 视觉参考方案 · 对比画廊</h1>
  <p class="sub">为 FinFeed 仪表盘设计的 10 套风格迥异的视觉方案。每套均为独立 HTML，可直接在浏览器打开预览，
  包含统一仪表盘样机 + 四要素设计说明（布局 / 外观 / 字体 / 组件）。点击下方卡片进入对应方案。</p>
</header>
<div class="grid">%s</div>
<footer>共 10 套方案 · 红涨绿跌（A 股惯例）在所有方案中保持一致 · 配色样本依次为：品牌色 / 上涨红 / 下跌绿。
生成于 2026-08-17。</footer>
</body>
</html>""" % (css, "\n".join(cards))
    return html


def main():
    for s in SCHEMES:
        path = os.path.join(OUT_DIR, s["id"] + ".html")
        with open(path, "w", encoding="utf-8") as f:
            f.write(build_html(s))
        print("written:", s["id"] + ".html")
    idx = os.path.join(OUT_DIR, "index.html")
    with open(idx, "w", encoding="utf-8") as f:
        f.write(build_index())
    print("written: index.html")
    print("total:", len(SCHEMES) + 1, "files in", OUT_DIR)


if __name__ == "__main__":
    main()
