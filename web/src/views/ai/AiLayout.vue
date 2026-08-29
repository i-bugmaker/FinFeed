<script setup>
/**
 * AiLayout — AI 分析模块布局容器
 * 顶部：模块页头（状态徽标 + 全局生成按钮）
 * 次导航：工作台 / 分析师 / 报告 / 任务 / 设置 五个子路由 Tab
 */
import { computed } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useAiStore } from '../../store/ai'
import AppIcon from '../../ui/AppIcon.vue'
import CommandPalette from '../../components/ai/CommandPalette.vue'

const route = useRoute()
const router = useRouter()
const store = useAiStore()

const NAVS = [
  { to: '/ai', label: '工作台', icon: 'dashboard', exact: true },
  { to: '/ai/analyst', label: '分析师', icon: 'chatter' },
  { to: '/ai/reports', label: '研究报告', icon: 'file-text' },
  { to: '/ai/tasks', label: '任务中心', icon: 'activity', badge: () => store.runningTasks.length },
  { to: '/ai/settings', label: '设置', icon: 'settings' },
]

const isActive = (n) => (n.exact ? route.path === n.to : route.path.startsWith(n.to))

const modelLabel = computed(() => {
  const dp = store.status?.default_provider
  if (!dp) return '未配置'
  return `${dp.name}${dp.model ? ' · ' + dp.model : ''}`
})

const commandOpen = computed({
  get: () => store.cmdOpen === true,
  set: (v) => { store.cmdOpen = v },
})
function openCmd() { store.cmdOpen = true }
</script>

<template>
  <div class="ail">
    <!-- 布局容器：Tab 导航已提供可视上下文，h1 供读屏与文档语义 -->
    <h1 class="ff-sr-only">AI 分析</h1>

    <nav class="ail__nav">
      <div class="ail__tabs">
        <router-link
          v-for="n in NAVS"
          :key="n.to"
          :to="n.to"
          class="ail__tab"
          :class="{ on: isActive(n) }"
        >
          <AppIcon :name="n.icon" size="sm" />
          <span>{{ n.label }}</span>
          <span v-if="n.badge && n.badge() > 0" class="ail__badge">{{ n.badge() }}</span>
        </router-link>
      </div>
      <div class="ail__right">
        <span class="ail__model" :title="modelLabel">
          <span class="ail__dot" :class="store.modelAvailable ? 'ok' : 'bad'"></span>
          {{ store.modelAvailable ? '模型可用' : '模型未配置' }}
          <span class="ail__model-name">{{ modelLabel }}</span>
        </span>
        <button class="ail__kbd" title="命令面板" @click="openCmd">
          <AppIcon name="command" size="sm" /> K
        </button>
      </div>
    </nav>

    <main class="ail__content">
      <router-view v-slot="{ Component }">
        <transition name="ff-page" mode="out-in">
          <component :is="Component" />
        </transition>
      </router-view>
    </main>

    <CommandPalette
      :open="commandOpen"
      :reports="store.reports"
      :model-available="store.modelAvailable"
      @close="store.cmdOpen = false"
      @generate="router.push('/ai/tasks')"
    />
  </div>
</template>

<style scoped>
.ail { max-width: var(--ff-container-max, 1400px); margin: 0 auto; padding: 0 24px 40px; display: flex; flex-direction: column; gap: 16px; }
.ail__top { display: flex; align-items: center; justify-content: space-between; gap: 16px; padding-top: 8px; }
.ail__right { display: flex; align-items: center; gap: 10px; flex-shrink: 0; }
.ail__model { display: inline-flex; align-items: center; gap: 7px; font-size: 12.5px; color: var(--ff-text-secondary); background: var(--ff-bg-surface); border: 1px solid var(--ff-border); border-radius: 20px; padding: 5px 13px; }
.ail__dot { width: 8px; height: 8px; border-radius: 50%; }
.ail__dot.ok { background: var(--ff-down); }
.ail__dot.bad { background: var(--ff-up); }
.ail__model-name { font-size: 11px; color: var(--ff-text-3); max-width: 220px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.ail__kbd { display: inline-flex; align-items: center; gap: 4px; border: 1px solid var(--ff-border); background: var(--ff-bg-surface); border-radius: 8px; padding: 5px 10px; font-size: 12px; font-weight: 600; color: var(--ff-text-2); cursor: pointer; transition: background-color var(--ff-dur-fast) var(--ff-ease-standard), border-color var(--ff-dur-fast) var(--ff-ease-standard), color var(--ff-dur-fast) var(--ff-ease-standard), box-shadow var(--ff-dur-fast) var(--ff-ease-standard), transform var(--ff-dur-fast) var(--ff-ease-standard); }
.ail__kbd:hover { border-color: var(--ff-brand); color: var(--ff-brand); }
.ail__nav { display: flex; align-items: center; justify-content: space-between; gap: 12px; background: var(--ff-bg-subtle); border-radius: 12px; padding: 4px 8px 4px 4px; border: 1px solid var(--ff-border); }
.ail__tabs { display: flex; gap: 4px; flex-wrap: nowrap; min-width: 0; overflow-x: auto; }
.ail__tab { display: inline-flex; align-items: center; gap: 6px; padding: 7px 16px; border-radius: 9px; font-size: 13.5px; font-weight: 600; color: var(--ff-text-2); text-decoration: none; transition: background-color var(--ff-dur-fast) var(--ff-ease-standard), border-color var(--ff-dur-fast) var(--ff-ease-standard), color var(--ff-dur-fast) var(--ff-ease-standard), box-shadow var(--ff-dur-fast) var(--ff-ease-standard), transform var(--ff-dur-fast) var(--ff-ease-standard); white-space: nowrap; }
.ail__tab:hover { color: var(--ff-text-primary); }
.ail__tab.on { background: var(--ff-bg-surface); color: var(--ff-brand-dark); box-shadow: 0 1px 4px rgba(16, 40, 30, 0.12); }
.ail__badge { min-width: 17px; height: 17px; padding: 0 5px; border-radius: 9px; background: var(--ff-brand); color: var(--ff-bg-surface); font-size: 10.5px; font-weight: 700; display: inline-flex; align-items: center; justify-content: center; }
.ail__content { min-height: 0; }

@media (max-width: 900px) {
  .ail { padding: 0 14px 30px; }
  .ail__model-name { display: none; }
  .ail__model { padding: 4px 10px; }
}
</style>
