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
      top: '36%',
      textStyle: { fontSize: 20, fontWeight: 700, color: chartVar('--ff-text-primary') },
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
    grid: { left: 90, right: 16, top: 6, bottom: 20 },
    xAxis: { type: 'value', splitLine: { lineStyle: { type: 'dashed' } } },
    yAxis: { type: 'category', data: entries.map((e) => e[0]).reverse() },
    series: [
      {
        type: 'bar',
        data: entries.map((e) => e[1]).reverse(),
        barMaxWidth: 16,
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

// 数据源健康明细：桌面默认展开，移动端默认收起（次要内容可折叠）
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
        <p class="ff-page__subtitle">系统运行状态、情绪分布与来源统计总览</p>
      </div>
    </div>

    <AppSkeleton v-if="loading" variant="text" :lines="8" />
    <EmptyState v-else-if="!stats" text="无法加载统计数据" icon="pie-chart" />

    <template v-else>
      <!-- ═══ L1 核心指标（置顶，最显眼）═══ -->
      <section class="ff-dash-section">
        <header class="ff-dash-section__head">
          <span class="ff-dash-section__eyebrow">
            <AppIcon name="activity" size="sm" /> 核心指标
          </span>
          <span class="ff-dash-section__hint">点击卡片直达相关模块</span>
        </header>
        <div class="ff-dashboard-view__kpis">
          <StatCard
            label="新闻总量"
            :value="stats.total_news?.toLocaleString()"
            sub="全部已入库新闻"
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
            sub="待阅读新闻"
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
      </section>

      <!-- ═══ L2 数据洞察（图表层）═══ -->
      <section class="ff-dash-section">
        <header class="ff-dash-section__head">
          <span class="ff-dash-section__eyebrow">
            <AppIcon name="pie-chart" size="sm" /> 数据洞察
          </span>
          <span class="ff-dash-section__hint">情绪结构与来源集中度</span>
        </header>
        <div class="ff-grid">
          <div class="ff-col-12 ff-col-lg-6">
            <AppCard title="情绪分布">
              <ChartPanel :option="sentimentOption" height="264px" />
            </AppCard>
          </div>
          <div class="ff-col-12 ff-col-lg-6">
            <AppCard title="来源 TOP10">
              <ChartPanel :option="sourceOption" height="264px" />
            </AppCard>
          </div>
        </div>
      </section>

      <!-- ═══ L3 运行状态与数据源（明细层）═══ -->
      <section class="ff-dash-section">
        <header class="ff-dash-section__head">
          <span class="ff-dash-section__eyebrow">
            <AppIcon name="server" size="sm" /> 运行状态与数据源
          </span>
          <span class="ff-dash-section__hint">服务进程与采集通道健康度</span>
        </header>
        <div class="ff-grid">
          <div class="ff-col-12 ff-col-lg-5">
            <AppCard title="运行状态">
              <ul class="ff-dashboard-view__kv">
                <li>
                  <span class="ff-dashboard-view__label">服务状态</span>
                  <AppStatus :text="stats.status || '运行中'" :tone="(stats.status || '运行中') === '运行中' ? 'success' : 'danger'" />
                </li>
                <li>
                  <span class="ff-dashboard-view__label">采集轮次</span>
                  <strong class="ff-num">{{ stats.cycle ?? 0 }}</strong>
                </li>
                <li>
                  <span class="ff-dashboard-view__label">本轮新增</span>
                  <strong class="ff-num ff-t-up">{{ stats.new_count ?? 0 }}</strong>
                </li>
                <li>
                  <span class="ff-dashboard-view__label">数据源数</span>
                  <strong class="ff-num">{{ stats.source_count ?? 0 }}</strong>
                </li>
              </ul>
            </AppCard>
          </div>

          <div class="ff-col-12 ff-col-lg-7">
            <AppCard :title="`数据源健康`" :no-padding="true">
              <template #actions>
                <AppButton
                  variant="ghost"
                  size="sm"
                  :icon="healthOpen ? 'chevron-up' : 'chevron-down'"
                  @click="healthOpen = !healthOpen"
                >
                  {{ healthOpen ? '收起' : '展开' }}
                </AppButton>
              </template>

              <!-- 折叠态：仅显示健康汇总条 -->
              <div v-if="!healthOpen" class="ff-dashboard-view__summary">
                <span class="ff-dash-badge ff-dash-badge--ok">正常 {{ healthSummary.ok }}</span>
                <span v-if="healthSummary.warn" class="ff-dash-badge ff-dash-badge--warn">预警 {{ healthSummary.warn }}</span>
                <span v-if="healthSummary.fused" class="ff-dash-badge ff-dash-badge--fused">熔断 {{ healthSummary.fused }}</span>
                <span v-if="healthSummary.idle" class="ff-dash-badge ff-dash-badge--idle">闲置 {{ healthSummary.idle }}</span>
                <span v-if="!healthSummary.total" class="ff-dash-badge">暂无数据源</span>
              </div>

              <div v-else-if="stats.source_health?.length" class="ff-dashboard-view__sources">
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
            </AppCard>
          </div>
        </div>
      </section>
    </template>
  </div>
</template>

<style scoped>
.ff-dashboard-view {
  max-width: var(--ff-container-max);
  margin: 0 auto;
}

.ff-dash-section {
  display: flex;
  flex-direction: column;
  gap: var(--ff-space-3);
}

.ff-dash-section__head {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  gap: var(--ff-space-3);
  padding: 0 var(--ff-space-1);
}

.ff-dash-section__eyebrow {
  display: inline-flex;
  align-items: center;
  gap: var(--ff-space-2);
  font-size: var(--ff-fs-body-sm);
  font-weight: 600;
  color: var(--ff-text-secondary);
  letter-spacing: 0.01em;
}

.ff-dash-section__hint {
  font-size: var(--ff-fs-caption);
  color: var(--ff-text-tertiary);
}

/* L1 核心指标：移动 2 列 / 桌面 4 列 */
.ff-dashboard-view__kpis {
  display: grid;
  grid-template-columns: repeat(2, 1fr);
  gap: var(--ff-space-3);
}

/* L3 运行状态 KV：2 列网格，减少纵向堆叠 */
.ff-dashboard-view__kv {
  list-style: none;
  display: grid;
  grid-template-columns: repeat(2, 1fr);
  gap: 0 var(--ff-space-5);
  margin: 0;
  padding: 0;
}
.ff-dashboard-view__kv li {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: var(--ff-space-2);
  padding: var(--ff-space-3) 0;
  border-bottom: 1px dashed var(--ff-border-subtle);
  font-size: var(--ff-fs-body-sm);
  min-width: 0;
}
.ff-dashboard-view__kv li:nth-last-child(-n + 2) {
  border-bottom: none;
}
.ff-dashboard-view__label {
  color: var(--ff-text-secondary);
  white-space: nowrap;
}
.ff-dashboard-view__kv strong {
  font-weight: 600;
  font-size: var(--ff-fs-body);
  color: var(--ff-text-primary);
  font-variant-numeric: tabular-nums;
}

/* 数据源健康折叠态汇总条 */
.ff-dashboard-view__summary {
  display: flex;
  flex-wrap: wrap;
  gap: var(--ff-space-2);
  padding: var(--ff-space-4);
}
.ff-dash-badge {
  display: inline-flex;
  align-items: center;
  gap: var(--ff-space-1);
  height: 28px;
  padding: 0 var(--ff-space-3);
  border-radius: var(--ff-radius-pill);
  border: 1px solid var(--ff-border);
  background: var(--ff-bg-subtle);
  color: var(--ff-text-secondary);
  font-size: var(--ff-fs-body-sm);
  font-weight: 500;
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

.ff-dashboard-view__sources {
  display: flex;
  flex-direction: column;
  max-height: 360px;
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
  padding: var(--ff-space-2) var(--ff-space-2);
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
