/**
 * useChartTheme — ECharts 统一主题出口
 *
 * 背景：ECharts 渲染在 canvas 上，无法消费 CSS 变量（--ff-* 语义令牌）。
 * 所有图表颜色必须经 getComputedStyle 解析语义令牌，并在主题切换后重渲染。
 *
 * 用法：
 *   import { chartVar, hexToRgba, axisLabelStyle, chartBaseTheme, useChartTheme } from '@/composables/useChartTheme'
 *
 *   // setup 内注册主题切换重绘（组件卸载自动随作用域销毁）：
 *   useChartTheme(() => render())   // render() 内部重新调用 chartVar() 取色
 *
 * 约定：任何新增 ECharts 组件不得硬编码颜色，一律走 chartVar()；
 *       通用底座配色直接混入 chartBaseTheme()。
 */
import { watch, nextTick } from 'vue'
import { useAppStore } from '@/store/app'

/** 解析语义令牌为实际颜色值；令牌缺失或解析失败时返回 fallback。 */
export function chartVar(name, fallback) {
  try {
    const v = getComputedStyle(document.documentElement).getPropertyValue(name).trim()
    return v || fallback
  } catch {
    return fallback
  }
}

/** #rrggbb → rgba(r, g, b, a)；非法输入回退品牌蓝。 */
export function hexToRgba(hex, alpha) {
  const m = /^#?([0-9a-f]{6})$/i.exec(hex || '')
  if (!m) return `rgba(37, 99, 235, ${alpha})`
  const n = parseInt(m[1], 16)
  return `rgba(${(n >> 16) & 255}, ${(n >> 8) & 255}, ${n & 255}, ${alpha})`
}

/** 图表文字字号地板：canvas 渲染无浏览器最小字号兜底，轴标/图例 ≥11px 保证可读。 */
export function chartFont(px = 11) {
  return Math.max(11, Math.round(px))
}

/** 常用坐标轴标签样式（统一 11px / 次级文本色）。 */
export function axisLabelStyle() {
  return { fontSize: chartFont(11), color: chartVar('--ff-text-secondary', '#475569') }
}

/**
 * 图表通用底座 option 片段：文字 / 标题 / 图例 / tooltip / 坐标轴。
 * 深合并由使用方保证（ChartPanel 采用浅覆盖，业务 option 同名字段优先）。
 */
export function chartBaseTheme() {
  const text = chartVar('--ff-text-primary', '#0f172a')
  const muted = chartVar('--ff-text-secondary', '#475569')
  const border = chartVar('--ff-border', '#e2e8f0')
  const subtle = chartVar('--ff-bg-subtle', '#f8fafc')
  return {
    backgroundColor: 'transparent',
    textStyle: { color: text },
    title: { textStyle: { color: text }, subtextStyle: { color: muted } },
    legend: { textStyle: { color: muted } },
    tooltip: {
      backgroundColor: chartVar('--ff-bg-surface', '#ffffff'),
      borderColor: border,
      textStyle: { color: text },
    },
    xAxis: {
      axisLine: { lineStyle: { color: border } },
      axisLabel: { color: muted },
      splitLine: { lineStyle: { color: subtle } },
    },
    yAxis: {
      axisLine: { lineStyle: { color: border } },
      axisLabel: { color: muted },
      splitLine: { lineStyle: { color: subtle } },
    },
  }
}

/**
 * 主题切换时重绘图表。renderFn 应重新取色并 setOption。
 * watch 随组件 setup 作用域自动销毁，无需手动清理。
 */
export function useChartTheme(renderFn) {
  const appStore = useAppStore()
  watch(
    () => appStore.theme,
    () => nextTick(renderFn),
  )
}
