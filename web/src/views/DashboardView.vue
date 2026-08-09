<script setup>
import { ref, onMounted, computed } from 'vue'
import { api } from '../api/client'
import StatCard from '../components/StatCard.vue'
import ChartPanel from '../components/ChartPanel.vue'
import EmptyState from '../components/EmptyState.vue'

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
          { name: '利好', value: s.positive || 0, itemStyle: { color: '#e5484d' } },
          { name: '利空', value: s.negative || 0, itemStyle: { color: '#16a34a' } },
          { name: '中性', value: s.neutral || 0, itemStyle: { color: '#9ca3af' } },
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
        itemStyle: { color: '#185fa5', borderRadius: [0, 4, 4, 0] },
      },
    ],
  }
})

function healthClass(s) {
  if (!s) return 'ok'
  if (s.is_circuit_open) return 'fused'
  if (s.consecutive_failures >= 2 || s.status === 'warning') return 'warn'
  if (s.status === 'fused') return 'fused'
  if (s.status === 'idle') return 'idle'
  return 'ok'
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
  <div class="dash">
    <div class="stats" v-if="stats">
      <StatCard label="新闻总量" :value="stats.total_news?.toLocaleString()" />
      <StatCard label="近 24h" :value="stats.total_24h?.toLocaleString()" tone="up" />
      <StatCard label="未读" :value="stats.unread_count?.toLocaleString()" />
      <StatCard label="收藏" :value="stats.favorite_count?.toLocaleString()" />
    </div>

    <div class="grid" v-if="stats">
      <!-- 运行状态 -->
      <div class="card block">
        <h3>运行状态</h3>
        <ul>
          <li>
            <span>服务状态</span>
            <b :class="(stats.status || '运行中') === '运行中' ? 'up' : 'down'">{{ stats.status || '运行中' }}</b>
          </li>
          <li><span>采集轮次</span><b class="num">{{ stats.cycle ?? 0 }}</b></li>
          <li><span>本轮新增</span><b class="num up">{{ stats.new_count ?? 0 }}</b></li>
          <li><span>数据源数</span><b class="num">{{ stats.source_count ?? 0 }}</b></li>
        </ul>
      </div>

      <!-- 数据源健康 -->
      <div class="card block">
        <h3>数据源健康（{{ stats.source_health?.length || 0 }}）</h3>
        <div class="srcs" v-if="stats.source_health?.length">
          <div v-for="s in stats.source_health" :key="s.name" class="src">
            <span class="dot" :class="healthClass(s)"></span>
            <span class="sn">{{ s.name }}</span>
            <span class="stext" :class="healthClass(s)">{{ healthText(s) }}</span>
            <span class="sr num text-3">{{ s.success_rate }}%</span>
            <span class="sc num text-3">{{ s.today_count }} 条</span>
          </div>
        </div>
        <EmptyState v-else text="暂无数据源信息" />
      </div>
    </div>

    <div class="grid" v-if="stats">
      <div class="card chart-card">
        <h3>情绪分布</h3>
        <ChartPanel :option="sentimentOption" height="280px" />
      </div>
      <div class="card chart-card">
        <h3>来源 TOP10</h3>
        <ChartPanel :option="sourceOption" height="280px" />
      </div>
    </div>
    <EmptyState v-if="!loading && !stats" text="无法加载统计数据" />
  </div>
</template>

<style scoped>
.dash {
  max-width: var(--content-max);
  margin: 0 auto;
  display: flex;
  flex-direction: column;
  gap: var(--sp-5);
}
.stats {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: var(--sp-4);
}
.grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: var(--sp-4);
}
.chart-card {
  padding: var(--sp-4) var(--sp-5);
}
.chart-card h3 {
  font-size: var(--fs-md);
  margin-bottom: var(--sp-3);
}
.block {
  padding: var(--sp-4) var(--sp-5);
}
.block h3 {
  font-size: var(--fs-md);
  margin-bottom: var(--sp-3);
}
.block ul {
  list-style: none;
  display: flex;
  flex-direction: column;
  gap: 10px;
}
.block li {
  display: flex;
  justify-content: space-between;
  font-size: var(--fs-sm);
}
.srcs {
  display: flex;
  flex-direction: column;
  gap: 8px;
  max-height: 320px;
  overflow-y: auto;
}
.src {
  display: flex;
  align-items: center;
  gap: 10px;
  font-size: var(--fs-sm);
}
.dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  background: var(--text-3);
  flex-shrink: 0;
}
.dot.ok {
  background: var(--down);
}
.dot.warn {
  background: var(--warn);
}
.dot.fused {
  background: var(--up);
}
.dot.idle {
  background: var(--text-3);
}
.stext {
  font-size: var(--fs-xs);
  font-weight: 600;
}
.stext.ok {
  color: var(--down);
}
.stext.warn {
  color: var(--warn);
}
.stext.fused {
  color: var(--up);
}
.stext.idle {
  color: var(--text-3);
}
.sn {
  flex: 1;
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.sr {
  width: 54px;
  text-align: right;
}
.sc {
  width: 56px;
  text-align: right;
}
@keyframes spin {
  to {
    transform: rotate(360deg);
  }
}
@media (max-width: 880px) {
  .stats {
    grid-template-columns: repeat(2, 1fr);
  }
  .grid {
    grid-template-columns: 1fr;
  }
}
</style>
