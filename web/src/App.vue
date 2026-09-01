<script setup>
import { onMounted, computed, ref } from 'vue'
import { useRouter } from 'vue-router'
import { useAppStore } from './store/app'
import { useSSE } from './composables/useSSE'
import Sidebar from './components/Sidebar.vue'
import TopBar from './components/TopBar.vue'
import NewNewsBadge from './components/NewNewsBadge.vue'
import ToastHost from './components/ToastHost.vue'

const store = useAppStore()
const router = useRouter()
useSSE()

// 新新闻角标仅在快讯页显示（快讯为 7×24 实时滚动内容，SSE 增量主要面向该页），
// 财经文章页为低频深度内容、不叠加实时角标，其他模块页面也不应出现
const isNewsPage = computed(() => router.currentRoute.value.name === 'flash')

const mobileDrawerOpen = ref(false)
const isDesktop = computed(() => typeof window !== 'undefined' && window.innerWidth >= 1024)

onMounted(() => {
  store.initTheme()
  window.addEventListener('resize', () => {
    if (isDesktop.value) mobileDrawerOpen.value = false
  })
})
</script>

<template>
  <div class="ff-app">
    <!-- 桌面侧边栏 -->
    <Sidebar class="ff-app__sidebar ff-app__sidebar--desktop" />

    <!-- 移动端抽屉 -->
    <AppDrawer
      v-model="mobileDrawerOpen"
      placement="left"
      size="sm"
      class="ff-app__drawer"
    >
      <Sidebar mobile @close="mobileDrawerOpen = false" />
    </AppDrawer>

    <div class="ff-app__main">
      <TopBar @menu="mobileDrawerOpen = true" />
      <!-- data-scroll-container：应用唯一滚动容器标记。容器为内部滚动（非 window），
           vue-router 的 scrollBehavior 对其无效，由 useScrollRestore 依赖此标记
           保存 / 恢复模块滚动位置 -->
      <main class="ff-app__content" data-scroll-container>
        <router-view v-slot="{ Component }">
          <transition name="ff-page" mode="out-in">
            <component :is="Component" />
          </transition>
        </router-view>
      </main>
    </div>

    <NewNewsBadge v-if="isNewsPage" />
    <ToastHost />
  </div>
</template>

<style scoped>
.ff-app {
  display: flex;
  height: 100vh;
  height: 100dvh;
  overflow: hidden;
  background: var(--ff-bg-canvas);
  color: var(--ff-text-primary);
}

.ff-app__sidebar--desktop {
  display: none;
}

.ff-app__main {
  flex: 1 1 auto;
  display: flex;
  flex-direction: column;
  min-width: 0;
  min-height: 0;
}

.ff-app__content {
  flex: 1 1 auto;
  overflow-y: auto;
  padding: var(--ff-page-pad-y) var(--ff-page-pad-x);
  scroll-behavior: smooth;
}

@media (min-width: 1024px) {
  .ff-app__sidebar--desktop {
    display: flex;
  }
}
</style>
