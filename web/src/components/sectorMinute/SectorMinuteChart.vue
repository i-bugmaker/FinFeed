<script setup>
/**
 * SectorMinuteChart — 单标的分时图（板块 / 个股通用）
 *
 * 要素：分时价格线（涨跌配色）· 均价线 · 昨收基准虚线 · 底部成交量柱 ·
 *       Y 轴双模式（绝对价格 / 涨跌幅归一化）· 午间休市标记 · 悬停联动。
 */
import { ref, watch, onMounted, onUnmounted, nextTick, computed } from 'vue'
import { echarts } from '@/shared/lib/echarts'
import AppIcon from '../../ui/AppIcon.vue'

const props = defineProps({
  chart: { type: Object, default: null },
  normalized: { type: Boolean, default: true }, // Y 轴：涨跌幅归一化 / 绝对价格
  showAvg: { type: Boolean, default: true },    // 显示均价线
  showPreClose: { type: Boolean, default: true }, // 显示昨收线
  theme: { type: String, default: 'light' },
  hoverIndex: { type: Number, default: -1 },    // 外部联动悬停索引（-1 = 不联动）
  compact: { type: Boolean, default: false },   // 紧凑模式（无图表头，仅画图）
})

const emit = defineEmits(['remove', 'hover'])

const el = ref(null)
let chartIns = null // ECharts 实例（勿与模板 props.chart 混淆，避免变量名遮蔽）
let ro = null
let selfHover = false // 防止联动回环

function themeColor(name) {
  return (
    getComputedStyle(document.documentElement).getPropertyValue(name).trim() ||
    undefined
  )
}

// 涨跌状态
const state = computed(() => {
  const c = props.chart
  if (!c) return { cls: '', up: false }
  const up = c.change_pct > 0
  return { cls: up ? 'is-up' : c.change_pct < 0 ? 'is-down' : 'is-flat', up }
})

const fmtPct = (v) =>
  v === null || v === undefined || !Number.isFinite(v)
    ? '—'
    : (v > 0 ? '+' : '') + v.toFixed(2) + '%'
const fmtNum = (v, d = 2) =>
  v === null || v === undefined || !Number.isFinite(v) ? '—' : v.toFixed(d)
const fmtVol = (v) => {
  if (!v && v !== 0) return '—'
  if (v >= 1e8) return (v / 1e8).toFixed(2) + '亿'
  if (v >= 1e4) return (v / 1e4).toFixed(1) + '万'
  return String(v)
}

// 构建 ECharts option
function buildOption() {
  const c = props.chart
  const points = c?.points || []
  const pre_close = c?.pre_close || 0
  const up = (c?.change_pct || 0) > 0

  const times = points.map((p) => p.time.slice(0, 5))
  const prices = points.map((p) => p.price)
  const avgs = points.map((p) => p.avg || null)
  const vols = points.map((p) => p.vol || 0)
  const pcts = prices.map((p) =>
    pre_close > 0 ? ((p - pre_close) / pre_close) * 100 : 0
  )

  const upColor = themeColor('--ff-chart-up') || '#e5484d'
  const downColor = themeColor('--ff-chart-down') || '#12a150'
  const axisColor = themeColor('--ff-chart-axis') || '#e7e2d8'
  const textColor = themeColor('--ff-text-primary') || '#23332b'
  const mutedColor = themeColor('--ff-text-secondary') || '#5c6b60'
  const lineColor = up ? upColor : downColor
  const avgColor = themeColor('--ff-chart-primary-2') || '#0ea5a5'
  const preColor = themeColor('--ff-text-tertiary') || '#968d7c'
  const volNeutral = themeColor('--ff-chart-neutral') || '#697586'

  // 午间休市标记：11:30 → 13:00
  const lunchStart = times.findIndex((t) => t >= '11:30')
  const lunchEnd = times.findIndex((t) => t >= '13:00')
  const lunchArea =
    lunchStart >= 0 && lunchEnd > lunchStart
      ? [{ name: '午间休市', xAxis: times[lunchStart], itemStyle: { color: 'rgba(128,128,128,0.06)' } },
         { xAxis: times[lunchEnd] }]
      : null

  // Y 轴取值：归一化模式用涨跌幅（对称边界），绝对价格用价格
  let yData = prices
  let yMin = null
  let yMax = null
  if (props.normalized) {
    yData = pcts
    const maxAbs = Math.max(Math.max(...pcts.map((v) => Math.abs(v))), 2)
    yMin = -maxAbs
    yMax = maxAbs
  } else {
    const vals = prices.filter((v) => Number.isFinite(v))
    if (vals.length) {
      const lo = Math.min(...vals)
      const hi = Math.max(...vals)
      const pad = Math.max((hi - lo) * 0.15, pre_close * 0.002)
      yMin = lo - pad
      yMax = hi + pad
    }
  }

  const markLine = props.showPreClose
    ? {
        silent: true,
        symbol: 'none',
        label: {
          show: true,
          formatter: props.normalized ? '昨收 0.00%' : '昨收 ' + fmtNum(pre_close),
          color: preColor,
          fontSize: 10,
          position: 'insideEndTop',
        },
        lineStyle: { color: preColor, type: 'dashed', width: 1 },
        data: [{ yAxis: props.normalized ? 0 : pre_close }],
      }
    : undefined

  const commonAxis = {
    axisLine: { lineStyle: { color: axisColor } },
    axisLabel: { color: mutedColor, fontSize: 10 },
    splitLine: { lineStyle: { color: axisColor, opacity: 0.35 } },
  }

  return {
    backgroundColor: 'transparent',
    animation: false,
    axisPointer: {
      link: [{ xAxisIndex: 'all' }],
      label: { backgroundColor: themeColor('--ff-bg-inverse') || '#202939' },
    },
    tooltip: {
      trigger: 'axis',
      confine: true,
      backgroundColor: themeColor('--ff-bg-surface') || '#ffffff',
      borderColor: themeColor('--ff-border') || '#e7e2d8',
      textStyle: { color: textColor, fontSize: 12 },
      formatter(params) {
        const i = params[0]?.dataIndex ?? 0
        const p = points[i]
        if (!p) return ''
        const pct = pre_close > 0 ? ((p.price - pre_close) / pre_close) * 100 : 0
        const dir = pct > 0 ? upColor : pct < 0 ? downColor : mutedColor
        const sign = pct > 0 ? '+' : ''
        return [
          `<div style="font-weight:600;margin-bottom:4px">${p.time}</div>`,
          `价格 <b style="color:${dir}">${fmtNum(p.price)}</b>  <span style="color:${dir}">${sign}${pct.toFixed(2)}%</span>`,
          props.showAvg && p.avg ? `均价 ${fmtNum(p.avg)}` : '',
          `量 ${fmtVol(p.vol * 100)}`,
        ]
          .filter(Boolean)
          .join('<br/>')
      },
    },
    grid: [
      { left: 46, right: 12, top: 8, height: '62%' },
      { left: 46, right: 12, top: '78%', height: '16%' },
    ],
    xAxis: [
      {
        type: 'category',
        data: times,
        boundaryGap: false,
        axisLine: { lineStyle: { color: axisColor } },
        axisLabel: { color: mutedColor, fontSize: 10, interval: Math.max(1, Math.floor(times.length / 5) - 1) },
        axisTick: { show: false },
        splitLine: { show: false },
        markArea: lunchArea ? { silent: true, data: lunchArea } : undefined,
      },
      { type: 'category', data: times, show: false, gridIndex: 1 },
    ],
    yAxis: [
      {
        type: 'value',
        min: yMin,
        max: yMax,
        scale: true,
        axisLabel: {
          color: mutedColor,
          fontSize: 10,
          formatter: (v) => (props.normalized ? v.toFixed(1) + '%' : fmtNum(v)),
        },
        splitLine: {
          lineStyle: { color: axisColor, opacity: 0.35 },
        },
        ...(props.showPreClose && !props.normalized
          ? {
              axisLine: { show: false },
              splitLine: {
                lineStyle: { color: axisColor, opacity: 0.35 },
              },
            }
          : {}),
      },
      { type: 'value', show: false, gridIndex: 1 },
    ],
    series: [
      {
        name: '价格',
        type: 'line',
        data: props.normalized ? pcts : prices,
        showSymbol: false,
        smooth: false,
        lineStyle: { width: 1.5, color: lineColor },
        itemStyle: { color: lineColor },
        markLine,
        z: 3,
      },
      props.showAvg && {
        name: '均价',
        type: 'line',
        data: props.normalized
          ? avgs.map((v) => (v && pre_close > 0 ? ((v - pre_close) / pre_close) * 100 : null))
          : avgs,
        showSymbol: false,
        lineStyle: { width: 1, color: avgColor, opacity: 0.85 },
        itemStyle: { color: avgColor },
        z: 2,
      },
      {
        name: '成交量',
        type: 'bar',
        xAxisIndex: 1,
        yAxisIndex: 1,
        data: vols.map((v, i) => ({
          value: v,
          itemStyle: {
            color:
              pcts[i] > 0 ? upColor : pcts[i] < 0 ? downColor : volNeutral,
            opacity: pcts[i] === 0 ? 0.45 : 0.75,
          },
        })),
        barWidth: '70%',
      },
    ].filter(Boolean),
  }
}

function render() {
  if (!chartIns || !props.chart) return
  chartIns.setOption(buildOption(), true)
}

function resize() {
  chartIns && chartIns.resize()
}

// 外部联动：高亮到指定索引
function applyHover(i) {
  if (!chartIns || !props.chart) return
  const idx = Math.max(0, Math.min(i, (props.chart.points || []).length - 1))
  selfHover = true
  chartIns.dispatchAction({ type: 'showTip', seriesIndex: 0, dataIndex: idx })
  setTimeout(() => (selfHover = false), 60)
}

onMounted(async () => {
  await nextTick()
  if (!el.value) return
  chartIns = echarts.init(el.value, null, { renderer: 'canvas' })
  render()
  window.addEventListener('resize', resize)
  ro = new ResizeObserver(resize)
  if (el.value) ro.observe(el.value)
  // 本图悬停 → 通知外部联动
  chartIns.on('updateAxisPointer', (evt) => {
    if (selfHover) return
    const di = evt.axesInfo?.[0]?.value
    if (typeof di === 'number') emit('hover', di)
  })
})

onUnmounted(() => {
  window.removeEventListener('resize', resize)
  ro && ro.disconnect()
  chartIns && chartIns.dispose()
  chartIns = null
})

watch(
  () => [props.chart, props.normalized, props.showAvg, props.showPreClose, props.theme],
  () => render(),
  { deep: false },
)
watch(
  () => props.hoverIndex,
  (v) => {
    if (v >= 0 && !selfHover) applyHover(v)
  },
)
</script>

<template>
  <div class="smic" :class="state.cls">
    <!-- 图头 -->
    <div v-if="!compact" class="smic__head">
      <span class="smic__badge" :class="props.chart?.kind === 'stock' ? 'is-stock' : props.chart?.kind === 'index' ? 'is-index' : 'is-board'">
        {{ props.chart?.kind === 'stock' ? '股' : props.chart?.kind === 'index' ? '指' : '板' }}
      </span>
      <span class="smic__name" :title="props.chart?.code">{{ props.chart?.name || props.chart?.code || '—' }}</span>
      <span class="smic__code" v-if="props.chart?.code">{{ props.chart?.code }}</span>
      <span class="smic__sp"></span>
      <template v-if="props.chart">
        <span class="smic__price">{{ fmtNum(props.chart.close) }}</span>
        <span class="smic__pct">{{ fmtPct(props.chart.change_pct) }}</span>
        <span class="smic__amt">{{ props.chart.change_amt > 0 ? '+' : '' }}{{ fmtNum(props.chart.change_amt) }}</span>
      </template>
      <button
        type="button"
        class="smic__close"
        title="从对比列表移除"
        @click="emit('remove')"
      >
        <AppIcon name="x" size="sm" />
      </button>
    </div>
    <div class="smic__canvas">
      <div v-if="!props.chart?.points?.length" class="smic__loading">
        <AppIcon name="refresh" size="sm" spin />
        <span>加载中…</span>
      </div>
      <div ref="el" class="smic__chart"></div>
    </div>
  </div>
</template>

<style scoped>
.smic {
  display: flex;
  flex-direction: column;
  gap: 4px;
  width: 100%;
  height: 100%;
  min-height: 0;
}
.smic.is-up { --smic-c: var(--ff-up-text); }
.smic.is-down { --smic-c: var(--ff-down-text); }
.smic.is-flat { --smic-c: var(--ff-text-secondary); }

.smic__head {
  flex: none;
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: var(--ff-fs-caption);
  min-height: 26px;
}
.smic__badge {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  min-width: 20px;
  height: 20px;
  padding: 0 4px;
  border-radius: var(--ff-radius-xs);
  font-size: 11px;
  font-weight: 700;
  color: #fff;
}
.smic__badge.is-board { background: var(--ff-brand); }
.smic__badge.is-stock { background: var(--ff-accent-teal); }
.smic__badge.is-index { background: var(--ff-accent-violet, #7c5cd6); }
.smic__name {
  font-weight: 600;
  color: var(--ff-text-primary);
  max-width: 140px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.smic__code {
  font-family: var(--ff-font-mono, monospace);
  color: var(--ff-text-tertiary);
  font-size: 11px;
}
.smic__sp { flex: 1; }
.smic__price {
  font-family: var(--ff-font-mono, monospace);
  font-weight: 700;
  color: var(--smic-c, var(--ff-text-primary));
  font-size: var(--ff-fs-data);
  font-variant-numeric: tabular-nums;
}
.smic__pct {
  font-family: var(--ff-font-mono, monospace);
  font-weight: 600;
  color: var(--smic-c, var(--ff-text-primary));
  font-variant-numeric: tabular-nums;
}
.smic__amt {
  font-family: var(--ff-font-mono, monospace);
  color: var(--ff-text-tertiary);
  font-size: 11px;
  font-variant-numeric: tabular-nums;
}
.smic__close {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 22px;
  height: 22px;
  border-radius: var(--ff-radius-sm);
  color: var(--ff-icon-muted);
  flex: none;
  transition: background var(--ff-dur-fast), color var(--ff-dur-fast);
}
.smic__close:hover {
  background: var(--ff-bg-hover);
  color: var(--ff-text-primary);
}
.smic__canvas {
  position: relative;
  flex: 1;
  min-height: 0;
  width: 100%;
}
.smic__loading {
  position: absolute;
  inset: 0;
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 6px;
  color: var(--ff-text-tertiary);
  font-size: var(--ff-fs-caption);
  z-index: 1;
}
.smic__chart {
  position: absolute;
  inset: 0;
}

/* ── 移动端适配（D4 · 根容器自适应）── */
@media (max-width: 768px) {
  .smic {
    max-width: 100%;
  }
  .smic > * {
    min-width: 0;
  }
}
</style>
