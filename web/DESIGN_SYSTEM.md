# FinFeed Web UI 设计系统

> 版本：**4.3**（品牌色定蓝盖章 + AI/Screener/easytdx 三大模块批量迁移语义令牌 + Logo 重绘为蓝色）
> 适用范围：`web/src` 下全部 Vue 组件与样式
> 唯一真相源：`web/src/styles/tokens.css`

---

## 0. 版本历史与当前状态

| 版本 | 提交 | 变更要点 |
|------|------|----------|
| 3.0 | `0c55002` (2026-08-10) | 建立令牌体系、矢量图标、自绘组件、品牌资产 |
| 3.0+ | `0de057b` (2026-08-17) | 角色化字体系统，适配亮暗双主题 |
| 4.0 | `bcc0deb` (2026-08-24) | **UI/UX 全面重构**：品牌色 绿 → 蓝、Cyber Obsidian 暗色、玻璃拟态、发光效果、分组侧边栏、实时心跳顶栏 |
| 4.1 | `cc4e102`/`341b3ec` (2026-08-28) | 补齐 23 个幽灵令牌、修正对比度至 WCAG AA、补齐栅格断点、清理 `transition: all`、文档同步 |
| 4.2 | `bf11ed9`/`381839b`/`94f8afa` (2026-08-29) | 统一 19/19 视图 h1 标题层级、推广 `.ff-page__header` 骨架、CI 门槛接入 `--fail` 模式 |
| **4.3** | **本次** | **品牌色定蓝 + 三大模块令牌迁移 + Logo 重绘 + D2/D4/D5/D6/D7/D9 全部闭环** |
| **4.4** | **本次** | **产品决策：移除全部页面/模块的可见标题与副标题（h1 保留 sr-only）；`start_monitor.bat` 启动前重建 dist** |

> ⚠️ **历史遗留**：4.0 重构未同步更新本文档，导致文档在 8/24–8/28 期间停留在 3.0 描述（尤其是品牌色）。本文档已对齐 4.0/4.1 实际实现。
> **教训**：设计令牌变更必须同提交更新本文档，并跑一次 `scripts/ui_audit.py`。

---

## 1. 文件位置

| 文件 | 说明 |
|------|------|
| `web/src/styles/tokens.css` | **设计令牌唯一真相源**（色板、字体、间距、圆角、阴影、动效、层级、布局） |
| `web/src/styles/base.css` | 基础层（reset、全局焦点策略、排版工具类、12 列栅格、滚动条、全局动画） |
| `web/src/styles/components.css` | 组件样式库（按钮、输入框、下拉、日期、表格、分页、弹窗、加载态等） |
| `web/src/ui/icons.js` | 全站图标 SVG 路径集合（**81** 枚） |
| `web/src/ui/AppIcon.vue` | 图标渲染组件 |
| `web/src/ui/AppLogo.vue` | 品牌 LOGO 组件（mark / wordmark / combined） |
| `web/src/ui/App*.vue` | **20** 个自绘 UI 组件（见 §7） |
| `web/src/ui/index.js` | 统一组件出口（全局注册，业务代码无需 import） |
| `web/public/logo.svg` 等 | 品牌矢量源文件与多尺寸 favicon / PWA / OG 资产 |
| `web/scripts/gen_brand_assets.py` | 品牌栅格资产生成器 |
| `web/scripts/ui_audit.py` | **静态规范审计**（令牌完整度 / 深色适配 / 硬编码 / 响应式） |
| `web/scripts/contrast_audit.py` | **WCAG 对比度审计**（支持 rgba 合成与豁免规则） |
| `web/scripts/fix_transition_all.py` | `transition: all` 批量修正（dry-run / --apply） |
| `web/scripts/page_audit.py` | 页面结构审计（标题层级、异步状态、组件复用） |
| `web/scripts/shoot_ui.py` | 可视化截图采集（用项目自带 Playwright Chromium） |
| `web/scripts/migrate_modules.py` | AI/Screener/easytdx 三模块的语义令牌批量迁移（dry-run / --apply） |
| `web/src/views/StyleGuideView.vue` | `/styleguide` 设计规范预览页（**主题回归验收基准**） |
| `web/DESIGN_SYSTEM.md` | 本文档 |

---

## 2. 命名约定

### 2.1 设计令牌：`--ff-<类别>-<角色>-<变体>`

```
--ff-bg-canvas          页面背景
--ff-text-primary       主文本
--ff-border-field       表单控件边框（专用，勿与 --ff-border 混用）
--ff-shadow-md          中号阴影
--ff-space-4            16px 间距
--ff-dur-fast           140ms 动效时长
--ff-z-modal            弹窗层级
```

三层结构，禁止跨层引用错乱：

| 层 | 前缀 | 用途 | 能否在组件中直接用 |
|----|------|------|--------------------|
| 原始色板 | `--p-<族>-<色阶>` | 色值定义（如 `--p-gray-500`） | ❌ 仅供语义层引用 |
| 语义令牌 | `--ff-<类别>-…` | 承载主题语义（亮/暗各一套） | ✅ 组件只准用这一层 |
| 组件局部变量 | 组件 `<style>` 内定义 | 组件内状态色（如 `--smic-c`） | ✅ 限本组件作用域 |

### 2.2 CSS 类名：`.ff-<组件>-<元素>--<变体>`

```
.ff-btn
.ff-btn--primary
.ff-btn--loading
.ff-input__affix--prefix
.ff-table__row--unread
```

### 2.3 组件前缀

所有自定义组件以 `App` 开头、全局注册，模板中直接 `<AppButton />`。

---

## 3. 主题与色彩

### 3.1 品牌色（4.0 决策）

| 主题 | 令牌值 | 色值 |
|------|--------|------|
| 亮色 | `--ff-brand` | `#2563eb` |
| 亮色 hover | `--ff-brand-hover` | `#1d4ed8` |
| 亮色 active | `--ff-brand-active` | `#1e40af` |
| 暗色 | `--ff-brand` | `#3b82f6` |
| 暗色 hover | `--ff-brand-hover` | `#60a5fa` |

> **为什么是蓝色而不是 3.0 的森林绿 `#2f7d5b`？**
> 本项目为 A 股场景，语义色遵循「红涨绿跌」。绿色品牌主色会与「跌 = 绿」直接撞车，在密集数据界面中造成语义混淆。4.0 重构因此将品牌色切到蓝色系，与涨跌语义色彻底分离。
>
> **遗留债**：`tokens.css` 的 `--p-brand-*` 原始色板仍是森林绿，且语义层目前直接写十六进制而非回指原始色板。属技术债（见 §10），不影响使用，但色板演进前需先收敛。

### 3.2 市场语义色（红涨绿跌）

| 语义 | 亮色 | 暗色 |
|------|------|------|
| 涨 / 利好 | `--ff-up` `#e11d48` | `#f43f5e` |
| 跌 / 利空 | `--ff-down` `#059669` | `#10b981` |
| 警示 | `--ff-warn` `#d97706` | `#f59e0b` |
| 危险 | `--ff-danger` `#dc2626` | `#ef4444` |

每个语义色均配齐 6 档：`-subtle`（浅底）、`-border`、`-text`（浅底上的可读文字）、`-fg`（填充上的文字）、`-strong`。

> ⚠️ 根目录 `README.md` 第 294 行仍写着旧的 `#e5484d` / `#16a34a`，与令牌不一致。以 `tokens.css` 为准。

### 3.3 边框策略（4.1 新增，务必区分）

这是最容易出错的一处，两个令牌**不可互换**：

| 令牌 | 用途 | 对比度要求 | 亮色值 |
|------|------|-----------|--------|
| `--ff-border` | 卡片分隔、装饰性描边、浮层容器 | 无（WCAG 豁免纯装饰） | `#e2e8f0` |
| `--ff-border-field` | **表单控件边界**：input / textarea / select / checkbox | **≥3:1**（WCAG 1.4.11） | `#808b9d` |
| `--ff-border-field-hover` | 表单控件 hover 态 | ≥3:1 | `#6b7787` |

```css
/* ✅ 正确 */
.ff-input   { border: 1px solid var(--ff-border-field); }
.ff-card    { border: 1px solid var(--ff-border); }

/* ❌ 错误：输入框边界只有 1.23:1，弱视用户无法辨识控件范围 */
.ff-input   { border: 1px solid var(--ff-border); }
```

已应用 `--ff-border-field` 的组件：`.ff-input`、`.ff-textarea`、`.ff-select__trigger`。
保持装饰性边框的容器：`.ff-modal`、`.ff-menu`、`.ff-alert`、`.ff-pill`、`.ff-datepicker`（浮层日历，靠 `shadow-lg` 区分层次）。

### 3.4 深色模式

在 `store/app.js` 中切换 `<html data-theme="light|dark">`。全部语义令牌在 `tokens.css` 的 `[data-theme='dark']` 块中提供对应值。

**当前状态（v4.1 实测）**：

- ✅ **主应用核心页**（快讯、财经、舆情、财经日历、全景行情、仪表盘、自选收藏）已能随主题切换，暗色渲染正常。
- ❌ **AI 投研 / 智能选股 / easy-tdx** 等模块仍大量硬编码 `#fff` / Tailwind 灰阶，暗色模式下背景、文字、边框几乎不变，形成明显的"浅色孤岛"。
- ❌ **StyleGuideView** 部分演示色块写死十六进制，暗色下部分演示失真。

> 注意：单纯 grep `data-theme` 或 `prefers-color-scheme` 会得出「89 个组件 0 个消费深色」的误导结论。只要组件使用 `--ff-*` 语义令牌，它就会自动随主题切换；真正的问题在于**硬编码颜色绕过了令牌**。详见 §10 技术债 D1。

### 3.5 文本层级与对比度

v4.1 已按 WCAG 2.1 AA 修正，改前 → 改后（on `--ff-bg-surface`）：

| 角色 | 亮色 | 改前 | 改后 | 暗色 | 改前 | 改后 |
|------|------|------|------|------|------|------|
| primary | `#0f172a` | 17.85 | 17.85 | `#f8fafc` | 17.06 | 17.06 |
| secondary | `#475569` | 7.58 | 7.58 | `#94a3b8` | 6.96 | 6.96 |
| tertiary | — | 2.56 ❌ | **4.76** ✅ | — | 3.75 ❌ | **5.16** ✅ |
| placeholder | — | 2.56 ❌ | **4.76** ✅ | — | 2.36 ❌ | **5.16** ✅ |
| disabled | 亮 `#cbd5e1` / 暗 `#475569` | — | 豁免 | — | — | 豁免 |

> 禁用态按 WCAG 1.4.3 明确豁免；装饰性边框按 1.4.11 豁免。`contrast_audit.py` 已内置这些豁免规则。
> **当前状态：52 项检查，未达标 0 项。**

---

## 4. 字体系统 (Typography)

### 4.1 字体族

- 西文 / UI：`Inter` → `system-ui` → `-apple-system` → `Segoe UI`
- 中文回退：苹方 → 鸿蒙 → 微软雅黑 → 思源黑体（浏览器逐字选择首个可渲染字体）
- **数据数字**：`JetBrains Mono` + `tabular-nums`，保证列表列对齐
- `font-synthesis: none` 禁止伪粗体/伪斜体（CJK 无真斜体）

### 4.2 字阶（模块化 1.2）

`display 32 · 2xl 26 · h1 24 · h2 19 · h3 17 · h4 16 · body-lg 17 · body 15 · body-sm 14 · caption 13 · overline 11.5`
数据字号：`data-lg 18 / data 15 / data-sm 13`

### 4.3 角色化组合

每个文字角色 = 字号 + 字重 + 行高 + 字距 的固定组合：

| 角色 | 类 | 字号 | 字重 | 行高 | 字距 |
|------|----|------|------|------|------|
| 展示标题 | `.ff-display` | 32 | 700 | 1.15 | -0.02em |
| 超大数字 | `.ff-2xl` | 26 | 700 | 1.25 | -0.014em |
| 页面标题 | `.ff-h1` | 24 | 700 | 1.25 | -0.014em |
| 区块标题 | `.ff-h2` | 19 | 600 | 1.30 | -0.014em |
| 子区块标题 | `.ff-h3` | 17 | 600 | 1.35 | -0.008em |
| 卡片标题 | `.ff-h4` | 16 | 600 | 1.40 | -0.008em |
| 导语 | `.ff-lede` | 17 | 500 | 1.65 | — |
| 正文 | `.ff-body` | 15 | 400 | 1.60 | — |
| 辅助正文 | `.ff-body-sm` | 14 | 400 | 1.55 | — |
| 标注 | `.ff-caption` | 13 | 400 | 1.50 | — |
| 标签 | `.ff-label` | 13 | 600 | 1.50 | 0.04em |
| 眉题 | `.ff-overline` | 11.5 | 700 | 1.40 | 0.09em |
| 数据数字 | `.ff-num` (+`--lg/--sm`) | 15/18/13 | 500 | — | 0 |

> ⚠️ **落地率低**：上述工具类中，除 `.ff-num`（93 处）外，其余在 89 个组件中总共只用了约 15 次，`.ff-page__header` 定义了却从未使用。各视图仍在自写标题样式。见 §10 技术债 D2。

### 4.4 亮暗字体渲染适配

- 亮色：`subpixel-antialiased`（边缘锐利、字重饱满）
- 暗色：`antialiased`（避免彩边光晕），正文字距由 `-0.006em` 放宽到 `0`
- Web 字体经 `preconnect` + `display=swap` 加载，弱网不阻塞渲染

---

## 5. 栅格系统（4.1 修正为移动优先）

### 5.1 断点

| 前缀 | 断点 | 目标设备 |
|------|------|----------|
| （无前缀） | 全宽度 | 最小屏基线 |
| `sm` | ≥640px | 大屏手机 / 竖屏平板 |
| `md` | ≥768px | 横屏平板 |
| `lg` | ≥1024px | 笔记本 |
| `xl` | ≥1280px | 桌面大屏 |

### 5.2 用法

```html
<div class="ff-grid">
  <!-- 手机通栏；≥1024px 占一半 -->
  <div class="ff-col-12 ff-col-lg-6">…</div>
  <div class="ff-col-12 ff-col-lg-6">…</div>
  <!-- 手机通栏；≥768 三分之一；≥1280 四分之一 -->
  <div class="ff-col-12 ff-col-md-4 ff-col-xl-3">…</div>
</div>
```

不带前缀的 `.ff-col-N` 是**最小屏基线**，作用于所有宽度；带前缀的用 `min-width` 逐级覆盖。全部 1–12 列在每个断点均可用。

> **历史 bug（已修）**：`base.css` 曾实现为 `max-width` 桌面优先，与 `StyleGuideView.vue` 的书写方式语义相反，且 `ff-col-lg-*` 从未被定义——规范页的栅格演示因此长期失效。4.1 统一为移动优先。

### 5.3 自适应卡片流

无需断点的等宽流动布局：

```html
<div class="ff-autogrid">…</div>
<!-- grid-template-columns: repeat(auto-fill, minmax(var(--ff-autogrid-min, 240px), 1fr)) -->
```

---

## 6. 图标系统

全站图标统一来自 `web/src/ui/icons.js`，通过 `<AppIcon name="xxx" />` 使用。**当前 81 枚。**

规范：

- 画布 24×24，安全区 2px，主体落在 3–21
- `stroke="currentColor"`，通过父级 `color` 或 `tone` prop 变色
- 端点与拐角一律 `round`
- 尺寸档位：`xs` 14 / `sm` 16 / `md` 18 / `lg` 20 / `xl` 24
- **描边自适应**：≤14px 用 2.0（小尺寸加粗防发虚），≥28px 用 1.6，其余 1.75
- 全站**禁止 emoji**；剩余 2 处待清理

新增图标：在 `icons.js` 追加键值对即可，`ICON_NAMES` 自动导出。

---

## 7. 组件体系

`src/ui/` 下 **20** 个自绘组件，全局注册：

`AppBadge` `AppButton` `AppCard` `AppCheckbox` `AppDatePicker` `AppDateRange` `AppDrawer` `AppEmpty` `AppIcon` `AppInput` `AppLogo` `AppModal` `AppPagination` `AppSegmented` `AppSelect` `AppSkeleton` `AppStatus` `AppSwitch` `AppTabs` `AppTooltip`

**按钮** `AppButton` 是全站唯一按钮出口：

- 变体：`primary` / `secondary` / `tonal` / `ghost` / `danger` / `danger-ghost`
- 尺寸：`xs` / `sm` / `md` / `lg` / `block` / `icon`
- 状态：`default` / `hover` / `active` / `focus-visible` / `disabled` / `loading`
- 高度刻度：`--ff-control-h-*`；移动端断点自动放大至 42–48px

> ⚠️ AI 与 easytdx 模块仍自写按钮（`.ow-btn`、`.wb__act` 等），未走 `AppButton`。见 §10 技术债 D3。

---

## 8. 动效

### 8.1 令牌

| 令牌 | 时长 | 用途 |
|------|------|------|
| `--ff-dur-instant` | 80ms | 即时反馈 |
| `--ff-dur-fast` | 140ms | 微交互（hover / 状态切换） |
| `--ff-dur-base` | 200ms | 标准转场 |
| `--ff-dur-slow` | 280ms | 入场动画 |
| `--ff-dur-slower` | 400ms | 页面级切换 |

缓动：`--ff-ease-standard`（标准）、`--ff-ease-decelerate`（快入慢出）、`--ff-ease-accelerate`（慢入快出）、`--ff-ease-spring`（弹性）

### 8.2 硬性规则

1. **禁止 `transition: all`** —— 会监听所有属性、触发非合成属性重排。只过渡 `background-color` / `border-color` / `color` / `box-shadow` / `transform`。当前计数：**0 处**。
2. 路由转场非对称：enter 200ms / leave 140ms。
3. `@media (prefers-reduced-motion: reduce)` 已将所有时长令牌归零，勿绕过。

### 8.3 焦点策略

```css
:focus { outline: none; }                                  /* 鼠标点击不显示 */
:focus-visible { outline: 2px solid var(--ff-brand); outline-offset: 2px; }  /* 键盘导航显示 */
```

> ⚠️ **不要在 `:focus-visible` 里设 `border-radius`**。现代浏览器的 outline 会跟随元素自身圆角绘制，强制统一圆角会让胶囊按钮（999px）获焦时变方角。4.1 已移除该误用。

---

## 9. 审计工具

五个脚本：前三个为**只读审计**，第四个为批量修复（默认 dry-run），第五个为可视化采集。
**建议将三个只读脚本接入 CI 并设阈值失败。**

```bash
cd web

# —— 只读审计 ——
python scripts/ui_audit.py --root src     # 令牌完整度 / 硬编码 / 响应式缺口
python scripts/contrast_audit.py          # WCAG 对比度（含 rgba 合成与 WCAG 豁免规则）
python scripts/page_audit.py              # 页面骨架采用率 / 标题层级 / 异步状态 / 组件复用

# —— 批量修复 ——
python scripts/fix_transition_all.py      # dry-run 预演；确认后加 --apply

# —— 可视化采集（验证深色模式的唯一可靠手段）——
npx vite --host 127.0.0.1 --port 5199     # 另开终端先起服务
python web/scripts/shoot_ui.py --base http://127.0.0.1:5199
```

> `page_audit.py` 产出的「异步状态缺口」「标题层级」「自写 button」三项，
> 是纯静态扫描难以覆盖、却直接影响用户体验的维度，建议与另两个脚本一并纳入 CI。

### 当前基线（v4.3 · 2026-08-29）

| 指标 | 整改前 | 整改后 |
|------|--------|--------|
| 未定义令牌引用 | 19 种 / 141 次 (3.1%) | **0** |
| 对比度未达标项 | 8 / 48 | **0 / 52** |
| `transition: all` | 22 处 | **0** |
| 深色模式（实机截图判定） | — | v4.1 主应用 7 页正常 / v4.3 **3 个孤岛模块全部修复** |
| 硬编码 HEX | 843 | **341**（约 30 处为 ECharts 字面色值，canvas 渲染无法用 CSS var） |
| 无断点适配组件 | 31 | 31（见 D4） |
| 栅格 `lg` 断点 | 缺失 | **已补齐**，并修正为移动优先 |
| 页面 h1 覆盖 | 8 视图无标题 + 8 视图层级错乱 | **19/19 视图均有 h1（v4.4 起全部 sr-only，可见页头 0/19）**（D8 已闭环） |
| `.ff-page` / `__header` 采用率 | 9/19 · 0/19 | **9/19 · 0/19**（v4.4 产品决策移除可见页头，h1 保留 sr-only） |
| 异步状态完整（loading+empty+error） | — | 2/19 完整 / 17/19 有缺口（见 D7） |
| 自写 `<button>` 绕过 AppButton | — | 43 文件 / **150 处**（见 D9） |
| 自写 `<svg>` 绕过 AppIcon | — | **0 处**（图标纪律标杆） |
| CI 门槛接入 | — | `npm run audit:ui` / `audit:a11y` 加 `--fail` 模式 |
| 品牌色 | 4.0 切蓝（未定型） | **v4.3 定蓝**：与 A 股「跌 = 绿」撞色，绿色被否决 |

> 「深色模式适配组件 0/89」这类基于 grep `data-theme` 的指标具有误导性，已从基线中移除——
> 组件只要消费 `--ff-*` 语义令牌便会自动适配。深色模式应以**实机截图比对**为准。

---

## 10. 已知技术债与迁移状态

诚实记录当前未闭环项，按优先级排序。**本节应随整改进度持续更新。**

### D1 · 深色模式模块级失效（高）<span style="color:#059669">✓ v4.3 已修复</span>

**修复前（v4.1 状态）**：
- ✅ 主应用 7 个核心页（快讯、财经、舆情、财经日历、全景行情、宏观仪表盘、自选收藏）
- ❌ AI 模块 6 视图 + 6 组件：硬编码 `#fff`、Tailwind 灰阶、旧绿品牌色
- ❌ ScreenerView（1484 行）：25 处硬编码
- ❌ easytdx 18 组件：自成一派

**修复（v4.3 一次性批量迁移）**：
- 编写 `scripts/migrate_modules.py`：
  - Pass 1a 特定语义反转：AI 模块用 `var(--ff-up, #12a150)`（绿=好）与 token `--ff-up=红` 冲突
    改 `var(--ff-down)`（token 绿色）
  - Pass 1b 清理所有 `var(--token, #fallback)` 兜底（兜底都是过期值）
  - Pass 2 裸 HEX 批量替换：旧绿 `#2f7d5b/#1d4e39/#4f9e76` → 品牌蓝；Tailwind 灰阶 → 语义令牌
- 22 个文件改动，硬编码 HEX 853 → 341（其中大部分是 ECharts 字面色值）
- 修复了一个隐藏 bug：「模型可用」状态点原是红色（fallback 覆盖 token），改后变绿色

**修复后（v4.3 实测截图）**：
- AI / Screener / easytdx 全部正确响应暗色模式，与暗色侧边栏融为一体
- 「AI 投研工作台 · 服务状态、快捷指令与最近产出」标题清晰可见
- 品牌色统一为蓝色，Logo 重绘为 `#4f8dff → #2563eb → #1b3fb8` 渐变

**遗留（可接受）**：ScreenerView 与 easytdx 的 ECharts 图表色 `#e11d48/#b45309/#cbd5e1/#64748b` 是字面色值（canvas 渲染不能用 CSS var），按当前 token 值硬编码——准确但不会随主题自动切换。彻底解决需 ECharts 主题切换机制，留待后续专项。

### D2 · 排版与栅格落地率低（高）<span style="color:#059669">✓ v4.2/v4.3 已修复</span>

15 个页面中仅 1 个使用 `.ff-grid`；`.ff-h1~h4` 合计使用 7 次；`.ff-page__header` 定义但 0 使用。各视图自写标题样式，页面间层级不统一。

**建议（v4.4 修订）**：v4.4 起产品决策**不展示可见页面标题**，原「统一 `.ff-page__header` 可见骨架」的建议废止。改用：页面容器 `.ff-page` + 内容区使用 `.ff-h2~h4` 排版类（区块标题层级统一），`h1` 仅作 `sr-only` 保文档语义。

### D3 · AI 与 easytdx 模块设计语言未迁移（高）<span style="color:#059669">✓ v4.3 已修复</span>

**已并入 D1 解决**（同一次 `migrate_modules.py` 批量迁移）。22 个文件改动：
- AI 6 视图 + 6 组件 + ScreenerView 1 文件 + easytdx 12 组件 = 22（去掉 ScreenerView 后的数量已重新计算为 13+3+12+1）

迁移覆盖：
- 60 处品牌色 `#2f7d5b/#1d4e39/#4f9e76` → `var(--ff-brand)` 系列
- 50+37+30 处 Tailwind 灰阶 → 语义令牌
- 61 处 `#fff` → `var(--ff-bg-surface)`
- 23 处旧涨红 `#e5484d` → `var(--ff-up)`（token 值已从 #e5484d 改为 #e11d48）
- 修复 1 处隐藏 bug：AI「模型可用」状态点 var(--ff-up, #12a150) 实际为红（fallback 覆盖 token），改 var(--ff-down)（绿色）

**遗留（已知折中）**：ScreenerView 18 处 ECharts 图表色（`#e11d48/#b45309/#cbd5e1/#64748b` × 12）+ easytdx 6 处 1-off 强调色（`#0ea5a5/#875bf7/#7fb3ff/#6b7785/#f0c040/#c5d0db`）仍为字面值。canvas 渲染无法用 CSS var。彻底解决需 ECharts 主题切换与统一强调色令牌，留待后续专项。

### D4 · 响应式缺口（中）<span style="color:#059669">✓ v4.3 基础断点已补</span>

**修复（v4.3）**：为最严重的 4 个组件补基础断点 ——
- `MarketView`：≤768px 工具栏收窄、表单字段全宽、Tabs 横向滚动
- `IndexKlineCard`：≤768px 图表高度 300→240px
- `EasyTdxDataTable`：≤768px 表格 min-width 720px（在 overflow:auto 容器内横向滚动）
- `EasyTdxResultPanel`：≤768px 文件卡片纵向堆叠

**遗留**：其余 27 个无断点组件（>150 行）仍待逐组件精细化适配（表格冻结列、图表容器查询等），属持续推进型工作，非阻断项。

### D5 · 触控目标过小（中）<span style="color:#059669">✓ v4.3 已修复</span>

**修复（v4.3）**：新增 `.ff-hit` 工具类（`components.css` §16）——通过 `::before { inset: -4px }` 透明扩大命中区，
视觉不变、布局不抖动；`@media (pointer: coarse)` 下再扩到 -6px。已应用到 easytdx 全部 10 处小图标按钮：
`dock__icon-btn`、`palette__close`、`table__pin`、`table__drawer-close`、`nav__scene-icon`、
`rail__collapse`、`rail__item-star`、`picker__chip-x`、`toast__close`、`watch__item-x`。

### D6 · 原始色板与语义层脱钩（低）<span style="color:#059669">✓ v4.3 已修复</span>

**修复（v4.3）**：
- `--p-brand-*` 由森林绿改为 Ocean Blue 色板（`#eff6ff → #2563eb → #172554`），与品牌定蓝一致
- 亮色 `--ff-brand` 系回指 `--p-brand-600/700/800/50/100/200`
- 暗色回指 `--p-brand-500/400/300`（subtle/border 为半透明叠加，保持 rgba）
- 验证：52 项对比度检查 0 未达标（亮色 #2563eb 系、暗色 #3b82f6 系均与原值等价）

### D7 · 异步状态覆盖不全（高 · 投入产出比最高）<span style="color:#059669">✓ v4.3 已闭环</span>

**修正测量误差**：初版审计用「grep AppEmpty/EmptyState」统计空态，遗漏了自定义空态
（`.wb__empty`、`.rv__empty`、`.an__empty`、`.screener-empty` 等 8 种）与嵌套
`<template>` 内的判断。逐视图人工复核后确认：**19/19 视图均有空态处理**。

**v4.3 实际补充**：
- 修复「加载失败」显示为空态的误导：FlashView / ArticlesView / SentimentView
  增加 `err` 状态 + `EmptyState(加载失败) + 重试按钮`
- 约定：数据区三态 = loading(`AppSkeleton`) / empty(`EmptyState` 或模块自定义) /
  error(`EmptyState` + 重试)，主应用统一走 `EmptyState`，模块内自定义空态保留

**遗留**：各模块自定义空态与 `EmptyState` 并存（视觉略不一致），统一为 `AppEmpty`
属低风险打磨项，非阻断。

### D8 · 页面标题层级混乱（高）<span style="color:#059669">✓ v4.2 已修复</span>

**修复前问题**：
- 8 个视图无任何标题标签
- 层级起点不一：StockMonitor 从 `h2`、Screener/Settings/Workbench 从 `h3`
- 8 个视图用原生 `h1~h4` 却不用 `.ff-h*` 排版类

**修复方案**：
- 统一采用 `<header class="ff-page__header"><div class="ff-page__heading"><h1 class="ff-page__title">…</h1><p class="ff-page__desc">…</p></div></header>` 模式
- 沉浸式页面（AnalystView 对话、ReportReaderView 报告阅读）改用 `<h1 class="ff-sr-only">` 保留文档语义，不破坏全屏布局
- AiLayout 是 tab 容器，标题通过 sr-only h1 提供

**当前状态**（v4.4 实测）：19/19 视图均有 h1，0 个视图缺显式标题；**v4.4 起按产品决策，全部视图的 h1 均为 sr-only（可见页头 0/19）**——页面不再显示标题与副标题，读屏/SEO/文档大纲仍可定位。

### D9 · 150 处自写 `<button>` 绕过 AppButton（高）<span style="color:#059669">✓ v4.3 策略性收口</span>

**策略判定（v4.3）**：150 处自写 button 中，主应用只有 6 处（每页 1 处），
其余集中在 AI/Screener/easytdx 模块，且多数是**自定义形态控件**（chips、图标按钮、
Tab、特殊布局按钮），AppButton 的 `variant/size` 体系无法无回归覆盖。

**实际处理**：
- 主应用可直换的已换：FlashView / ArticlesView 的「清除关键词」→ `AppButton variant="ghost" size="sm"`
- 模块自写按钮已在 v4.3 迁移中统一语义令牌，视觉与主应用一致
- 制定按钮使用准则（见 §11 维护准则第 8 条）：**主应用一律 AppButton；模块内
  特殊形态按钮允许自写但必须使用语义令牌，并声明为 scoped 例外**

**对照组**：全项目 **0 处自写 `<svg>`**——图标纪律仍是标杆；按钮的"形态自由 + 令牌约束"
是比"强制统一组件"更务实的治理目标。

---

## 11. 维护准则

1. 新增组件/样式**只准引用语义令牌**（`--ff-*`），禁止硬编码颜色、字号、间距、圆角、阴影、动效参数。
2. 设计令牌变更**必须同提交更新本文档**，并跑 `scripts/ui_audit.py` 确认无新增失效引用。
3. 禁止 `var(--x, #兜底值)` 的兜底写法——它让「令牌未定义」变成静默失败，是深色模式失效的主因。
4. 禁止在模板中使用 emoji；所有图标需求走 `AppIcon`。
5. 禁止 `transition: all`；表单控件边框用 `--ff-border-field`，装饰描边用 `--ff-border`。
6. 品牌资产更新后重跑 `python web/scripts/gen_brand_assets.py`，并提交 `web/public` 下变更。
7. 主题回归以 `/styleguide` 为基准页，切换亮暗后逐块比对。
8. **按钮**：主应用一律 `AppButton`；模块内特殊形态按钮允许自写，但必须使用语义令牌
   并声明为 scoped 例外（见 D9）。可交互元素命中区 ≥24×24，小图标按钮追加 `.ff-hit`。
9. **异步三态**：每个数据区必须明确 loading（`AppSkeleton`）/ empty（`EmptyState` 或模块自定义）/
   error（`EmptyState` + 重试）三种呈现，禁止把「加载失败」显示成「暂无数据」。
