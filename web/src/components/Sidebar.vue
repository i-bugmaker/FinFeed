<script setup>
import { computed } from 'vue'
import { useRoute } from 'vue-router'
import AppIcon from '../ui/AppIcon.vue'
import AppLogo from '../ui/AppLogo.vue'

const props = defineProps({
  mobile: { type: Boolean, default: false },
})

const emit = defineEmits(['close'])

const route = useRoute()

const nav = [
  { to: '/news', label: '新闻流', icon: 'newspaper' },
  { to: '/sentiment', label: '舆情', icon: 'chatter' },
  { to: '/calendar', label: '财经日历', icon: 'calendar' },
  { to: '/market', label: '行情', icon: 'trending-up' },
  { to: '/favorites', label: '收藏', icon: 'star' },
  { to: '/dashboard', label: '仪表盘', icon: 'dashboard' },
  { to: '/ai', label: 'AI 分析', icon: 'sparkles' },
]

const activeIndex = computed(() => nav.findIndex(item => route.path === item.to || route.path.startsWith(item.to + '/')))
</script>

<template>
  <aside class="ff-sidebar" :class="mobile && 'ff-sidebar--mobile'">
    <div class="ff-sidebar__brand">
      <AppLogo mode="combined" :size="34" />
    </div>

    <nav class="ff-sidebar__nav" aria-label="主导航">
      <router-link
        v-for="(item, idx) in nav"
        :key="item.to"
        :to="item.to"
        class="ff-sidebar__item"
        :class="activeIndex === idx && 'ff-sidebar__item--active'"
        @click="mobile && emit('close')"
      >
        <AppIcon
          :name="item.icon"
          :tone="activeIndex === idx ? 'brand' : 'muted'"
          size="md"
          class="ff-sidebar__icon"
        />
        <span class="ff-sidebar__label">{{ item.label }}</span>
      </router-link>
    </nav>

    <div class="ff-sidebar__footer">
      <div class="ff-sidebar__hint">
        <AppIcon name="broadcast" size="xs" tone="success" />
        <span>实时数据接入中</span>
      </div>
    </div>
  </aside>
</template>

<style scoped>
.ff-sidebar {
  width: var(--ff-sidebar-w);
  flex-shrink: 0;
  background: var(--ff-bg-surface);
  border-right: 1px solid var(--ff-border);
  display: flex;
  flex-direction: column;
  padding: var(--ff-space-5) 0 var(--ff-space-4);
  min-height: 100%;
}

.ff-sidebar__brand {
  display: flex;
  align-items: center;
  padding: 0 var(--ff-space-5) var(--ff-space-5);
}

.ff-sidebar__nav {
  display: flex;
  flex-direction: column;
  gap: var(--ff-space-1);
  padding: 0 var(--ff-space-3);
  flex: 1 1 auto;
}

.ff-sidebar__item {
  display: flex;
  align-items: center;
  gap: var(--ff-space-3);
  padding: var(--ff-space-3) var(--ff-space-4);
  border-radius: var(--ff-radius-md);
  color: var(--ff-text-secondary);
  font-size: var(--ff-fs-base);
  font-weight: 500;
  line-height: 1;
  text-decoration: none;
  transition: background var(--ff-dur-fast), color var(--ff-dur-fast);
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
  background: var(--ff-bg-brand-subtle);
  color: var(--ff-text-brand);
  font-weight: 600;
}

.ff-sidebar__icon {
  flex-shrink: 0;
}

.ff-sidebar__footer {
  padding: 0 var(--ff-space-4);
  margin-top: auto;
}

.ff-sidebar__hint {
  display: inline-flex;
  align-items: center;
  gap: var(--ff-space-2);
  padding: var(--ff-space-2) var(--ff-space-3);
  border-radius: var(--ff-radius-pill);
  background: var(--ff-bg-subtle);
  color: var(--ff-text-secondary);
  font-size: var(--ff-fs-xs);
  font-weight: 500;
}
</style>
