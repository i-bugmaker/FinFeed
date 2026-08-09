<script setup>
import { onMounted, computed, ref } from 'vue'
import { useAppStore } from './store/app'
import { useSSE } from './composables/useSSE'
import Sidebar from './components/Sidebar.vue'
import TopBar from './components/TopBar.vue'
import NewNewsBadge from './components/NewNewsBadge.vue'

const store = useAppStore()
useSSE()

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
      <main class="ff-app__content">
        <router-view v-slot="{ Component }">
          <transition name="ff-page" mode="out-in">
            <component :is="Component" />
          </transition>
        </router-view>
      </main>
    </div>

    <NewNewsBadge />
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
  padding: var(--ff-space-4);
  scroll-behavior: smooth;
}

@media (min-width: 1024px) {
  .ff-app__sidebar--desktop {
    display: flex;
  }

  .ff-app__content {
    padding: var(--ff-space-6);
  }
}

@media (min-width: 1280px) {
  .ff-app__content {
    padding: var(--ff-space-8);
  }
}
</style>
