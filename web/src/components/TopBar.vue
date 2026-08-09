<script setup>
import { ref, onMounted, onUnmounted } from 'vue'
import { useAppStore } from '../store/app'
import AppIcon from '../ui/AppIcon.vue'
import AppStatus from '../ui/AppStatus.vue'
import AppButton from '../ui/AppButton.vue'

const store = useAppStore()
const emit = defineEmits(['menu'])

const clock = ref('')
let timer = null

function tick() {
  const d = new Date()
  const p = (n) => String(n).padStart(2, '0')
  clock.value = `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())} ${p(d.getHours())}:${p(d.getMinutes())}:${p(d.getSeconds())}`
}

onMounted(() => {
  tick()
  timer = setInterval(tick, 1000)
})
onUnmounted(() => clearInterval(timer))
</script>

<template>
  <header class="ff-topbar">
    <div class="ff-topbar__left">
      <AppButton
        class="ff-topbar__menu"
        variant="ghost"
        size="sm"
        icon="menu"
        :aria-label="'展开菜单'"
        @click="emit('menu')"
      />
      <AppStatus
        :text="store.live ? '实时连接' : '连接中…'"
        :tone="store.live ? 'success' : 'neutral'"
        :pulse="store.live"
      />
      <span class="ff-topbar__clock ff-num">{{ clock }}</span>
    </div>

    <div class="ff-topbar__right">
      <AppButton
        variant="ghost"
        size="sm"
        :icon="store.theme === 'light' ? 'moon' : 'sun'"
        :title="store.theme === 'light' ? '切换暗色模式' : '切换亮色模式'"
        @click="store.toggleTheme()"
      />
    </div>
  </header>
</template>

<style scoped>
.ff-topbar {
  height: var(--ff-topbar-h);
  flex-shrink: 0;
  background: var(--ff-bg-surface);
  border-bottom: 1px solid var(--ff-border);
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 0 var(--ff-space-4);
  gap: var(--ff-space-3);
}

.ff-topbar__left,
.ff-topbar__right {
  display: flex;
  align-items: center;
  gap: var(--ff-space-3);
  min-width: 0;
}

.ff-topbar__menu {
  display: inline-flex;
}

.ff-topbar__clock {
  font-size: var(--ff-fs-sm);
  color: var(--ff-text-primary);
  letter-spacing: 0.02em;
  white-space: nowrap;
}

@media (min-width: 768px) {
  .ff-topbar {
    padding: 0 var(--ff-space-6);
  }

  .ff-topbar__left,
  .ff-topbar__right {
    gap: var(--ff-space-5);
  }
}

@media (min-width: 1024px) {
  .ff-topbar__menu {
    display: none;
  }
}
</style>
