<script setup>
import { ref, computed, watch, onMounted, onUnmounted } from 'vue'
import { api } from '../api/client'
import ChartPanel from './ChartPanel.vue'
import EmptyState from './EmptyState.vue'
import AppSkeleton from '../ui/AppSkeleton.vue'
import AppIcon from '../ui/AppIcon.vue'

const props = defineProps({
  code: { type: String, required: true },
  name: { type: String, required: true },
})

// 周期：分时 + 日/周/月/季/年 K
const PERIODS = [
  { key: 'trends', label: '分时', type: 'trends', klt: null },
  { key: 'day', label: '日K', type: 'kline', klt: 101 },
  { key: 'week', label: '周K', type: 'kline', klt: 102 },
  { key: 'month', label: '月K', type: 'kline', klt: 103 },
  { key: 'quarter', label: '季K', type: 'kline', klt: 104 },
  { key: 'year', label: '年K', type: 'kline', klt: 105 },
]

// 预设快捷区间（按周期自适应根数）
const RANGES = [
  { label: '近1月', lmt: { day: 20, week: 4, month: 1, quarter: 1, year: 1 } },
  { label: '近3月', lmt: { day: 60, week: 13, month: 3, quarter: 1, year: 1 } },
  { label: '近1年', lmt: { day: 250, week: 52, month: 12, quarter: 4, year: 1 } },
  { label: '近3年', lmt: { day: 750, week: 156, month: 36, quarter: 12, year: 3 } },
  { label: '全部', lmt: { day: 1500, week: 520, month: 240, quarter: 80, year: 30 } },
  { label: '自定义', custom: true },
]

const period = ref('day')
const range = ref('近1年')
const customStart = ref('')
const customEnd = ref('')
const loading = ref(false)
const error = ref('')
const reason = ref('ok')
const rows = ref([])

// 限流态自动重试：后端 em_push2his 冷却为 600s（10 分钟），
// 冷却期内重试零成本（后端直接短路），冷却结束后即命中真实数据。
const RETRY_MS = 60_000
let retryTimer = null
function clearRetry() {
  if (retryTimer) {
    clearInterval(retryTimer)
    retryTimer = null
  }
}
function scheduleRetry() {
  clearRetry()
  if (reason.value === 'rate_limited') {
    retryTimer = setInterval(load, RETRY_MS)
  }
}

const currentPeriod = computed(() => PERIODS.find((p) => p.key === period.value) || PERIODS[1])
const isTrends = computed(() => currentPeriod.value.type === 'trends')

// ECharts canvas 无法解析 CSS 变量，须取具体色值
function chartVar(name) {
  return getComputedStyle(document.documentElement).getPropertyValue(name).trim() || undefined
}

function lmtFor() {
  const map = RANGES.find((r) => r.label === range.value)?.lmt || RANGES[2].lmt
  return map[currentPeriod.value.key] || 120
}

function onRange(rg) {
  range.value = rg.label
  // 进入自定义区间时给一组合理默认值（近一年），避免空区间
  if (rg.custom && !customEnd.value) {
    const t = new Date()
    const y = new Date(t)
    y.setFullYear(y.getFullYear() - 1)
    customEnd.value = t.toISOString().slice(0, 10)
    customStart.value = y.toISOString().slice(0, 10)
  }
}

async function load() {
  loading.value = true
  error.value = ''
  reason.value = 'ok'
  try {
    const p = currentPeriod.value
    const params = { code: props.code }
    if (p.type === 'trends') {
      params.type = 'trends'
      params.ndays = 1
    } else {
      params.type = 'kline'
      params.klt = p.klt
      if (range.value === '自定义') {
        params.start = customStart.value || undefined
        params.end = customEnd.value || undefined
        params.lmt = 2000
      } else {
        params.lmt = lmtFor()
      }
    }
    const r = await api.market('kline', params)
    // 兼容新结构 {rows, reason} 与旧纯数组
    const d = r && r.data
    rows.value = d && Array.isArray(d.rows)
      ? d.rows
      : (Array.isArray(d) ? d : [])
    reason.value = (d && d.reason) || 'ok'
    if (reason.value === 'error' && d && d.error) {
      error.value = `拉取失败：${d.error}`
    } else {
      error.value = ''
    }
  } catch (e) {
    error.value = (e && e.message) || '加载失败'
    rows.value = []
    reason.value = 'error'
  } finally {
    loading.value = false
    scheduleRetry()
  }
}

const option = computed(() => {
  const data = rows.value || []
  if (!data.length) return {}

  if (isTrends.value) {
    const times = data.map((d) => (d.time || '').slice(11))
    const prices = data.map((d) => d.price)
    const avgs = data.map((d) => d.avg_price)
    const base = prices[0] || 0
    const up = prices[prices.length - 1] >= base
    const lineColor = chartVar(up ? '--ff-chart-up' : '--ff-chart-down')
    return {
      tooltip: { trigger: 'axis', formatter: (ps) => {
        const t = ps[0]?.axisValue || ''
        const price = ps.find((x) => x.seriesName === '价格')?.value
        const avg = ps.find((x) => x.seriesName === '均价')?.value
        return `${t}<br/>价格：${price}<br/>均价：${avg}`
      } },
      grid: { left: 56, right: 16, top: 16, bottom: 28 },
      xAxis: {
        type: 'category',
        data: times,
        boundaryGap: false,
        axisLabel: { hideOverlap: true, color: chartVar('--ff-text-tertiary'), fontSize: 10 },
        axisLine: { lineStyle: { color: chartVar('--ff-border') } },
      },
      yAxis: {
        scale: true,
        type: 'value',
        splitLine: { lineStyle: { type: 'dashed', color: chartVar('--ff-bg-subtle') } },
        axisLabel: { color: chartVar('--ff-text-tertiary'), fontSize: 10 },
      },
      series: [
        {
          name: '均价',
          type: 'line',
          data: avgs,
          showSymbol: false,
          lineStyle: { width: 1, color: chartVar('--ff-chart-primary') },
          itemStyle: { color: chartVar('--ff-chart-primary') },
          z: 1,
        },
        {
          name: '价格',
          type: 'line',
          data: prices,
          showSymbol: false,
          lineStyle: { width: 1.5, color: lineColor },
          itemStyle: { color: lineColor },
          areaStyle: { color: (lineColor || '#888888') + '1a' },
          markLine: {
            silent: true,
            symbol: 'none',
            lineStyle: { type: 'dashed', color: chartVar('--ff-text-tertiary') },
            label: { formatter: '基准', color: chartVar('--ff-text-tertiary'), fontSize: 10 },
            data: [{ yAxis: base }],
          },
          z: 2,
        },
      ],
    }
  }

  // K 线（蜡烛图 + 成交量副图）：主图 [开, 收, 低, 高]，副图按涨跌着色
  const dates = data.map((d) => d.trade_date)
  const ohlc = data.map((d) => [d.open, d.close, d.low, d.high])
  const volumes = data.map((d) => ({
    value: d.volume,
    itemStyle: { color: chartVar(d.close >= d.open ? '--ff-chart-up' : '--ff-chart-down') },
  }))
  return {
    tooltip: {
      trigger: 'axis',
      axisPointer: { type: 'cross' },
      formatter: (ps) => {
        const t = ps[0]?.axisValue || ''
        const row = data.find((d) => d.trade_date === t)
        if (!row) return t
        const fmt = (n) => (Number.isFinite(n) ? String(Number(n).toFixed(2)) : null)
        const fmtBig = (n) => {
          if (!Number.isFinite(n)) return null
          if (Math.abs(n) >= 1e8) return (n / 1e8).toFixed(2) + '亿'
          if (Math.abs(n) >= 1e4) return (n / 1e4).toFixed(2) + '万'
          return String(Math.round(n))
        }
        const open = fmt(row.open)
        const close = fmt(row.close)
        const high = fmt(row.high)
        const low = fmt(row.low)
        const lines = [`<div style="font-weight:600;margin-bottom:4px">${t}</div>`]
        if (open) lines.push(`开盘价：${open}`)
        if (close) lines.push(`收盘价：${close}`)
        if (high) lines.push(`最高价：${high}`)
        if (low) lines.push(`最低价：${low}`)
        if (Number.isFinite(row.pct_chg)) {
          const pct = Number(row.pct_chg)
          const color = chartVar(pct >= 0 ? '--ff-chart-up' : '--ff-chart-down') || '#888888'
          lines.push(`涨跌幅：<span style="color:${color}">${(pct >= 0 ? '+' : '') + pct.toFixed(2)}%</span>`)
        }
        const vol = fmtBig(row.volume)
        if (vol) lines.push(`成交量：${vol}`)
        const amt = fmtBig(row.amount)
        if (amt) lines.push(`成交额：${amt}`)
        return lines.join('<br/>')
      },
    },
    grid: [
      { left: 56, right: 16, top: 16, height: '62%' },
      { left: 56, right: 16, top: '74%', height: '16%' },
    ],
    xAxis: [
      {
        type: 'category',
        data: dates,
        gridIndex: 0,
        axisLabel: { show: false },
        axisLine: { lineStyle: { color: chartVar('--ff-border') } },
      },
      {
        type: 'category',
        data: dates,
        gridIndex: 1,
        axisLabel: { hideOverlap: true, color: chartVar('--ff-text-tertiary'), fontSize: 10 },
        axisLine: { lineStyle: { color: chartVar('--ff-border') } },
      },
    ],
    yAxis: [
      {
        scale: true,
        type: 'value',
        gridIndex: 0,
        splitLine: { lineStyle: { type: 'dashed', color: chartVar('--ff-bg-subtle') } },
        axisLabel: { color: chartVar('--ff-text-tertiary'), fontSize: 10 },
      },
      {
        scale: true,
        type: 'value',
        gridIndex: 1,
        splitNumber: 2,
        splitLine: { show: false },
        axisLabel: { color: chartVar('--ff-text-tertiary'), fontSize: 10 },
      },
    ],
    dataZoom: [
      { type: 'inside', xAxisIndex: [0, 1] },
      { type: 'slider', xAxisIndex: [0, 1], height: 16, bottom: 4 },
    ],
    series: [
      {
        name: 'K线',
        type: 'candlestick',
        xAxisIndex: 0,
        yAxisIndex: 0,
        data: ohlc,
        itemStyle: {
          color: chartVar('--ff-chart-up'),
          color0: chartVar('--ff-chart-down'),
          borderColor: chartVar('--ff-chart-up'),
          borderColor0: chartVar('--ff-chart-down'),
        },
      },
      {
        name: '成交量',
        type: 'bar',
        xAxisIndex: 1,
        yAxisIndex: 1,
        data: volumes,
      },
    ],
  }
})

onMounted(load)
onUnmounted(clearRetry)
watch([period, range, customStart, customEnd], load)
</script>

<template>
  <div class="ff-ikc">
    <div class="ff-ikc__bar">
      <div class="ff-ikc__tabs">
        <button
          v-for="p in PERIODS"
          :key="p.key"
          class="ff-ikc__tab"
          :class="{ 'is-active': p.key === period }"
          @click="period = p.key"
        >
          {{ p.label }}
        </button>
      </div>
      <div v-if="!isTrends" class="ff-ikc__ranges">
        <button
          v-for="rg in RANGES"
          :key="rg.label"
          class="ff-ikc__range"
          :class="{ 'is-active': rg.label === range }"
          @click="onRange(rg)"
        >
          {{ rg.label }}
        </button>
      </div>
      <div v-if="!isTrends && range === '自定义'" class="ff-ikc__custom">
        <input v-model="customStart" type="date" class="ff-ikc__date" aria-label="起始日期" />
        <span class="ff-ikc__dash">至</span>
        <input v-model="customEnd" type="date" class="ff-ikc__date" aria-label="结束日期" />
      </div>
    </div>

    <div class="ff-ikc__chart">
      <div v-if="loading && !rows.length" class="ff-ikc__state">
        <AppSkeleton variant="text" :lines="4" />
      </div>
      <EmptyState v-else-if="error" :text="error" icon="alert-triangle" />
      <div v-else-if="reason === 'rate_limited'" class="ff-ikc__retry">
        <AppIcon name="clock" size="lg" />
        <span>东财接口限流中（IP 冷却约 10 分钟），正在自动重试…</span>
        <button class="ff-ikc__retry-btn" type="button" @click="load">立即重试</button>
      </div>
      <EmptyState v-else-if="!rows.length" text="暂无数据" icon="chart-line" />
      <ChartPanel v-else :option="option" height="300px" />
    </div>

    <div v-if="loading && rows.length" class="ff-ikc__loading-hint">
      <AppIcon name="refresh" size="xs" /> 加载中…
    </div>
  </div>
</template>

<style scoped>
.ff-ikc {
  display: flex;
  flex-direction: column;
  gap: var(--ff-space-3);
}
.ff-ikc__bar {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  justify-content: space-between;
  gap: var(--ff-space-2);
}
.ff-ikc__tabs {
  display: inline-flex;
  gap: 4px;
  padding: 3px;
  border: 1px solid var(--ff-border);
  border-radius: var(--ff-radius-md);
  background: var(--ff-bg-subtle);
}
.ff-ikc__tab {
  border: 0;
  background: transparent;
  color: var(--ff-text-secondary);
  font-size: var(--ff-fs-sm);
  font-weight: 500;
  padding: 4px 10px;
  border-radius: var(--ff-radius-sm);
  cursor: pointer;
  transition: background-color 0.15s, color 0.15s;
}
.ff-ikc__tab:hover {
  color: var(--ff-text-primary);
}
.ff-ikc__tab.is-active {
  background: var(--ff-bg-surface);
  color: var(--ff-text-primary);
  box-shadow: var(--ff-shadow-xs);
}
.ff-ikc__ranges {
  display: inline-flex;
  flex-wrap: wrap;
  gap: 4px;
}
.ff-ikc__range {
  border: 1px solid var(--ff-border);
  background: transparent;
  color: var(--ff-text-tertiary);
  font-size: var(--ff-fs-caption);
  padding: 4px 8px;
  border-radius: var(--ff-radius-sm);
  cursor: pointer;
  transition: all 0.15s;
}
.ff-ikc__range:hover {
  color: var(--ff-text-secondary);
  border-color: var(--ff-border-strong);
}
.ff-ikc__range.is-active {
  color: var(--ff-text-primary);
  border-color: var(--ff-chart-primary);
  background: var(--ff-bg-subtle);
}
.ff-ikc__custom {
  display: inline-flex;
  align-items: center;
  gap: var(--ff-space-2);
  flex-wrap: wrap;
}
.ff-ikc__date {
  border: 1px solid var(--ff-border);
  background: var(--ff-bg-surface);
  color: var(--ff-text-primary);
  font-size: var(--ff-fs-caption);
  padding: 4px 8px;
  border-radius: var(--ff-radius-sm);
  color-scheme: light;
}
.ff-ikc__date:focus {
  outline: none;
  border-color: var(--ff-chart-primary);
}
.ff-ikc__dash {
  color: var(--ff-text-tertiary);
  font-size: var(--ff-fs-caption);
}
.ff-ikc__chart {
  min-height: 300px;
}
.ff-ikc__retry {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: var(--ff-space-3);
  padding: var(--ff-space-6) 0;
  color: var(--ff-text-secondary);
  font-size: var(--ff-fs-sm);
}
.ff-ikc__retry-btn {
  border: 1px solid var(--ff-border);
  background: var(--ff-bg-surface);
  color: var(--ff-text-primary);
  font-size: var(--ff-fs-sm);
  font-weight: 500;
  padding: 6px 16px;
  border-radius: var(--ff-radius-md);
  cursor: pointer;
  transition: all 0.15s;
}
.ff-ikc__retry-btn:hover {
  border-color: var(--ff-chart-primary);
  color: var(--ff-text-primary);
}
.ff-ikc__state,
.ff-ikc__loading-hint {
  padding: var(--ff-space-4) 0;
  color: var(--ff-text-tertiary);
  font-size: var(--ff-fs-sm);
}
.ff-ikc__loading-hint {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 0;
  margin-top: -8px;
}
</style>
