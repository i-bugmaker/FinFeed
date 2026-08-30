<script setup>
/**
 * MarketOverviewCard — 全市场涨跌统计（通达信行情）
 *
 * 数据来源：GET /api/easytdx/dashboard/overview（后端 60s TTL 缓存）
 * 展示：上涨 / 下跌 / 平盘 / 涨停 / 跌停 / 成交额 + 涨跌分布条 + 总量辅信息。
 * 红涨绿跌（--ff-text-up / --ff-down-text）。
 */
import { ref, watch, onMounted, computed } from 'vue'
import easytdxApi from '../../features/easytdx/api/easytdxApi'
import AppEmpty from '../../ui/AppEmpty.vue'
import AppSkeleton from '../../ui/AppSkeleton.vue'
import { fmtAmount, fmtChg, fmtInt } from './format'

const props = defineProps({
  refreshKey: { type: Number, default: 0 },
})

const loading = ref(false)
const err = ref('')
const payload = ref(null) // { ok, data }

const overview = computed(() => (payload.value && payload.value.ok ? payload.value.data : null))

// 涨跌分布条比例
const dist = computed(() => {
  const o = overview.value
  if (!o) return null
  const total = o.total || 0
  const pct = (v) => (total ? ((v / total) * 100).toFixed(1) + '%' : '0%')
  return {
    up: pct(o.up || 0),
    down: pct(o.down || 0),
    neutral: pct(o.neutral || 0),
  }
})

const metrics = computed(() => {
  const o = overview.value
  if (!o) return []
  return [
    { label: '上涨家数', value: fmtInt(o.up), tone: 'up' },
    { label: '下跌家数', value: fmtInt(o.down), tone: 'down' },
    { label: '平盘', value: fmtInt(o.neutral), tone: '' },
    { label: '成交额', value: fmtAmount(o.amount), tone: '' },
  ]
})

async function load() {
  loading.value = true
  err.value = ''
  try {
    payload.value = await easytdxApi.dashboard.overview()
  } catch (e) {
    err.value = e.message || String(e)
    payload.value = null
  } finally {
    loading.value = false
  }
}

watch(() => props.refreshKey, () => load())
onMounted(load)
</script>

<template>
  <div class="mo">
    <div v-if="loading" class="mo__load">
      <AppSkeleton variant="text" :lines="4" />
    </div>
    <AppEmpty
      v-else-if="!overview"
      icon="activity"
      title="暂无全市场涨跌统计"
      description="通达信行情不可用或尚未返回数据"
    />
    <template v-else>
      <div class="mo__metrics">
        <div v-for="m in metrics" :key="m.label" class="mo__metric" :class="`is-${m.tone}`">
          <span class="mo__label">{{ m.label }}</span>
          <span class="mo__value ff-num">{{ m.value }}</span>
        </div>
        <div class="mo__metric mo__metric--ratio">
          <span class="mo__label">上涨比例</span>
          <span class="mo__value ff-num is-up">{{ overview.up_ratio }}%</span>
        </div>
      </div>

      <!-- 涨跌分布条 -->
      <div class="mo__dist" aria-label="涨跌分布">
        <div class="mo__dist-track">
          <span class="mo__dist-up" :style="{ flex: overview.up }" :title="`上涨 ${dist.up}`"></span>
          <span class="mo__dist-neutral" :style="{ flex: overview.neutral }" :title="`平盘 ${dist.neutral}`"></span>
          <span class="mo__dist-down" :style="{ flex: overview.down }" :title="`下跌 ${dist.down}`"></span>
        </div>
        <div class="mo__dist-legend">
          <span class="mo__legend mo__legend--up"><i></i>上涨 {{ dist.up }}</span>
          <span class="mo__legend mo__legend--flat"><i></i>平盘 {{ dist.neutral }}</span>
          <span class="mo__legend mo__legend--down"><i></i>下跌 {{ dist.down }}</span>
        </div>
      </div>

      <!-- 辅信息 -->
      <div class="mo__foot">
        <span>合计 <strong class="ff-num">{{ fmtInt(overview.total) }}</strong> 家</span>
        <span>停牌 <strong class="ff-num">{{ fmtInt(overview.suspended) }}</strong></span>
        <span>流通市值 <strong class="ff-num">{{ fmtAmount(overview.mcap) }}</strong></span>
      </div>
    </template>
  </div>
</template>

<style scoped>
.mo {
  display: flex;
  flex-direction: column;
  gap: var(--ff-space-4);
}
.mo__load {
  min-height: 120px;
}

/* 指标格 */
.mo__metrics {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: var(--ff-space-3);
}
@media (min-width: 900px) {
  .mo__metrics {
    grid-template-columns: repeat(5, 1fr);
  }
}
.mo__metric {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 2px;
  padding: var(--ff-space-3);
  border-radius: var(--ff-radius-md);
  background: var(--ff-bg-subtle);
  border: 1px solid var(--ff-border-subtle);
}
.mo__label {
  font-size: var(--ff-fs-caption);
  color: var(--ff-text-tertiary);
  white-space: nowrap;
}
.mo__value {
  font-size: var(--ff-fs-h3);
  font-weight: var(--ff-fw-bold);
  font-variant-numeric: tabular-nums;
  color: var(--ff-text-primary);
}
.mo__metric.is-up .mo__value {
  color: var(--ff-text-up);
}
.mo__metric.is-down .mo__value {
  color: var(--ff-down-text);
}
.mo__metric--ratio .mo__value {
  color: var(--ff-text-up);
}

/* 涨跌分布条 */
.mo__dist {
  display: flex;
  flex-direction: column;
  gap: var(--ff-space-2);
}
.mo__dist-track {
  display: flex;
  height: 10px;
  border-radius: var(--ff-radius-pill);
  overflow: hidden;
  background: var(--ff-bg-muted);
}
.mo__dist-up {
  background: var(--ff-up);
}
.mo__dist-neutral {
  background: var(--ff-chart-neutral);
}
.mo__dist-down {
  background: var(--ff-down);
}
.mo__dist-legend {
  display: flex;
  flex-wrap: wrap;
  gap: var(--ff-space-3);
}
.mo__legend {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  font-size: var(--ff-fs-caption);
  color: var(--ff-text-secondary);
}
.mo__legend i {
  width: 8px;
  height: 8px;
  border-radius: 2px;
  display: inline-block;
}
.mo__legend--up i {
  background: var(--ff-up);
}
.mo__legend--flat i {
  background: var(--ff-chart-neutral);
}
.mo__legend--down i {
  background: var(--ff-down);
}

/* 辅信息 */
.mo__foot {
  display: flex;
  flex-wrap: wrap;
  gap: var(--ff-space-2) var(--ff-space-4);
  font-size: var(--ff-fs-caption);
  color: var(--ff-text-tertiary);
}
.mo__foot strong {
  color: var(--ff-text-secondary);
  font-variant-numeric: tabular-nums;
}
</style>
