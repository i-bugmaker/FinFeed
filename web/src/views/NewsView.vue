<script setup>
import { ref, onMounted, onUnmounted, watch, nextTick } from 'vue'
import { useRoute } from 'vue-router'
import { api } from '../api/client'
import { useAppStore } from '../store/app'
import NewsRow from '../components/NewsRow.vue'
import FilterBar from '../components/FilterBar.vue'
import EmptyState from '../components/EmptyState.vue'
import AppCard from '../ui/AppCard.vue'
import AppIcon from '../ui/AppIcon.vue'
import AppSkeleton from '../ui/AppSkeleton.vue'

const route = useRoute()
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

function prependPending() {
  const pend = store.takePending()
  if (!pend.length) return
  const ids = new Set(list.value.map((n) => n.id))
  const fresh = pend.filter((n) => !ids.has(n.id))
  list.value = [...fresh, ...list.value]
  store.pendingNews = []
}

watch(
  () => route.query._new,
  () => prependPending(),
)

onMounted(async () => {
  await loadFirst()
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
          <NewsRow v-for="item in list" :key="item.id" :item="item" />
        </tbody>
      </table>
      <EmptyState v-else-if="!loading" text="没有符合条件的新闻" icon="search" />
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
