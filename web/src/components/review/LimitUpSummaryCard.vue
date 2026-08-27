<script setup>
/**
 * LimitUpSummaryCard — 涨停摘要 · 梯队聚焦（同花顺涨停数据）
 *
 * 数据来源：/api/market/thslimitup?section=intensity 与 section=ladder
 * 展示：涨停 / 炸板 / 跌停 / 炸板率 / 封板率 + 连板个股（全梯队卡片）。
 * 红涨绿跌（--ff-text-up / --ff-down-text）。
 */
import { ref, watch, onMounted, computed } from 'vue'
import { api } from '../../api/client'
import AppEmpty from '../../ui/AppEmpty.vue'
import AppSkeleton from '../../ui/AppSkeleton.vue'
import AppIcon from '../../ui/AppIcon.vue'
import { fmtChg, chgClass, fmtPrice, fmtRatio, fmtSignedAmount } from './format'

const props = defineProps({
  refreshKey: { type: Number, default: 0 },
})

const loading = ref(false)
const err = ref('')
const intensity = ref(null) // { up_total, open_total, lower_total, metrics, up:[...] }
const ladder = ref([]) // [{ height, number, stocks }]

const metrics = computed(() => {
  const d = intensity.value
  if (!d) return []
  const m = d.metrics || {}
  const rate = (v) => (v == null ? '—' : (Number(v) * 100).toFixed(1) + '%')
  return [
    { label: '涨停', value: d.up_total ?? (d.up ? d.up.length : 0), tone: 'up' },
    { label: '炸板', value: d.open_total ?? (d.open ? d.open.length : 0), tone: 'warn' },
    { label: '跌停', value: d.lower_total ?? (d.lower ? d.lower.length : 0), tone: 'down' },
    { label: '炸板率', value: rate(m.broken_rate), tone: '' },
    { label: '封板率', value: rate(m.seal_rate), tone: '' },
  ]
})

// 连板梯队：降序排列的高度列表（height desc）
const tiers = computed(() => {
  return [...ladder.value].sort((a, b) => (b.height || 0) - (a.height || 0))
})
// 全梯队连板个股总数
const totalStockCount = computed(() =>
  tiers.value.reduce((sum, t) => sum + ((t.stocks || []).length || 0), 0),
)

// 数据日期 / 缓存状态提示条（来自 intensity 载荷的 date / source / fallback / cached_date）
const dataMeta = computed(() => {
  const d = intensity.value || {}
  const source = d.source || ''
  const fallback = d.fallback || ''
  const date = (fallback.includes('db_latest') && d.cached_date)
    ? d.cached_date
    : (d.date || d.cached_date || '')
  let label = '实时'
  let tone = 'live'
  if (fallback) {
    label = fallback.includes('db_latest') ? '最近交易日缓存' : '当日缓存'
    tone = 'cache'
  } else if (source === 'live_partial') {
    label = '实时 · 部分降级'
    tone = 'degraded'
  } else if (source === 'db') {
    label = '数据库缓存'
    tone = 'cache'
  }
  return { date, label, tone }
})

async function fetchIntensity() {
  const res = await api.market('thslimitup', { section: 'intensity' })
  // 后端包装 { success, data }；data 即强度载荷（date/source/fallback/up_total/…）
  intensity.value = (res && (res.data || res)) || null
}
async function fetchLadder() {
  const res = await api.market('thslimitup', { section: 'ladder' })
  const d = res && (res.data || res)
  ladder.value = (d && d.ladder) || []
}

async function load() {
  loading.value = true
  err.value = ''
  try {
    await Promise.all([fetchIntensity(), fetchLadder()])
  } catch (e) {
    err.value = e.message || String(e)
  } finally {
    loading.value = false
  }
}

watch(() => props.refreshKey, () => load())
onMounted(load)
</script>

<template>
  <div class="lu-sum">
    <div v-if="loading" class="lu-sum__load">
      <AppSkeleton variant="text" :lines="4" />
    </div>
    <div v-else-if="err && !intensity && !tiers.length" class="lu-sum__err">
      <AppEmpty icon="flame" title="暂无涨停摘要" :description="err" />
    </div>
    <AppEmpty v-else-if="!intensity && !tiers.length" icon="flame" title="暂无涨停摘要" />

    <template v-else>
      <!-- 数据日期 / 缓存状态提示条 -->
      <div class="lu-sum__meta">
        <span class="lu-sum__meta-date">数据日期 <b class="ff-num">{{ dataMeta.date || '—' }}</b></span>
        <span class="lu-sum__meta-src" :class="`is-${dataMeta.tone}`">
          <i class="lu-sum__dot"></i>{{ dataMeta.label }}
        </span>
      </div>

      <!-- 强度指标 -->
      <div v-if="metrics.length" class="lu-sum__metrics">
        <div v-for="m in metrics" :key="m.label" class="lu-sum__metric" :class="`is-${m.tone}`">
          <span class="lu-sum__label">{{ m.label }}</span>
          <span class="lu-sum__value ff-num">{{ m.value }}</span>
        </div>
      </div>

      <!-- 连板天梯（梯队列表行，全量） -->
      <div v-if="tiers.length" class="lu-sum__ladder">
        <div class="lu-sum__ladder-head">
          <span class="lu-sum__ladder-title">
            <AppIcon name="columns" size="sm" /> 连板天梯
          </span>
          <span class="lu-sum__ladder-count">共 <b class="ff-num">{{ totalStockCount }}</b> 只</span>
        </div>
        <div
          v-for="t in tiers"
          :key="'g' + t.height"
          class="lu-sum__tier"
          :class="{ 'is-hot': t.height >= 4 }"
        >
          <div class="lu-sum__tier-head">
            <span class="lu-sum__tier-badge ff-num">{{ t.height }}板</span>
            <span class="lu-sum__tier-count ff-num">{{ (t.stocks || []).length }} 只</span>
          </div>
          <div class="lu-sum__tier-rows">
            <div
              v-for="(s, i) in t.stocks"
              :key="(s.code || '') + '-' + i"
              class="lu-sum__row"
              :title="`${s.name} ${s.code} · ${s.continue_num} 连板`"
            >
              <span class="lu-sum__row-badge ff-num">{{ s.continue_num }}连板</span>
              <span class="lu-sum__row-name">{{ s.name }}</span>
              <span class="lu-sum__row-code ff-num">{{ s.code }}</span>
              <span class="lu-sum__row-price ff-num">{{ fmtPrice(s.price) }}</span>
              <span class="lu-sum__row-chg ff-num" :class="chgClass(s.change_pct)">{{ fmtChg(s.change_pct) }}</span>
              <span class="lu-sum__row-reason" :title="s.reason || ''">{{ s.reason || '—' }}</span>
              <span class="lu-sum__row-tags">
                <span v-if="s.limit_up_time" class="lu-sum__row-tag">封板 {{ s.limit_up_time }}</span>
                <span v-if="s.main_net_amount" class="lu-sum__row-tag" :class="chgClass(s.main_net_amount)">
                  主力 {{ fmtSignedAmount(s.main_net_amount) }}
                </span>
                <span v-if="s.turnover_ratio" class="lu-sum__row-tag">换手 {{ fmtRatio(s.turnover_ratio) }}%</span>
              </span>
            </div>
          </div>
        </div>
      </div>
    </template>
  </div>
</template>

<style scoped>
.lu-sum {
  display: flex;
  flex-direction: column;
  gap: var(--ff-space-4);
}
.lu-sum__load {
  min-height: 120px;
}

/* 数据日期 / 缓存状态提示条 */
.lu-sum__meta {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--ff-space-2);
  padding-bottom: var(--ff-space-1);
  border-bottom: 1px solid var(--ff-border-subtle);
  font-size: var(--ff-fs-caption);
  color: var(--ff-text-tertiary);
}
.lu-sum__meta-date b {
  font-weight: var(--ff-fw-semibold);
  color: var(--ff-text-secondary);
}
.lu-sum__meta-src {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  white-space: nowrap;
}
.lu-sum__dot {
  width: 6px;
  height: 6px;
  border-radius: 50%;
}
.lu-sum__meta-src.is-live {
  color: var(--ff-text-up);
}
.lu-sum__meta-src.is-live .lu-sum__dot {
  background: var(--ff-text-up);
}
.lu-sum__meta-src.is-cache,
.lu-sum__meta-src.is-degraded {
  color: var(--ff-warn-text);
}
.lu-sum__meta-src.is-cache .lu-sum__dot,
.lu-sum__meta-src.is-degraded .lu-sum__dot {
  background: var(--ff-warn-text);
}

/* 强度指标 */
.lu-sum__metrics {
  display: grid;
  grid-template-columns: repeat(5, 1fr);
  gap: var(--ff-space-2);
}
@media (max-width: 480px) {
  .lu-sum__metrics {
    grid-template-columns: repeat(3, 1fr);
  }
}
.lu-sum__metric {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 2px;
  padding: var(--ff-space-2-5) var(--ff-space-1);
  border-radius: var(--ff-radius-md);
  background: var(--ff-bg-subtle);
  border: 1px solid var(--ff-border-subtle);
}
.lu-sum__label {
  font-size: var(--ff-fs-caption);
  color: var(--ff-text-tertiary);
  white-space: nowrap;
}
.lu-sum__value {
  font-size: var(--ff-fs-h3);
  font-weight: var(--ff-fw-bold);
  font-variant-numeric: tabular-nums;
  color: var(--ff-text-primary);
}
.lu-sum__metric.is-up .lu-sum__value {
  color: var(--ff-text-up);
}
.lu-sum__metric.is-down .lu-sum__value {
  color: var(--ff-down-text);
}
.lu-sum__metric.is-warn .lu-sum__value {
  color: var(--ff-warn-text);
}

/* ================= 连板天梯：梯队分组 + 列表行 ================= */
.lu-sum__ladder {
  display: flex;
  flex-direction: column;
  gap: var(--ff-space-3);
  padding-top: var(--ff-space-3);
  border-top: 1px solid var(--ff-border-subtle);
}
.lu-sum__ladder-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--ff-space-2);
}
.lu-sum__ladder-title {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  font-size: var(--ff-fs-body-sm);
  font-weight: var(--ff-fw-semibold);
  color: var(--ff-text-primary);
}
.lu-sum__ladder-title :deep(.ff-icon) {
  color: var(--ff-brand-text);
}
.lu-sum__ladder-count {
  font-size: var(--ff-fs-caption);
  color: var(--ff-text-tertiary);
}
.lu-sum__ladder-count b {
  font-weight: var(--ff-fw-semibold);
  color: var(--ff-text-secondary);
}

/* 梯队分组 */
.lu-sum__tier {
  display: flex;
  flex-direction: column;
  gap: var(--ff-space-2);
}
.lu-sum__tier-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--ff-space-2);
}
.lu-sum__tier-badge {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  min-width: 46px;
  padding: 1px 10px;
  border-radius: var(--ff-radius-pill);
  font-size: var(--ff-fs-body-sm);
  font-weight: var(--ff-fw-bold);
  color: var(--ff-up-fg);
  background: linear-gradient(90deg, var(--ff-up-strong), var(--ff-up));
  font-variant-numeric: tabular-nums;
  line-height: 1.6;
}
.lu-sum__tier.is-hot .lu-sum__tier-badge {
  background: linear-gradient(90deg, #ff8a3d, #ff2d55);
}
.lu-sum__tier-count {
  font-size: var(--ff-fs-caption);
  color: var(--ff-text-tertiary);
  font-variant-numeric: tabular-nums;
}

/* 梯队行列表 */
.lu-sum__tier-rows {
  display: flex;
  flex-direction: column;
  gap: var(--ff-space-1-5);
}
.lu-sum__row {
  display: flex;
  align-items: center;
  gap: 6px 12px;
  padding: 7px 12px;
  border-radius: var(--ff-radius-md);
  border: 1px solid var(--ff-border-subtle);
  border-left: 3px solid var(--ff-up);
  background: var(--ff-bg-subtle);
  min-width: 0;
  overflow: hidden;
  cursor: default;
  transition: background-color var(--ff-dur-fast) var(--ff-ease-standard),
    border-color var(--ff-dur-fast) var(--ff-ease-standard);
}
.lu-sum__tier.is-hot .lu-sum__row {
  border-left-color: #ff2d55;
}
.lu-sum__row:hover {
  background: var(--ff-bg-hover);
  border-color: var(--ff-border);
}
.lu-sum__row-badge {
  flex-shrink: 0;
  padding: 0 6px;
  border-radius: var(--ff-radius-sm);
  font-size: var(--ff-fs-overline);
  font-weight: var(--ff-fw-semibold);
  color: var(--ff-up-text);
  background: var(--ff-up-subtle);
  border: 1px solid var(--ff-up-border);
  font-variant-numeric: tabular-nums;
  line-height: 1.6;
}
.lu-sum__tier.is-hot .lu-sum__row-badge {
  color: #ff2d55;
  background: #fff1f0;
  border-color: #ffd6d0;
}
.lu-sum__row-name {
  flex-shrink: 0;
  max-width: 140px;
  font-size: var(--ff-fs-body-sm);
  font-weight: var(--ff-fw-semibold);
  color: var(--ff-text-primary);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
.lu-sum__row-code {
  flex-shrink: 0;
  font-size: var(--ff-fs-overline);
  color: var(--ff-text-tertiary);
  font-variant-numeric: tabular-nums;
}
.lu-sum__row-price {
  flex-shrink: 0;
  min-width: 52px;
  font-size: var(--ff-fs-body-sm);
  font-weight: var(--ff-fw-bold);
  color: var(--ff-text-up);
  font-variant-numeric: tabular-nums;
}
.lu-sum__row-chg {
  flex-shrink: 0;
  min-width: 58px;
  font-size: var(--ff-fs-body-sm);
  font-weight: var(--ff-fw-semibold);
  font-variant-numeric: tabular-nums;
}

/* 归因：独占弹性宽度，占满行内剩余空间；超长省略，完整内容见 title */
.lu-sum__row-reason {
  flex: 1 1 200px;
  min-width: 0;
  font-size: var(--ff-fs-caption);
  color: var(--ff-text-secondary);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

/* 标签组：靠右 */
.lu-sum__row-tags {
  flex-shrink: 0;
  display: inline-flex;
  align-items: center;
  gap: 6px;
}
.lu-sum__row-tag {
  padding: 0 6px;
  border-radius: var(--ff-radius-sm);
  font-size: var(--ff-fs-overline);
  color: var(--ff-text-secondary);
  background: var(--ff-bg-muted);
  white-space: nowrap;
  font-variant-numeric: tabular-nums;
  line-height: 1.6;
}

/* 窄屏：归因独占一行、标签换行 */
@media (max-width: 640px) {
  .lu-sum__row {
    flex-wrap: wrap;
    row-gap: 4px;
    padding: 8px 10px;
  }
  .lu-sum__row-reason {
    flex-basis: 100%;
    order: 1;
  }
  .lu-sum__row-tags {
    order: 2;
    margin-left: auto;
  }
  .lu-sum__row-name {
    max-width: 96px;
  }
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
</style>
