<script setup>
import { computed } from 'vue'
import { useAppStore } from '../store/app'
import AppButton from '../ui/AppButton.vue'
import AppIcon from '../ui/AppIcon.vue'

const store = useAppStore()
const count = computed(() => store.pendingNews.length)

// 新闻已实时合并进列表；角标仅作为「回到顶部看新消息」的便捷入口。
function onClick() {
  const el = document.querySelector('.ff-app__content')
  if (el) el.scrollTo({ top: 0, behavior: 'smooth' })
  store.markSeen()
}
</script>

<template>
  <Transition name="ff-newsbadge">
    <AppButton
      v-if="count > 0"
      class="ff-newsbadge"
      variant="primary"
      size="md"
      pill
      @click="onClick"
    >
      <AppIcon name="arrow-up" size="sm" />
      {{ count }} 条新新闻
    </AppButton>
  </Transition>
</template>

<style scoped>
.ff-newsbadge {
  position: fixed;
  bottom: var(--ff-space-6);
  left: 50%;
  transform: translateX(-50%);
  z-index: var(--ff-z-popover);
  box-shadow: var(--ff-shadow-lg);
}

.ff-newsbadge-enter-active,
.ff-newsbadge-leave-active {
  transition: opacity var(--ff-dur-fast) var(--ff-ease-out),
              transform var(--ff-dur-fast) var(--ff-ease-out);
}

.ff-newsbadge-enter-from,
.ff-newsbadge-leave-to {
  opacity: 0;
  transform: translateX(-50%) translateY(12px);
}
</style>
