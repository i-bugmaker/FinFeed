<script setup>
import { ref, onMounted, onUnmounted, watch, nextTick } from 'vue'
import { useRoute } from 'vue-router'
import { api } from '../api/client'
import { useAppStore } from '../store/app'
import NewsRow from '../components/NewsRow.vue'
import FilterBar from '../components/FilterBar.vue'
import EmptyState from '../components/EmptyState.vue'

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
      // 用新闻自己的来源列表（与舆情隔离）
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
  <div class="news-view">
    <FilterBar
      v-model="filters"
      :sources="sources"
      @change="onFilterChange"
    />
    <table class="news-table" v-if="list.length > 0">
      <thead>
        <tr>
          <th class="nt-fav"></th>
          <th class="nt-imp">重要性</th>
          <th class="nt-time">时间</th>
          <th class="nt-source">来源</th>
          <th class="nt-title">标题</th>
        </tr>
      </thead>
      <tbody>
        <NewsRow v-for="item in list" :key="item.id" :item="item" />
      </tbody>
    </table>
    <EmptyState v-else-if="!loading" text="没有符合条件的新闻" />
    <div ref="sentinel" class="nt-sentinel">
      <span v-if="loading" class="spinner"></span>
      <span v-else-if="finished && list.length > 0" class="text-3">— 已加载全部 {{ total }} 条 —</span>
    </div>
  </div>
</template>

<style scoped>
.news-view {
  max-width: var(--content-max);
  margin: 0 auto;
}
</style>
