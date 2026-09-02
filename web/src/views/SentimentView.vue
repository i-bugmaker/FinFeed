<script setup>
import { ref, watch, onMounted, onUnmounted, nextTick } from 'vue'
import { api } from '../api/client'
import { useAppStore } from '../store/app'
import NewsCard from '../components/NewsCard.vue'
import FilterBar from '../components/FilterBar.vue'
import EmptyState from '../components/EmptyState.vue'
import AppIcon from '../ui/AppIcon.vue'
import AppSkeleton from '../ui/AppSkeleton.vue'

const store = useAppStore()

const filters = ref({ source: 'all', sentiment: 'all', keyword: '', start: '', end: '', favorites: false })
const list = ref([])
const total = ref(0)
const page = ref(1)
const pageSize = 30
const loading = ref(false)
const err = ref('')
const finished = ref(false)
const sources = ref([])
const sentinel = ref(null)
let observer = null

async function loadFirst() {
  page.value = 1
  finished.value = false
  err.value = ''
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
    err.value = e?.message || String(e)
    console.error(e)
  } finally {
    loading.value = false
  }
}

function onFilterChange() {
  loadFirst()
}

// SSE 断线恢复后重拉第一页，保证断线期间的舆情不丢
const reconnectNotice = ref('')
let noticeTimer = null
watch(
  () => store.reconnectTick,
  () => {
    loadFirst()
    const mins = Math.round(store.lastOfflineMs / 60000)
    reconnectNotice.value = mins >= 1
      ? `连接中断约 ${mins} 分钟，已为您刷新最新舆情`
      : '连接已恢复，已为您刷新最新舆情'
    clearTimeout(noticeTimer)
    noticeTimer = setTimeout(() => (reconnectNotice.value = ''), 6000)
  },
)

onMounted(async () => {
  await loadFirst()
  await nextTick()
  observer = new IntersectionObserver(
    (e) => e[0].isIntersecting && fetchPage(),
    { rootMargin: '300px' },
  )
  if (sentinel.value) observer.observe(sentinel.value)
})

onUnmounted(() => {
  if (observer) observer.disconnect()
  if (noticeTimer) clearTimeout(noticeTimer)
})
</script>

<template>
  <div class="ff-page ff-sentiment-view">
    <!-- 页面标题按产品要求移除，h1 保留 sr-only 保文档语义 -->
    <h1 class="ff-sr-only">舆情</h1>

    <FilterBar v-model="filters" :sources="sources" :show-fav="true" @change="onFilterChange" />

    <!-- SSE 断线恢复提示 -->
    <div v-if="reconnectNotice" class="ff-sentiment-view__reconnect">
      <AppIcon name="broadcast" size="xs" />
      <span>{{ reconnectNotice }}</span>
    </div>

    <div class="ff-sentiment-view__list">
      <NewsCard v-for="item in list" :key="item.id" :item="item" mode="sentiment" />
      <EmptyState v-if="err && !list.length" text="加载失败" icon="alert-circle">
        <template #description>{{ err }}</template>
        <template #action>
          <AppButton variant="secondary" size="sm" icon="refresh" @click="loadFirst">重试</AppButton>
        </template>
      </EmptyState>
      <EmptyState v-else-if="!loading && list.length === 0" text="暂无舆情数据" icon="chatter" />
    </div>

    <div ref="sentinel" class="ff-sentiment-view__sentinel">
      <AppSkeleton v-if="loading" variant="text" :lines="2" />
      <template v-else-if="err && list.length > 0">
        <span class="ff-sentiment-view__load-error"><AppIcon name="alert-triangle" size="xs" /> 加载失败：{{ err }}</span>
        <AppButton variant="ghost" size="sm" icon="refresh" @click="fetchPage">重试</AppButton>
      </template>
      <span v-else-if="finished && list.length > 0" class="ff-text-muted">
        <AppIcon name="check-circle" size="xs" /> 已加载全部 {{ total }} 条
      </span>
    </div>
  </div>
</template>

<style scoped>
.ff-sentiment-view__reconnect {
  display: flex;
  align-items: center;
  gap: var(--ff-space-2);
  margin-bottom: var(--ff-space-3);
  padding: var(--ff-space-2) var(--ff-space-3);
  border: 1px solid var(--ff-brand-border);
  background: var(--ff-brand-subtle);
  border-radius: var(--ff-radius-md);
  color: var(--ff-text-secondary);
  font-size: var(--ff-fs-caption);
  animation: ff-scale-in var(--ff-dur-base) var(--ff-ease-spring);
}

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
  font-size: var(--ff-fs-display);
  font-weight: var(--ff-fw-bold);
  line-height: 1;
  letter-spacing: -0.03em;
}

.ff-sentiment-view__gauge-label {
  font-size: var(--ff-fs-xs);
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
  font-size: var(--ff-fs-caption);
}

.ff-sentiment-view__ratio-title {
  font-weight: 600;
  color: var(--ff-text-primary);
}

.ff-sentiment-view__ratio-nums {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  font-size: var(--ff-fs-caption);
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
  font-size: var(--ff-fs-xs);
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

.ff-sentiment-view__load-error {
  display: inline-flex;
  align-items: center;
  gap: var(--ff-space-1);
  color: var(--ff-danger-text);
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
