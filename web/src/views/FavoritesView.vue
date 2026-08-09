<script setup>
import { ref, onMounted, onUnmounted, nextTick } from 'vue'
import { api } from '../api/client'
import NewsCard from '../components/NewsCard.vue'

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
  <div class="view">
    <div v-if="!loading && list.length === 0" class="empty-wrap">
      <div class="empty-card card">
        <div class="empty-ico">⭐</div>
        <h3>收藏夹还是空的</h3>
        <p class="text-2">在「新闻流」或「舆情」中点击任意条目右侧的 ☆ 图标，<br />即可把感兴趣的内容收藏到这里，随时回看。</p>
        <router-link to="/news" class="btn btn-primary">去新闻流看看</router-link>
      </div>
    </div>
    <template v-else>
      <div class="list">
        <NewsCard v-for="item in list" :key="item.id" :item="item" mode="news" />
      </div>
      <div ref="sentinel" class="sentinel">
        <span v-if="loading" class="spinner"></span>
        <span v-else-if="finished" class="text-3">— 共 {{ total }} 条收藏 —</span>
      </div>
    </template>
  </div>
</template>

<style scoped>
.view {
  max-width: var(--content-max);
  margin: 0 auto;
}
.list {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(440px, 1fr));
  gap: var(--sp-3);
}
@media (max-width: 920px) {
  .list {
    grid-template-columns: 1fr;
  }
}
.sentinel {
  text-align: center;
  padding: var(--sp-5);
  color: var(--text-3);
  display: flex;
  gap: 10px;
  align-items: center;
  justify-content: center;
}
.empty-wrap {
  display: flex;
  align-items: center;
  justify-content: center;
  min-height: 60vh;
}
.empty-card {
  max-width: 460px;
  width: 100%;
  text-align: center;
  padding: var(--sp-6) var(--sp-5);
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: var(--sp-3);
  box-shadow: var(--shadow-sm);
}
.empty-ico {
  font-size: 52px;
  line-height: 1;
  filter: grayscale(0.1);
}
.empty-card h3 {
  font-size: var(--fs-lg);
  font-weight: 700;
  margin: 0;
}
.empty-card p {
  font-size: var(--fs-sm);
  line-height: 1.7;
  margin: 0;
}
</style>
