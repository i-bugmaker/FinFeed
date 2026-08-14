<script setup>
import { ref, onMounted, onUnmounted, watch, nextTick } from 'vue'
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
const finished = ref(false)
const sources = ref([])
const sentinel = ref(null)
const contentEl = ref(null)
let observer = null

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
    const res = await api.news(params)
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

// 实时合并 SSE 推送的增量：增量到达即前置插入可见列表，不再要求用户
// 滚到顶部或手动点击。pendingNews 作为「未读」缓冲保留，用于驱动右上角
// 「N 条新新闻」提示；当用户已在顶部（新条目立即可见）时自动标记已读。
function applyPending() {
  const items = store.pendingNews.filter((n) => n.category === 'finance')
  // 单轮增量被截断（items 只含部分条目）时，局部插入会漏条目，整表刷新兜底。
  if (store.pendingTruncated.finance) {
    store.pendingNews = store.pendingNews.filter((n) => n.category !== 'finance')
    store.pendingTruncated.finance = false
    loadFirst()
    return
  }
  const ids = new Set(list.value.map((n) => n.id))
  const fresh = items.filter((n) => !ids.has(n.id))
  if (fresh.length) {
    list.value = [...fresh, ...list.value]
  }
  // 已在顶部：新条目立即可见，标记已读（清空未读缓冲，角标自动隐藏）
  if (isNearTop()) store.markSeen('finance')
}

function onContentScroll() {
  // 滚到顶部即视为已读最新条目，清空未读缓冲
  if (isNearTop()) store.markSeen('finance')
}

// 增量到达即实时合并，不再受滚动位置限制
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
  // 首屏列表已包含最新数据；若处于顶部，直接清空未读缓冲
  if (isNearTop()) store.markSeen('finance')
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
  <div class="ff-page ff-news-view">
    <div class="ff-page__header">
      <div>
        <h1 class="ff-page__title">
          <AppIcon name="newspaper" size="lg" /> 新闻流
        </h1>
        <p class="ff-page__subtitle">实时监控与聚合全市场财经新闻</p>
      </div>
    </div>

    <FilterBar
      v-model="filters"
      :sources="sources"
      @change="onFilterChange"
    />

    <div v-if="filters.keyword" class="ff-news-view__result">
      <AppIcon name="search" size="xs" />
      <span>找到 <strong class="ff-num">{{ total }}</strong> 条与「<strong>{{ filters.keyword }}</strong>」相关的新闻</span>
      <button type="button" class="ff-news-view__result-clear" @click="clearKeyword">
        <AppIcon name="x" size="xs" /> 清除关键词
      </button>
    </div>

    <AppCard :no-padding="true" class="ff-news-view__table">
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
        :text="filters.keyword ? `未找到与「${filters.keyword}」相关的新闻` : '没有符合条件的新闻'"
        icon="search"
      >
        <template v-if="filters.keyword" #description>
          换个关键词试试，或清除筛选条件查看全部新闻。
        </template>
        <template v-if="filters.keyword" #action>
          <AppButton variant="secondary" size="sm" icon="x" @click="clearKeyword">清除筛选</AppButton>
        </template>
      </EmptyState>
    </AppCard>

    <div ref="sentinel" class="ff-news-view__sentinel">
      <AppSkeleton v-if="loading" variant="text" :lines="2" />
      <span v-else-if="finished && list.length > 0" class="ff-text-muted">
        <AppIcon name="check-circle" size="xs" /> 已加载全部 {{ total }} 条
      </span>
    </div>
  </div>
</template>

<style scoped>
.ff-news-view {
  max-width: var(--ff-container-max);
  margin: 0 auto;
}

.ff-news-view__table {
  overflow: hidden;
}

.ff-news-view__result {
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
.ff-news-view__result strong {
  color: var(--ff-text-primary);
  font-weight: 600;
}
.ff-news-view__result-clear {
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
.ff-news-view__result-clear:hover {
  background: var(--ff-bg-hover);
  border-color: var(--ff-border-strong);
  color: var(--ff-text-primary);
}

.ff-news-view__sentinel {
  display: flex;
  align-items: center;
  justify-content: center;
  padding: var(--ff-space-5) 0 var(--ff-space-10);
  color: var(--ff-text-tertiary);
  font-size: var(--ff-fs-sm);
  gap: var(--ff-space-2);
}
</style>
