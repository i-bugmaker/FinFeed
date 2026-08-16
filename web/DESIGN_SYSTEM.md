# FinFeed Web UI 3.0 设计系统

> 版本：3.0
> 适用范围：`web/src` 下全部 Vue 组件与样式
> 设计目标：移除所有 emoji，统一专业矢量图标；自绘全部交互组件；建立可维护的设计令牌体系；支持响应式与深色模式。

---

## 1. 文件位置

| 文件 | 说明 |
|------|------|
| `web/src/styles/tokens.css` | 设计令牌源文件（颜色、字体、间距、圆角、阴影、动画、z-index） |
| `web/src/styles/base.css` | 基础层（reset、排版辅助、12 列栅格、滚动条、全局动画） |
| `web/src/styles/components.css` | 组件样式库（按钮、输入框、下拉、日期、表格、分页、弹窗、加载态等） |
| `web/src/styles/news-table.css` | 旧版新闻表格样式（保留兼容，逐步迁移到 `.ff-table`） |
| `web/src/ui/icons.js` | 全站图标 SVG 路径集合 |
| `web/src/ui/AppIcon.vue` | 图标渲染组件 |
| `web/src/ui/AppLogo.vue` | 品牌 LOGO 组件（mark / wordmark / combined） |
| `web/src/ui/AppButton.vue` | 按钮 |
| `web/src/ui/AppInput.vue` | 输入框 |
| `web/src/ui/AppSelect.vue` | 下拉选择器 |
| `web/src/ui/AppDatePicker.vue` | 日期选择器 |
| `web/src/ui/AppCheckbox.vue` / `AppSwitch.vue` | 复选框 / 开关 |
| `web/src/ui/AppModal.vue` / `AppDrawer.vue` | 弹窗 / 抽屉 |
| `web/src/ui/AppPagination.vue` | 分页 |
| `web/src/ui/AppSegmented.vue` / `AppTabs.vue` | 分段控制器 / 标签页 |
| `web/src/ui/AppTooltip.vue` | 文字提示 |
| `web/src/ui/AppSkeleton.vue` | 骨架屏 |
| `web/src/ui/AppEmpty.vue` | 空状态 |
| `web/src/ui/AppCard.vue` | 卡片容器 |
| `web/src/ui/AppBadge.vue` / `AppStatus.vue` | 徽标 / 状态点 |
| `web/src/ui/index.js` | 统一组件出口 |
| `web/public/logo.svg` / `favicon.svg` / `logo-lockup.svg` | 品牌矢量源文件 |
| `web/scripts/gen_brand_assets.py` | 品牌栅格资产生成器 |
| `web/src/views/StyleGuideView.vue` | `/styleguide` 设计规范预览页 |
| `web/DESIGN_SYSTEM.md` | 本文档 |

---

## 2. 命名约定

### 2.1 设计令牌：`--ff-<类别>-<角色>-<变体>`

```
--ff-bg-canvas          /* 页面背景 */
--ff-bg-surface         /* 卡片/面板背景 */
--ff-text-primary       /* 主文本 */
--ff-text-secondary     /* 次级文本 */
--ff-border-hover       /* 边框悬停态 */
--ff-border-focus       /* 边框聚焦态 */
--ff-shadow-md          /* 中号阴影 */
--ff-space-4            /* 16px 间距 */
--ff-radius-lg          /* 12px 圆角 */
--ff-dur-fast           /* 150ms 动画时长 */
--ff-z-popover          /* 弹窗层级 */
```

### 2.2 CSS 类名：`.ff-<组件>-<元素>--<变体>`

```
.ff-btn
.ff-btn--primary
.ff-btn--loading
.ff-input__affix--prefix
.ff-table__row--unread
```

### 2.3 组件前缀

所有自定义组件均以 `App` 开头注册为全局组件，模板中可直接使用 `<AppButton />`。

---

## 3. 主题与色彩

### 3.1 品牌色

- 主色：`#2563eb`（Cobalt 600）
- 浅色：`#4f8dff`
- 深色：`#1b3fb8`

### 3.2 市场语义色（红涨绿跌）

- 上涨 / 利好：`#e5484d` → `--ff-chart-up`, `--ff-text-up`
- 下跌 / 利空：`#12a150` → `--ff-chart-down`, `--ff-text-down`
- 中性：`#9ca3af`

### 3.3 深色模式

在 `store/app.js` 中切换 `data-theme="light|dark"` 属性。全部令牌在 `tokens.css` 中通过 `[data-theme="dark"]` 提供对应值。

### 3.4 字体系统 (Typography)

字体令牌集中在 `tokens.css` 第 2 节，排版工具类在 `base.css` 第 2 节。核心约定：

- **双语混合排版**：西文走 `Inter`，CJK 自动回退到苹方 / 鸿蒙 / 微软雅黑 / 思源黑体；浏览器逐字选择首个可渲染字体。数据数字统一走 `JetBrains Mono` + 表格数字（`tabular-nums`），保证列对齐。
- **模块化字号刻度（1.2）**：`display 32 · 2xl 26 · h1 24 · h2 19 · h3 17 · h4 16 · body-lg 17 · body 15 · body-sm 14 · caption 13 · overline 11.5`，数据字号 `18 / 15 / 13`。
- **角色化组合**：每个文字角色 = 字号 + 字重 + 行高 + 字距 的固定组合，对应工具类：

  | 角色 | 类 | 字号 | 字重 | 行高 | 字距 | 用途 |
  |------|----|------|------|------|------|------|
  | 展示标题 | `.ff-display` | 32 | 700 | 1.15 | -0.02em | Hero / 落地页 |
  | 超大数字 | `.ff-2xl` | 26 | 700 | 1.25 | -0.014em | 统计数字 |
  | 页面标题 | `.ff-h1` | 24 | 700 | 1.25 | -0.014em | 页面主标题 |
  | 区块标题 | `.ff-h2` | 19 | 600 | 1.30 | -0.014em | 区块标题 |
  | 子区块标题 | `.ff-h3` | 17 | 600 | 1.35 | -0.008em | 子区块标题 |
  | 卡片标题 | `.ff-h4` | 16 | 600 | 1.40 | -0.008em | 卡片标题 |
  | 导语 | `.ff-lede` | 17 | 500 | 1.65 | body | 正文强调 |
  | 正文 | `.ff-body` | 15 | 400 | 1.60 | body | 正文基准 |
  | 辅助正文 | `.ff-body-sm` | 14 | 400 | 1.55 | body | 列表 / 说明 |
  | 标注 | `.ff-caption` | 13 | 400 | 1.50 | body | 脚注 / 标注 |
  | 标签 | `.ff-label` | 13 | 600 | 1.50 | 0.04em | 栏目眉题 |
  | 眉题 | `.ff-overline` | 11.5 | 700 | 1.40 | 0.09em | 大写拉丁眉题 |
  | 数据数字 | `.ff-num` (+`--lg/--sm`) | 15/18/13 | 500 | — | 0 | 价格 / 涨跌幅 |

- **亮暗字体渲染适配**：
  - 亮色：`--ff-font-smoothing: subpixel-antialiased`（亚像素，边缘锐利、字重饱满）。
  - 暗色：`--ff-font-smoothing: antialiased`（灰度，避免彩边与大面积光晕）；同时正文追踪 `--ff-ls-body` 由 `-0.006em` 放宽到 `0`，缓解 CJK 在暗背景下的拥挤感。
  - 全局 `font-synthesis: none` 禁止伪粗体 / 伪斜体（CJK 无斜体），`font-optical-sizing: auto` 启用可变字体光学尺寸。
- **Web 字体**：`index.html` 通过 `preconnect` + `display=swap` 加载 Inter 与 JetBrains Mono，系统字体为回退，离线 / 弱网下不阻塞渲染。
- **预览验收**：访问 `/styleguide` 的「字体层级」「数据字体」卡片，切换亮暗主题核对对比度与对齐。

---

## 4. 栅格系统

`base.css` 提供 12 列响应式栅格：

```html
<div class="ff-grid">
  <div class="ff-col-12 ff-col-lg-6">…</div>
  <div class="ff-col-12 ff-col-lg-6">…</div>
</div>
```

断点：

- `sm`：640px
- `md`：768px
- `lg`：1024px
- `xl`：1280px

---

## 5. 图标系统

全站图标统一来自 `web/src/ui/icons.js`，通过 `<AppIcon name="xxx" />` 使用。规范：

- 画布 24×24，安全区 2px
- `stroke="currentColor"`，支持通过父级 color / `tone` prop 变色
- 描边端点与拐角均为 round
- 多尺寸：`xs` 14px / `sm` 16px / `md` 18px / `lg` 20px / `xl` 24px

新增图标只需在 `icons.js` 中追加键值对并在 `ICON_NAMES` 中登记。

---

## 6. 品牌标识

品牌 LOGO 为圆角方形徽章，内含上升折线与实时节点，寓意「财经数据流 + 实时信号」。

### 6.1 输出资产

运行 `python web/scripts/gen_brand_assets.py` 生成：

- `favicon-16.png`, `favicon-32.png`, `favicon-48.png`
- `favicon.ico`（16/32/48 三分辨率）
- `icon-64.png` ~ `icon-512.png`
- `apple-touch-icon.png`
- `maskable-192.png`, `maskable-512.png`
- `og-image.png`
- `brand/logo-glyph-512.png`

### 6.2 使用方式

- 网页 `index.html` 已引用 `/favicon.svg`、PNG fallback、`manifest.webmanifest` 与 OG 图
- 应用内使用 `<AppLogo mode="combined" :size="34" />`

---

## 7. 改动范围摘要

1. **图标与品牌标识**
   - 移除全部 emoji，替换为 `AppIcon` 矢量图标
   - 新增 FinFeed 品牌 LOGO 与多尺寸 favicon / PWA / OG 资产

2. **组件自定义**
   - 新增 18 个 Vue 组件覆盖按钮、输入框、下拉、日期、复选、开关、弹窗、抽屉、分页、分段、标签、提示、骨架、空状态、卡片、徽标、状态
   - `components.css` 覆盖全部状态：default / hover / focus / active / disabled / error / loading / readonly
   - 自定义滚动条、表单控件、表格、分页、弹窗动画

3. **布局重构**
   - `App.vue` 改为响应式布局：桌面固定侧边栏 + 移动端抽屉
   - `Sidebar.vue` / `TopBar.vue` 使用新令牌与图标
   - 各视图统一使用 `.ff-page`、`.ff-page__header`、`.ff-grid`、`.ff-card`

4. **设计规范落地**
   - `tokens.css` 为 Single Source of Truth
   - `base.css` 提供 reset、排版、栅格、动画
   - `components.css` 提供全量组件样式
   - 全局注册 `App*` 组件，业务代码无需逐一手动 import
   - 新增 `/styleguide` 路由用于预览与验收

---

## 8. 后续维护建议

- 新增组件时优先使用 `--ff-*` 令牌，避免硬编码颜色/尺寸
- 不要在模板中直接写 emoji；所有图标需求走 `AppIcon`
- 需要复杂表单校验可扩展 `AppInput` 的 `error` slot；需要弹窗表单优先使用 `AppModal`
- 品牌资产更新后重新运行 `gen_brand_assets.py`，并提交 `web/public` 下变更
