<script setup>
/**
 * TaskProgress — 分析任务阶段进度条
 * 将后端 stage 字段映射为「排队 → 采集 → 统计 → 压缩 → 成文 → 拼装」可视流程。
 */
import { computed } from 'vue'

const props = defineProps({
  task: { type: Object, default: null },
  compact: { type: Boolean, default: false },
})

// 阶段顺序（与后端 STAGE_LABELS 对齐）
const STAGES = ['queued', 'collect', 'stats', 'chunk', 'map', 'reduce', 'assemble', 'done']
const LABELS = {
  queued: '排队',
  collect: '检索',
  stats: '统计',
  chunk: '分批',
  map: '压缩',
  reduce: '成文',
  assemble: '拼装',
  done: '完成',
}

const stageIndex = computed(() => {
  const s = props.task?.stage
  const idx = STAGES.indexOf(s)
  return idx >= 0 ? idx : props.task?.status === 'success' ? STAGES.length - 1 : 0
})

const statusMeta = computed(() => {
  const t = props.task
  if (!t) return { tone: 'idle', text: '等待任务' }
  switch (t.status) {
    case 'pending': return { tone: 'run', text: t.message || '排队中' }
    case 'running': return { tone: 'run', text: t.message || '分析中' }
    case 'success': return { tone: 'ok', text: t.message || '已完成' }
    case 'failed': return { tone: 'err', text: t.error || t.message || '失败' }
    case 'cancelled': return { tone: 'idle', text: '已取消' }
    default: return { tone: 'idle', text: t.message || '' }
  }
})

const pct = computed(() => {
  const t = props.task
  if (!t) return 0
  if (t.status === 'failed' || t.status === 'cancelled') return 0 // 失败/取消不再显示满进度
  if (t.status === 'success') return 100
  const base = (stageIndex.value / (STAGES.length - 1)) * 100
  return Math.max(1, Math.min(99, Math.round(base + (t.progress || 0) * 0.4)))
})

const doneCount = computed(() => (props.task?.status === 'success' ? STAGES.length - 1 : stageIndex.value))
</script>

<template>
  <div v-if="task" class="tp" :class="`tp--${statusMeta.tone}`">
    <div class="tp__head">
      <span class="tp__msg">{{ statusMeta.text }}</span>
      <span class="tp__pct">{{ pct }}%</span>
    </div>
    <div class="tp__track">
      <span
        v-for="(s, i) in STAGES.filter((x) => x !== 'done')"
        :key="s"
        class="tp__seg"
        :class="{ on: i < doneCount, active: i === stageIndex && task.status === 'running' }"
      ></span>
    </div>
    <div v-if="!compact" class="tp__labels">
      <span
        v-for="(s, i) in STAGES.filter((x) => x !== 'done')"
        :key="s"
        class="tp__label"
        :class="{ on: i <= stageIndex }"
      >{{ LABELS[s] }}</span>
    </div>
  </div>
  <div v-else class="tp tp--idle">
    <div class="tp__head"><span class="tp__msg">暂无运行任务</span></div>
    <div class="tp__track"><span class="tp__seg"></span></div>
  </div>
</template>

<style scoped>
.tp { width: 100%; }
.tp__head { display: flex; align-items: center; justify-content: space-between; gap: 8px; font-size: 12.5px; margin-bottom: 6px; }
.tp__msg { color: var(--ff-text-secondary); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.tp__pct { font-family: var(--ff-font-mono, ui-monospace, monospace); font-weight: 600; color: var(--ff-text-primary); }
.tp--err .tp__msg { color: var(--ff-up); }
.tp--ok .tp__msg { color: var(--ff-down); }
.tp__track { display: flex; gap: 3px; height: 6px; }
.tp__seg { flex: 1; border-radius: 3px; background: var(--ff-bg-subtle); transition: background 300ms ease; }
.tp__seg.on { background: var(--ff-brand); }
.tp--run .tp__seg.active { background: var(--ff-brand-light); animation: tp-pulse 1.4s infinite ease-in-out; }
.tp--err .tp__seg.on { background: var(--ff-up); }
.tp__labels { display: flex; gap: 3px; margin-top: 5px; }
.tp__label { flex: 1; text-align: center; font-size: 10.5px; color: var(--ff-text-3); transition: color 200ms; }
.tp__label.on { color: var(--ff-text-secondary); font-weight: 600; }
@keyframes tp-pulse { 0%,100% { opacity: 1; } 50% { opacity: 0.45; } }
</style>
