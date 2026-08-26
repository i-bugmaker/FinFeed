<script setup>
/**
 * StockRankingCard — 个股涨幅榜 / 跌幅榜 / 成交额榜（通达信行情）
 *
 * 数据来源：GET /api/easytdx/dashboard/stocks?list=up|down|amount
 * 切换榜单即时取数并缓存。红涨绿跌（--ff-text-up / --ff-down-text）。
 */
import { ref, watch, onMounted, computed } from 'vue'
import easytdxApi from '../../features/easytdx/api/easytdxApi'
import AppTabs from '../../ui/AppTabs.vue'
import AppEmpty from '../../ui/AppEmpty.vue'
import AppSkeleton from '../../ui/AppSkeleton.vue'
import AppIcon from '../../ui/AppIcon.vue'
import { fmtAmount, fmtChg, chgClass } from './format'

const props = defineProps({
  refreshKey: { type: Number, default: 0 },
})

const LIST_TABS = [
  { value: 'up', label: '涨幅榜' },
  { value: 'down', label: '跌幅榜' },
  { value: 'amount', label: '成交额榜' },
]
const listTab = ref('up')

const cache = ref({})
const loading = ref(false)
const err = ref('')

const rows = computed(() => cache.value[listTab.value] || [])

// 涨跌幅迷你条：按整榜最大绝对涨跌幅缩放
const maxAbsChg = computed(() =>
  rows.value.length ? Math.max(...rows.value.map((r) => Math.abs(r.change_pct || 0))) : 0,
)
function chgBarPct(v) {
  if (!maxAbsChg.value) return '0%'
  return (Math.abs(v || 0) / maxAbsChg.value) * 100 + '%'
}

async function load() {
  const key = listTab.value
  if (cache.value[key]) return
  loading.value = true
  err.value = ''
  try {
    const res = await easytdxApi.dashboard.stocks(key, 15)
    cache.value[key] = res.ok ? res.data : []
    if (!res.ok) err.value = res.error || '获取失败'
  } catch (e) {
    err.value = e.message || String(e)
  } finally {
    loading.value = false
  }
}

function refresh() {
  cache.value = {}
  load()
}

watch(listTab, load)
watch(() => props.refreshKey, refresh)
onMounted(load)
</script>

<template>
  <div class="sk">
    <div class="sk__tabs">
      <AppTabs :items="LIST_TABS" v-model="listTab" type="pill" size="sm" />
      <button type="button" class="sk__reload" title="刷新" :disabled="loading" @click="refresh">
        <AppIcon name="refresh" :spin="loading" size="sm" />
      </button>
    </div>

    <div v-if="loading && !rows.length" class="sk__load">
      <AppSkeleton variant="text" :lines="6" />
    </div>
    <div v-else-if="err && !rows.length" class="sk__err">
      <AppEmpty icon="list" title="暂无个股榜单" :description="err" />
    </div>
    <AppEmpty v-else-if="!rows.length" icon="list" title="暂无个股榜单" />

    <div v-else class="sk__list">
      <div class="sk__head">
        <span class="sk__c-rank">#</span>
        <span class="sk__c-stock">名称 / 代码</span>
        <span class="sk__c-price">现价</span>
        <span class="sk__c-chg">涨跌幅</span>
        <span class="sk__c-amount">成交额</span>
      </div>
      <div v-for="(row, i) in rows" :key="(row.code || '') + '-' + i" class="sk__row">
        <span class="sk__c-rank ff-num">{{ i + 1 }}</span>
        <div class="sk__c-stock">
          <span class="sk__name">{{ row.name }}</span>
          <span class="sk__code ff-num">{{ row.board }}{{ row.code }}</span>
        </div>
        <span class="sk__c-price ff-num">{{ row.price != null ? row.price.toFixed(2) : '—' }}</span>
        <span class="sk__c-chg ff-num" :class="chgClass(row.change_pct)">
          <span
            class="sk__chg-bar"
            :class="chgClass(row.change_pct)"
            :style="{ width: chgBarPct(row.change_pct) }"
          ></span>
          {{ fmtChg(row.change_pct) }}
        </span>
        <span class="sk__c-amount ff-num">{{ fmtAmount(row.amount) }}</span>
      </div>
    </div>
  </div>
</template>

<style scoped>
.sk {
  display: flex;
  flex-direction: column;
  gap: var(--ff-space-3);
}
.sk__tabs {
  display: flex;
  align-items: center;
  gap: var(--ff-space-2);
}
.sk__reload {
  margin-left: auto;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 28px;
  height: 28px;
  border-radius: var(--ff-radius-sm);
  border: 1px solid var(--ff-border);
  background: var(--ff-bg-surface);
  color: var(--ff-text-tertiary);
  cursor: pointer;
  transition: background-color var(--ff-dur-fast) var(--ff-ease-standard),
    color var(--ff-dur-fast) var(--ff-ease-standard),
    transform var(--ff-dur-fast) var(--ff-ease-standard);
}
.sk__reload:hover:not(:disabled) {
  background: var(--ff-bg-hover);
  color: var(--ff-text-primary);
}
.sk__reload:active:not(:disabled) {
  transform: scale(0.92);
}
.sk__reload:disabled {
  opacity: 0.5;
  cursor: default;
}
.sk__load {
  min-height: 160px;
}

.sk__list {
  display: flex;
  flex-direction: column;
}
.sk__head,
.sk__row {
  display: grid;
  grid-template-columns: 28px minmax(0, 1fr) 72px 84px 84px;
  align-items: center;
  gap: var(--ff-space-2);
  padding: var(--ff-space-1-5) 0;
  border-bottom: 1px solid var(--ff-border-subtle);
}
.sk__head {
  font-size: var(--ff-fs-caption);
  color: var(--ff-text-tertiary);
  border-bottom-color: var(--ff-border);
}
.sk__row:hover {
  background: var(--ff-bg-hover);
}
.sk__c-rank {
  color: var(--ff-text-tertiary);
  font-weight: var(--ff-fw-semibold);
}
.sk__c-stock {
  display: flex;
  align-items: baseline;
  gap: 6px;
  min-width: 0;
}
.sk__name {
  font-weight: var(--ff-fw-medium);
  color: var(--ff-text-primary);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
.sk__code {
  flex: 0 0 auto;
  font-size: var(--ff-fs-caption);
  color: var(--ff-text-tertiary);
}
.sk__c-price,
.sk__c-chg,
.sk__c-amount {
  text-align: right;
  justify-self: end;
  font-weight: var(--ff-fw-semibold);
  font-size: var(--ff-fs-body-sm);
  font-variant-numeric: tabular-nums;
}
/* 涨跌幅迷你条 */
.sk__c-chg {
  position: relative;
  overflow: hidden;
  padding: 4px 8px;
  border-radius: var(--ff-radius-sm);
}
.sk__chg-bar {
  position: absolute;
  top: 0;
  bottom: 0;
  right: 0;
  opacity: 0.14;
  border-radius: var(--ff-radius-sm);
}
.sk__chg-bar.is-up {
  background: var(--ff-up);
}
.sk__chg-bar.is-down {
  background: var(--ff-down);
}
.sk__chg-bar.is-flat {
  background: var(--ff-chart-neutral);
}
.sk__c-price {
  color: var(--ff-text-primary);
}
.sk__c-amount {
  color: var(--ff-text-secondary);
}
.is-up {
  color: var(--ff-text-up);
}
.is-down {
  color: var(--ff-down-text);
}
.is-flat {
  color: var(--ff-text-tertiary);
}

@media (max-width: 520px) {
  .sk__head,
  .sk__row {
    grid-template-columns: 24px minmax(0, 1fr) 72px 80px;
  }
  .sk__c-amount {
    display: none;
  }
}
</style>
