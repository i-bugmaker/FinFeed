<script setup>
import { useRoute } from 'vue-router'

const route = useRoute()
const nav = [
  { to: '/news', label: '新闻流', icon: '📰' },
  { to: '/sentiment', label: '舆情', icon: '💬' },
  { to: '/calendar', label: '财经日历', icon: '📅' },
  { to: '/market', label: '行情', icon: '📈' },
  { to: '/favorites', label: '收藏', icon: '⭐' },
  { to: '/dashboard', label: '仪表盘', icon: '📊' },
  { to: '/ai', label: 'AI 分析', icon: '🤖' },
]
</script>

<template>
  <aside class="sidebar">
    <div class="brand">
      <span class="logo">FF</span>
      <span class="brand-name">FinFeed</span>
    </div>
    <nav class="nav">
      <router-link
        v-for="item in nav"
        :key="item.to"
        :to="item.to"
        class="nav-item"
        :class="{ active: route.path === item.to }"
      >
        <span class="ico">{{ item.icon }}</span>
        <span>{{ item.label }}</span>
      </router-link>
    </nav>
  </aside>
</template>

<style scoped>
.sidebar {
  width: var(--sidebar-w);
  flex-shrink: 0;
  background: var(--bg-surface);
  border-right: 1px solid var(--border);
  display: flex;
  flex-direction: column;
  padding: var(--sp-4) 0;
}
.brand {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 0 var(--sp-5) var(--sp-5);
}
.logo {
  width: 32px;
  height: 32px;
  border-radius: 9px;
  background: var(--primary);
  color: var(--primary-text);
  display: flex;
  align-items: center;
  justify-content: center;
  font-weight: 700;
  font-size: var(--fs-sm);
}
.brand-name {
  font-size: var(--fs-lg);
  font-weight: 700;
  letter-spacing: -0.3px;
}
.nav {
  display: flex;
  flex-direction: column;
  gap: 2px;
  padding: 0 var(--sp-3);
  flex: 1;
}
.nav-item {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 11px 14px;
  border-radius: var(--r-sm);
  color: var(--text-2);
  font-size: var(--fs-base);
  font-weight: 500;
  transition: 0.15s;
}
.nav-item:hover {
  background: var(--bg-hover);
  color: var(--text-1);
}
.nav-item.active {
  background: var(--primary-subtle);
  color: var(--primary);
  font-weight: 600;
}
.ico {
  font-size: var(--fs-md);
  width: 22px;
  text-align: center;
}
</style>
