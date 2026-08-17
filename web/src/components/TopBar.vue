<script setup>
import { ref, onMounted, onUnmounted, computed } from 'vue'
import { useAppStore } from '../store/app'
import { api } from '../api/client'
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

// 全局运行态：最近成功抓取时间 + 离线告警（高频轮询，独立于 /api/stats）
const monitor = ref({ last_success_str: '', offline_seconds: -1, offline_alert: false })
let monitorTimer = null

function fmtAgo(sec) {
  if (sec == null || sec < 0) return '—'
  if (sec < 60) return `${sec}秒前`
  if (sec < 3600) return `${Math.floor(sec / 60)}分钟前`
  if (sec < 86400) return `${Math.floor(sec / 3600)}小时前`
  return `${Math.floor(sec / 86400)}天前`
}

const lastFetchText = computed(() => {
  if (!monitor.value.last_success_str) return '暂无抓取记录'
  return `${monitor.value.last_success_str.slice(11)}（${fmtAgo(monitor.value.offline_seconds)}）`
})

async function refreshMonitor() {
  try {
    const r = await api.monitorStatus()
    if (r) monitor.value = r
  } catch (e) {
    /* 轮询失败静默，保持上一次状态 */
  }
}

onMounted(() => {
  tick()
  timer = setInterval(tick, 1000)
  refreshMonitor()
  monitorTimer = setInterval(refreshMonitor, 10000)
})
onUnmounted(() => {
  clearInterval(timer)
  if (monitorTimer) clearInterval(monitorTimer)
})
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
      <div class="ff-topbar__live" :class="{ 'is-live': store.live }">
        <AppStatus
          :text="store.live ? '实时连接' : '连接中…'"
          :tone="store.live ? 'success' : 'neutral'"
          :pulse="store.live"
        />
        <span v-if="store.live" class="ff-topbar__live-dot" aria-hidden="true" />
      </div>
      <span
        class="ff-topbar__fetch"
        :class="monitor.offline_alert ? 'is-alert' : 'is-ok'"
        :title="monitor.offline_alert ? '超过阈值未成功抓取，系统可能离线' : '最近一次成功抓取时间'"
      >
        <AppIcon :name="monitor.offline_alert ? 'alert-triangle' : 'clock'" size="xs" />
        <span class="ff-topbar__fetch-text">最近抓取 {{ lastFetchText }}</span>
      </span>
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
  font-size: var(--ff-fs-body-sm);
  color: var(--ff-text-primary);
  letter-spacing: 0.02em;
  white-space: nowrap;
}

.ff-topbar__fetch {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  padding: 4px 10px;
  border-radius: var(--ff-radius-pill);
  font-size: var(--ff-fs-body-sm);
  white-space: nowrap;
  border: 1px solid transparent;
}
.ff-topbar__fetch.is-ok {
  background: var(--ff-bg-subtle);
  color: var(--ff-text-secondary);
}
.ff-topbar__fetch.is-alert {
  background: var(--ff-down-subtle);
  border-color: var(--ff-down-border);
  color: var(--ff-down-text);
  animation: ff-topbar-fetch-pulse 1.8s var(--ff-ease-standard) infinite;
}
.ff-topbar__fetch-text {
  letter-spacing: 0.01em;
}
@keyframes ff-topbar-fetch-pulse {
  0% { box-shadow: 0 0 0 0 var(--ff-down-border); }
  70% { box-shadow: 0 0 0 6px transparent; }
  100% { box-shadow: 0 0 0 0 transparent; }
}
@media (max-width: 600px) {
  .ff-topbar__fetch-text {
    display: none;
  }
  .ff-topbar__fetch::after {
    content: attr(data-short);
  }
}

.ff-topbar__live {
  display: inline-flex;
  align-items: center;
  gap: var(--ff-space-2);
  padding: 4px 10px 4px 8px;
  border-radius: var(--ff-radius-pill);
  background: var(--ff-bg-subtle);
  color: var(--ff-text-secondary);
  border: 1px solid transparent;
  transition:
    background-color var(--ff-dur-base) var(--ff-ease-standard),
    border-color var(--ff-dur-base) var(--ff-ease-standard),
    color var(--ff-dur-base) var(--ff-ease-standard),
    box-shadow var(--ff-dur-base) var(--ff-ease-standard);
}
.ff-topbar__live.is-live {
  background: var(--ff-down-subtle);
  border-color: var(--ff-down-border);
  color: var(--ff-down-text);
  box-shadow: 0 0 0 1px var(--ff-down-border);
}
/* 仅保留右侧独立脉冲点作为唯一指示器，隐藏 AppStatus 自带状态点（左侧） */
.ff-topbar__live :deep(.ff-status__dot) {
  display: none;
}
.ff-topbar__live-dot {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: var(--ff-down);
  box-shadow: 0 0 0 0 var(--ff-down);
  animation: ff-topbar-live-pulse 1.6s var(--ff-ease-standard) infinite;
}
@keyframes ff-topbar-live-pulse {
  0% {
    box-shadow: 0 0 0 0 var(--ff-down);
    opacity: 1;
  }
  70% {
    box-shadow: 0 0 0 8px transparent;
    opacity: 0.4;
  }
  100% {
    box-shadow: 0 0 0 0 transparent;
    opacity: 0;
  }
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
