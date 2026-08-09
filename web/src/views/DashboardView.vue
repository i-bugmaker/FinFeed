<script setup>
import { ref, onMounted, computed } from 'vue'
import { api } from '../api/client'
import StatCard from '../components/StatCard.vue'
import ChartPanel from '../components/ChartPanel.vue'
import EmptyState from '../components/EmptyState.vue'
import AppCard from '../ui/AppCard.vue'
import AppStatus from '../ui/AppStatus.vue'
import AppIcon from '../ui/AppIcon.vue'
import AppSkeleton from '../ui/AppSkeleton.vue'

const stats = ref(null)
const loading = ref(true)

const sentimentOption = computed(() => {
  const s = stats.value?.sentiment_stats || {}
  return {
    tooltip: { trigger: 'item' },
    legend: { bottom: 0 },
    series: [
      {
        type: 'pie',
        radius: ['45%', '70%'],
        center: ['50%', '45%'],
        data: [
          { name: '利好', value: s.positive || 0, itemStyle: { color: 'var(--ff-chart-up)' } },
          { name: '利空', value: s.negative || 0, itemStyle: { color: 'var(--ff-chart-down)' } },
          { name: '中性', value: s.neutral || 0, itemStyle: { color: 'var(--ff-chart-neutral)' } },
        ],
        label: { formatter: '{b}\n{d}%' },
      },
    ],
  }
})

const sourceOption = computed(() => {
  const ss = stats.value?.source_stats || {}
  const entries = Object.entries(ss).sort((a, b) => b[1] - a[1]).slice(0, 10)
  return {
    tooltip: { trigger: 'axis' },
    grid: { left: 90, right: 20, top: 10, bottom: 20 },
    xAxis: { type: 'value' },
    yAxis: { type: 'category', data: entries.map((e) => e[0]).reverse() },
    series: [
      {
        type: 'bar',
        data: entries.map((e) => e[1]).reverse(),
        itemStyle: { color: 'var(--ff-chart-primary)', borderRadius: [0, 4, 4, 0] },
      },
    ],
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
        <p class="ff-page__subtitle">系统运行状态、情绪分布与来源统计</p>
      </div>
    </div>

    <AppSkeleton v-if="loading" variant="text" :lines="8" />
    <EmptyState v-else-if="!stats" text="无法加载统计数据" icon="pie-chart" />

    <template v-else>
      <div class="ff-dashboard-view__stats">
        <StatCard label="新闻总量" :value="stats.total_news?.toLocaleString()" />
        <StatCard label="近 24h" :value="stats.total_24h?.toLocaleString()" tone="up" />
        <StatCard label="未读" :value="stats.unread_count?.toLocaleString()" />
        <StatCard label="收藏" :value="stats.favorite_count?.toLocaleString()" />
      </div>

      <div class="ff-grid">
        <div class="ff-col-12 ff-col-lg-6">
          <AppCard title="运行状态">
            <ul class="ff-dashboard-view__kv">
              <li>
                <span>服务状态</span>
                <AppStatus :text="stats.status || '运行中'" :tone="(stats.status || '运行中') === '运行中' ? 'success' : 'danger'" />
              </li>
              <li><span>采集轮次</span><strong class="ff-num">{{ stats.cycle ?? 0 }}</strong></li>
              <li><span>本轮新增</span><strong class="ff-num ff-t-up">{{ stats.new_count ?? 0 }}</strong></li>
              <li><span>数据源数</span><strong class="ff-num">{{ stats.source_count ?? 0 }}</strong></li>
            </ul>
          </AppCard>
        </div>

        <div class="ff-col-12 ff-col-lg-6">
          <AppCard :title="`数据源健康（${stats.source_health?.length || 0}）`" :no-padding="true">
            <div v-if="stats.source_health?.length" class="ff-dashboard-view__sources">
              <div v-for="s in stats.source_health" :key="s.name" class="ff-dashboard-view__source">
                <AppStatus :tone="healthTone(s)" />
                <span class="ff-dashboard-view__name">{{ s.name }}</span>
                <span class="ff-dashboard-view__text" :class="`ff-t-${healthTone(s) === 'success' ? 'down' : healthTone(s)}`">
                  {{ healthText(s) }}
                </span>
                <span class="ff-dashboard-view__num ff-num">{{ s.success_rate }}%</span>
                <span class="ff-dashboard-view__num ff-num">{{ s.today_count }} 条</span>
              </div>
            </div>
            <EmptyState v-else text="暂无数据源信息" icon="database" />
          </AppCard>
        </div>
      </div>

      <div class="ff-grid">
        <div class="ff-col-12 ff-col-lg-6">
          <AppCard title="情绪分布">
            <ChartPanel :option="sentimentOption" height="280px" />
          </AppCard>
        </div>
        <div class="ff-col-12 ff-col-lg-6">
          <AppCard title="来源 TOP10">
            <ChartPanel :option="sourceOption" height="280px" />
          </AppCard>
        </div>
      </div>
    </template>
  </div>
</template>

<style scoped>
.ff-dashboard-view {
  max-width: var(--ff-container-max);
  margin: 0 auto;
}

.ff-dashboard-view__stats {
  display: grid;
  grid-template-columns: repeat(2, 1fr);
  gap: var(--ff-space-4);
  margin-bottom: var(--ff-space-5);
}

.ff-dashboard-view__kv {
  list-style: none;
  display: flex;
  flex-direction: column;
  gap: var(--ff-space-3);
  margin: 0;
  padding: 0;
}

.ff-dashboard-view__kv li {
  display: flex;
  justify-content: space-between;
  align-items: center;
  font-size: var(--ff-fs-sm);
}

.ff-dashboard-view__sources {
  display: flex;
  flex-direction: column;
  gap: var(--ff-space-2);
  max-height: 320px;
  overflow-y: auto;
  padding: var(--ff-space-4);
}

.ff-dashboard-view__source {
  display: flex;
  align-items: center;
  gap: var(--ff-space-3);
  font-size: var(--ff-fs-sm);
}

.ff-dashboard-view__name {
  flex: 1 1 auto;
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.ff-dashboard-view__text {
  font-size: var(--ff-fs-xs);
  font-weight: 600;
}

.ff-dashboard-view__num {
  width: 56px;
  text-align: right;
  color: var(--ff-text-tertiary);
}

@media (min-width: 1024px) {
  .ff-dashboard-view__stats {
    grid-template-columns: repeat(4, 1fr);
  }
}
</style>
