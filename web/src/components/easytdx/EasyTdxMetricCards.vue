<script setup>
// KPI 指标卡：回测绩效 / 资金流 / 排行统计，红涨绿跌语义
import { computed } from 'vue'
import { extractKpis, formatKpi, cellColor } from './format'

const props = defineProps({
  data: { type: Object, default: null }, // json result.data 或 table 首行/统计
  source: { type: String, default: 'json' }, // json | table
})

const kpis = computed(() => {
  if (!props.data) return []
  return extractKpis(props.data)
})
</script>

<template>
  <div v-if="kpis.length" class="etdx-kpis">
    <div
      v-for="k in kpis"
      :key="k.key"
      class="etdx-kpi"
      :class="cellColor(k.value, k.key)"
    >
      <span class="etdx-kpi__label" :title="k.key">{{ k.label }}</span>
      <span class="etdx-kpi__value">{{ formatKpi(k) }}</span>
    </div>
  </div>
</template>

<style scoped>
.etdx-kpis {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(150px, 1fr));
  gap: var(--ff-space-3);
  margin-bottom: var(--ff-space-3);
}
.etdx-kpi {
  display: flex;
  flex-direction: column;
  gap: 4px;
  padding: var(--ff-space-3) var(--ff-space-4);
  background: var(--ff-bg-surface);
  border: 1px solid var(--ff-border-subtle);
  border-radius: var(--ff-radius-md);
}
.etdx-kpi__label {
  font-size: var(--ff-fs-caption);
  color: var(--ff-text-tertiary);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.etdx-kpi__value {
  font-size: var(--ff-fs-h1);
  font-weight: 700;
  font-variant-numeric: tabular-nums;
  color: var(--ff-text-primary);
  line-height: 1.2;
}
.etdx-kpi.is-up {
  background: var(--ff-up-subtle);
  border-color: var(--ff-up-border);
}
.etdx-kpi.is-up .etdx-kpi__value {
  color: var(--ff-up-text);
}
.etdx-kpi.is-down {
  background: var(--ff-down-subtle);
  border-color: var(--ff-down-border);
}
.etdx-kpi.is-down .etdx-kpi__value {
  color: var(--ff-down-text);
}
.etdx-kpi.is-warn {
  background: var(--ff-warn-subtle);
  border-color: var(--ff-warn-border);
}
.etdx-kpi.is-warn .etdx-kpi__value {
  color: var(--ff-warn-text);
}
</style>
