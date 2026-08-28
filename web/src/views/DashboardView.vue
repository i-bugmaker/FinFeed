<script setup>
/**
 * DashboardView — 盘面复盘主控台（v3.2 重构）
 *
 * 视觉层级：
 *   1) 顶部状态条：市场情绪灯 + 实时推送 + 刷新
 *   2) 今日市场速览：7 项核心情绪指标
 *   3) 盘面复盘主控台：涨跌全景（上下布局：宽度 + 涨停强度+连板天梯）
 *      + 板块排行榜 / 个股榜单
 *   4) 指数 K 线（上证 / 深证）
 *   5) 新闻舆情分析（可折叠辅助区）
 *   6) 数据源健康状态
 */
import { ref, computed, onMounted, onUnmounted } from 'vue'
import { api } from '../api/client'
import { useAppStore } from '../store/app'
import ChartPanel from '../components/ChartPanel.vue'
import EmptyState from '../components/EmptyState.vue'
import AppCard from '../ui/AppCard.vue'
import AppStatus from '../ui/AppStatus.vue'
import AppIcon from '../ui/AppIcon.vue'
import AppButton from '../ui/AppButton.vue'
import AppSkeleton from '../ui/AppSkeleton.vue'
import IndexKlineCard from '../components/IndexKlineCard.vue'
import { useMarketSocket } from '../composables/useMarketSocket'

// ─── 盘面复盘卡片（easy-tdx 行情） ───
import MarketOverviewCard from '../components/review/MarketOverviewCard.vue'
import LimitUpSummaryCard from '../components/review/LimitUpSummaryCard.vue'
import BoardRankingCard from '../components/review/BoardRankingCard.vue'
import StockRankingCard from '../components/review/StockRankingCard.vue'

// ─── 市场热榜（同花顺用户关注榜） ───
import ThsHotList from '../components/ThsHotList.vue'

const store = useAppStore()
const stats = ref(null)
const loading = ref(true)
const hasStats = computed(() => !!stats.value && !!stats.value?.cycle !== undefined && stats.value?.cycle > 0)

// ─── 今日市场速览（涨停聚焦指标，60s 后端缓存，与复盘卡同源） ───
const luFlow = ref(null)
const flowMetrics = computed(() => {
  const f = luFlow.value
  if (!f) return []
  const m = f.metrics || {}
  const rate = (v) => (v == null ? '—' : (Number(v) * 100).toFixed(1) + '%')
  return [
    { label: '涨停', value: f.up ?? '—', tone: 'up', icon: 'trending-up', note: '今日封板个股数' },
    { label: '跌停', value: f.lower ?? '—', tone: 'down', icon: 'trending-down', note: '今日封跌个股数' },
    { label: '炸板', value: f.open ?? '—', tone: 'warn', icon: 'flame', note: '封板后开板' },
    { label: '炸板率', value: rate(m.broken_rate), tone: '', icon: 'activity', note: '炸板 / (涨停+炸板)' },
    { label: '封板率', value: rate(m.seal_rate), tone: '', icon: 'check', note: '涨停 / (涨停+炸板)' },
    { label: '最高连板', value: f.maxHeight ? f.maxHeight + ' 板' : '—', tone: 'hot', icon: 'sparkles', note: '市场连板高度' },
    { label: '断板', value: f.broken ?? '—', tone: 'broken', icon: 'x', note: f.prevDate ? `对比基准 ${f.prevDate}` : '昨日连板今日未封板' },
  ]
})

async function fetchFlow() {
  try {
    const [intensityRes, ladderRes] = await Promise.all([
      api.market('thslimitup', { section: 'intensity' }),
      api.market('thslimitup', { section: 'ladder' }),
    ])
    const it = intensityRes && (intensityRes.data || intensityRes)
    const la = ladderRes && (ladderRes.data || ladderRes)
    luFlow.value = {
      up: la && la.tdx_up_total != null ? la.tdx_up_total : (it ? it.up_total : null),
      open: it ? it.open_total : null,
      lower: la && la.tdx_down_total != null ? la.tdx_down_total : (it ? it.lower_total : null),
      metrics: it ? (it.metrics || {}) : {},
      maxHeight: la ? la.max_height : 0,
      broken: (la && la.broken_ladder || [])
        .reduce((s, t) => s + ((t.stocks || []).length || 0), 0),
      prevDate: la ? la.prev_date : '',
    }
  } catch (e) {
    console.error('今日市场速览获取失败', e)
  }
}

// 盘面面板刷新：递增 refreshKey，各复盘卡片 watch 后重新取数
const panelRefreshKey = ref(0)
const refreshing = ref(false)
async function refreshPanel() {
  refreshing.value = true
  panelRefreshKey.value += 1
  try {
    await Promise.all([api.stats(), fetchFlow()])
  } catch (e) {
    console.error(e)
  } finally {
    refreshing.value = false
  }
}

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
        itemStyle: { borderColor: chartVar('--ff-bg-surface'), borderWidth: 2, borderRadius: 4 },
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

// 近 24h 新闻量时间趋势（补全缺失数据：stats.time_trend）
const trendOption = computed(() => {
  void store.theme
  const arr = stats.value?.time_trend || []
  const xs = arr.map((d) => d.time)
  const ys = arr.map((d) => d.count)
  return {
    tooltip: { trigger: 'axis', formatter: '{b}<br/>新闻量：{c} 条' },
    grid: { left: 36, right: 14, top: 18, bottom: 28 },
    xAxis: {
      type: 'category',
      data: xs,
      boundaryGap: false,
      axisLabel: { fontSize: 10, color: chartVar('--ff-text-tertiary'), hideOverlap: true },
      axisLine: { lineStyle: { color: chartVar('--ff-border') } },
    },
    yAxis: {
      type: 'value',
      splitLine: { lineStyle: { type: 'dashed', color: chartVar('--ff-bg-subtle') } },
      axisLabel: { fontSize: 10, color: chartVar('--ff-text-tertiary') },
    },
    series: [
      {
        type: 'line',
        smooth: true,
        showSymbol: false,
        data: ys,
        lineStyle: { width: 2, color: chartVar('--ff-chart-primary') },
        itemStyle: { color: chartVar('--ff-chart-primary') },
        areaStyle: { color: 'rgba(37,99,235,0.12)' },
      },
    ],
  }
})

// 重要性分布（补全缺失数据：stats.importance_distribution）
const importanceOption = computed(() => {
  void store.theme
  const d = stats.value?.importance_distribution || {}
  const order = ['极重要', '重要', '一般', '较低', '低']
  const entries = order.filter((k) => d[k] != null).map((k) => [k, d[k]])
  const cats = entries.map((e) => e[0]).reverse()
  const vals = entries.map((e) => e[1]).reverse()
  const palette = {
    '极重要': chartVar('--ff-chart-down'),
    '重要': chartVar('--ff-warn'),
    '一般': chartVar('--ff-chart-primary'),
    '较低': chartVar('--ff-text-tertiary'),
    '低': chartVar('--ff-text-tertiary'),
  }
  return {
    tooltip: { trigger: 'axis', axisPointer: { type: 'shadow' }, formatter: '{b}：{c} 条' },
    grid: { left: 56, right: 28, top: 12, bottom: 10 },
    xAxis: {
      type: 'value',
      splitLine: { lineStyle: { type: 'dashed', color: chartVar('--ff-bg-subtle') } },
      axisLabel: { fontSize: 10, color: chartVar('--ff-text-tertiary') },
    },
    yAxis: {
      type: 'category',
      data: cats,
      axisLabel: { fontSize: 11, color: chartVar('--ff-text-secondary') },
    },
    series: [
      {
        type: 'bar',
        data: vals.map((v, i) => ({
          value: v,
          itemStyle: { color: palette[cats[i]] || chartVar('--ff-chart-primary'), borderRadius: [0, 4, 4, 0] },
        })),
        barMaxWidth: 16,
        label: { show: true, position: 'right', fontSize: 10, color: chartVar('--ff-text-tertiary') },
      },
    ],
  }
})

// 分类分布（补全缺失数据：stats.category_stats）
const categoryOption = computed(() => {
  void store.theme
  const d = stats.value?.category_stats || {}
  const entries = Object.entries(d).filter(([, v]) => v > 0).sort((a, b) => b[1] - a[1])
  const palette = [
    chartVar('--ff-chart-primary'),
    chartVar('--ff-chart-up'),
    chartVar('--ff-chart-down'),
    chartVar('--ff-warn'),
    '#8b5cf6',
    '#0ea5e9',
  ]
  return {
    tooltip: { trigger: 'item', formatter: '{b}：{c} 条（{d}%）' },
    legend: { bottom: 0, left: 'center', icon: 'circle', itemWidth: 8, itemHeight: 8 },
    series: [
      {
        type: 'pie',
        radius: ['45%', '70%'],
        center: ['50%', '44%'],
        avoidLabelOverlap: true,
        itemStyle: { borderColor: chartVar('--ff-bg-surface'), borderWidth: 2, borderRadius: 4 },
        label: { show: true, formatter: '{d}%', fontSize: 11, color: chartVar('--ff-text-secondary') },
        data: entries.map((e, i) => ({
          name: e[0],
          value: e[1],
          itemStyle: { color: palette[i % palette.length] },
        })),
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

// 新闻舆情区（辅助区）与数据源健康：桌面默认展开，移动端默认收起
const mqMobile = window.matchMedia('(max-width: 767px)')
const newsOpen = ref(!mqMobile.matches)
const healthOpen = ref(false)
function onMqChange() {
  newsOpen.value = !mqMobile.matches
  healthOpen.value = false
}
onMounted(() => {
  mqMobile.addEventListener('change', onMqChange)
})
onUnmounted(() => {
  mqMobile.removeEventListener('change', onMqChange)
})

// 统计更新时间提示
const updateTime = computed(() => stats.value?.update_time || '')

// ─── 实时行情推送（WebSocket）：仅保留头部连接状态指示灯 ───
const {
  connected: liveConnected,
  connecting: liveConnecting,
} = useMarketSocket({ autoConnect: true })

const liveConnTone = computed(() =>
  liveConnected.value ? 'success' : liveConnecting.value ? 'warn' : 'danger',
)
const liveConnText = computed(() =>
  liveConnected.value ? '推送已连接' : liveConnecting.value ? '连接中…' : '已断开（自动重连）',
)

onMounted(async () => {
  try {
    await Promise.all([api.stats(), fetchFlow()])
  } catch (e) {
    console.error(e)
  } finally {
    loading.value = false
  }
})
</script>

<template>
  <div class="ff-page ff-dashboard-view">
    <!-- ═══ 顶部状态条 ═══ -->
    <header class="ff-dashboard-view__topbar">
      <!-- 页面标题按产品要求移除，h1 保留 sr-only 保文档语义 -->
      <h1 class="ff-sr-only">盘面复盘</h1>
      <div class="ff-dashboard-view__topbar-meta">
        <span v-if="updateTime" class="ff-dashboard-view__updated">
          <AppIcon name="refresh" size="xs" /> 更新于 {{ updateTime }}
        </span>
        <span
          class="ff-dashboard-view__live-badge"
          :class="liveConnected ? 'is-on' : liveConnecting ? 'is-wait' : 'is-off'"
        >
          <span class="ff-dashboard-view__live-dot"></span>
          {{ liveConnText }}
        </span>
        <AppButton
          variant="tonal"
          size="sm"
          icon="refresh"
          :loading="refreshing"
          @click="refreshPanel"
        >
          刷新
        </AppButton>
      </div>
    </header>

    <!-- ═══ 今日市场速览 ═══ -->
    <section v-if="flowMetrics.length" class="ff-dashboard-view__flow">
      <div
        v-for="m in flowMetrics"
        :key="m.label"
        class="ff-dashboard-view__flow-metric"
        :class="`is-${m.tone}`"
      >
        <span class="ff-dashboard-view__flow-icon">
          <AppIcon :name="m.icon" size="sm" />
        </span>
        <div class="ff-dashboard-view__flow-body">
          <span class="ff-dashboard-view__flow-label">{{ m.label }}</span>
          <span class="ff-dashboard-view__flow-value ff-num">{{ m.value }}</span>
          <span class="ff-dashboard-view__flow-note">{{ m.note }}</span>
        </div>
      </div>
    </section>

    <!-- ═══ 盘面复盘主控台 ═══ -->
    <section class="ff-dashboard-view__panel">
      <header class="ff-dashboard-view__panel-head">
        <h2 class="ff-dashboard-view__panel-title">
          <span class="ff-dashboard-view__panel-bar"></span>
          盘面复盘主控台
        </h2>
        <span class="ff-dashboard-view__panel-sub">通达信实时行情 · 晋级 / 断板一目了然</span>
        <span class="ff-dashboard-view__panel-spacer"></span>
        <span class="ff-dashboard-view__panel-legend">
          <i class="is-up"></i>晋级实色
          <i class="is-broken"></i>断板虚化打叉
        </span>
      </header>

      <div class="ff-dashboard-view__grid">
        <!-- 涨跌全景：上下布局（宽度 + 涨停强度 / 连板天梯） -->
        <div class="ff-dashboard-view__cell full">
          <AppCard title="涨跌全景" subtitle="市场宽度 + 涨停强度与连板梯队">
            <div class="ff-dashboard-view__panorama">
              <div class="ff-dashboard-view__panorama-width">
                <MarketOverviewCard :refresh-key="panelRefreshKey" />
              </div>
              <div class="ff-dashboard-view__panorama-focus">
                <LimitUpSummaryCard :refresh-key="panelRefreshKey" />
              </div>
            </div>
          </AppCard>
        </div>
        <div class="ff-dashboard-view__cell">
          <AppCard title="板块排行榜" subtitle="行业 / 概念 · 涨幅 / 主力资金">
            <BoardRankingCard :refresh-key="panelRefreshKey" />
          </AppCard>
        </div>
        <div class="ff-dashboard-view__cell">
          <AppCard title="个股榜单" subtitle="涨幅 / 跌幅 / 成交额">
            <StockRankingCard :refresh-key="panelRefreshKey" />
          </AppCard>
        </div>
      </div>
    </section>

    <!-- ═══ 市场热榜 ═══ -->
    <section class="ff-dashboard-view__hotrank">
      <header class="ff-dashboard-view__panel-head">
        <h2 class="ff-dashboard-view__panel-title">
          <span class="ff-dashboard-view__panel-bar"></span>
          市场热榜
        </h2>
        <span class="ff-dashboard-view__panel-sub">同花顺用户关注榜 · 实时热度</span>
      </header>
      <AppCard :no-padding="true" class="ff-dashboard-view__hotrank-card">
        <ThsHotList />
      </AppCard>
    </section>

    <!-- ═══ 指数 K 线 ═══ -->
    <section class="ff-dashboard-view__kline">
      <AppCard title="上证指数" subtitle="000001 · 多周期 + 分时">
        <IndexKlineCard code="000001" name="上证指数" />
      </AppCard>
      <AppCard title="深证成指" subtitle="399001 · 多周期 + 分时">
        <IndexKlineCard code="399001" name="深证成指" />
      </AppCard>
    </section>

    <!-- ═══ 新闻舆情（辅助区，可折叠）═══ -->
    <section class="ff-dashboard-view__news">
      <div class="ff-dashboard-view__news-head">
        <h2 class="ff-dashboard-view__news-title">
          <span class="ff-dashboard-view__panel-bar"></span>
          新闻舆情分析
        </h2>
        <span class="ff-dashboard-view__news-sub">已入库新闻的统计辅助视图</span>
        <span class="ff-dashboard-view__news-spacer"></span>
        <AppButton
          variant="ghost"
          size="sm"
          :icon="newsOpen ? 'chevron-up' : 'chevron-down'"
          @click="newsOpen = !newsOpen"
        >
          {{ newsOpen ? '收起' : '展开' }}
        </AppButton>
      </div>

      <AppSkeleton v-if="loading" variant="text" :lines="6" />
      <EmptyState v-else-if="!hasStats" text="暂无新闻舆情统计数据" icon="pie-chart" />

      <Transition name="ff-fade">
        <div v-if="!loading && hasStats && newsOpen" class="ff-dashboard-view__news-body">
          <div class="ff-dashboard-view__charts">
            <AppCard title="情绪分布">
              <ChartPanel :option="sentimentOption" height="220px" />
            </AppCard>
            <AppCard title="来源 TOP10">
              <ChartPanel :option="sourceOption" height="220px" />
            </AppCard>
            <AppCard title="近 24h 趋势">
              <ChartPanel :option="trendOption" height="220px" />
            </AppCard>
          </div>
          <div class="ff-dashboard-view__dist">
            <AppCard title="重要性分布">
              <ChartPanel :option="importanceOption" height="220px" />
            </AppCard>
            <AppCard title="分类分布">
              <ChartPanel :option="categoryOption" height="220px" />
            </AppCard>
          </div>
        </div>
      </Transition>
    </section>

    <!-- ═══ 数据源健康（紧凑平铺）═══ -->
    <section class="ff-dashboard-view__health">
      <div class="ff-dashboard-view__statusbar">
        <div class="ff-dashboard-view__statusbar-group">
          <AppIcon name="server" size="sm" />
          <span class="ff-dashboard-view__statusbar-label">运行状态</span>
          <AppStatus :text="stats?.status || '运行中'" :tone="(stats?.status || '运行中') === '运行中' ? 'success' : 'danger'" />
        </div>
        <template v-if="hasStats">
          <span class="ff-dashboard-view__sep" aria-hidden="true"></span>
          <span class="ff-dashboard-view__kv-mini">轮次 <strong class="ff-num">{{ stats?.cycle ?? 0 }}</strong></span>
          <span class="ff-dashboard-view__kv-mini">本轮 <strong class="ff-num ff-t-up">{{ stats?.new_count ?? 0 }}</strong></span>
          <span class="ff-dashboard-view__kv-mini">数据源 <strong class="ff-num">{{ stats?.source_count ?? 0 }}</strong></span>
        </template>
        <span class="ff-dashboard-view__statusbar-spacer"></span>
        <div class="ff-dashboard-view__statusbar-group">
          <AppIcon name="database" size="sm" />
          <span class="ff-dashboard-view__statusbar-label">健康</span>
          <span class="ff-dash-badge ff-dash-badge--ok">正常 {{ healthSummary.ok }}</span>
          <span v-if="healthSummary.warn" class="ff-dash-badge ff-dash-badge--warn">预警 {{ healthSummary.warn }}</span>
          <span v-if="healthSummary.fused" class="ff-dash-badge ff-dash-badge--fused">熔断 {{ healthSummary.fused }}</span>
          <span v-if="healthSummary.idle" class="ff-dash-badge ff-dash-badge--idle">闲置 {{ healthSummary.idle }}</span>
        </div>
        <AppButton
          variant="ghost"
          size="sm"
          :icon="healthOpen ? 'chevron-up' : 'chevron-down'"
          @click="healthOpen = !healthOpen"
        >
          {{ healthOpen ? '收起明细' : '展开明细' }}
        </AppButton>
      </div>

      <Transition name="ff-fade">
        <div v-if="healthOpen && hasStats" class="ff-dashboard-view__tiles">
          <div
            v-for="s in stats.source_health || []"
            :key="s.name"
            class="ff-dashboard-view__tile"
          >
            <div class="ff-dashboard-view__tile-head">
              <AppStatus :tone="healthTone(s)" />
              <span class="ff-dashboard-view__tile-name" :title="s.name">{{ s.name }}</span>
              <span class="ff-dashboard-view__tile-status" :class="`is-${healthTone(s)}`">{{ healthText(s) }}</span>
            </div>
            <div class="ff-dashboard-view__tile-meta">
              <span>成功率 <strong class="ff-num">{{ s.success_rate }}%</strong></span>
              <span>今日 <strong class="ff-num">{{ s.today_count }} 条</strong></span>
            </div>
          </div>
          <EmptyState v-if="!stats.source_health?.length" text="暂无数据源信息" icon="database" />
        </div>
      </Transition>
    </section>
  </div>
</template>

<style scoped>
.ff-dashboard-view {
  max-width: var(--ff-container-max);
  margin: 0 auto;
  display: flex;
  flex-direction: column;
  gap: var(--ff-space-5);
}

/* ═══ 顶部状态条 ═══ */
.ff-dashboard-view__topbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--ff-space-4);
  padding: var(--ff-space-3) var(--ff-space-5);
  border: 1px solid var(--ff-border);
  border-radius: var(--ff-radius-lg);
  background: linear-gradient(135deg, var(--ff-bg-surface), var(--ff-bg-subtle));
  box-shadow: var(--ff-shadow-xs);
}
.ff-dashboard-view__brand {
  display: flex;
  align-items: center;
  gap: var(--ff-space-3);
  color: var(--ff-brand-text);
}
.ff-dashboard-view__brand-text {
  display: flex;
  flex-direction: column;
  gap: 2px;
}
.ff-dashboard-view__title {
  margin: 0;
  font-size: var(--ff-fs-h3);
  font-weight: 700;
  letter-spacing: -0.01em;
  color: var(--ff-text-primary);
  line-height: 1.1;
}
.ff-dashboard-view__title-sub {
  font-size: var(--ff-fs-caption);
  color: var(--ff-text-tertiary);
}
.ff-dashboard-view__topbar-meta {
  display: flex;
  align-items: center;
  gap: var(--ff-space-3);
  flex-wrap: wrap;
}
.ff-dashboard-view__updated {
  display: inline-flex;
  align-items: center;
  gap: var(--ff-space-1);
  font-size: var(--ff-fs-caption);
  color: var(--ff-text-tertiary);
  white-space: nowrap;
}

/* ═══ 今日市场速览（7 指标精致化）═══ */
.ff-dashboard-view__flow {
  display: grid;
  grid-template-columns: repeat(2, 1fr);
  gap: var(--ff-space-3);
}
@media (min-width: 768px) {
  .ff-dashboard-view__flow {
    grid-template-columns: repeat(4, 1fr);
  }
}
@media (min-width: 1100px) {
  .ff-dashboard-view__flow {
    grid-template-columns: repeat(7, 1fr);
  }
}
.ff-dashboard-view__flow-metric {
  position: relative;
  display: flex;
  align-items: stretch;
  gap: var(--ff-space-2-5);
  padding: var(--ff-space-3);
  border-radius: var(--ff-radius-lg);
  border: 1px solid var(--ff-border-subtle);
  background: var(--ff-bg-surface);
  box-shadow: var(--ff-shadow-xs);
  overflow: hidden;
  transition: transform var(--ff-dur-fast) var(--ff-ease-standard),
    border-color var(--ff-dur-fast) var(--ff-ease-standard),
    box-shadow var(--ff-dur-fast) var(--ff-ease-standard);
}
.ff-dashboard-view__flow-metric::before {
  content: '';
  position: absolute;
  left: 0;
  top: 8px;
  bottom: 8px;
  width: 3px;
  border-radius: 2px;
  background: var(--ff-border);
}
.ff-dashboard-view__flow-metric.is-up::before { background: var(--ff-up); }
.ff-dashboard-view__flow-metric.is-down::before { background: var(--ff-down); }
.ff-dashboard-view__flow-metric.is-warn::before { background: var(--ff-warn); }
.ff-dashboard-view__flow-metric.is-hot::before { background: linear-gradient(180deg, #ff8a3d, #ff2d55); }
.ff-dashboard-view__flow-metric.is-broken::before { background: var(--ff-text-tertiary); }
.ff-dashboard-view__flow-metric:hover {
  transform: translateY(-2px);
  border-color: var(--ff-border);
  box-shadow: var(--ff-shadow-sm);
}
.ff-dashboard-view__flow-icon {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
  width: 32px;
  height: 32px;
  border-radius: var(--ff-radius-md);
  background: var(--ff-bg-subtle);
  color: var(--ff-text-tertiary);
}
.ff-dashboard-view__flow-metric.is-up .ff-dashboard-view__flow-icon {
  background: var(--ff-up-subtle);
  color: var(--ff-text-up);
}
.ff-dashboard-view__flow-metric.is-down .ff-dashboard-view__flow-icon {
  background: var(--ff-down-subtle);
  color: var(--ff-down-text);
}
.ff-dashboard-view__flow-metric.is-warn .ff-dashboard-view__flow-icon {
  background: var(--ff-warn-subtle);
  color: var(--ff-warn-text);
}
.ff-dashboard-view__flow-metric.is-hot .ff-dashboard-view__flow-icon {
  background: #fff1f0;
  color: #ff2d55;
}
.ff-dashboard-view__flow-metric.is-broken .ff-dashboard-view__flow-icon {
  background: var(--ff-bg-muted);
  color: var(--ff-text-tertiary);
}
.ff-dashboard-view__flow-body {
  display: flex;
  flex-direction: column;
  justify-content: center;
  gap: 2px;
  min-width: 0;
  flex: 1;
}
.ff-dashboard-view__flow-label {
  font-size: var(--ff-fs-caption);
  color: var(--ff-text-tertiary);
  line-height: 1;
}
.ff-dashboard-view__flow-value {
  font-size: var(--ff-fs-h4);
  font-weight: var(--ff-fw-bold);
  font-variant-numeric: tabular-nums;
  line-height: 1.2;
  color: var(--ff-text-primary);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
.ff-dashboard-view__flow-metric.is-up .ff-dashboard-view__flow-value {
  color: var(--ff-text-up);
}
.ff-dashboard-view__flow-metric.is-down .ff-dashboard-view__flow-value {
  color: var(--ff-down-text);
}
.ff-dashboard-view__flow-metric.is-warn .ff-dashboard-view__flow-value {
  color: var(--ff-warn-text);
}
.ff-dashboard-view__flow-metric.is-hot .ff-dashboard-view__flow-value {
  color: #ff2d55;
}
.ff-dashboard-view__flow-metric.is-broken .ff-dashboard-view__flow-value {
  color: var(--ff-text-tertiary);
}
.ff-dashboard-view__flow-note {
  font-size: var(--ff-fs-overline);
  color: var(--ff-text-tertiary);
  line-height: 1.2;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

/* ═══ 盘面复盘主控台 ═══ */
.ff-dashboard-view__panel {
  display: flex;
  flex-direction: column;
  gap: var(--ff-space-3);
}
.ff-dashboard-view__panel-head {
  display: flex;
  align-items: baseline;
  gap: var(--ff-space-3);
  flex-wrap: wrap;
  padding: 0 var(--ff-space-1);
}
.ff-dashboard-view__panel-title {
  display: inline-flex;
  align-items: center;
  gap: var(--ff-space-2);
  margin: 0;
  font-size: var(--ff-fs-h3);
  font-weight: 700;
  color: var(--ff-text-primary);
  position: relative;
}
.ff-dashboard-view__panel-bar {
  display: inline-block;
  width: 4px;
  height: 18px;
  border-radius: 2px;
  background: linear-gradient(180deg, var(--ff-up), var(--ff-up-strong));
}
.ff-dashboard-view__panel-sub {
  font-size: var(--ff-fs-caption);
  color: var(--ff-text-tertiary);
}
.ff-dashboard-view__panel-spacer {
  flex: 1 1 auto;
}
.ff-dashboard-view__panel-legend {
  display: inline-flex;
  align-items: center;
  gap: var(--ff-space-2);
  font-size: var(--ff-fs-caption);
  color: var(--ff-text-secondary);
  padding: 4px 10px;
  border-radius: var(--ff-radius-pill);
  background: var(--ff-bg-subtle);
  border: 1px solid var(--ff-border-subtle);
}
.ff-dashboard-view__panel-legend i {
  display: inline-block;
  width: 8px;
  height: 8px;
  border-radius: 50%;
  margin-right: 4px;
  vertical-align: middle;
}
.ff-dashboard-view__panel-legend i.is-up {
  background: var(--ff-up);
  box-shadow: 0 0 0 3px var(--ff-up-subtle);
}
.ff-dashboard-view__panel-legend i.is-broken {
  background: var(--ff-text-tertiary);
  box-shadow: 0 0 0 3px var(--ff-bg-muted);
}

/* 复盘网格：移动 1 列 / 桌面 2 列，全宽卡片横跨两列 */
.ff-dashboard-view__grid {
  display: grid;
  grid-template-columns: 1fr;
  gap: var(--ff-space-3);
  align-items: start;
}
@media (min-width: 1024px) {
  .ff-dashboard-view__grid {
    grid-template-columns: repeat(2, 1fr);
  }
  .ff-dashboard-view__cell.full {
    grid-column: 1 / -1;
  }
}

/* 涨跌全景：上下布局（宽度 + 涨停强度/连板天梯） */
.ff-dashboard-view__panorama {
  display: flex;
  flex-direction: column;
  gap: var(--ff-space-5);
}
.ff-dashboard-view__panorama-width {
  /* 全宽：市场宽度走水平条 + 5 指标 */
}
.ff-dashboard-view__panorama-focus {
  /* 全宽：涨停强度 + 连板天梯 */
}

/* ═══ 市场热榜 ═══ */
.ff-dashboard-view__hotrank {
  display: flex;
  flex-direction: column;
  gap: var(--ff-space-3);
}
/* ThsHotList 自带「同花顺热榜」标题，嵌入区块后隐藏，避免与区块标题重复 */
.ff-dashboard-view__hotrank-card :deep(.ths__hero) {
  display: none;
}

/* 指数 K 线 */
.ff-dashboard-view__kline {
  display: grid;
  grid-template-columns: 1fr;
  gap: var(--ff-space-3);
}
@media (min-width: 1024px) {
  .ff-dashboard-view__kline {
    grid-template-columns: repeat(2, 1fr);
  }
}

/* 新闻舆情（辅助区） */
.ff-dashboard-view__news {
  display: flex;
  flex-direction: column;
  gap: var(--ff-space-3);
  padding: var(--ff-space-4);
  border: 1px solid var(--ff-border);
  border-radius: var(--ff-radius-lg);
  background: var(--ff-bg-surface);
  box-shadow: var(--ff-shadow-xs);
}
.ff-dashboard-view__news-head {
  display: flex;
  align-items: center;
  gap: var(--ff-space-3);
  flex-wrap: wrap;
}
.ff-dashboard-view__news-title {
  display: inline-flex;
  align-items: center;
  gap: var(--ff-space-2);
  margin: 0;
  font-size: var(--ff-fs-h3);
  font-weight: 700;
  color: var(--ff-text-primary);
}
.ff-dashboard-view__news-sub {
  font-size: var(--ff-fs-caption);
  color: var(--ff-text-tertiary);
}
.ff-dashboard-view__news-spacer {
  flex: 1 1 auto;
}
.ff-dashboard-view__news-body {
  display: flex;
  flex-direction: column;
  gap: var(--ff-space-3);
}
.ff-dashboard-view__charts {
  display: grid;
  grid-template-columns: 1fr;
  gap: var(--ff-space-3);
}
.ff-dashboard-view__dist {
  display: grid;
  grid-template-columns: 1fr;
  gap: var(--ff-space-3);
}
@media (min-width: 1024px) {
  .ff-dashboard-view__charts {
    grid-template-columns: repeat(3, 1fr);
  }
  .ff-dashboard-view__dist {
    grid-template-columns: repeat(2, 1fr);
  }
}

/* 数据源健康：紧凑平铺 */
.ff-dashboard-view__health {
  display: flex;
  flex-direction: column;
  gap: var(--ff-space-3);
}
.ff-dashboard-view__statusbar {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: var(--ff-space-3);
  padding: var(--ff-space-3) var(--ff-space-4);
  border: 1px solid var(--ff-border);
  border-radius: var(--ff-radius-lg);
  background: var(--ff-bg-surface);
  box-shadow: var(--ff-shadow-xs);
}
.ff-dashboard-view__statusbar-group {
  display: inline-flex;
  align-items: center;
  gap: var(--ff-space-2);
  color: var(--ff-text-secondary);
}
.ff-dashboard-view__statusbar-spacer {
  flex: 1 1 auto;
  min-width: var(--ff-space-3);
}
.ff-dashboard-view__statusbar-label {
  font-size: var(--ff-fs-body-sm);
  font-weight: 600;
  color: var(--ff-text-secondary);
  white-space: nowrap;
}
.ff-dashboard-view__sep {
  display: inline-block;
  width: 1px;
  height: 14px;
  background: var(--ff-border);
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
  height: 22px;
  padding: 0 var(--ff-space-2);
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

/* 数据源健康：紧凑平铺网格 */
.ff-dashboard-view__tiles {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(170px, 1fr));
  gap: var(--ff-space-2);
}
.ff-dashboard-view__tile {
  display: flex;
  flex-direction: column;
  gap: var(--ff-space-1-5);
  padding: var(--ff-space-2-5) var(--ff-space-3);
  border: 1px solid var(--ff-border-subtle);
  border-radius: var(--ff-radius-md);
  background: var(--ff-bg-subtle);
  transition: background-color var(--ff-dur-fast) var(--ff-ease-standard),
    border-color var(--ff-dur-fast) var(--ff-ease-standard);
}
.ff-dashboard-view__tile:hover {
  background: var(--ff-bg-hover);
  border-color: var(--ff-border);
}
.ff-dashboard-view__tile-head {
  display: flex;
  align-items: center;
  gap: var(--ff-space-1-5);
  min-width: 0;
}
.ff-dashboard-view__tile-name {
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  font-size: var(--ff-fs-body-sm);
  font-weight: 500;
  color: var(--ff-text-primary);
}
.ff-dashboard-view__tile-status {
  margin-left: auto;
  flex: 0 0 auto;
  font-size: var(--ff-fs-caption);
  font-weight: 500;
  white-space: nowrap;
}
.ff-dashboard-view__tile-status.is-success {
  color: var(--ff-down-text);
}
.ff-dashboard-view__tile-status.is-warn {
  color: var(--ff-warn-text);
}
.ff-dashboard-view__tile-status.is-danger {
  color: var(--ff-danger-text);
}
.ff-dashboard-view__tile-status.is-neutral {
  color: var(--ff-text-tertiary);
}
.ff-dashboard-view__tile-meta {
  display: flex;
  align-items: baseline;
  gap: var(--ff-space-3);
  font-size: var(--ff-fs-caption);
  color: var(--ff-text-tertiary);
}
.ff-dashboard-view__tile-meta strong {
  color: var(--ff-text-secondary);
  font-variant-numeric: tabular-nums;
  font-weight: 600;
}

/* 头部实时推送指示灯 */
.ff-dashboard-view__live-badge {
  display: inline-flex;
  align-items: center;
  gap: var(--ff-space-1);
  font-size: var(--ff-fs-caption);
  font-weight: 500;
  white-space: nowrap;
  padding: 3px var(--ff-space-2-5);
  border-radius: var(--ff-radius-pill);
  border: 1px solid var(--ff-border);
  background: var(--ff-bg-subtle);
  color: var(--ff-text-tertiary);
}
.ff-dashboard-view__live-dot {
  width: 7px;
  height: 7px;
  border-radius: 50%;
  background: var(--ff-text-tertiary);
  flex-shrink: 0;
}
.ff-dashboard-view__live-badge.is-on {
  color: var(--ff-down-text);
  background: var(--ff-down-subtle);
  border-color: var(--ff-down-border);
}
.ff-dashboard-view__live-badge.is-on .ff-dashboard-view__live-dot {
  background: var(--ff-chart-up);
  box-shadow: 0 0 0 3px rgba(239, 68, 68, 0.18);
  animation: ff-live-pulse 1.6s ease-in-out infinite;
}
.ff-dashboard-view__live-badge.is-wait {
  color: var(--ff-warn-text);
  background: var(--ff-warn-subtle);
  border-color: var(--ff-warn-border);
}
.ff-dashboard-view__live-badge.is-wait .ff-dashboard-view__live-dot {
  background: var(--ff-warn);
}
.ff-dashboard-view__live-badge.is-off {
  color: var(--ff-danger-text);
  background: var(--ff-danger-subtle);
  border-color: var(--ff-danger-border);
}
.ff-dashboard-view__live-badge.is-off .ff-dashboard-view__live-dot {
  background: var(--ff-danger);
}
@keyframes ff-live-pulse {
  0%, 100% { opacity: 1; }
  50% { opacity: 0.45; }
}
</style>