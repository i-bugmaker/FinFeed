<script setup>
import { ref, computed, onMounted, onUnmounted, watch, nextTick } from 'vue'
import { api } from '../api/client'
import { useAppStore } from '../store/app'
import NewsRow from '../components/NewsRow.vue'
import NewsCard from '../components/NewsCard.vue'
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
const finished = ref(false)
const sources = ref([])
const sentinel = ref(null)
const contentEl = ref(null)
const viewMode = ref('table') // 'table' | 'cards'
let observer = null

// 统计情绪占比
const sentimentCounts = computed(() => {
  let pos = 0, neg = 0, neu = 0
  for (const item of list.value) {
    const s = (item.sentiment || '').toLowerCase()
    if (s === 'positive') pos++
    else if (s === 'negative') neg++
    else neu++
  }
  const t = list.value.length || 1
  return {
    pos, neg, neu,
    posPct: Math.round((pos / t) * 100),
    negPct: Math.round((neg / t) * 100),
    neuPct: Math.round((neu / t) * 100),
  }
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
      source: filters.value.source !== 'all' ? filters.value.source : undefined,
      keyword: filters.value.keyword || undefined,
      sentiment: filters.value.sentiment !== 'all' ? filters.value.sentiment : undefined,
      start: filters.value.start || undefined,
      end: filters.value.end || undefined,
      favorites: filters.value.favorites ? 1 : 0,
    }
    const res = await api.flash(params)
    const items = res.news || []
    if (page.value === 1) {
      list.value = items
      if (res.sources) {
        sources.value = res.sources.map((s) => ({ name: s }))
        store.setSources(sources.value)
      }
    } else {
      list.value.push(...items)
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

function clearKeyword() {
  filters.value.keyword = ''
  loadFirst()
}

function isNearTop() {
  if (!contentEl.value) return true
  return contentEl.value.scrollTop < 80
}

function applyPending() {
  const items = store.pendingNews.filter((n) => n.category === 'flash')
  if (store.pendingTruncated.flash) {
    store.pendingNews = store.pendingNews.filter((n) => n.category !== 'flash')
    store.pendingTruncated.flash = false
    loadFirst()
    return
  }
  const ids = new Set(list.value.map((n) => n.id))
  const fresh = items.filter((n) => !ids.has(n.id))
  if (fresh.length) {
    list.value = [...fresh, ...list.value]
  }
  if (isNearTop()) store.markSeen('flash')
}

function onContentScroll() {
  if (isNearTop()) store.markSeen('flash')
}

watch(
  () => store.pendingNews.length,
  () => applyPending(),
)

onMounted(async () => {
  contentEl.value = document.querySelector('.ff-app__content')
  if (contentEl.value) {
    contentEl.value.addEventListener('scroll', onContentScroll)
  }
  await loadFirst()
  if (isNearTop()) store.markSeen('flash')
  await nextTick()
  observer = new IntersectionObserver(
    (entries) => {
      if (entries[0].isIntersecting) fetchPage()
    },
    { rootMargin: '300px' },
  )
  if (sentinel.value) observer.observe(sentinel.value)
})

onUnmounted(() => {
  if (observer) observer.disconnect()
  if (contentEl.value) {
    contentEl.value.removeEventListener('scroll', onContentScroll)
  }
})
</script>

<template>
  <div class="ff-page ff-flash-view">
    <!-- 顶部状态栏与情绪比例条 -->
    <div class="ff-flash-view__hero ff-glass" v-if="list.length > 0">
      <div class="ff-flash-view__hero-stats">
        <div class="ff-flash-view__stat-item">
          <span class="ff-flash-view__stat-label">当前已收录</span>
          <span class="ff-flash-view__stat-val ff-num">{{ total }}</span>
        </div>
        <div class="ff-flash-view__stat-divider" />
        <div class="ff-flash-view__stat-item">
          <span class="ff-flash-view__stat-label ff-t-up">利好讯息</span>
          <span class="ff-flash-view__stat-val ff-num ff-t-up">{{ sentimentCounts.pos }}</span>
        </div>
        <div class="ff-flash-view__stat-divider" />
        <div class="ff-flash-view__stat-item">
          <span class="ff-flash-view__stat-label ff-t-down">利空讯息</span>
          <span class="ff-flash-view__stat-val ff-num ff-t-down">{{ sentimentCounts.neg }}</span>
        </div>
      </div>

      <div class="ff-flash-view__ratio-bar" title="当前列表情绪分布">
        <div class="ff-flash-view__ratio-seg ff-flash-view__ratio-seg--up" :style="{ width: sentimentCounts.posPct + '%' }" />
        <div class="ff-flash-view__ratio-seg ff-flash-view__ratio-seg--neu" :style="{ width: sentimentCounts.neuPct + '%' }" />
        <div class="ff-flash-view__ratio-seg ff-flash-view__ratio-seg--down" :style="{ width: sentimentCounts.negPct + '%' }" />
      </div>

      <div class="ff-flash-view__view-toggle">
        <button
          class="ff-flash-view__toggle-btn"
          :class="{ 'is-active': viewMode === 'table' }"
          title="表格列表视图"
          @click="viewMode = 'table'"
        >
          <AppIcon name="menu" size="xs" />
        </button>
        <button
          class="ff-flash-view__toggle-btn"
          :class="{ 'is-active': viewMode === 'cards' }"
          title="卡片流视图"
          @click="viewMode = 'cards'"
        >
          <AppIcon name="dashboard" size="xs" />
        </button>
      </div>
    </div>

    <!-- 筛选过滤栏 -->
    <FilterBar
      v-model="filters"
      :sources="sources"
      @change="onFilterChange"
    />

    <div v-if="filters.keyword" class="ff-flash-view__result">
      <AppIcon name="search" size="xs" />
      <span>找到 <strong class="ff-num">{{ total }}</strong> 条与「<strong>{{ filters.keyword }}</strong>」相关的快讯</span>
      <button type="button" class="ff-flash-view__result-clear" @click="clearKeyword">
        <AppIcon name="x" size="xs" /> 清除关键词
      </button>
    </div>

    <!-- 表格模式 -->
    <AppCard :no-padding="true" class="ff-flash-view__table" v-if="viewMode === 'table'">
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
        v-else-if="!loading"
        :text="filters.keyword ? `未找到与「${filters.keyword}」相关的快讯` : '暂无快讯数据'"
        icon="zap"
      >
        <template v-if="filters.keyword" #description>
          换个关键词试试，或清除筛选条件查看全部快讯。
        </template>
        <template v-if="filters.keyword" #action>
          <AppButton variant="secondary" size="sm" icon="x" @click="clearKeyword">清除筛选</AppButton>
        </template>
      </EmptyState>
    </AppCard>

    <!-- 卡片流模式 -->
    <div class="ff-flash-view__cards" v-else>
      <NewsCard v-for="item in list" :key="item.id" :item="item" mode="news" />
      <EmptyState
        v-if="!loading && list.length === 0"
        :text="filters.keyword ? `未找到与「${filters.keyword}」相关的快讯` : '暂无快讯数据'"
        icon="zap"
      />
    </div>

    <div ref="sentinel" class="ff-flash-view__sentinel">
      <AppSkeleton v-if="loading" variant="text" :lines="2" />
      <span v-else-if="finished && list.length > 0" class="ff-text-muted">
        <AppIcon name="check-circle" size="xs" /> 已加载全部 {{ total }} 条
      </span>
    </div>
  </div>
</template>

<style scoped>
.ff-flash-view {
  max-width: var(--ff-container-max);
  margin: 0 auto;
}

.ff-flash-view__hero {
  display: flex;
  align-items: center;
  gap: var(--ff-space-4);
  padding: 12px 18px;
  border-radius: var(--ff-radius-lg);
  margin-bottom: var(--ff-space-4);
  border: 1px solid var(--ff-border);
}

.ff-flash-view__hero-stats {
  display: flex;
  align-items: center;
  gap: var(--ff-space-3);
}

.ff-flash-view__stat-item {
  display: flex;
  align-items: baseline;
  gap: 6px;
}

.ff-flash-view__stat-label {
  font-size: 11.5px;
  color: var(--ff-text-tertiary);
  font-weight: 500;
}

.ff-flash-view__stat-val {
  font-size: 14px;
  font-weight: 700;
  color: var(--ff-text-primary);
}

.ff-flash-view__stat-divider {
  width: 1px;
  height: 14px;
  background: var(--ff-border);
}

.ff-flash-view__ratio-bar {
  flex: 1 1 auto;
  height: 6px;
  border-radius: var(--ff-radius-pill);
  background: var(--ff-bg-muted);
  display: flex;
  overflow: hidden;
  min-width: 80px;
}

.ff-flash-view__ratio-seg--up {
  background: var(--ff-up);
  transition: width var(--ff-dur-base);
}
.ff-flash-view__ratio-seg--neu {
  background: var(--ff-chart-neutral);
  transition: width var(--ff-dur-base);
}
.ff-flash-view__ratio-seg--down {
  background: var(--ff-down);
  transition: width var(--ff-dur-base);
}

.ff-flash-view__view-toggle {
  display: inline-flex;
  padding: 2px;
  border-radius: var(--ff-radius-md);
  background: var(--ff-bg-subtle);
  border: 1px solid var(--ff-border-subtle);
}

.ff-flash-view__toggle-btn {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 28px;
  height: 28px;
  border-radius: var(--ff-radius-sm);
  color: var(--ff-text-tertiary);
  background: none;
  border: none;
  cursor: pointer;
  transition: all var(--ff-dur-fast);
}

.ff-flash-view__toggle-btn:hover {
  color: var(--ff-text-primary);
}

.ff-flash-view__toggle-btn.is-active {
  background: var(--ff-bg-surface);
  color: var(--ff-brand-text);
  box-shadow: var(--ff-shadow-xs);
}

.ff-flash-view__table {
  overflow: hidden;
}

.ff-flash-view__cards {
  display: flex;
  flex-direction: column;
  gap: var(--ff-space-3);
}

.ff-flash-view__result {
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
.ff-flash-view__result strong {
  color: var(--ff-text-primary);
  font-weight: 600;
}
.ff-flash-view__result-clear {
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
.ff-flash-view__result-clear:hover {
  background: var(--ff-bg-hover);
  border-color: var(--ff-border-strong);
  color: var(--ff-text-primary);
}

.ff-flash-view__sentinel {
  display: flex;
  align-items: center;
  justify-content: center;
  padding: var(--ff-space-5) 0 var(--ff-space-10);
  color: var(--ff-text-tertiary);
  font-size: var(--ff-fs-sm);
  gap: var(--ff-space-2);
}

@media (max-width: 640px) {
  .ff-flash-view__hero {
    flex-wrap: wrap;
  }
  .ff-flash-view__ratio-bar {
    order: 3;
    width: 100%;
  }
}
</style>
