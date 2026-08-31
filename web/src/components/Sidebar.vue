<script setup>
import { computed, ref, onMounted, onUnmounted } from 'vue'
import { useRoute } from 'vue-router'
import { useAppStore } from '../store/app'
import { api } from '../api/client'
import AppIcon from '../ui/AppIcon.vue'
import AppLogo from '../ui/AppLogo.vue'
import AppButton from '../ui/AppButton.vue'

const props = defineProps({
  mobile: { type: Boolean, default: false },
})

const emit = defineEmits(['close'])
const route = useRoute()
const store = useAppStore()

const groups = [
  {
    title: '实时动态',
    items: [
      { to: '/flash', label: '快讯', icon: 'zap', badge: computed(() => store.pendingNews.filter(n => n.category === 'flash').length || 0) },
      { to: '/articles', label: '财经', icon: 'newspaper' },
      { to: '/sentiment', label: '舆情', icon: 'chatter' },
      { to: '/calendar', label: '财经日历', icon: 'calendar' },
    ],
  },
  {
    title: '行情与量化',
    items: [
      { to: '/market', label: '全景行情', icon: 'trending-up' },
      { to: '/stock-monitor', label: '股票监控', icon: 'monitor' },
      { to: '/limitup-ladder', label: '连板天地', icon: 'layers' },
      { to: '/market-hot', label: '市场热榜', icon: 'flame' },
      { to: '/screener', label: '智能选股', icon: 'filter' },
      { to: '/easytdx', label: 'easy-tdx', icon: 'cpu' },
    ],
  },
  {
    title: 'AI 分析',
    items: [
      { to: '/dashboard', label: '仪表盘', icon: 'dashboard' },
      { to: '/ai', label: 'AI 分析', icon: 'sparkles' },
      { to: '/favorites', label: '自选收藏', icon: 'star' },
      { to: '/notifications', label: '通知设置', icon: 'bell' },
    ],
  },
  {
    title: '独立大屏',
    items: [
      { href: '/sector-minute', label: '多标的分时对比', icon: 'activity', external: true },
      { href: '/capital', label: '资金流监控', icon: 'bar-chart', external: true },
      { href: '/f10', label: 'F10 个股资料', icon: 'database', external: true },
    ],
  },
]

function isActive(item) {
  if (item.external) return false
  if (item.exact) return route.path === item.to
  return route.path === item.to || route.path.startsWith(item.to + '/')
}

// ──────────────────────────────────────────────────────────────────────────────
// 侧边栏底部：原顶栏的状态信息（LIVE 心跳、抓取同步、时钟、主题切换）
// ──────────────────────────────────────────────────────────────────────────────

// 当前时钟（每秒滚动一次）
const clock = ref('')
let clockTimer = null
function tickClock() {
  const d = new Date()
  const p = (n) => String(n).padStart(2, '0')
  clock.value = `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())} ${p(d.getHours())}:${p(d.getMinutes())}:${p(d.getSeconds())}`
}

// 抓取状态（高频轮询 /api/monitor/status，独立于 /api/stats）
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
  tickClock()
  clockTimer = setInterval(tickClock, 1000)
  refreshMonitor()
  monitorTimer = setInterval(refreshMonitor, 10000)
})

onUnmounted(() => {
  clearInterval(clockTimer)
  if (monitorTimer) clearInterval(monitorTimer)
})
</script>

<template>
  <aside class="ff-sidebar" :class="mobile && 'ff-sidebar--mobile'">
    <div class="ff-sidebar__brand">
      <AppLogo mode="combined" :size="32" />
    </div>

    <div class="ff-sidebar__scroll">
      <nav class="ff-sidebar__nav" aria-label="主导航">
        <div v-for="grp in groups" :key="grp.title" class="ff-sidebar__group">
          <div class="ff-sidebar__group-title">{{ grp.title }}</div>
          <div class="ff-sidebar__group-items">
            <template v-for="item in grp.items" :key="item.to || item.href">
              <a
                v-if="item.external"
                :href="item.href"
                target="_blank"
                rel="noopener noreferrer"
                class="ff-sidebar__item ff-sidebar__item--external"
                :title="`${item.label}（在新标签页打开）`"
                @click="mobile && emit('close')"
              >
                <div class="ff-sidebar__icon-wrap">
                  <AppIcon :name="item.icon" size="md" />
                </div>
                <span class="ff-sidebar__label">{{ item.label }}</span>
                <AppIcon name="external-link" size="xs" class="ff-sidebar__ext-icon" />
              </a>

              <router-link
                v-else
                :to="item.to"
                class="ff-sidebar__item"
                :class="{ 'ff-sidebar__item--active': isActive(item) }"
                @click="mobile && emit('close')"
              >
                <div class="ff-sidebar__icon-wrap">
                  <AppIcon :name="item.icon" size="md" />
                </div>
                <span class="ff-sidebar__label">{{ item.label }}</span>
                <span
                  v-if="item.badge && item.badge.value > 0"
                  class="ff-sidebar__badge"
                >
                  {{ item.badge.value > 99 ? '99+' : item.badge.value }}
                </span>
              </router-link>
            </template>
          </div>
        </div>
      </nav>
    </div>

    <!-- 侧边栏底部：原顶栏状态信息 -->
    <div class="ff-sidebar__footer">
      <!-- SSE 实时心跳状态 -->
      <div class="ff-sidebar__live" :class="{ 'is-live': store.live }">
        <span class="ff-sidebar__radar-ring" v-if="store.live" />
        <span class="ff-sidebar__live-dot" />
        <span class="ff-sidebar__live-text">{{ store.live ? 'LIVE 实时推流' : '连接建立中…' }}</span>
      </div>

      <!-- 抓取状态 -->
      <div
        class="ff-sidebar__fetch"
        :class="monitor.offline_alert ? 'is-alert' : 'is-ok'"
        :title="monitor.offline_alert ? '超过阈值未成功抓取，系统可能离线' : '最近一次成功抓取时间'"
      >
        <AppIcon :name="monitor.offline_alert ? 'alert-triangle' : 'activity'" size="xs" />
        <span class="ff-sidebar__fetch-text">同步 {{ lastFetchText }}</span>
      </div>

      <!-- 时钟 + 主题切换 -->
      <div class="ff-sidebar__util-row">
        <div class="ff-sidebar__clock ff-num">
          <AppIcon name="clock" size="xs" class="ff-sidebar__clock-icon" />
          <span>{{ clock }}</span>
        </div>
        <AppButton
          variant="ghost"
          size="sm"
          :icon="store.theme === 'light' ? 'moon' : 'sun'"
          :title="store.theme === 'light' ? '切换暗色模式' : '切换亮色模式'"
          class="ff-sidebar__theme-btn"
          @click="store.toggleTheme()"
        />
      </div>
    </div>

  </aside>
</template>

<style scoped>
.ff-sidebar {
  width: var(--ff-sidebar-w);
  flex-shrink: 0;
  background: var(--ff-glass-bg);
  backdrop-filter: var(--ff-glass-blur);
  -webkit-backdrop-filter: var(--ff-glass-blur);
  border-right: 1px solid var(--ff-border);
  display: flex;
  flex-direction: column;
  height: 100%;
  user-select: none;
  transition: width var(--ff-dur-base) var(--ff-ease-standard);
  z-index: var(--ff-z-raised);
}

.ff-sidebar__brand {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: var(--ff-space-4) var(--ff-space-5);
  border-bottom: 1px solid var(--ff-border-subtle);
  height: var(--ff-topbar-h);
}

.ff-sidebar__scroll {
  flex: 1 1 auto;
  overflow-y: auto;
  padding: var(--ff-space-3) 0;
}

.ff-sidebar__nav {
  display: flex;
  flex-direction: column;
  gap: var(--ff-space-4);
  padding: 0 var(--ff-space-3);
}

.ff-sidebar__group {
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.ff-sidebar__group-title {
  font-size: 11px;
  font-weight: 700;
  text-transform: uppercase;
  letter-spacing: 0.08em;
  color: var(--ff-text-tertiary);
  padding: var(--ff-space-1) var(--ff-space-3) var(--ff-space-1);
}

.ff-sidebar__group-items {
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.ff-sidebar__item {
  position: relative;
  display: flex;
  align-items: center;
  gap: var(--ff-space-3);
  padding: 8px 12px;
  border-radius: var(--ff-radius-md);
  color: var(--ff-text-secondary);
  font-size: 13.5px;
  font-weight: 500;
  line-height: 1;
  text-decoration: none;
  transition: background-color var(--ff-dur-fast) var(--ff-ease-standard), border-color var(--ff-dur-fast) var(--ff-ease-standard), color var(--ff-dur-fast) var(--ff-ease-standard), box-shadow var(--ff-dur-fast) var(--ff-ease-standard), transform var(--ff-dur-fast) var(--ff-ease-standard);
  outline: none;
}

.ff-sidebar__item:hover {
  background: var(--ff-bg-hover);
  color: var(--ff-text-primary);
}

.ff-sidebar__item:focus-visible {
  box-shadow: var(--ff-focus-ring);
}

.ff-sidebar__item--active {
  background: var(--ff-brand-subtle);
  color: var(--ff-brand-text);
  font-weight: 600;
}

.ff-sidebar__icon-wrap {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 20px;
  height: 20px;
  flex-shrink: 0;
  transition: transform var(--ff-dur-fast);
}

.ff-sidebar__item:hover .ff-sidebar__icon-wrap {
  transform: scale(1.08);
}

.ff-sidebar__label {
  flex: 1 1 auto;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.ff-sidebar__ext-icon {
  opacity: 0.4;
  transition: opacity var(--ff-dur-fast);
}
.ff-sidebar__item:hover .ff-sidebar__ext-icon {
  opacity: 0.9;
}

.ff-sidebar__badge {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  font-size: 11px;
  font-family: var(--ff-font-mono);
  font-weight: 700;
  min-width: 18px;
  height: 18px;
  padding: 0 5px;
  border-radius: var(--ff-radius-pill);
  background: var(--ff-up);
  color: var(--ff-up-fg);
  animation: ff-scale-in var(--ff-dur-fast) var(--ff-ease-spring);
}

/* ──────────────────────────────────────────────────────────────────────────
   侧边栏底部 footer（原顶栏状态信息）
   ────────────────────────────────────────────────────────────────────────── */

.ff-sidebar__footer {
  flex-shrink: 0;
  display: flex;
  flex-direction: column;
  gap: 6px;
  padding: var(--ff-space-3) var(--ff-space-4) var(--ff-space-4);
  border-top: 1px solid var(--ff-border-subtle);
  background: var(--ff-glass-bg);
  backdrop-filter: var(--ff-glass-blur);
  -webkit-backdrop-filter: var(--ff-glass-blur);
}

/* SSE 实时心跳 */
.ff-sidebar__live {
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
  align-self: flex-start;
  max-width: 100%;
  transition: background-color var(--ff-dur-base) var(--ff-ease-standard), border-color var(--ff-dur-base) var(--ff-ease-standard), color var(--ff-dur-base) var(--ff-ease-standard), box-shadow var(--ff-dur-base) var(--ff-ease-standard), transform var(--ff-dur-base) var(--ff-ease-standard);
}

.ff-sidebar__live.is-live {
  background: var(--ff-down-subtle);
  border-color: var(--ff-down-border);
  color: var(--ff-down-text);
  box-shadow: 0 0 12px -2px rgba(16, 185, 129, 0.25);
}

.ff-sidebar__live-dot {
  width: 7px;
  height: 7px;
  border-radius: 50%;
  background: var(--ff-text-tertiary);
  flex-shrink: 0;
}

.ff-sidebar__live.is-live .ff-sidebar__live-dot {
  background: var(--ff-down);
}

.ff-sidebar__radar-ring {
  position: absolute;
  left: 8px;
  top: 50%;
  transform: translateY(-50%);
  width: 11px;
  height: 11px;
  border-radius: 50%;
  border: 1.5px solid var(--ff-down);
  animation: ff-sidebar-radar 2s cubic-bezier(0.2, 0.8, 0.2, 1) infinite;
  pointer-events: none;
}

@keyframes ff-sidebar-radar {
  0% {
    transform: translateY(-50%) scale(0.6);
    opacity: 1;
  }
  100% {
    transform: translateY(-50%) scale(2.2);
    opacity: 0;
  }
}

.ff-sidebar__live-text {
  letter-spacing: 0.03em;
  font-family: var(--ff-font-mono);
  font-size: 11.5px;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

/* 抓取状态 */
.ff-sidebar__fetch {
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
  align-self: flex-start;
  max-width: 100%;
  overflow: hidden;
  text-overflow: ellipsis;
}

.ff-sidebar__fetch.is-alert {
  background: var(--ff-up-subtle);
  border-color: var(--ff-up-border);
  color: var(--ff-up-text);
  animation: ff-pulse-ring 2s infinite;
}

.ff-sidebar__fetch-text {
  overflow: hidden;
  text-overflow: ellipsis;
}

/* 时钟 + 主题切换的横向工具行 */
.ff-sidebar__util-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--ff-space-2);
  margin-top: 2px;
}

.ff-sidebar__clock {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  font-size: 12px;
  color: var(--ff-text-secondary);
  font-family: var(--ff-font-mono);
  font-variant-numeric: tabular-nums;
  padding: 3px 8px;
  border-radius: var(--ff-radius-pill);
  background: var(--ff-bg-subtle);
  border: 1px solid var(--ff-border-subtle);
  white-space: nowrap;
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
}

.ff-sidebar__clock-icon {
  color: var(--ff-text-tertiary);
  flex-shrink: 0;
}

.ff-sidebar__theme-btn {
  flex-shrink: 0;
  border-radius: var(--ff-radius-md);
  transition: transform var(--ff-dur-fast);
}

.ff-sidebar__theme-btn:hover {
  transform: rotate(15deg);
}

/* 移动抽屉内同样启用 footer */
@media (max-width: 680px) {
  .ff-sidebar__clock {
    font-size: 11px;
  }
}
</style>
