<script setup>
import { ref, computed, onMounted, onUnmounted } from 'vue'
import { api } from '../api/client'
import { useAppStore } from '../store/app'
import StatCard from '../components/StatCard.vue'
import ChartPanel from '../components/ChartPanel.vue'
import EmptyState from '../components/EmptyState.vue'
import AppCard from '../ui/AppCard.vue'
import AppStatus from '../ui/AppStatus.vue'
import AppIcon from '../ui/AppIcon.vue'
import AppButton from '../ui/AppButton.vue'
import AppSkeleton from '../ui/AppSkeleton.vue'

const store = useAppStore()
const stats = ref(null)
const loading = ref(true)

// ECharts 走 canvas 渲染，无法解析 var()，须取具体色值
function chartVar(name) {
  return getComputedStyle(document.documentElement).getPropertyValue(name).trim() || undefined
}

const sentimentOption = computed(() => {
  void store.theme // 换肤后重绘
  const s = stats.value?.sentiment_stats || {}
  const total = (s.positive || 0) + (s.negative || 0) + (s.neutral || 0)
  return {
    title: {
      text: total ? String(total) : '—',
      subtext: '总新闻',
      left: 'center',
      top: '34%',
      textStyle: { fontSize: 18, fontWeight: 700, color: chartVar('--ff-text-primary') },
      subtextStyle: { fontSize: 11, color: chartVar('--ff-text-tertiary') },
    },
    tooltip: { trigger: 'item', formatter: '{b}：{c} 条（{d}%）' },
    legend: { bottom: 0, left: 'center', icon: 'circle', itemWidth: 8, itemHeight: 8 },
    series: [
      {
        type: 'pie',
        radius: ['48%', '72%'],
        center: ['50%', '46%'],
        avoidLabelOverlap: true,
        itemStyle: {
          borderColor: chartVar('--ff-bg-surface'),
          borderWidth: 2,
          borderRadius: 4,
        },
        label: {
          show: true,
          formatter: '{d}%',
          color: chartVar('--ff-text-secondary'),
          fontSize: 12,
          fontWeight: 500,
        },
        labelLine: { length: 8, length2: 6 },
        data: [
          { name: '利好', value: s.positive || 0, itemStyle: { color: chartVar('--ff-chart-up') } },
          { name: '利空', value: s.negative || 0, itemStyle: { color: chartVar('--ff-chart-down') } },
          { name: '中性', value: s.neutral || 0, itemStyle: { color: chartVar('--ff-chart-neutral') } },
        ],
      },
    ],
  }
})

const sourceOption = computed(() => {
  void store.theme
  const ss = stats.value?.source_stats || {}
  const entries = Object.entries(ss).sort((a, b) => b[1] - a[1]).slice(0, 10)
  return {
    tooltip: { trigger: 'axis', axisPointer: { type: 'shadow' } },
    grid: { left: 88, right: 14, top: 4, bottom: 16 },
    xAxis: { type: 'value', splitLine: { lineStyle: { type: 'dashed' } } },
    yAxis: { type: 'category', data: entries.map((e) => e[0]).reverse() },
    series: [
      {
        type: 'bar',
        data: entries.map((e) => e[1]).reverse(),
        barMaxWidth: 14,
        itemStyle: { color: chartVar('--ff-chart-primary'), borderRadius: [0, 4, 4, 0] },
      },
    ],
  }
})

const healthSummary = computed(() => {
  const h = stats.value?.source_health || []
  return {
    total: h.length,
    ok: h.filter((x) => !x.is_circuit_open && x.status !== 'idle' && x.status !== 'warning').length,
    warn: h.filter((x) => x.status === 'warning' || x.consecutive_failures >= 2).length,
    fused: h.filter((x) => x.is_circuit_open || x.status === 'fused').length,
    idle: h.filter((x) => x.status === 'idle').length,
  }
})

function healthTone(s) {
  if (!s) return 'success'
  if (s.is_circuit_open || s.status === 'fused') return 'danger'
  if (s.consecutive_failures >= 2 || s.status === 'warning') return 'warn'
  if (s.status === 'idle') return 'neutral'
  return 'success'
}
function healthText(s) {
  if (!s) return '正常'
  if (s.is_circuit_open || s.status === 'fused') return '熔断'
  if (s.consecutive_failures >= 2 || s.status === 'warning') return '预警'
  if (s.status === 'idle') return '闲置'
  return '正常'
}

// 数据源健康明细：桌面默认展开，移动端默认收起（健康度信息始终可见）
const mqMobile = window.matchMedia('(max-width: 767px)')
const healthOpen = ref(!mqMobile.matches)
function onMqChange() {
  healthOpen.value = !mqMobile.matches
}
onMounted(() => {
  mqMobile.addEventListener('change', onMqChange)
})
onUnmounted(() => {
  mqMobile.removeEventListener('change', onMqChange)
})

onMounted(async () => {
  try {
    stats.value = await api.stats()
  } catch (e) {
    console.error(e)
  } finally {
    loading.value = false
  }
})
</script>

<template>
  <div class="ff-page ff-dashboard-view">
    <div class="ff-page__header">
      <div>
        <h1 class="ff-page__title">
          <AppIcon name="dashboard" size="lg" /> 仪表盘
        </h1>
        <p class="ff-page__subtitle">核心指标 · 情绪结构 · 系统状态 一屏总览</p>
      </div>
    </div>

    <AppSkeleton v-if="loading" variant="text" :lines="8" />
    <EmptyState v-else-if="!stats" text="无法加载统计数据" icon="pie-chart" />

    <template v-else>
      <!-- ═══ L1 核心指标（首要）═══ -->
      <div class="ff-dashboard-view__kpis">
        <StatCard
          label="新闻总量"
          :value="stats.total_news?.toLocaleString()"
          sub="全部已入库"
          icon="newspaper"
          to="/news"
        />
        <StatCard
          label="近 24h"
          :value="stats.total_24h?.toLocaleString()"
          sub="24 小时内新增"
          tone="up"
          icon="activity"
          to="/news"
        />
        <StatCard
          label="未读"
          :value="stats.unread_count?.toLocaleString()"
          sub="待阅读"
          icon="inbox"
          to="/news"
        />
        <StatCard
          label="收藏"
          :value="stats.favorite_count?.toLocaleString()"
          sub="我的收藏"
          icon="star"
          to="/favorites"
        />
      </div>

      <!-- ═══ L2 运行状态 + 数据源健康（紧凑单条）═══ -->
      <div class="ff-dashboard-view__statusbar">
        <span class="ff-dashboard-view__statusbar-label">
          <AppIcon name="server" size="sm" /> 运行状态
        </span>
        <AppStatus :text="stats.status || '运行中'" :tone="(stats.status || '运行中') === '运行中' ? 'success' : 'danger'" />
        <span class="ff-dashboard-view__sep" aria-hidden="true"></span>
        <span class="ff-dashboard-view__kv-mini">轮次 <strong class="ff-num">{{ stats.cycle ?? 0 }}</strong></span>
        <span class="ff-dashboard-view__kv-mini">本轮 <strong class="ff-num ff-t-up">{{ stats.new_count ?? 0 }}</strong></span>
        <span class="ff-dashboard-view__kv-mini">数据源 <strong class="ff-num">{{ stats.source_count ?? 0 }}</strong></span>
        <span class="ff-dashboard-view__statusbar-spacer"></span>
        <span class="ff-dashboard-view__statusbar-label">
          <AppIcon name="database" size="sm" /> 健康
        </span>
        <span class="ff-dash-badge ff-dash-badge--ok">正常 {{ healthSummary.ok }}</span>
        <span v-if="healthSummary.warn" class="ff-dash-badge ff-dash-badge--warn">预警 {{ healthSummary.warn }}</span>
        <span v-if="healthSummary.fused" class="ff-dash-badge ff-dash-badge--fused">熔断 {{ healthSummary.fused }}</span>
        <span v-if="healthSummary.idle" class="ff-dash-badge ff-dash-badge--idle">闲置 {{ healthSummary.idle }}</span>
        <AppButton
          variant="ghost"
          size="sm"
          :icon="healthOpen ? 'chevron-up' : 'chevron-down'"
          @click="healthOpen = !healthOpen"
        >
          {{ healthOpen ? '收起' : '明细' }}
        </AppButton>
      </div>

      <!-- ═══ L3 数据洞察（两图等宽并列）═══ -->
      <div class="ff-grid ff-dashboard-view__charts">
        <div class="ff-col-12 ff-col-lg-6">
          <AppCard title="情绪分布" subtitle="近 24h 舆情倾向">
            <ChartPanel :option="sentimentOption" height="220px" />
          </AppCard>
        </div>
        <div class="ff-col-12 ff-col-lg-6">
          <AppCard title="来源 TOP10" subtitle="各数据源新闻量">
            <ChartPanel :option="sourceOption" height="220px" />
          </AppCard>
        </div>
      </div>

      <!-- ═══ L4 数据源健康明细（按需展开）═══ -->
      <Transition name="ff-fade">
        <div v-if="healthOpen" class="ff-dashboard-view__sources-wrap">
          <div v-if="stats.source_health?.length" class="ff-dashboard-view__sources">
            <div class="ff-dashboard-view__sources-head">
              <span></span>
              <span>名称</span>
              <span class="ff-dashboard-view__cell-status">状态</span>
              <span class="ff-dashboard-view__num">成功率</span>
              <span class="ff-dashboard-view__num">今日</span>
            </div>
            <div
              v-for="s in stats.source_health"
              :key="s.name"
              class="ff-dashboard-view__source"
            >
              <AppStatus :tone="healthTone(s)" />
              <span class="ff-dashboard-view__name">{{ s.name }}</span>
              <span class="ff-dashboard-view__status">{{ healthText(s) }}</span>
              <span class="ff-dashboard-view__num ff-num">{{ s.success_rate }}%</span>
              <span class="ff-dashboard-view__num ff-num">{{ s.today_count }} 条</span>
            </div>
          </div>
          <EmptyState v-else text="暂无数据源信息" icon="database" />
        </div>
      </Transition>
    </template>
  </div>
</template>

<style scoped>
.ff-dashboard-view {
  max-width: var(--ff-container-max);
  margin: 0 auto;
  display: flex;
  flex-direction: column;
  gap: var(--ff-space-3);
}

/* L1 核心指标：移动 2 列 / 桌面 4 列 */
.ff-dashboard-view__kpis {
  display: grid;
  grid-template-columns: repeat(2, 1fr);
  gap: var(--ff-space-3);
}

/* L2 图表区 */
.ff-dashboard-view__charts {
  row-gap: var(--ff-space-3);
}

/* L3 状态条：一行排布，移动端换行 */
.ff-dashboard-view__statusbar {
  display: flex;
  align-items: center;
  justify-content: flex-start;
  flex-wrap: wrap;
  gap: var(--ff-space-2) var(--ff-space-3);
  padding: var(--ff-space-2-5) var(--ff-space-4);
  border: 1px solid var(--ff-border);
  border-radius: var(--ff-radius-lg);
  background: var(--ff-bg-surface);
  box-shadow: var(--ff-shadow-xs);
}
.ff-dashboard-view__statusbar-spacer {
  flex: 1 1 auto;
  min-width: var(--ff-space-3);
}
.ff-dashboard-view__statusbar-label {
  display: inline-flex;
  align-items: center;
  gap: var(--ff-space-1-5);
  font-size: var(--ff-fs-body-sm);
  font-weight: 600;
  color: var(--ff-text-secondary);
  white-space: nowrap;
}
/* 分隔线（视觉分组） */
.ff-dashboard-view__sep {
  display: inline-block;
  width: 1px;
  height: 14px;
  background: var(--ff-border);
  margin: 0 var(--ff-space-1);
}
.ff-dashboard-view__kv-mini {
  display: inline-flex;
  align-items: baseline;
  gap: var(--ff-space-1);
  font-size: var(--ff-fs-body-sm);
  color: var(--ff-text-tertiary);
  white-space: nowrap;
}
.ff-dashboard-view__kv-mini strong {
  color: var(--ff-text-primary);
  font-weight: 600;
  font-variant-numeric: tabular-nums;
}

/* 健康汇总胶囊 */
.ff-dash-badge {
  display: inline-flex;
  align-items: center;
  height: 24px;
  padding: 0 var(--ff-space-2-5);
  border-radius: var(--ff-radius-pill);
  border: 1px solid var(--ff-border);
  background: var(--ff-bg-subtle);
  color: var(--ff-text-secondary);
  font-size: var(--ff-fs-caption);
  font-weight: 500;
  white-space: nowrap;
}
.ff-dash-badge--ok {
  color: var(--ff-down-text);
  background: var(--ff-down-subtle);
  border-color: var(--ff-down-border);
}
.ff-dash-badge--warn {
  color: var(--ff-warn-text);
  background: var(--ff-warn-subtle);
  border-color: var(--ff-warn-border);
}
.ff-dash-badge--fused {
  color: var(--ff-danger-text);
  background: var(--ff-danger-subtle);
  border-color: var(--ff-danger-border);
}
.ff-dash-badge--idle {
  color: var(--ff-text-tertiary);
  background: var(--ff-bg-muted);
  border-color: var(--ff-border);
}

/* 数据源健康明细 */
.ff-dashboard-view__sources-wrap {
  border: 1px solid var(--ff-border);
  border-radius: var(--ff-radius-lg);
  background: var(--ff-bg-surface);
  box-shadow: var(--ff-shadow-xs);
}
.ff-dashboard-view__sources {
  max-height: 280px;
  overflow-y: auto;
  overflow-x: auto;
  padding: var(--ff-space-2) var(--ff-space-4) var(--ff-space-4);
}
.ff-dashboard-view__sources-head {
  display: grid;
  grid-template-columns: 18px minmax(0, 1fr) 64px 72px 72px;
  align-items: center;
  gap: var(--ff-space-3);
  padding: var(--ff-space-2) 0;
  font-size: var(--ff-fs-caption);
  font-weight: 600;
  color: var(--ff-text-tertiary);
  letter-spacing: 0.06em;
  text-transform: uppercase;
  border-bottom: 1px solid var(--ff-border-subtle);
  position: sticky;
  top: 0;
  background: var(--ff-bg-surface);
  z-index: 1;
}
.ff-dashboard-view__cell-status {
  text-align: left;
}
.ff-dashboard-view__source {
  display: grid;
  grid-template-columns: 18px minmax(0, 1fr) 64px 72px 72px;
  align-items: center;
  gap: var(--ff-space-3);
  padding: var(--ff-space-2);
  font-size: var(--ff-fs-body-sm);
  border-radius: var(--ff-radius-sm);
  transition: background-color var(--ff-dur-fast) var(--ff-ease-standard);
}
.ff-dashboard-view__source:hover {
  background: var(--ff-bg-hover);
}
.ff-dashboard-view__name {
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  color: var(--ff-text-primary);
  font-weight: 500;
}
.ff-dashboard-view__status {
  font-size: var(--ff-fs-caption);
  color: var(--ff-text-secondary);
  font-weight: 500;
  white-space: nowrap;
}
.ff-dashboard-view__num {
  text-align: right;
  color: var(--ff-text-tertiary);
  font-variant-numeric: tabular-nums;
  white-space: nowrap;
}

@media (min-width: 1024px) {
  .ff-dashboard-view__kpis {
    grid-template-columns: repeat(4, 1fr);
    gap: var(--ff-space-4);
  }
}
</style>
