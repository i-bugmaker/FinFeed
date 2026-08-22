<script setup>
// 图表视图：K线 / 走势折线 / 资金曲线，ECharts 渲染（ChartPanel 已处理主题与销毁）
import { computed } from 'vue'
import ChartPanel from '../ChartPanel.vue'
import { columnLabel } from './format'

const props = defineProps({
  result: { type: Object, default: null }, // { type, columns, rows, data }
  func: { type: Object, default: null },
  mode: { type: String, default: 'auto' }, // auto | candle | line | equity
})

function num(v) {
  const n = parseFloat(v)
  return Number.isFinite(n) ? n : 0
}

// 读取主题色（ECharts canvas 无法解析 CSS var，需取实际颜色值）
// A 股惯例：涨=红(--ff-up)，跌=绿(--ff-down)
function themeColor(name, fallback) {
  const v = getComputedStyle(document.documentElement).getPropertyValue(name).trim()
  return v || fallback
}

function buildCandle(t) {
  const cols = t.columns
  const dateIdx = cols.findIndex((c) => /date|datetime|time/i.test(c))
  const oi = cols.findIndex((c) => c.toLowerCase() === 'open')
  const hi = cols.findIndex((c) => c.toLowerCase() === 'high')
  const lo = cols.findIndex((c) => c.toLowerCase() === 'low')
  const ci = cols.findIndex((c) => c.toLowerCase() === 'close')
  if ([dateIdx, oi, hi, lo, ci].some((i) => i < 0)) return null
  const x = t.rows.map((r) => r[dateIdx])
  const data = t.rows.map((r) => [num(r[oi]), num(r[ci]), num(r[lo]), num(r[hi])])
  const up = themeColor('--ff-up', '#f0575c')
  const down = themeColor('--ff-down', '#2bb763')
  return {
    tooltip: {
      trigger: 'axis',
      axisPointer: { type: 'cross' },
      formatter(params) {
        const p = Array.isArray(params) ? params[0] : params
        const d = p.data
        const f = (n) => Number(n).toFixed(2)
        return `${p.axisValue}<br/>开 ${f(d[0])}　收 ${f(d[1])}<br/>低 ${f(d[2])}　高 ${f(d[3])}`
      },
    },
    grid: { left: 50, right: 16, top: 16, bottom: 30 },
    xAxis: { type: 'category', data: x, boundaryGap: true },
    yAxis: { scale: true, axisLabel: { formatter: (v) => Number(v).toFixed(2) } },
    dataZoom: [{ type: 'inside' }, { type: 'slider', height: 16 }],
    series: [
      {
        type: 'candlestick',
        data,
        itemStyle: {
          color: up, // 阳线（涨）红
          color0: down, // 阴线（跌）绿
          borderColor: up,
          borderColor0: down,
        },
      },
    ],
  }
}

function buildLine(t) {
  const cols = t.columns
  const xIdx = cols.findIndex((c) => /date|datetime|time/i.test(c))
  const xi = xIdx >= 0 ? xIdx : 0
  const x = t.rows.map((r) => r[xi])
  const numeric = cols
    .map((c, i) => ({ c, i }))
    .filter(({ c, i }) => i !== xi && /open|high|low|close|vol|amount|price|pct|value|ratio|net/i.test(c))
    .slice(0, 6)
  const series = numeric.map(({ c, i }) => ({
    name: columnLabel(c),
    type: 'line',
    showSymbol: false,
    smooth: true,
    data: t.rows.map((r) => num(r[i])),
  }))
  return {
    tooltip: { trigger: 'axis' },
    legend: { data: series.map((s) => s.name) },
    grid: { left: 56, right: 16, top: 36, bottom: 30 },
    xAxis: { type: 'category', data: x, boundaryGap: false },
    yAxis: { scale: true },
    dataZoom: [{ type: 'inside' }, { type: 'slider', height: 16 }],
    series,
  }
}

function buildEquity(data) {
  const eq = Array.isArray(data) ? data : []
  if (!eq.length) return null
  const x = eq.map((r) => r.datetime || r.date || r.index || '')
  const maps = [
    ['total', '总资产'],
    ['cash', '现金'],
    ['position_value', '持仓市值'],
    ['drawdown', '回撤'],
  ]
  const series = []
  for (const [k, label] of maps) {
    if (k in eq[0]) {
      series.push({
        name: label,
        type: 'line',
        showSymbol: false,
        smooth: true,
        data: eq.map((r) => num(r[k])),
      })
    }
  }
  if (!series.length) return null
  return {
    tooltip: {
      trigger: 'axis',
      valueFormatter: (v) => Number(v).toLocaleString('zh-CN', { maximumFractionDigits: 2 }),
    },
    legend: { data: series.map((s) => s.name) },
    grid: { left: 70, right: 16, top: 36, bottom: 30 },
    xAxis: { type: 'category', data: x, boundaryGap: false },
    yAxis: {
      scale: true,
      axisLabel: { formatter: (v) => Number(v).toLocaleString('zh-CN', { maximumFractionDigits: 0 }) },
    },
    series,
  }
}

const option = computed(() => {
  if (!props.result) return null
  if (props.mode === 'equity') return buildEquity(props.result?.data?.equity)
  if (props.result.type === 'table') {
    if (props.mode === 'candle' || (props.mode === 'auto' && props.func?.chart === 'candle')) {
      return buildCandle(props.result)
    }
    return buildLine(props.result)
  }
  if (props.result.type === 'json') return buildEquity(props.result.data?.equity)
  return null
})
</script>

<template>
  <div v-if="option" class="etdx-chart">
    <ChartPanel :option="option" height="340px" />
  </div>
</template>

<style scoped>
.etdx-chart {
  width: 100%;
}
</style>
