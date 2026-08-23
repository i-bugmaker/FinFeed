<script setup>
import { ref, onMounted, onUnmounted, nextTick } from 'vue'
import { api } from '../api/client'
import NewsCard from '../components/NewsCard.vue'
import AppCard from '../ui/AppCard.vue'
import AppEmpty from '../ui/AppEmpty.vue'
import AppButton from '../ui/AppButton.vue'
import AppIcon from '../ui/AppIcon.vue'
import AppSkeleton from '../ui/AppSkeleton.vue'

const filters = ref({ keyword: '', source: 'all', sentiment: 'all', start: '', end: '' })
const list = ref([])
const total = ref(0)
const page = ref(1)
const pageSize = 30
const loading = ref(false)
const finished = ref(false)
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
    const res = await api.favorites({
      page: page.value,
      page_size: pageSize,
      keyword: filters.value.keyword || undefined,
    })
    const items = res.news || []
    list.value = page.value === 1 ? items : [...list.value, ...items]
    total.value = res.total || 0
    if (list.value.length >= total.value || items.length === 0) finished.value = true
    page.value += 1
  } catch (e) {
    console.error(e)
  } finally {
    loading.value = false
  }
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
  <div class="ff-page ff-favorites-view">
    <template v-if="!loading && list.length === 0">
      <AppCard class="ff-favorites-view__empty-card">
        <AppEmpty
          title="收藏夹还是空的"
          description="在「快讯」「财经」或「舆情」中点击任意条目右侧的星形图标，即可把感兴趣的内容收藏到这里，随时回看。"
          icon="star"
        >
          <template #action>
            <AppButton variant="primary" icon="zap" href="#/flash">去快讯看看</AppButton>
          </template>
        </AppEmpty>
      </AppCard>
    </template>

    <template v-else>
      <div class="ff-favorites-view__list">
        <NewsCard v-for="item in list" :key="item.id" :item="item" mode="news" />
      </div>
      <div ref="sentinel" class="ff-favorites-view__sentinel">
        <AppSkeleton v-if="loading" variant="text" :lines="2" />
        <span v-else-if="finished" class="ff-text-muted">
          <AppIcon name="check-circle" size="xs" /> 共 {{ total }} 条收藏
        </span>
      </div>
    </template>
  </div>
</template>

<style scoped>
.ff-favorites-view {
  max-width: var(--ff-container-max);
  margin: 0 auto;
}

.ff-favorites-view__list {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(440px, 1fr));
  gap: var(--ff-space-3);
}

.ff-favorites-view__empty-card {
  display: flex;
  align-items: center;
  justify-content: center;
  min-height: 60vh;
}

.ff-favorites-view__sentinel {
  display: flex;
  align-items: center;
  justify-content: center;
  padding: var(--ff-space-5) 0 var(--ff-space-10);
  color: var(--ff-text-tertiary);
  font-size: var(--ff-fs-sm);
  gap: var(--ff-space-2);
}

@media (max-width: 920px) {
  .ff-favorites-view__list {
    grid-template-columns: 1fr;
  }
}
</style>
