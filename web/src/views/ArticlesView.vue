<script setup>
import { ref, watch, onMounted, onUnmounted, nextTick } from 'vue'
import { api } from '../api/client'
import { useAppStore } from '../store/app'
import NewsRow from '../components/NewsRow.vue'
import FilterBar from '../components/FilterBar.vue'
import EmptyState from '../components/EmptyState.vue'
import AppCard from '../ui/AppCard.vue'
import AppIcon from '../ui/AppIcon.vue'
import AppButton from '../ui/AppButton.vue'
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
      source: filters.value.source !== 'all' ? filters.value.source : undefined,
      keyword: filters.value.keyword || undefined,
      sentiment: filters.value.sentiment !== 'all' ? filters.value.sentiment : undefined,
      start: filters.value.start || undefined,
      end: filters.value.end || undefined,
      favorites: filters.value.favorites ? 1 : 0,
    }
    const res = await api.articles(params)
    const items = res.news || []
    if (page.value === 1) {
      list.value = items
      if (res.sources) sources.value = res.sources.map((s) => ({ name: s }))
    } else {
      list.value.push(...items)
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

// SSE 断线恢复后重拉第一页，保证断线期间的文章不丢
const reconnectNotice = ref('')
let noticeTimer = null
watch(
  () => store.reconnectTick,
  () => {
    loadFirst()
    const mins = Math.round(store.lastOfflineMs / 60000)
    reconnectNotice.value = mins >= 1
      ? `连接中断约 ${mins} 分钟，已为您刷新最新文章`
      : '连接已恢复，已为您刷新最新文章'
    clearTimeout(noticeTimer)
    noticeTimer = setTimeout(() => (reconnectNotice.value = ''), 6000)
  },
)

function clearKeyword() {
  filters.value.keyword = ''
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

onUnmounted(() => {
  if (observer) observer.disconnect()
  if (noticeTimer) clearTimeout(noticeTimer)
})
</script>

<template>
  <div class="ff-page ff-articles-view">
    <!-- 页面标题按产品要求移除，h1 保留 sr-only 保文档语义 -->
    <h1 class="ff-sr-only">财经</h1>

    <FilterBar
      v-model="filters"
      :sources="sources"
      @change="onFilterChange"
    />

    <!-- SSE 断线恢复提示 -->
    <div v-if="reconnectNotice" class="ff-articles-view__reconnect">
      <AppIcon name="broadcast" size="xs" />
      <span>{{ reconnectNotice }}</span>
    </div>

    <div v-if="filters.keyword" class="ff-articles-view__result">
      <AppIcon name="search" size="xs" />
      <span>找到 <strong class="ff-num">{{ total }}</strong> 条与「<strong>{{ filters.keyword }}</strong>」相关的文章</span>
      <AppButton variant="ghost" size="sm" icon="x" @click="clearKeyword">清除关键词</AppButton>
    </div>

    <!-- 表格模式 -->
    <AppCard :no-padding="true" class="ff-articles-view__table">
      <table class="ff-table ff-table--sticky ff-table--hover" v-if="list.length > 0">
        <thead>
          <tr>
            <th class="ff-table__header ff-table__header--center" style="width:48px"></th>
            <th class="ff-table__header ff-table__header--center" style="width:72px">重要性</th>
            <th class="ff-table__header" style="width:140px">时间</th>
            <th class="ff-table__header ff-table__header--center" style="width:120px">来源</th>
            <th class="ff-table__header">标题</th>
          </tr>
        </thead>
        <tbody>
          <NewsRow v-for="item in list" :key="item.id" :item="item" :keyword="filters.keyword" />
        </tbody>
      </table>
      <EmptyState
        v-else-if="err"
        text="加载失败"
        icon="alert-circle"
      >
        <template #description>{{ err }}</template>
        <template #action>
          <AppButton variant="secondary" size="sm" icon="refresh" @click="loadFirst">重试</AppButton>
        </template>
      </EmptyState>
      <EmptyState
        v-else-if="!loading"
        :text="filters.keyword ? `未找到与「${filters.keyword}」相关的文章` : '暂无文章数据'"
        icon="newspaper"
      >
        <template v-if="filters.keyword" #description>
          换个关键词试试，或清除筛选条件查看全部文章。
        </template>
        <template v-if="filters.keyword" #action>
          <AppButton variant="secondary" size="sm" icon="x" @click="clearKeyword">清除筛选</AppButton>
        </template>
      </EmptyState>
    </AppCard>

    <div ref="sentinel" class="ff-articles-view__sentinel">
      <AppSkeleton v-if="loading" variant="text" :lines="2" />
      <span v-else-if="finished && list.length > 0" class="ff-text-muted">
        <AppIcon name="check-circle" size="xs" /> 已加载全部 {{ total }} 条
      </span>
    </div>
  </div>
</template>

<style scoped>
.ff-articles-view {
  max-width: var(--ff-container-max);
  margin: 0 auto;
}

.ff-articles-view__table {
  overflow: hidden;
}

.ff-articles-view__reconnect {
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

.ff-articles-view__result {
  display: flex;
  align-items: center;
  gap: var(--ff-space-2);
  margin-bottom: var(--ff-space-3);
  padding: var(--ff-space-2-5) var(--ff-space-4);
  border: 1px solid var(--ff-brand-border);
  background: var(--ff-brand-subtle);
  border-radius: var(--ff-radius-lg);
  color: var(--ff-text-secondary);
  font-size: var(--ff-fs-body-sm);
}
.ff-articles-view__result strong {
  color: var(--ff-text-primary);
  font-weight: 600;
}
.ff-articles-view__result-clear {
  margin-left: auto;
  display: inline-flex;
  align-items: center;
  gap: 4px;
  height: 28px;
  padding: 0 var(--ff-space-2-5);
  border: 1px solid var(--ff-border);
  border-radius: var(--ff-radius-pill);
  background: var(--ff-bg-surface);
  color: var(--ff-text-secondary);
  font-size: var(--ff-fs-caption);
  font-weight: 500;
  cursor: pointer;
  transition:
    background-color var(--ff-dur-fast) var(--ff-ease-standard),
    border-color var(--ff-dur-fast) var(--ff-ease-standard),
    color var(--ff-dur-fast) var(--ff-ease-standard);
}
.ff-articles-view__result-clear:hover {
  background: var(--ff-bg-hover);
  border-color: var(--ff-border-strong);
  color: var(--ff-text-primary);
}

.ff-articles-view__sentinel {
  display: flex;
  align-items: center;
  justify-content: center;
  padding: var(--ff-space-5) 0 var(--ff-space-10);
  color: var(--ff-text-tertiary);
  font-size: var(--ff-fs-sm);
  gap: var(--ff-space-2);
}
</style>
