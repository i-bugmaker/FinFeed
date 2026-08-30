<script setup>
// 顶栏精简为仅承载移动端「展开菜单」按钮。
// 原来的 LIVE 心跳 / 抓取同步 / 时钟 / 主题切换 已迁移至侧边栏底部（Sidebar.vue）。
import { useAppStore } from '../store/app'
import AppButton from '../ui/AppButton.vue'

const store = useAppStore()
const emit = defineEmits(['menu'])
</script>

<template>
  <header class="ff-topbar ff-glass">
    <!-- 移动端菜单触发器：仅在 <1024px 显示；桌面端由侧边栏常年可见 -->
    <AppButton
      class="ff-topbar__menu"
      variant="ghost"
      size="sm"
      icon="menu"
      :aria-label="'展开菜单'"
      @click="emit('menu')"
    />
  </header>
</template>

<style scoped>
.ff-topbar {
  height: var(--ff-topbar-h);
  flex-shrink: 0;
  border-bottom: 1px solid var(--ff-border);
  display: flex;
  align-items: center;
  padding: 0 var(--ff-space-4);
  gap: var(--ff-space-3);
  position: sticky;
  top: 0;
  z-index: var(--ff-z-sticky);
}

.ff-topbar__menu {
  display: inline-flex;
}

@media (min-width: 1024px) {
  /* 桌面端顶栏已无内容（仅在 <1024px 承载抽屉触发器），整条隐藏以释放顶部空隙 */
  .ff-topbar {
    display: none;
  }
}
</style>
