<script setup>
import { ref, onMounted, onUnmounted, nextTick } from 'vue'
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
    <div class="ff-page__header">
      <div>
        <h1 class="ff-page__title">
          <AppIcon name="chatter" size="lg" /> 舆情
        </h1>
        <p class="ff-page__subtitle">股吧 / 论坛舆情聚合，感知市场情绪与热点讨论</p>
      </div>
    </div>

    <FilterBar v-model="filters" :sources="sources" :show-fav="true" @change="onFilterChange" />

    <div class="ff-sentiment-view__list">
      <NewsCard v-for="item in list" :key="item.id" :item="item" mode="sentiment" />
      <EmptyState v-if="!loading && list.length === 0" text="暂无舆情数据" icon="chatter" />
    </div>

    <div ref="sentinel" class="ff-sentiment-view__sentinel">
      <AppSkeleton v-if="loading" variant="text" :lines="2" />
      <span v-else-if="finished" class="ff-text-muted">
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
</style>
