<script setup>
import { computed } from 'vue'
import { useAppStore } from '../store/app'
import { useRouter } from 'vue-router'

const store = useAppStore()
const router = useRouter()
const count = computed(() => store.pendingNews.length)

function go() {
  router.push({ path: '/news', query: { _new: String(Date.now()) } })
}
</script>

<template>
  <transition name="slide">
    <button v-if="count > 0" class="badge" @click="go">
      ↑ {{ count }} 条新新闻
    </button>
  </transition>
</template>

<style scoped>
.badge {
  position: fixed;
  bottom: 28px;
  left: 50%;
  transform: translateX(-50%);
  z-index: 50;
  background: var(--primary);
  color: var(--primary-text);
  border: none;
  border-radius: var(--r-pill);
  padding: 11px 22px;
  font-size: var(--fs-sm);
  font-weight: 600;
  box-shadow: var(--shadow-lg);
  animation: fadeIn 0.25s ease;
}
.slide-enter-active,
.slide-leave-active {
  transition: all 0.25s ease;
}
.slide-enter-from,
.slide-leave-to {
  opacity: 0;
  transform: translateX(-50%) translateY(12px);
}
</style>
