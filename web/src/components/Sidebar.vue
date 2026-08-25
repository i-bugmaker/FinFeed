<script setup>
import { computed } from 'vue'
import { useRoute } from 'vue-router'
import { useAppStore } from '../store/app'
import AppIcon from '../ui/AppIcon.vue'
import AppLogo from '../ui/AppLogo.vue'

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
      { to: '/screener', label: '智能选股', icon: 'filter' },
      { to: '/easytdx', label: 'easy-tdx', icon: 'cpu' },
    ],
  },
  {
    title: '投研分析',
    items: [
      { to: '/dashboard', label: '仪表盘', icon: 'dashboard' },
      // AI 投研为可展开子菜单：进入 /ai 相关页面时自动展开
      {
        to: '/ai',
        label: 'AI 投研',
        icon: 'sparkles',
        submenu: true,
        children: [
          { to: '/ai', label: '投研工作台', icon: 'dashboard', exact: true },
          { to: '/ai/analyst', label: '分析师', icon: 'chatter' },
          { to: '/ai/reports', label: '研究报告', icon: 'file-text' },
          { to: '/ai/tasks', label: '任务中心', icon: 'activity' },
          { to: '/ai/settings', label: '设置', icon: 'settings' },
        ],
      },
      { to: '/favorites', label: '自选收藏', icon: 'star' },
    ],
  },
  {
    title: '独立大屏',
    items: [
      { href: '/sector-minute', label: '多标的分时对比', icon: 'activity', external: true },
      { href: '/capital', label: '资金流监控', icon: 'bar-chart', external: true },
    ],
  },
]

function isActive(item) {
  if (item.external) return false
  if (item.exact) return route.path === item.to
  return route.path === item.to || route.path.startsWith(item.to + '/')
}

// AI 投研子菜单：命中 /ai 前缀时自动展开
const aiExpanded = computed(() => route.path.startsWith('/ai'))
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

              <!-- 可展开子菜单（AI 投研）：父项 + 子项 -->
              <template v-else-if="item.submenu">
                <router-link
                  :to="item.to"
                  class="ff-sidebar__item ff-sidebar__item--submenu"
                  :class="{ 'ff-sidebar__item--active': isActive(item) }"
                  @click="mobile && emit('close')"
                >
                  <div class="ff-sidebar__icon-wrap">
                    <AppIcon :name="item.icon" size="md" />
                  </div>
                  <span class="ff-sidebar__label">{{ item.label }}</span>
                  <AppIcon :name="aiExpanded ? 'chevron-down' : 'chevron-right'" size="xs" class="ff-sidebar__caret" />
                </router-link>
                <div v-if="aiExpanded" class="ff-sidebar__children">
                  <router-link
                    v-for="c in item.children"
                    :key="c.to"
                    :to="c.to"
                    class="ff-sidebar__child"
                    :class="{ 'ff-sidebar__child--active': isActive(c) }"
                    @click="mobile && emit('close')"
                  >
                    <AppIcon :name="c.icon" size="xs" />
                    <span>{{ c.label }}</span>
                  </router-link>
                </div>
              </template>

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
  transition: all var(--ff-dur-fast) var(--ff-ease-standard);
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

.ff-sidebar__item--active::before {
  content: '';
  position: absolute;
  left: 0;
  top: 6px;
  bottom: 6px;
  width: 3px;
  border-radius: var(--ff-radius-pill);
  background: var(--ff-brand);
  box-shadow: 0 0 10px var(--ff-brand);
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

/* AI 投研子菜单 */
.ff-sidebar__caret {
  opacity: 0.45;
  margin-left: auto;
  transition: transform var(--ff-dur-fast);
}
.ff-sidebar__children {
  display: flex;
  flex-direction: column;
  gap: 2px;
  padding: 2px 0 6px 16px;
  margin-left: 15px;
  border-left: 1px solid var(--ff-border);
}
.ff-sidebar__child {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 6px 10px;
  border-radius: 8px;
  font-size: 12.5px;
  color: var(--ff-text-secondary);
  text-decoration: none;
  transition: background var(--ff-dur-fast), color var(--ff-dur-fast);
}
.ff-sidebar__child:hover {
  background: var(--ff-bg-hover);
  color: var(--ff-text-primary);
}
.ff-sidebar__child--active {
  background: var(--ff-bg-brand-subtle);
  color: var(--ff-brand-dark);
  font-weight: 600;
}
.ff-sidebar__child--active svg {
  color: var(--ff-icon-brand);
}
</style>
