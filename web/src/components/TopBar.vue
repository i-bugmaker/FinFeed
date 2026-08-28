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
  <header class="ff-topbar ff-glass">
    <div class="ff-topbar__left">
      <AppButton
        class="ff-topbar__menu"
        variant="ghost"
        size="sm"
        icon="menu"
        :aria-label="'展开菜单'"
        @click="emit('menu')"
      />
      
      <!-- SSE 实时心跳状态 -->
      <div class="ff-topbar__live" :class="{ 'is-live': store.live }">
        <span class="ff-topbar__radar-ring" v-if="store.live" />
        <span class="ff-topbar__live-dot" />
        <span class="ff-topbar__live-text">{{ store.live ? 'LIVE 实时推流' : '连接建立中…' }}</span>
      </div>

      <!-- 抓取状态 -->
      <span
        class="ff-topbar__fetch"
        :class="monitor.offline_alert ? 'is-alert' : 'is-ok'"
        :title="monitor.offline_alert ? '超过阈值未成功抓取，系统可能离线' : '最近一次成功抓取时间'"
      >
        <AppIcon :name="monitor.offline_alert ? 'alert-triangle' : 'activity'" size="xs" />
        <span class="ff-topbar__fetch-text">同步 {{ lastFetchText }}</span>
      </span>
    </div>

    <div class="ff-topbar__right">
      <div class="ff-topbar__clock ff-num">
        <AppIcon name="clock" size="xs" class="ff-topbar__clock-icon" />
        <span>{{ clock }}</span>
      </div>

      <div class="ff-topbar__actions">
        <AppButton
          variant="ghost"
          size="sm"
          :icon="store.theme === 'light' ? 'moon' : 'sun'"
          :title="store.theme === 'light' ? '切换暗色模式' : '切换亮色模式'"
          class="ff-topbar__theme-btn"
          @click="store.toggleTheme()"
        />
      </div>
    </div>
  </header>
</template>

<style scoped>
.ff-topbar {
  height: var(--ff-topbar-h);
  flex-shrink: 0;
  border-bottom: 1px solid var(--ff-border);
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 0 var(--ff-space-4);
  gap: var(--ff-space-3);
  position: sticky;
  top: 0;
  z-index: var(--ff-z-sticky);
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

.ff-topbar__live {
  position: relative;
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 4px 10px;
  border-radius: var(--ff-radius-pill);
  background: var(--ff-bg-subtle);
  border: 1px solid var(--ff-border);
  font-size: 12px;
  font-weight: 600;
  color: var(--ff-text-secondary);
  transition: background-color var(--ff-dur-base) var(--ff-ease-standard), border-color var(--ff-dur-base) var(--ff-ease-standard), color var(--ff-dur-base) var(--ff-ease-standard), box-shadow var(--ff-dur-base) var(--ff-ease-standard), transform var(--ff-dur-base) var(--ff-ease-standard);
}

.ff-topbar__live.is-live {
  background: var(--ff-down-subtle);
  border-color: var(--ff-down-border);
  color: var(--ff-down-text);
  box-shadow: 0 0 12px -2px rgba(16, 185, 129, 0.25);
}

.ff-topbar__live-dot {
  width: 7px;
  height: 7px;
  border-radius: 50%;
  background: var(--ff-text-tertiary);
  flex-shrink: 0;
}

.ff-topbar__live.is-live .ff-topbar__live-dot {
  background: var(--ff-down);
}

.ff-topbar__radar-ring {
  position: absolute;
  left: 8px;
  top: 50%;
  transform: translateY(-50%);
  width: 11px;
  height: 11px;
  border-radius: 50%;
  border: 1.5px solid var(--ff-down);
  animation: ff-topbar-radar 2s cubic-bezier(0.2, 0.8, 0.2, 1) infinite;
  pointer-events: none;
}

@keyframes ff-topbar-radar {
  0% {
    transform: translateY(-50%) scale(0.6);
    opacity: 1;
  }
  100% {
    transform: translateY(-50%) scale(2.2);
    opacity: 0;
  }
}

.ff-topbar__live-text {
  letter-spacing: 0.03em;
  font-family: var(--ff-font-mono);
  font-size: 11.5px;
}

.ff-topbar__fetch {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  padding: 4px 10px;
  border-radius: var(--ff-radius-pill);
  font-size: 12px;
  white-space: nowrap;
  border: 1px solid var(--ff-border);
  background: var(--ff-bg-subtle);
  color: var(--ff-text-secondary);
  font-family: var(--ff-font-mono);
}

.ff-topbar__fetch.is-alert {
  background: var(--ff-up-subtle);
  border-color: var(--ff-up-border);
  color: var(--ff-up-text);
  animation: ff-pulse-ring 2s infinite;
}

.ff-topbar__clock {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  font-size: 12.5px;
  color: var(--ff-text-secondary);
  font-family: var(--ff-font-mono);
  font-variant-numeric: tabular-nums;
  padding: 4px 10px;
  border-radius: var(--ff-radius-pill);
  background: var(--ff-bg-subtle);
  border: 1px solid var(--ff-border-subtle);
  white-space: nowrap;
}

.ff-topbar__clock-icon {
  color: var(--ff-text-tertiary);
}

.ff-topbar__actions {
  display: flex;
  align-items: center;
  gap: var(--ff-space-2);
}

.ff-topbar__theme-btn {
  border-radius: var(--ff-radius-md);
  transition: transform var(--ff-dur-fast);
}

.ff-topbar__theme-btn:hover {
  transform: rotate(15deg);
}

@media (max-width: 680px) {
  .ff-topbar__clock,
  .ff-topbar__fetch {
    display: none;
  }
}

@media (min-width: 1024px) {
  .ff-topbar__menu {
    display: none;
  }
}
</style>
