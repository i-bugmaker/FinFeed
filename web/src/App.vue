<script setup>
import { onMounted } from 'vue'
import { useAppStore } from './store/app'
import { useSSE } from './composables/useSSE'
import Sidebar from './components/Sidebar.vue'
import TopBar from './components/TopBar.vue'
import NewNewsBadge from './components/NewNewsBadge.vue'

const store = useAppStore()
useSSE()

onMounted(() => store.initTheme())
</script>

<template>
  <div class="layout">
    <Sidebar />
    <div class="main">
      <TopBar />
      <main class="content">
        <router-view v-slot="{ Component }">
          <transition name="fade" mode="out-in">
            <component :is="Component" />
          </transition>
        </router-view>
      </main>
    </div>
    <NewNewsBadge />
  </div>
</template>

<style scoped>
.layout {
  display: flex;
  height: 100vh;
  overflow: hidden;
}
.main {
  flex: 1;
  display: flex;
  flex-direction: column;
  min-width: 0;
}
.content {
  flex: 1;
  overflow-y: auto;
  padding: var(--sp-5);
}
.fade-enter-active,
.fade-leave-active {
  transition: opacity 0.18s ease;
}
.fade-enter-from,
.fade-leave-to {
  opacity: 0;
}
</style>
