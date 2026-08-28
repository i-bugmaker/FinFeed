<script setup>
// 场景导航：六大工作场景 + 场景内功能快捷入口 + 功能搜索
import { computed } from 'vue'
import AppIcon from '../../ui/AppIcon.vue'

const props = defineProps({
  scenes: { type: Array, default: () => [] }, // [{ id, label, icon, funcIds:[...] }]
  functions: { type: Array, default: () => [] }, // 全量功能（来自 meta）
  activeView: { type: String, default: '' }, // 当前场景 id
  activeFuncId: { type: String, default: '' },
  query: { type: String, default: '' },
})
const emit = defineEmits(['view', 'select', 'update:query'])

const q = computed(() => props.query.trim().toLowerCase())

// 搜索命中：在所有功能中模糊匹配
const searchHits = computed(() => {
  if (!q.value) return []
  return props.functions
    .filter((f) => f.label.toLowerCase().includes(q.value) || f.id.toLowerCase().includes(q.value))
    .slice(0, 20)
})

// 当前场景下功能列表
const sceneFuncs = computed(() => {
  const scene = props.scenes.find((s) => s.id === props.activeView)
  if (!scene) return []
  const set = new Set(scene.funcIds || [])
  return props.functions.filter((f) => set.has(f.id))
})

function funcTag(func) {
  // 由功能 id 推断分组标签
  if (func.id.startsWith('mac_')) return 'Mac'
  if (func.id.startsWith('cninfo_')) return '巨潮'
  if (func.id.startsWith('ex_')) return '扩展'
  if (func.id.startsWith('chanlun')) return '缠论'
  if (func.id.startsWith('backtest')) return '回测'
  return 'TDX'
}

function onSceneClick(scene) {
  if (scene.id === props.activeView) return
  emit('view', scene.id)
}
</script>

<template>
  <nav class="etdx-nav" aria-label="easy-tdx 功能导航">
    <!-- 搜索 -->
    <div class="etdx-nav__search">
      <AppIcon name="search" size="sm" class="etdx-nav__search-icon" />
      <input
        :value="query"
        class="etdx-nav__search-input"
        placeholder="搜索功能…"
        @input="emit('update:query', $event.target.value)"
      />
      <AppIcon v-if="query" name="x" size="xs" class="etdx-nav__search-clear" @click="emit('update:query', '')" />
    </div>

    <!-- 搜索命中结果 -->
    <div v-if="searchHits.length" class="etdx-nav__hits">
      <p class="etdx-nav__hits-title">搜索结果 · {{ searchHits.length }}</p>
      <ul class="etdx-nav__list">
        <li v-for="f in searchHits" :key="f.id">
          <button
            type="button"
            class="etdx-nav__item"
            :class="activeFuncId === f.id && 'etdx-nav__item--active'"
            @click="emit('select', f.id)"
          >
            <span class="etdx-nav__item-label">{{ f.label }}</span>
            <span class="etdx-nav__item-tag">{{ funcTag(f) }}</span>
          </button>
        </li>
      </ul>
    </div>

    <!-- 场景导航 -->
    <template v-else>
      <p class="etdx-nav__group-head etdx-nav__group-head--scenes">功能场景</p>
      <div class="etdx-nav__scenes">
        <button
          v-for="scene in scenes"
          :key="scene.id"
          type="button"
          class="etdx-nav__scene"
          :class="activeView === scene.id && 'etdx-nav__scene--active'"
          @click="onSceneClick(scene)"
        >
          <span class="etdx-nav__scene-icon ff-hit"><AppIcon :name="scene.icon" size="sm" /></span>
          <span class="etdx-nav__scene-label">{{ scene.label }}</span>
          <span class="etdx-nav__scene-count">{{ scene.funcIds?.length || 0 }}</span>
        </button>
      </div>

      <!-- 当前场景功能 -->
      <p v-if="sceneFuncs.length" class="etdx-nav__group-head">
        {{ scenes.find((s) => s.id === activeView)?.label || '功能' }}
      </p>
      <ul class="etdx-nav__list">
        <li v-for="f in sceneFuncs" :key="f.id">
          <button
            type="button"
            class="etdx-nav__item"
            :class="activeFuncId === f.id && 'etdx-nav__item--active'"
            @click="emit('select', f.id)"
          >
            <span class="etdx-nav__item-label">{{ f.label }}</span>
            <span class="etdx-nav__item-tag">{{ funcTag(f) }}</span>
          </button>
        </li>
      </ul>
    </template>
  </nav>
</template>

<style scoped>
.etdx-nav {
  display: flex;
  flex-direction: column;
  gap: 8px;
}
.etdx-nav__search {
  position: relative;
  display: flex;
  align-items: center;
}
.etdx-nav__search-icon {
  position: absolute;
  left: 10px;
  color: var(--ff-icon-muted);
  pointer-events: none;
}
.etdx-nav__search-input {
  width: 100%;
  height: 34px;
  padding: 0 30px 0 32px;
  border: 1px solid var(--ff-border);
  border-radius: var(--ff-radius-md);
  background: var(--ff-bg-surface);
  font-size: var(--ff-fs-body-sm);
  color: var(--ff-text-primary);
  outline: none;
  transition: border-color var(--ff-dur-fast), box-shadow var(--ff-dur-fast);
}
.etdx-nav__search-input:focus {
  border-color: var(--ff-border-brand);
  box-shadow: var(--ff-focus-ring);
}
.etdx-nav__search-clear {
  position: absolute;
  right: 10px;
  color: var(--ff-icon-muted);
  cursor: pointer;
}
.etdx-nav__group-head {
  margin: 4px 4px 0;
  font-size: 11px;
  font-weight: 600;
  letter-spacing: 0.08em;
  color: var(--ff-text-tertiary);
}
.etdx-nav__group-head--scenes {
  margin-top: 8px;
}
.etdx-nav__hits-title {
  margin: 4px 4px 0;
  font-size: 11px;
  font-weight: 600;
  letter-spacing: 0.06em;
  color: var(--ff-text-tertiary);
}
.etdx-nav__scenes {
  display: flex;
  flex-direction: column;
  gap: 2px;
}
.etdx-nav__scene {
  display: flex;
  align-items: center;
  gap: 9px;
  width: 100%;
  padding: 7px 9px;
  border-radius: var(--ff-radius-md);
  text-align: left;
  transition: background var(--ff-dur-fast);
}
.etdx-nav__scene:hover {
  background: var(--ff-bg-hover);
}
.etdx-nav__scene--active {
  background: var(--ff-bg-brand-subtle);
}
.etdx-nav__scene-icon {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 28px;
  height: 28px;
  flex: none;
  border-radius: 8px;
  background: var(--ff-bg-subtle);
  color: var(--ff-icon-muted);
  transition: background var(--ff-dur-fast), color var(--ff-dur-fast);
}
.etdx-nav__scene--active .etdx-nav__scene-icon {
  background: var(--ff-bg-brand);
  color: var(--ff-bg-surface);
}
.etdx-nav__scene-label {
  flex: 1;
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  font-size: var(--ff-fs-body-sm);
  font-weight: 500;
  color: var(--ff-text-primary);
}
.etdx-nav__scene--active .etdx-nav__scene-label {
  color: var(--ff-text-brand);
  font-weight: 600;
}
.etdx-nav__scene-count {
  flex: none;
  padding: 0 7px;
  border-radius: var(--ff-radius-pill);
  background: var(--ff-bg-subtle);
  font-size: 10.5px;
  font-family: var(--ff-font-mono, monospace);
  color: var(--ff-text-tertiary);
}
.etdx-nav__scene--active .etdx-nav__scene-count {
  background: var(--ff-bg-surface);
  color: var(--ff-text-brand);
}
.etdx-nav__list {
  list-style: none;
  display: flex;
  flex-direction: column;
  gap: 1px;
}
.etdx-nav__item {
  display: flex;
  align-items: center;
  gap: 8px;
  width: 100%;
  padding: 6px 10px;
  border-radius: var(--ff-radius-sm);
  text-align: left;
  transition: background var(--ff-dur-fast);
}
.etdx-nav__item:hover {
  background: var(--ff-bg-hover);
}
.etdx-nav__item--active {
  background: var(--ff-bg-brand-subtle);
}
.etdx-nav__item-label {
  flex: 1;
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  font-size: var(--ff-fs-body-sm);
  color: var(--ff-text-secondary);
}
.etdx-nav__item--active .etdx-nav__item-label {
  color: var(--ff-text-brand);
  font-weight: 600;
}
.etdx-nav__item-tag {
  flex: none;
  font-size: 10px;
  font-weight: 600;
  padding: 0 6px;
  border-radius: 4px;
  background: var(--ff-bg-subtle);
  color: var(--ff-text-tertiary);
  letter-spacing: 0.02em;
}
</style>
