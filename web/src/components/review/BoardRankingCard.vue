<script setup>
/**
 * BoardRankingCard — 板块涨幅榜 / 主力资金榜（通达信行情）
 *
 * 数据来源：GET /api/easytdx/dashboard/boards?type=hy|gn&sort=change_pct|main_net_amount
 * 标签：类型（行业 / 概念）× 排序（涨幅榜 / 资金榜），切换即时取数并缓存。
 * 红涨绿跌（--ff-text-up / --ff-down-text）。
 */
import { ref, watch, onMounted, computed } from 'vue'
import easytdxApi from '../../features/easytdx/api/easytdxApi'
import AppTabs from '../../ui/AppTabs.vue'
import AppEmpty from '../../ui/AppEmpty.vue'
import AppSkeleton from '../../ui/AppSkeleton.vue'
import AppIcon from '../../ui/AppIcon.vue'
import { fmtAmount, fmtChg, chgClass, fmtInt } from './format'

const props = defineProps({
  refreshKey: { type: Number, default: 0 },
})

const TYPE_TABS = [
  { value: 'hy', label: '行业' },
  { value: 'gn', label: '概念' },
]
const SORT_TABS = [
  { value: 'change_pct', label: '涨幅榜' },
  { value: 'main_net_amount', label: '资金榜' },
]
const typeTab = ref('hy')
const sortTab = ref('change_pct')

const cache = ref({}) // `${type}:${sort}` -> rows
const loading = ref(false)
const err = ref('')

const activeKey = computed(() => `${typeTab.value}:${sortTab.value}`)
const rows = computed(() => cache.value[activeKey.value] || [])
const isFund = computed(() => sortTab.value === 'main_net_amount')

// 涨跌幅迷你条：按整榜最大绝对涨跌幅缩放
const maxAbsChg = computed(() =>
  rows.value.length ? Math.max(...rows.value.map((r) => Math.abs(r.change_pct || 0))) : 0,
)
function chgBarPct(v) {
  if (!maxAbsChg.value) return '0%'
  return (Math.abs(v || 0) / maxAbsChg.value) * 100 + '%'
}

async function load() {
  const key = activeKey.value
  if (cache.value[key]) return
  loading.value = true
  err.value = ''
  try {
    const res = await easytdxApi.dashboard.boards(typeTab.value, sortTab.value, 15)
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

watch(typeTab, load)
watch(sortTab, load)
watch(() => props.refreshKey, refresh)
onMounted(load)
</script>

<template>
  <div class="br">
    <div class="br__tabs">
      <AppTabs :items="TYPE_TABS" v-model="typeTab" type="pill" size="sm" />
      <span class="br__tabs-sep"></span>
      <AppTabs :items="SORT_TABS" v-model="sortTab" type="pill" size="sm" />
      <button type="button" class="br__reload" title="刷新" :disabled="loading" @click="refresh">
        <AppIcon name="refresh" :spin="loading" size="sm" />
      </button>
    </div>

    <div v-if="loading && !rows.length" class="br__load">
      <AppSkeleton variant="text" :lines="6" />
    </div>
    <div v-else-if="err && !rows.length" class="br__err">
      <AppEmpty icon="layers" title="暂无板块排行" :description="err" />
    </div>
    <AppEmpty v-else-if="!rows.length" icon="layers" title="暂无板块排行" />

    <div v-else class="br__list">
      <div class="br__head">
        <span class="br__c-rank">#</span>
        <span class="br__c-name">板块</span>
        <span class="br__c-num">家数</span>
        <span class="br__c-chg">涨跌幅</span>
        <span class="br__c-amount">成交额</span>
        <span class="br__c-fund">主力净额</span>
      </div>
      <div
        v-for="(row, i) in rows"
        :key="(row.code || '') + '-' + i"
        class="br__row"
      >
        <span class="br__c-rank ff-num">{{ i + 1 }}</span>
        <span class="br__c-name" :title="row.name">{{ row.name }}</span>
        <span class="br__c-num ff-num">{{ fmtInt(row.member_count) }}</span>
        <span class="br__c-chg ff-num" :class="chgClass(row.change_pct)">
          <span
            class="br__chg-bar"
            :class="chgClass(row.change_pct)"
            :style="{ width: chgBarPct(row.change_pct) }"
          ></span>
          {{ fmtChg(row.change_pct) }}
        </span>
        <span class="br__c-amount ff-num">{{ fmtAmount(row.amount) }}</span>
        <span class="br__c-fund ff-num" :class="chgClass(row.main_net_amount)">
          {{ fmtAmount(row.main_net_amount) }}
        </span>
      </div>
    </div>
  </div>
</template>

<style scoped>
.br {
  display: flex;
  flex-direction: column;
  gap: var(--ff-space-3);
}
.br__tabs {
  display: flex;
  align-items: center;
  gap: var(--ff-space-2);
  flex-wrap: wrap;
}
.br__tabs-sep {
  width: 1px;
  height: 16px;
  background: var(--ff-border);
  margin: 0 var(--ff-space-1);
}
.br__reload {
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
.br__reload:hover:not(:disabled) {
  background: var(--ff-bg-hover);
  color: var(--ff-text-primary);
}
.br__reload:active:not(:disabled) {
  transform: scale(0.92);
}
.br__reload:disabled {
  opacity: 0.5;
  cursor: default;
}
.br__load {
  min-height: 160px;
}

/* 列表 */
.br__list {
  display: flex;
  flex-direction: column;
  min-height: 0;
}
.br__head,
.br__row {
  display: grid;
  grid-template-columns: 28px minmax(0, 1fr) 56px 76px 76px 84px;
  align-items: center;
  gap: var(--ff-space-2);
  padding: var(--ff-space-1-5) 0;
  border-bottom: 1px solid var(--ff-border-subtle);
}
.br__head {
  font-size: var(--ff-fs-caption);
  color: var(--ff-text-tertiary);
  border-bottom-color: var(--ff-border);
}
.br__row:hover {
  background: var(--ff-bg-hover);
}
.br__c-rank {
  color: var(--ff-text-tertiary);
  font-weight: var(--ff-fw-semibold);
}
.br__c-name {
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  font-weight: var(--ff-fw-medium);
  color: var(--ff-text-primary);
}
.br__c-num {
  color: var(--ff-text-secondary);
  font-size: var(--ff-fs-body-sm);
  text-align: right;
}
.br__c-chg,
.br__c-amount,
.br__c-fund {
  text-align: right;
  justify-self: end;
  font-weight: var(--ff-fw-semibold);
  font-size: var(--ff-fs-body-sm);
  font-variant-numeric: tabular-nums;
}
/* 涨跌幅迷你条 */
.br__c-chg {
  position: relative;
  overflow: hidden;
  padding: 4px 8px;
  border-radius: var(--ff-radius-sm);
}
.br__chg-bar {
  position: absolute;
  top: 0;
  bottom: 0;
  right: 0;
  opacity: 0.14;
  border-radius: var(--ff-radius-sm);
}
.br__chg-bar.is-up {
  background: var(--ff-up);
}
.br__chg-bar.is-down {
  background: var(--ff-down);
}
.br__chg-bar.is-flat {
  background: var(--ff-chart-neutral);
}
.br__c-amount {
  color: var(--ff-text-secondary);
}
.br__c-fund {
  font-size: var(--ff-fs-body-sm);
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

@media (max-width: 560px) {
  .br__head,
  .br__row {
    grid-template-columns: 24px minmax(0, 1fr) 68px 80px;
  }
  .br__c-num,
  .br__c-amount {
    display: none;
  }
}
</style>
