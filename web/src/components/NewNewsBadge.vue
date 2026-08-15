<script setup>
import { computed } from 'vue'
import { useAppStore } from '../store/app'
import AppButton from '../ui/AppButton.vue'
import AppIcon from '../ui/AppIcon.vue'

const store = useAppStore()
// 角标只统计「快讯页实际展示」的未读。SSE 会广播 flash / article / forum 三类，
// 但快讯页（FlashView）的 API 只取 category='flash'，财经文章页只取 category='article'。
// 若把 article / forum 计入未读，会导致其源源不断推送时角标永远清不掉、点了又出现。
const count = computed(() =>
  store.pendingNews.filter((n) => n.category === 'flash').length,
)

// 冷却期（ms）：用户手动点击 badge 后，即使 SSE 立即推送新条目，
// 也在冷却期内不重新显示 badge，避免「点了又出来」的体验问题
const BADGE_COOLDOWN = 3000

const visible = computed(() => {
  if (count.value === 0) return false
  if (store.badgeDismissedAt > 0) {
    return Date.now() - store.badgeDismissedAt > BADGE_COOLDOWN
  }
  return true
})

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
      v-if="visible"
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
