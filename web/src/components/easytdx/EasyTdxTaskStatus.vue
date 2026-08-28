<script setup>
import { ref, watch, nextTick, computed } from 'vue'
import AppIcon from '../../ui/AppIcon.vue'

const props = defineProps({
  task: { type: Object, default: null },
})

const logEl = ref(null)

const statusMeta = computed(() => {
  const s = props.task?.status
  if (s === 'success') return { label: '已完成', cls: 'is-done', icon: 'check-circle' }
  if (s === 'error') return { label: '失败', cls: 'is-error', icon: 'alert-circle' }
  if (s === 'running') return { label: '执行中', cls: 'is-running', icon: 'refresh' }
  return { label: '空闲', cls: 'is-idle', icon: 'dot' }
})

const logs = computed(() => props.task?.logs || [])

// 日志级别 → 中文
const LEVEL_LABELS = { DEBUG: '调试', INFO: '信息', WARNING: '警告', ERROR: '错误', CRITICAL: '致命' }
function levelLabel(level) {
  return LEVEL_LABELS[level] || '信息'
}

watch(
  () => logs.value.length,
  async () => {
    await nextTick()
    if (logEl.value) logEl.value.scrollTop = logEl.value.scrollHeight
  },
)
</script>

<template>
  <div class="etdx-status">
    <div class="etdx-status__top">
      <span class="etdx-status__badge" :class="statusMeta.cls">
        <AppIcon :name="statusMeta.icon" size="sm" :spin="statusMeta.cls.includes('running')" />
        {{ statusMeta.label }}
      </span>
      <span v-if="task" class="etdx-status__pct">{{ task.progress || 0 }}%</span>
    </div>

    <div v-if="task && task.status === 'running'" class="etdx-status__bar">
      <div class="etdx-status__bar-fill" :style="{ width: (task.progress || 0) + '%' }" />
    </div>

    <div v-if="task && task.error" class="etdx-status__error">
      <AppIcon name="alert-triangle" size="sm" />
      <span>{{ task.error }}</span>
    </div>

    <div ref="logEl" class="etdx-status__logs" :class="{ 'is-empty': !logs.length }">
      <p v-if="!logs.length" class="etdx-status__logs-empty">暂无日志输出</p>
      <div
        v-for="(l, i) in logs"
        :key="i"
        class="etdx-status__log"
        :class="'lvl-' + (l.level || 'INFO').toLowerCase()"
      >
        <span class="etdx-status__log-level">{{ levelLabel(l.level) }}</span>
        <span class="etdx-status__log-msg">{{ l.msg }}</span>
      </div>
    </div>
  </div>
</template>

<style scoped>
.etdx-status {
  display: flex;
  flex-direction: column;
  gap: var(--ff-space-2);
  padding: var(--ff-space-3);
  height: 100%;
}
.etdx-status__top {
  display: flex;
  align-items: center;
  gap: var(--ff-space-3);
}
.etdx-status__badge {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 2px 10px;
  border-radius: var(--ff-radius-pill);
  font-size: var(--ff-fs-caption);
  font-weight: 600;
}
.etdx-status__badge.is-done {
  background: var(--ff-bg-up-subtle);
  color: var(--ff-up-text);
}
.etdx-status__badge.is-error {
  background: var(--ff-bg-down-subtle);
  color: var(--ff-down-text);
}
.etdx-status__badge.is-running {
  background: var(--ff-bg-brand-subtle);
  color: var(--ff-text-brand);
}
.etdx-status__badge.is-idle {
  background: var(--ff-bg-subtle);
  color: var(--ff-text-tertiary);
}
.etdx-status__pct {
  margin-left: auto;
  font-variant-numeric: tabular-nums;
  font-weight: 600;
  color: var(--ff-text-secondary);
}
.etdx-status__bar {
  height: 6px;
  border-radius: var(--ff-radius-pill);
  background: var(--ff-bg-subtle);
  overflow: hidden;
}
.etdx-status__bar-fill {
  height: 100%;
  background: var(--ff-brand-text);
  transition: width 0.4s var(--ff-ease-standard);
}
.etdx-status__error {
  display: flex;
  align-items: flex-start;
  gap: 6px;
  padding: var(--ff-space-2) var(--ff-space-3);
  background: var(--ff-bg-down-subtle);
  color: var(--ff-down-text);
  border-radius: var(--ff-radius-sm);
  font-size: var(--ff-fs-body-sm);
}
.etdx-status__logs {
  flex: 1;
  overflow-y: auto;
  background: var(--ff-bg-code);
  border-radius: var(--ff-radius-md);
  padding: var(--ff-space-2) var(--ff-space-3);
  font-family: var(--ff-font-mono, monospace);
  font-size: var(--ff-fs-caption);
  line-height: 1.6;
  min-height: 120px;
}
.etdx-status__logs.is-empty {
  display: flex;
  align-items: center;
  justify-content: center;
}
.etdx-status__logs-empty {
  color: #6b7785;
  margin: 0;
}
.etdx-status__log {
  display: flex;
  gap: var(--ff-space-2);
  white-space: pre-wrap;
  word-break: break-all;
}
.etdx-status__log-level {
  flex-shrink: 0;
  font-weight: 600;
  width: 52px;
}
.etdx-status__log.lvl-info .etdx-status__log-level {
  color: #7fb3ff;
}
.etdx-status__log.lvl-warning .etdx-status__log-level {
  color: #f0c040;
}
.etdx-status__log.lvl-error .etdx-status__log-level {
  color: var(--ff-up);
}
.etdx-status__log-msg {
  color: #c5d0db;
  flex: 1;
}
</style>
