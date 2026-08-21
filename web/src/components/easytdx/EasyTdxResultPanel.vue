<script setup>
import { computed } from 'vue'
import ChartPanel from '../ChartPanel.vue'
import AppIcon from '../../ui/AppIcon.vue'
import AppButton from '../../ui/AppButton.vue'
import { columnLabel, cellText, isLink, fullText } from './format'

const props = defineProps({
  result: { type: Object, default: null },
  func: { type: Object, default: null },
  loading: { type: Boolean, default: false },
  stockNames: { type: Object, default: () => ({}) }, // { code: name }
})

const hasResult = computed(() => !!props.result)
const type = computed(() => props.result?.type || 'none')

// ---------------- 图表 ----------------
const showChart = computed(
  () => hasResult.value && type.value === 'table' && !!props.func?.chart,
)

const chartOption = computed(() => {
  if (!showChart.value) return null
  const t = props.result
  if (props.func.chart === 'candle') return buildCandle(t)
  if (props.func.chart === 'line') return buildLine(t)
  return null
})

function num(v) {
  const n = parseFloat(v)
  return Number.isFinite(n) ? n : 0
}

// 读取主题色（ECharts canvas 无法解析 CSS var 字符串，需取实际颜色值）
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
  // 红涨绿跌：阳线(close>=open)=红，阴线=绿
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

// ---------------- 回测：资金曲线 / 交易明细 ----------------
const equityOption = computed(() => {
  if (type.value !== 'json') return null
  const eq = props.result?.data?.equity
  if (!Array.isArray(eq) || !eq.length) return null
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
})

const tradesRows = computed(() => {
  if (type.value !== 'json') return []
  const tr = props.result?.data?.trades
  return Array.isArray(tr) ? tr : []
})
const tradesCols = computed(() =>
  tradesRows.value.length ? Object.keys(tradesRows.value[0]) : [],
)

// ---------------- JSON 渲染 ----------------
const jsonEntries = computed(() => {
  if (type.value !== 'json') return []
  const d = props.result.data || {}
  return Object.entries(d)
    .filter(([k]) => !['trades', 'equity'].includes(k))
    .map(([k, v]) => ({ k, v }))
})

function fmt(v, col = '') {
  if (v === null || v === undefined) return '—'
  if (typeof v === 'object') {
    if (Array.isArray(v)) return v.length ? `${v.length} 项` : '空数组'
    const keys = Object.keys(v)
    return keys.length ? `${keys.length} 个字段` : '空对象'
  }
  return cellText(v, col)
}

// 单元格展示：code 列自动带出股票名称（贵州茅台 (600519)）
function fmtCell(v, col) {
  const c = String(col || '').toLowerCase()
  if (c === 'code' && typeof v === 'string' && /^\d{6}$/.test(v)) {
    const name = props.stockNames[v]
    if (name) return `${name} (${v})`
  }
  return cellText(v, col)
}

// 纯标量字典（如 performance）→ 展开为子行展示
function isPlainDict(v) {
  return (
    v !== null &&
    typeof v === 'object' &&
    !Array.isArray(v) &&
    Object.values(v).every((x) => x === null || typeof x !== 'object')
  )
}
</script>

<template>
  <div class="etdx-result">
    <AppIcon v-if="loading" name="refresh" size="lg" spin class="etdx-result__spin" />

    <template v-else-if="hasResult">
      <!-- 文件下载 -->
      <div v-if="type === 'file'" class="etdx-result__file">
        <AppIcon name="file-text" size="lg" />
        <div class="etdx-result__file-meta">
          <div class="etdx-result__file-name">{{ result.filename }}</div>
          <div class="etdx-result__file-size">{{ (result.size / 1024).toFixed(1) }} KB</div>
        </div>
        <AppButton
          :href="result.download_url"
          target="_blank"
          variant="primary"
          icon="download"
        >
          下载文件
        </AppButton>
      </div>

      <!-- 纯文本消息 -->
      <div v-else-if="type === 'message'" class="etdx-result__message">
        <AppIcon name="info" size="md" />
        <span>{{ result.text }}</span>
      </div>

      <!-- JSON 键值 -->
      <div v-else-if="type === 'json'">
        <div v-if="equityOption" class="etdx-result__chart">
          <ChartPanel :option="equityOption" height="300px" />
        </div>
        <div v-if="tradesRows.length" class="etdx-result__trades">
          <div class="etdx-result__tablemeta">
            <AppIcon name="list" size="sm" />
            <span>交易明细 {{ tradesRows.length }} 笔</span>
          </div>
          <div class="etdx-result__tablewrap">
            <table class="ff-table ff-table--sticky">
              <thead>
                <tr>
                  <th v-for="col in tradesCols" :key="col" class="ff-table__header" :title="col">
                    {{ columnLabel(col) }}
                  </th>
                </tr>
              </thead>
              <tbody>
                <tr v-for="(row, ri) in tradesRows" :key="ri" class="ff-table__row">
                  <td v-for="col in tradesCols" :key="col" class="ff-table__cell">
                    <a
                      v-if="isLink(row[col], col)"
                      :href="row[col]"
                      target="_blank"
                      rel="noopener"
                      class="etdx-result__link"
                    >打开链接</a>
                    <span v-else :title="fullText(row[col])">{{ fmtCell(row[col], col) }}</span>
                  </td>
                </tr>
              </tbody>
            </table>
          </div>
        </div>
        <div v-if="jsonEntries.length" class="etdx-result__json">
          <div v-for="e in jsonEntries" :key="e.k" class="etdx-kv">
            <span class="etdx-kv__k" :title="e.k">{{ columnLabel(e.k) }}</span>
            <div v-if="isPlainDict(e.v)" class="etdx-kv__nested">
              <div v-for="(sv, sk) in e.v" :key="sk" class="etdx-kv__row">
                <span class="etdx-kv__k2" :title="String(sk)">{{ columnLabel(sk) }}</span>
                <span class="etdx-kv__v2">
                  <a
                    v-if="isLink(sv, String(sk))"
                    :href="sv"
                    target="_blank"
                    rel="noopener"
                    class="etdx-result__link"
                  >打开链接</a>
                  <template v-else>{{ cellText(sv, String(sk)) }}</template>
                </span>
              </div>
            </div>
            <span v-else class="etdx-kv__v">
              <a
                v-if="isLink(e.v, e.k)"
                :href="e.v"
                target="_blank"
                rel="noopener"
                class="etdx-result__link"
              >打开链接</a>
              <template v-else>{{ fmt(e.v, e.k) }}</template>
            </span>
          </div>
        </div>
      </div>

      <!-- 表格 (+ 可选图表) -->
      <div v-else-if="type === 'table'">
        <div v-if="showChart" class="etdx-result__chart">
          <ChartPanel :option="chartOption" height="320px" />
        </div>
        <div class="etdx-result__tablemeta">
          <AppIcon name="list" size="sm" />
          <span>{{ result.row_count }} 行 × {{ result.columns.length }} 列</span>
          <span v-if="result.truncated" class="etdx-result__truncated">（已截断显示前 {{ result.rows.length }} 行）</span>
        </div>
        <div class="etdx-result__tablewrap">
          <table class="ff-table ff-table--sticky">
            <thead>
              <tr>
                <th
                  v-for="(col, i) in result.columns"
                  :key="col"
                  class="ff-table__header"
                  :title="col"
                >
                  {{ columnLabel(col) }}
                </th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="(row, ri) in result.rows" :key="ri" class="ff-table__row">
                <td
                  v-for="(cell, ci) in row"
                  :key="ci"
                  class="ff-table__cell"
                >
                  <a
                    v-if="isLink(cell, result.columns[ci])"
                    :href="cell"
                    target="_blank"
                    rel="noopener"
                    class="etdx-result__link"
                  >打开链接</a>
                  <span v-else :title="fullText(cell)">{{ fmtCell(cell, result.columns[ci]) }}</span>
                </td>
              </tr>
            </tbody>
          </table>
        </div>
      </div>
    </template>

    <div v-else class="etdx-result__placeholder">
      <AppIcon name="play" size="lg" />
      <p>选择一个功能并填写参数后，点击「执行」查看结果。</p>
    </div>
  </div>
</template>

<style scoped>
.etdx-result {
  min-height: 240px;
  padding: var(--ff-space-4);
}
.etdx-result__spin {
  display: block;
  margin: 60px auto;
  color: var(--ff-brand-text);
}
.etdx-result__placeholder {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: var(--ff-space-2);
  min-height: 240px;
  color: var(--ff-text-tertiary);
  text-align: center;
}
.etdx-result__message {
  display: flex;
  align-items: center;
  gap: var(--ff-space-2);
  padding: var(--ff-space-3);
  background: var(--ff-bg-subtle);
  border-radius: var(--ff-radius-md);
  color: var(--ff-text-secondary);
  font-size: var(--ff-fs-body-sm);
}
.etdx-result__file {
  display: flex;
  align-items: center;
  gap: var(--ff-space-4);
  padding: var(--ff-space-4);
  background: var(--ff-bg-subtle);
  border-radius: var(--ff-radius-md);
}
.etdx-result__file-meta {
  flex: 1;
}
.etdx-result__file-name {
  font-weight: 600;
  color: var(--ff-text-primary);
}
.etdx-result__file-size {
  font-size: var(--ff-fs-caption);
  color: var(--ff-text-tertiary);
}
.etdx-result__json {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(260px, 1fr));
  gap: var(--ff-space-3);
}
.etdx-kv {
  display: flex;
  flex-direction: column;
  gap: 2px;
  padding: var(--ff-space-3);
  background: var(--ff-bg-surface);
  border: 1px solid var(--ff-border-subtle);
  border-radius: var(--ff-radius-md);
}
.etdx-kv__k {
  font-size: var(--ff-fs-caption);
  color: var(--ff-text-tertiary);
}
.etdx-kv__v {
  font-size: var(--ff-fs-body-sm);
  color: var(--ff-text-primary);
  font-family: var(--ff-font-mono, monospace);
  word-break: break-all;
}
.etdx-kv__nested {
  display: flex;
  flex-direction: column;
  gap: 2px;
  margin-top: 2px;
}
.etdx-kv__row {
  display: flex;
  justify-content: space-between;
  gap: var(--ff-space-3);
  font-size: var(--ff-fs-body-sm);
}
.etdx-kv__k2 {
  color: var(--ff-text-secondary);
  flex-shrink: 0;
}
.etdx-kv__v2 {
  color: var(--ff-text-primary);
  font-family: var(--ff-font-mono, monospace);
  word-break: break-all;
  text-align: right;
}
.etdx-result__link {
  color: var(--ff-text-brand);
  text-decoration: underline;
  text-underline-offset: 2px;
}
.etdx-result__link:hover {
  color: var(--ff-brand);
}
.etdx-result__chart {
  margin-bottom: var(--ff-space-3);
}
.etdx-result__trades {
  margin-bottom: var(--ff-space-3);
}
.etdx-result__tablemeta {
  display: flex;
  align-items: center;
  gap: var(--ff-space-2);
  margin-bottom: var(--ff-space-2);
  font-size: var(--ff-fs-caption);
  color: var(--ff-text-tertiary);
}
.etdx-result__truncated {
  color: var(--ff-text-warning, #b7791f);
}
.etdx-result__tablewrap {
  overflow-x: auto;
  border: 1px solid var(--ff-border-subtle);
  border-radius: var(--ff-radius-md);
}
</style>
