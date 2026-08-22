<script setup>
// 股票列表卡片网格：code + name + 关键字段红涨绿跌
import { computed } from 'vue'
import { cellText, cellColor, columnLabel } from './format'

const props = defineProps({
  columns: { type: Array, default: () => [] },
  rows: { type: Array, default: () => [] },
  stockNames: { type: Object, default: () => ({}) },
})

const codeIdx = computed(() => props.columns.findIndex((c) => c === 'code'))
const nameIdx = computed(() => props.columns.findIndex((c) => c === 'name'))
// 卡片额外展示字段：涨跌幅类优先，其次数值列（最多 3 个）
const extraCols = computed(() =>
  props.columns
    .map((c, i) => ({ c, i }))
    .filter(({ c, i }) => i !== codeIdx.value && i !== nameIdx.value && /(pct|change|price|vol|amount|net|ratio|turnover)/i.test(c))
    .slice(0, 3)
    .map(({ c, i }) => ({ col: c, idx: i })),
)

function stockName(code) {
  return props.stockNames[String(code)] || ''
}
</script>

<template>
  <div class="etdx-list">
    <div v-for="(row, ri) in rows" :key="ri" class="etdx-list__card">
      <div class="etdx-list__main">
        <span class="etdx-list__name">{{ nameIdx >= 0 ? row[nameIdx] : stockName(row[codeIdx]) }}</span>
        <span class="etdx-list__code" v-if="codeIdx >= 0">
          {{ row[codeIdx] }}{{ stockName(row[codeIdx]) ? '' : '' }}
        </span>
      </div>
      <div class="etdx-list__extra">
        <div
          v-for="e in extraCols"
          :key="e.col"
          class="etdx-list__metric"
          :class="cellColor(row[e.idx], e.col)"
        >
          <span class="etdx-list__metric-label">{{ columnLabel(e.col) }}</span>
          <span class="etdx-list__metric-value">{{ cellText(row[e.idx], e.col) }}</span>
        </div>
      </div>
    </div>
    <div v-if="!rows.length" class="etdx-list__empty">暂无数据</div>
  </div>
</template>

<style scoped>
.etdx-list {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(220px, 1fr));
  gap: var(--ff-space-3);
}
.etdx-list__card {
  display: flex;
  flex-direction: column;
  gap: var(--ff-space-2);
  padding: var(--ff-space-3) var(--ff-space-4);
  background: var(--ff-bg-surface);
  border: 1px solid var(--ff-border-subtle);
  border-radius: var(--ff-radius-md);
  transition: border-color var(--ff-dur-fast), box-shadow var(--ff-dur-fast), transform var(--ff-dur-fast);
}
.etdx-list__card:hover {
  border-color: var(--ff-border-brand);
  box-shadow: var(--ff-shadow-sm);
  transform: translateY(-1px);
}
.etdx-list__main {
  display: flex;
  align-items: baseline;
  gap: var(--ff-space-2);
  min-width: 0;
}
.etdx-list__name {
  font-weight: 600;
  font-size: var(--ff-fs-body-sm);
  color: var(--ff-text-primary);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.etdx-list__code {
  font-size: var(--ff-fs-caption);
  color: var(--ff-text-tertiary);
  font-family: var(--ff-font-mono, monospace);
  flex-shrink: 0;
}
.etdx-list__extra {
  display: flex;
  gap: var(--ff-space-3);
  flex-wrap: wrap;
}
.etdx-list__metric {
  display: flex;
  flex-direction: column;
  gap: 1px;
}
.etdx-list__metric-label {
  font-size: var(--ff-fs-caption);
  color: var(--ff-text-tertiary);
}
.etdx-list__metric-value {
  font-size: var(--ff-fs-body-sm);
  font-weight: 700;
  font-variant-numeric: tabular-nums;
  color: var(--ff-text-primary);
}
.etdx-list__metric.is-up .etdx-list__metric-value {
  color: var(--ff-up-text);
}
.etdx-list__metric.is-down .etdx-list__metric-value {
  color: var(--ff-down-text);
}
.etdx-list__metric.is-warn .etdx-list__metric-value {
  color: var(--ff-warn-text);
}
.etdx-list__empty {
  grid-column: 1 / -1;
  text-align: center;
  color: var(--ff-text-tertiary);
  padding: var(--ff-space-6);
}
</style>
