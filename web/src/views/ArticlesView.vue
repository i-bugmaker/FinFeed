<script setup>
import { ref, onMounted, onUnmounted, nextTick } from 'vue'
import { api } from '../api/client'
import NewsRow from '../components/NewsRow.vue'
import NewsCard from '../components/NewsCard.vue'
import FilterBar from '../components/FilterBar.vue'
import EmptyState from '../components/EmptyState.vue'
import AppCard from '../ui/AppCard.vue'
import AppIcon from '../ui/AppIcon.vue'
import AppButton from '../ui/AppButton.vue'
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
const viewMode = ref('cards') // 'cards' | 'table'
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
  <div class="ff-page ff-articles-view">
    <div class="ff-articles-view__header">
      <div class="ff-articles-view__header-info">
        <h1 class="ff-h2">深度财经</h1>
        <p class="ff-body-sm ff-text-muted">权威机构研报、深度产业剖析与宏观财经专栏</p>
      </div>

      <div class="ff-articles-view__view-toggle">
        <button
          class="ff-articles-view__toggle-btn"
          :class="{ 'is-active': viewMode === 'cards' }"
          title="卡片图文视图"
          @click="viewMode = 'cards'"
        >
          <AppIcon name="dashboard" size="xs" />
        </button>
        <button
          class="ff-articles-view__toggle-btn"
          :class="{ 'is-active': viewMode === 'table' }"
          title="数据表格视图"
          @click="viewMode = 'table'"
        >
          <AppIcon name="menu" size="xs" />
        </button>
      </div>
    </div>

    <FilterBar
      v-model="filters"
      :sources="sources"
      @change="onFilterChange"
    />

    <div v-if="filters.keyword" class="ff-articles-view__result">
      <AppIcon name="search" size="xs" />
      <span>找到 <strong class="ff-num">{{ total }}</strong> 条与「<strong>{{ filters.keyword }}</strong>」相关的文章</span>
      <button type="button" class="ff-articles-view__result-clear" @click="clearKeyword">
        <AppIcon name="x" size="xs" /> 清除关键词
      </button>
    </div>

    <!-- 卡片流模式 -->
    <div class="ff-articles-view__cards" v-if="viewMode === 'cards'">
      <NewsCard v-for="item in list" :key="item.id" :item="item" mode="news" />
      <EmptyState
        v-if="!loading && list.length === 0"
        :text="filters.keyword ? `未找到与「${filters.keyword}」相关的文章` : '暂无文章数据'"
        icon="newspaper"
      />
    </div>

    <!-- 表格模式 -->
    <AppCard :no-padding="true" class="ff-articles-view__table" v-else>
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

.ff-articles-view__header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: var(--ff-space-4);
  gap: var(--ff-space-4);
}

.ff-articles-view__header-info h1 {
  margin: 0 0 4px 0;
}

.ff-articles-view__header-info p {
  margin: 0;
}

.ff-articles-view__view-toggle {
  display: inline-flex;
  padding: 2px;
  border-radius: var(--ff-radius-md);
  background: var(--ff-bg-subtle);
  border: 1px solid var(--ff-border);
}

.ff-articles-view__toggle-btn {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 30px;
  height: 30px;
  border-radius: var(--ff-radius-sm);
  color: var(--ff-text-tertiary);
  background: none;
  border: none;
  cursor: pointer;
  transition: all var(--ff-dur-fast);
}

.ff-articles-view__toggle-btn:hover {
  color: var(--ff-text-primary);
}

.ff-articles-view__toggle-btn.is-active {
  background: var(--ff-bg-surface);
  color: var(--ff-brand-text);
  box-shadow: var(--ff-shadow-xs);
}

.ff-articles-view__cards {
  display: flex;
  flex-direction: column;
  gap: var(--ff-space-3);
}

.ff-articles-view__table {
  overflow: hidden;
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
