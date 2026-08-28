<script setup>
// Zone D · 活动坞：任务状态 + 实时日志 + 最近任务，空闲收起 / 运行自动展开
import { watch, computed } from 'vue'
import AppIcon from '../../ui/AppIcon.vue'
import EasyTdxTaskStatus from './EasyTdxTaskStatus.vue'
import { useEasytdxStore } from '../../store/easytdx'
import { statusMeta } from '../../composables/useTaskRunner'

const store = useEasytdxStore()

// 运行中自动展开；成功后保持展开（除非已被固定/收起）
watch(
  () => store.running,
  (v) => {
    if (v) store.setDockOpen(true)
  },
)

const idleMeta = computed(() => {
  if (store.running) return statusMeta('running')
  if (store.task?.status === 'success') return statusMeta('success')
  if (store.task?.status === 'error') return statusMeta('error')
  return statusMeta('idle')
})

const dockHeight = computed(() => (store.ui.dockOpen ? 'min(320px, 40vh)' : '46px'))

function toggleDock() {
  store.setDockOpen(!store.ui.dockOpen)
}

function loadRecentTask(t) {
  store.loadTask(t.task_id)
  store.setDockOpen(true)
}
</script>

<template>
  <section class="etdx-dock" :style="{ height: dockHeight }">
    <!-- 状态条（折叠态） -->
    <div v-if="!store.ui.dockOpen" class="etdx-dock__bar" role="button" tabindex="0" @click="toggleDock">
      <span class="etdx-dock__dot" :class="'is-' + idleMeta.tone" />
      <span class="etdx-dock__label">{{ idleMeta.label }}</span>
      <span v-if="store.task && store.task.status === 'running'" class="etdx-dock__progress">
        {{ store.task.progress || 0 }}%
      </span>
      <span v-else-if="store.recent.length" class="etdx-dock__recent-count">
        最近 {{ store.recent.length }} 条
      </span>
      <AppIcon name="chevron-up" size="sm" class="etdx-dock__arrow" />
    </div>

    <!-- 展开态 -->
    <div v-else class="etdx-dock__open">
      <div class="etdx-dock__head">
        <span class="etdx-dock__title">
          <AppIcon name="list" size="sm" /> 执行状态与日志
        </span>
        <span v-if="store.recent.length" class="etdx-dock__hint">最近任务</span>
        <button type="button" class="etdx-dock__icon-btn ff-hit" title="收起" @click="toggleDock">
          <AppIcon name="chevron-down" size="sm" />
        </button>
      </div>

      <!-- 最近任务 -->
      <div v-if="store.recent.length" class="etdx-dock__recent">
        <button
          v-for="t in store.recent"
          :key="t.task_id"
          type="button"
          class="etdx-dock__chip"
          :title="t.function_id + ' · ' + t.status"
          @click="loadRecentTask(t)"
        >
          <span class="etdx-dock__chip-dot" :class="'is-' + statusMeta(t.status).tone" />
          <span class="etdx-dock__chip-name">{{ t.function_id }}</span>
          <span class="etdx-dock__chip-time">{{ (t.created_at || '').slice(5, 16) }}</span>
        </button>
      </div>

      <div class="etdx-dock__body">
        <EasyTdxTaskStatus />
      </div>
    </div>
  </section>
</template>

<style scoped>
.etdx-dock {
  flex-shrink: 0;
  background: var(--ff-bg-surface);
  border: 1px solid var(--ff-border-subtle);
  border-radius: var(--ff-radius-lg);
  overflow: hidden;
  transition: height 200ms var(--ff-ease-decelerate);
  display: flex;
  flex-direction: column;
}
.etdx-dock__bar {
  display: flex;
  align-items: center;
  gap: var(--ff-space-2);
  height: 46px;
  padding: 0 var(--ff-space-4);
  cursor: pointer;
  user-select: none;
  transition: background var(--ff-dur-fast);
}
.etdx-dock__bar:hover {
  background: var(--ff-bg-hover);
}
.etdx-dock__dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  flex-shrink: 0;
}
.etdx-dock__dot.is-running { background: var(--ff-brand); animation: etdx-pulse 1.2s ease-in-out infinite; }
.etdx-dock__dot.is-done { background: var(--ff-up); }
.etdx-dock__dot.is-error { background: var(--ff-down); }
.etdx-dock__dot.is-idle { background: var(--ff-text-tertiary); }
@keyframes etdx-pulse {
  0%, 100% { opacity: 1; }
  50% { opacity: 0.35; }
}
.etdx-dock__label {
  font-size: var(--ff-fs-body-sm);
  font-weight: 600;
  color: var(--ff-text-secondary);
}
.etdx-dock__progress {
  margin-left: auto;
  font-size: var(--ff-fs-caption);
  font-weight: 600;
  color: var(--ff-text-brand);
  font-variant-numeric: tabular-nums;
}
.etdx-dock__recent-count {
  margin-left: auto;
  font-size: var(--ff-fs-caption);
  color: var(--ff-text-tertiary);
}
.etdx-dock__arrow {
  color: var(--ff-icon-muted);
}
.etdx-dock__open {
  display: flex;
  flex-direction: column;
  height: 100%;
  min-height: 0;
}
.etdx-dock__head {
  display: flex;
  align-items: center;
  gap: var(--ff-space-2);
  padding: var(--ff-space-2-5) var(--ff-space-4);
  border-bottom: 1px solid var(--ff-border-subtle);
  font-size: var(--ff-fs-body-sm);
  font-weight: 600;
  color: var(--ff-text-secondary);
}
.etdx-dock__hint {
  font-weight: 400;
  font-size: var(--ff-fs-caption);
  color: var(--ff-text-tertiary);
}
.etdx-dock__icon-btn {
  margin-left: auto;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 26px;
  height: 26px;
  border: none;
  border-radius: var(--ff-radius-sm);
  background: transparent;
  color: var(--ff-icon-muted);
  cursor: pointer;
}
.etdx-dock__icon-btn:hover {
  background: var(--ff-bg-hover);
  color: var(--ff-text-primary);
}
.etdx-dock__recent {
  display: flex;
  gap: 6px;
  overflow-x: auto;
  padding: var(--ff-space-2) var(--ff-space-4);
  border-bottom: 1px solid var(--ff-border-subtle);
}
.etdx-dock__chip {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 3px 10px;
  border: 1px solid var(--ff-border);
  border-radius: var(--ff-radius-pill);
  background: var(--ff-bg-surface);
  color: var(--ff-text-secondary);
  font-size: var(--ff-fs-caption);
  cursor: pointer;
  white-space: nowrap;
  transition: border-color var(--ff-dur-fast), color var(--ff-dur-fast);
}
.etdx-dock__chip:hover {
  border-color: var(--ff-border-brand);
  color: var(--ff-text-brand);
}
.etdx-dock__chip-dot {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  flex-shrink: 0;
}
.etdx-dock__chip-dot.is-running { background: var(--ff-brand); }
.etdx-dock__chip-dot.is-done { background: var(--ff-up); }
.etdx-dock__chip-dot.is-error { background: var(--ff-down); }
.etdx-dock__chip-dot.is-idle { background: var(--ff-text-tertiary); }
.etdx-dock__chip-name {
  max-width: 140px;
  overflow: hidden;
  text-overflow: ellipsis;
}
.etdx-dock__chip-time {
  color: var(--ff-text-tertiary);
  font-family: var(--ff-font-mono, monospace);
  font-size: 10.5px;
}
.etdx-dock__body {
  flex: 1;
  min-height: 0;
}
</style>
