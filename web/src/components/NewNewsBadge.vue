<script setup>
import { computed } from 'vue'
import { useAppStore } from '../store/app'
import { useRouter } from 'vue-router'
import AppButton from '../ui/AppButton.vue'
import AppIcon from '../ui/AppIcon.vue'

const store = useAppStore()
const router = useRouter()
const count = computed(() => store.pendingNews.length)

function go() {
  router.push({ path: '/news', query: { _new: String(Date.now()) } })
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
      @click="go"
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
