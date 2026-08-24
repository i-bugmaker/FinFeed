<script setup>
import { ref, computed, onMounted, onUnmounted, nextTick } from 'vue'
import { api } from '../api/client'
import NewsCard from '../components/NewsCard.vue'
import FilterBar from '../components/FilterBar.vue'
import EmptyState from '../components/EmptyState.vue'
import AppIcon from '../ui/AppIcon.vue'
import AppSkeleton from '../ui/AppSkeleton.vue'

const filters = ref({ source: 'all', sentiment: 'all', keyword: '', start: '', end: '', favorites: false })
const list = ref([])
const total = ref(0)
const page = ref(1)
const pageSize = 30
const loading = ref(false)
const finished = ref(false)
const sources = ref([])
const sentinel = ref(null)
let observer = null

const sentimentStats = computed(() => {
  let pos = 0, neg = 0, neu = 0
  for (const item of list.value) {
    const s = (item.sentiment || '').toLowerCase()
    if (s === 'positive') pos++
    else if (s === 'negative') neg++
    else neu++
  }
  const t = list.value.length || 1
  const posPct = Math.round((pos / t) * 100)
  const negPct = Math.round((neg / t) * 100)
  const neuPct = Math.round((neu / t) * 100)
  // 情绪指数：0~100 (50 为中性)
  const sentimentScore = Math.round(((pos - neg) / t + 1) * 50)
  return { pos, neg, neu, posPct, negPct, neuPct, sentimentScore }
})

async function loadFirst() {
  page.value = 1
  finished.value = false
  list.value = []
  await fetchPage()
}

async function fetchPage() {
  if (loading.value || finished.value) return
  loading.value = true
  try {
    const params = {
      page: page.value,
      page_size: pageSize,
      keyword: filters.value.keyword || undefined,
      sentiment: filters.value.sentiment !== 'all' ? filters.value.sentiment : undefined,
      source: filters.value.source && filters.value.source !== 'all' ? filters.value.source : undefined,
      start: filters.value.start || undefined,
      end: filters.value.end || undefined,
      favorites: filters.value.favorites ? 1 : 0,
    }
    const res = await api.sentiment(params)
    const items = res.news || []
    if (page.value === 1) {
      list.value = items
      if (res.sources) sources.value = res.sources.map((s) => ({ name: s }))
    } else {
      list.value = [...list.value, ...items]
    }
    total.value = res.total || 0
    if (list.value.length >= total.value || items.length === 0) finished.value = true
    page.value += 1
  } catch (e) {
    console.error(e)
  } finally {
    loading.value = false
  }
}

function onFilterChange() {
  loadFirst()
}

onMounted(async () => {
  await loadFirst()
  await nextTick()
  observer = new IntersectionObserver(
    (e) => e[0].isIntersecting && fetchPage(),
    { rootMargin: '300px' },
  )
  if (sentinel.value) observer.observe(sentinel.value)
})

onUnmounted(() => observer && observer.disconnect())
</script>

<template>
  <div class="ff-page ff-sentiment-view">
    <!-- 舆情晴雨表 Hero 面板 -->
    <div class="ff-sentiment-view__barometer ff-glass" v-if="list.length > 0">
      <div class="ff-sentiment-view__gauge-wrap">
        <div class="ff-sentiment-view__gauge-val ff-num" :class="sentimentStats.sentimentScore >= 50 ? 'ff-t-up' : 'ff-t-down'">
          {{ sentimentStats.sentimentScore }}
        </div>
        <div class="ff-sentiment-view__gauge-label">
          {{ sentimentStats.sentimentScore >= 60 ? '多头偏热' : sentimentStats.sentimentScore <= 40 ? '空头偏冷' : '情绪均衡' }}
        </div>
      </div>

      <div class="ff-sentiment-view__barometer-details">
        <div class="ff-sentiment-view__ratio-header">
          <span class="ff-sentiment-view__ratio-title">全网舆情多空比例</span>
          <span class="ff-sentiment-view__ratio-nums">
            <strong class="ff-t-up ff-num">{{ sentimentStats.posPct }}% 利好</strong>
            <span class="ff-text-muted">/</span>
            <strong class="ff-t-down ff-num">{{ sentimentStats.negPct }}% 利空</strong>
          </span>
        </div>

        <div class="ff-sentiment-view__ratio-bar">
          <div class="ff-sentiment-view__ratio-bar-up" :style="{ width: sentimentStats.posPct + '%' }" />
          <div class="ff-sentiment-view__ratio-bar-neu" :style="{ width: sentimentStats.neuPct + '%' }" />
          <div class="ff-sentiment-view__ratio-bar-down" :style="{ width: sentimentStats.negPct + '%' }" />
        </div>

        <div class="ff-sentiment-view__chips">
          <span class="ff-sentiment-view__chip ff-sentiment-view__chip--up">
            <AppIcon name="trending-up" size="xs" /> 利好: {{ sentimentStats.pos }} 条
          </span>
          <span class="ff-sentiment-view__chip ff-sentiment-view__chip--neu">
            <AppIcon name="minus" size="xs" /> 中性: {{ sentimentStats.neu }} 条
          </span>
          <span class="ff-sentiment-view__chip ff-sentiment-view__chip--down">
            <AppIcon name="trending-down" size="xs" /> 利空: {{ sentimentStats.neg }} 条
          </span>
        </div>
      </div>
    </div>

    <FilterBar v-model="filters" :sources="sources" :show-fav="true" @change="onFilterChange" />

    <div class="ff-sentiment-view__list">
      <NewsCard v-for="item in list" :key="item.id" :item="item" mode="sentiment" />
      <EmptyState v-if="!loading && list.length === 0" text="暂无舆情数据" icon="chatter" />
    </div>

    <div ref="sentinel" class="ff-sentiment-view__sentinel">
      <AppSkeleton v-if="loading" variant="text" :lines="2" />
      <span v-else-if="finished && list.length > 0" class="ff-text-muted">
        <AppIcon name="check-circle" size="xs" /> 已加载全部 {{ total }} 条
      </span>
    </div>
  </div>
</template>

<style scoped>
.ff-sentiment-view {
  max-width: var(--ff-container-max);
  margin: 0 auto;
}

.ff-sentiment-view__barometer {
  display: flex;
  align-items: center;
  gap: var(--ff-space-5);
  padding: 18px 24px;
  border-radius: var(--ff-radius-lg);
  border: 1px solid var(--ff-border);
  margin-bottom: var(--ff-space-4);
}

.ff-sentiment-view__gauge-wrap {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  min-width: 100px;
  padding-right: var(--ff-space-4);
  border-right: 1px solid var(--ff-border);
}

.ff-sentiment-view__gauge-val {
  font-size: 32px;
  font-weight: 800;
  line-height: 1;
  letter-spacing: -0.03em;
}

.ff-sentiment-view__gauge-label {
  font-size: 12px;
  font-weight: 600;
  color: var(--ff-text-secondary);
  margin-top: 4px;
}

.ff-sentiment-view__barometer-details {
  flex: 1 1 auto;
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.ff-sentiment-view__ratio-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  font-size: 13px;
}

.ff-sentiment-view__ratio-title {
  font-weight: 600;
  color: var(--ff-text-primary);
}

.ff-sentiment-view__ratio-nums {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  font-size: 12.5px;
}

.ff-sentiment-view__ratio-bar {
  height: 8px;
  border-radius: var(--ff-radius-pill);
  background: var(--ff-bg-muted);
  display: flex;
  overflow: hidden;
}

.ff-sentiment-view__ratio-bar-up {
  background: var(--ff-up);
  transition: width var(--ff-dur-base);
}
.ff-sentiment-view__ratio-bar-neu {
  background: var(--ff-chart-neutral);
  transition: width var(--ff-dur-base);
}
.ff-sentiment-view__ratio-bar-down {
  background: var(--ff-down);
  transition: width var(--ff-dur-base);
}

.ff-sentiment-view__chips {
  display: flex;
  align-items: center;
  gap: var(--ff-space-2);
  flex-wrap: wrap;
}

.ff-sentiment-view__chip {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  font-size: 11.5px;
  font-weight: 500;
  font-family: var(--ff-font-mono);
  padding: 2px 8px;
  border-radius: var(--ff-radius-xs);
}

.ff-sentiment-view__chip--up {
  background: var(--ff-up-subtle);
  color: var(--ff-up-text);
  border: 1px solid var(--ff-up-border);
}
.ff-sentiment-view__chip--neu {
  background: var(--ff-bg-subtle);
  color: var(--ff-text-secondary);
  border: 1px solid var(--ff-border);
}
.ff-sentiment-view__chip--down {
  background: var(--ff-down-subtle);
  color: var(--ff-down-text);
  border: 1px solid var(--ff-down-border);
}

.ff-sentiment-view__list {
  display: flex;
  flex-direction: column;
  gap: var(--ff-space-3);
}

.ff-sentiment-view__sentinel {
  display: flex;
  align-items: center;
  justify-content: center;
  padding: var(--ff-space-5) 0 var(--ff-space-10);
  color: var(--ff-text-tertiary);
  font-size: var(--ff-fs-sm);
  gap: var(--ff-space-2);
}

@media (max-width: 640px) {
  .ff-sentiment-view__barometer {
    flex-direction: column;
    align-items: flex-start;
  }
  .ff-sentiment-view__gauge-wrap {
    border-right: none;
    border-bottom: 1px solid var(--ff-border);
    width: 100%;
    padding-bottom: var(--ff-space-3);
  }
}
</style>
