<script setup>
/**
 * CommandPalette — 全局命令面板（Ctrl+K）
 * 键盘流用户的效率入口：页面跳转、生成复盘、打开最近报告、切换视图。
 */
import { ref, computed, watch, onMounted, onBeforeUnmount } from 'vue'
import { useRouter } from 'vue-router'
import { useAiStore } from '../../store/ai'
import AppIcon from '../../ui/AppIcon.vue'

const props = defineProps({
  open: { type: Boolean, default: false },
  reports: { type: Array, default: () => [] },
  modelAvailable: { type: Boolean, default: false },
})
const emit = defineEmits(['close', 'generate'])

const router = useRouter()
const store = useAiStore()
const q = ref('')
const inputEl = ref(null)
const sel = ref(0)

const COMMANDS = [
  { id: 'workbench', label: '打开投研工作台', icon: 'dashboard', group: '页面', action: () => router.push('/ai') },
  { id: 'analyst', label: '打开分析师工作区', icon: 'chatter', group: '页面', action: () => router.push('/ai/analyst') },
  { id: 'reports', label: '打开研究报告', icon: 'file-text', group: '页面', action: () => router.push('/ai/reports') },
  { id: 'tasks', label: '打开任务中心', icon: 'activity', group: '页面', action: () => router.push('/ai/tasks') },
  { id: 'settings', label: '打开 AI 设置', icon: 'settings', group: '页面', action: () => router.push('/ai/settings') },
  { id: 'gen', label: '生成每日复盘报告', icon: 'zap', group: '动作', action: () => emit('generate') },
]

const results = computed(() => {
  const k = q.value.trim().toLowerCase()
  let list = COMMANDS
  if (k) list = COMMANDS.filter((c) => c.label.toLowerCase().includes(k))
  const reportHits = props.reports
    .filter((r) => !k || (r.title || '').toLowerCase().includes(k))
    .slice(0, 5)
    .map((r) => ({
      id: 'r' + r.id, label: r.title || '报告 #' + r.id, icon: 'file-text', group: '最近报告',
      action: () => router.push('/ai/reports/' + r.id),
    }))
  return [...list, ...reportHits]
})

watch(() => props.open, (v) => {
  if (v) {
    q.value = ''
    sel.value = 0
    setTimeout(() => inputEl.value?.focus(), 30)
  }
})

function run(item) {
  if (!item) return
  emit('close')
  item.action()
}

function onKey(e) {
  if (e.key === 'ArrowDown') { e.preventDefault(); sel.value = Math.min(sel.value + 1, results.value.length - 1) }
  else if (e.key === 'ArrowUp') { e.preventDefault(); sel.value = Math.max(sel.value - 1, 0) }
  else if (e.key === 'Enter') { run(results.value[sel.value]) }
  else if (e.key === 'Escape') { emit('close') }
}

const onDocKey = (e) => {
  // 全局 Ctrl/Cmd+K：打开命令面板
  if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 'k') {
    e.preventDefault()
    if (!props.open) {
      store.cmdOpen = true
    } else {
      store.cmdOpen = false
    }
  }
}
onMounted(() => document.addEventListener('keydown', onDocKey))
onBeforeUnmount(() => document.removeEventListener('keydown', onDocKey))
</script>

<template>
  <Teleport to="body">
    <Transition name="cp-fade">
      <div v-if="open" class="cp-mask" @click.self="emit('close')">
        <div class="cp-panel" @keydown="onKey">
          <div class="cp-input">
            <AppIcon name="search" size="md" />
            <input
              ref="inputEl"
              v-model="q"
              placeholder="输入命令或搜索最近报告…"
              @keydown="onKey"
            />
            <span class="cp-esc">ESC</span>
          </div>
          <div class="cp-list">
            <template v-if="results.length">
              <div v-for="(item, i) in results" :key="item.id" class="cp-item" :class="{ on: i === sel }" @mousedown.prevent="run(item)" @mouseenter="sel = i">
                <AppIcon :name="item.icon" size="sm" />
                <span class="cp-label">{{ item.label }}</span>
                <span class="cp-group">{{ item.group }}</span>
              </div>
            </template>
            <div v-else class="cp-none">无匹配结果</div>
          </div>
          <div class="cp-foot">
            <span><b>↑↓</b> 选择</span><span><b>↵</b> 执行</span><span><b>ESC</b> 关闭</span>
          </div>
        </div>
      </div>
    </Transition>
  </Teleport>
</template>

<style scoped>
.cp-mask { position: fixed; inset: 0; z-index: 1000; background: rgba(15, 25, 20, 0.35); display: flex; align-items: flex-start; justify-content: center; padding-top: 12vh; }
.cp-panel { width: 560px; max-width: calc(100vw - 32px); background: var(--ff-bg-surface, #fff); border-radius: 14px; box-shadow: 0 12px 40px rgba(10, 30, 22, 0.25); border: 1px solid var(--ff-border, #e5e7eb); overflow: hidden; }
.cp-input { display: flex; align-items: center; gap: 10px; padding: 14px 16px; border-bottom: 1px solid var(--ff-border, #e5e7eb); color: var(--ff-text-3, #9ca3af); }
.cp-input input { flex: 1; border: none; outline: none; font-size: 15px; background: none; color: var(--ff-text-primary, #1f2937); }
.cp-esc { font-size: 10px; color: var(--ff-text-3, #9ca3af); border: 1px solid var(--ff-border, #d1d5db); border-radius: 4px; padding: 1px 5px; }
.cp-list { max-height: 340px; overflow-y: auto; padding: 8px; }
.cp-item { display: flex; align-items: center; gap: 10px; padding: 9px 12px; border-radius: 9px; cursor: pointer; }
.cp-item.on { background: var(--ff-bg-brand-subtle, #eaf4ef); }
.cp-item.on .cp-label { color: var(--ff-brand-dark, #1d4e39); }
.cp-item .cp-label { flex: 1; font-size: 13.5px; color: var(--ff-text-primary, #1f2937); }
.cp-group { font-size: 11px; color: var(--ff-text-3, #9ca3af); }
.cp-none { padding: 28px; text-align: center; color: var(--ff-text-3, #9ca3af); font-size: 13px; }
.cp-foot { display: flex; gap: 16px; padding: 9px 16px; border-top: 1px solid var(--ff-border, #e5e7eb); font-size: 11.5px; color: var(--ff-text-3, #9ca3af); background: var(--ff-bg-subtle, #f9fafb); }
.cp-foot b { font-family: var(--ff-font-mono, ui-monospace, monospace); }
.cp-fade-enter-active, .cp-fade-leave-active { transition: opacity 150ms, transform 150ms; }
.cp-fade-enter-from, .cp-fade-leave-to { opacity: 0; transform: translateY(-8px); }
</style>
