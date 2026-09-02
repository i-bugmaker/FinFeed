<script setup>
import { ref, onMounted, onUnmounted, nextTick } from 'vue'
import { api } from '../api/client'
import NewsCard from '../components/NewsCard.vue'
import AppCard from '../ui/AppCard.vue'
import AppEmpty from '../ui/AppEmpty.vue'
import AppButton from '../ui/AppButton.vue'
import AppIcon from '../ui/AppIcon.vue'
import AppInput from '../ui/AppInput.vue'
import AppSkeleton from '../ui/AppSkeleton.vue'

const keyword = ref('')
const list = ref([])
const total = ref(0)
const page = ref(1)
const pageSize = 30
const loading = ref(false)
const finished = ref(false)
const err = ref('')
const sentinel = ref(null)
let observer = null

async function loadFirst() {
  page.value = 1
  finished.value = false
  list.value = []
  await fetchPage()
  // 错误态分支不渲染 sentinel；重试成功后需重新挂上观察器，否则无限滚动失效
  await nextTick()
  if (observer && sentinel.value) observer.observe(sentinel.value)
}

async function fetchPage() {
  if (loading.value || finished.value) return
  loading.value = true
  err.value = ''
  try {
    const res = await api.favorites({
      page: page.value,
      page_size: pageSize,
      keyword: keyword.value || undefined,
    })
    const items = res.news || []
    list.value = page.value === 1 ? items : [...list.value, ...items]
    total.value = res.total || 0
    if (list.value.length >= total.value || items.length === 0) finished.value = true
    page.value += 1
  } catch (e) {
    // 明确区分「加载失败」与「暂无收藏」，失败时绝不渲染成空态
    err.value = e?.message || String(e)
  } finally {
    loading.value = false
  }
}

let kwTimer = null
function onKwInput() {
  if (kwTimer) clearTimeout(kwTimer)
  kwTimer = setTimeout(() => loadFirst(), 350)
}

// 取消收藏后即时移除卡片（此前星星熄灭但卡片滞留，操作像没生效）
function onUnfavorited(item) {
  list.value = list.value.filter((n) => n.id !== item.id)
  total.value = Math.max(0, total.value - 1)
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
  if (kwTimer) clearTimeout(kwTimer)
})
</script>

<template>
  <div class="ff-page ff-favorites-view">
    <div class="ff-favorites-view__hero ff-glass">
      <!-- 页面标题按产品要求移除，h1 保留 sr-only 保文档语义 -->
      <h1 class="ff-sr-only">自选与收藏</h1>

      <div class="ff-favorites-view__hero-right">
        <AppInput
          v-model="keyword"
          prefix-icon="search"
          placeholder="搜索收藏内容…"
          class="ff-favorites-view__search"
          @input="onKwInput"
        />
        <div class="ff-favorites-view__count ff-num">
          共 <strong>{{ total }}</strong> 条收藏
        </div>
      </div>
    </div>

    <!-- 首屏加载失败：必须显式报错，禁止伪装成「收藏夹还是空的」 -->
    <AppCard v-if="err && list.length === 0 && !loading" class="ff-favorites-view__empty-card">
      <AppEmpty
        title="收藏加载失败"
        :description="`网络或服务异常，无法获取收藏列表（${err}）。请重试。`"
        icon="alert-triangle"
      >
        <template #action>
          <AppButton variant="primary" icon="refresh" @click="loadFirst">重试</AppButton>
        </template>
      </AppEmpty>
    </AppCard>

    <template v-else-if="!loading && list.length === 0">
      <AppCard class="ff-favorites-view__empty-card">
        <AppEmpty
          :title="keyword ? `未找到包含「${keyword}」的收藏` : '收藏夹还是空的'"
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
        <NewsCard v-for="item in list" :key="item.id" :item="item" mode="news" @fav="onUnfavorited" />
      </div>
      <div ref="sentinel" class="ff-favorites-view__sentinel">
        <AppSkeleton v-if="loading" variant="text" :lines="2" />
        <template v-else-if="err">
          <span class="ff-favorites-view__error"><AppIcon name="alert-triangle" size="xs" /> 加载失败：{{ err }}</span>
          <AppButton variant="ghost" size="sm" icon="refresh" @click="fetchPage">重试</AppButton>
        </template>
        <span v-else-if="finished" class="ff-text-muted">
          <AppIcon name="check-circle" size="xs" /> 已加载全部 {{ total }} 条收藏
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

.ff-favorites-view__hero {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--ff-space-4);
  padding: 16px 20px;
  border-radius: var(--ff-radius-lg);
  border: 1px solid var(--ff-border);
  margin-bottom: var(--ff-space-4);
  flex-wrap: wrap;
}

.ff-favorites-view__hero-left h1 {
  margin: 0 0 4px 0;
}

.ff-favorites-view__hero-left p {
  margin: 0;
}

.ff-favorites-view__hero-right {
  display: flex;
  align-items: center;
  gap: var(--ff-space-3);
}

.ff-favorites-view__search {
  width: 220px;
}

.ff-favorites-view__count {
  font-size: 13px;
  color: var(--ff-text-secondary);
}

.ff-favorites-view__empty-card {
  padding: var(--ff-space-8) var(--ff-space-4);
}

.ff-favorites-view__list {
  display: flex;
  flex-direction: column;
  gap: var(--ff-space-3);
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

.ff-favorites-view__error {
  display: inline-flex;
  align-items: center;
  gap: var(--ff-space-1);
  color: var(--ff-danger-text);
}

/* ── 窄屏适配（≤768px：搜索框占满一行）── */
@media (max-width: 768px) {
  .ff-favorites-view__search {
    width: 100%;
    flex: 1 1 100%;
  }
}
</style>
