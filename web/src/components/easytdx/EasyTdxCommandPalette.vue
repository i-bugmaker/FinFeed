<script setup>
// 命令面板：点击 CommandBar 搜索框唤起，输入即过滤，点击候选执行
import { ref, computed, watch, nextTick } from 'vue'
import AppIcon from '../../ui/AppIcon.vue'
import { useEasytdxStore } from '../../store/easytdx'
import { clientLabel } from './format'

const store = useEasytdxStore()
const q = ref('')
const inputRef = ref(null)

watch(
  () => store.ui.paletteOpen,
  async (v) => {
    if (v) {
      q.value = ''
      await nextTick()
      inputRef.value?.focus()
    }
  },
)

const results = computed(() => {
  const query = q.value.trim().toLowerCase()
  if (!query) return store.navGroups
  return store.navGroups
    .map((g) => ({
      ...g,
      items: g.items.filter(
        (f) => f.label.toLowerCase().includes(query) || f.id.toLowerCase().includes(query),
      ),
    }))
    .filter((g) => g.items.length)
})

const total = computed(() => results.value.reduce((n, g) => n + g.items.length, 0))

function run(id) {
  store.selectFunc(id)
  store.run()
  store.setPalette(false)
}

function select(id) {
  store.selectFunc(id)
  store.setPalette(false)
}
</script>

<template>
  <Teleport to="body">
    <Transition name="ff-overlay">
      <div class="etdx-palette" @click.self="store.setPalette(false)">
        <div class="etdx-palette__box">
          <div class="etdx-palette__search">
            <AppIcon name="search" size="md" class="etdx-palette__search-icon" />
            <input
              ref="inputRef"
              v-model="q"
              class="etdx-palette__input"
              placeholder="输入功能名称或 ID…"
              autocomplete="off"
            />
            <button
              type="button"
              class="etdx-palette__close ff-hit"
              aria-label="关闭"
              @click="store.setPalette(false)"
            >
              <AppIcon name="x" size="sm" />
            </button>
          </div>
          <div class="etdx-palette__hint">
            <span>{{ total }} 项匹配</span>
            <span>点击功能立即执行</span>
          </div>
          <div class="etdx-palette__body">
            <div v-for="g in results" :key="g.id" class="etdx-palette__group">
              <div class="etdx-palette__group-head">
                <AppIcon :name="g.icon" size="xs" /> {{ g.label }}
              </div>
              <div
                v-for="f in g.items"
                :key="f.id"
                class="etdx-palette__item"
                role="button"
                @click="run(f.id)"
              >
                <span class="etdx-palette__item-label">{{ f.label }}</span>
                <span class="etdx-palette__item-tag">{{ clientLabel(f.client) }}</span>
                <span class="etdx-palette__item-run">
                  <AppIcon name="play" size="xs" /> 执行
                </span>
              </div>
            </div>
            <div v-if="!total" class="etdx-palette__empty">无匹配功能</div>
          </div>
        </div>
      </div>
    </Transition>
  </Teleport>
</template>

<style scoped>
.etdx-palette {
  position: fixed;
  inset: 0;
  z-index: 1300;
  background: var(--ff-bg-overlay);
  backdrop-filter: blur(4px);
  display: flex;
  align-items: flex-start;
  justify-content: center;
  padding-top: 12vh;
}
.etdx-palette__box {
  width: min(560px, calc(100vw - 32px));
  max-height: 60vh;
  background: var(--ff-bg-surface-raised);
  border: 1px solid var(--ff-border);
  border-radius: var(--ff-radius-lg);
  box-shadow: var(--ff-shadow-xl);
  display: flex;
  flex-direction: column;
  overflow: hidden;
  animation: etdx-palette-in 200ms var(--ff-ease-decelerate);
}
@keyframes etdx-palette-in {
  from { opacity: 0; transform: translateY(-12px) scale(0.98); }
  to { opacity: 1; transform: translateY(0) scale(1); }
}
.etdx-palette__search {
  display: flex;
  align-items: center;
  gap: var(--ff-space-2);
  padding: var(--ff-space-3) var(--ff-space-4);
  border-bottom: 1px solid var(--ff-border-subtle);
}
.etdx-palette__search-icon {
  color: var(--ff-icon-muted);
}
.etdx-palette__input {
  flex: 1;
  border: none;
  outline: none;
  background: transparent;
  font-size: var(--ff-fs-body);
  color: var(--ff-text-primary);
}
.etdx-palette__close {
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
.etdx-palette__close:hover {
  background: var(--ff-bg-hover);
  color: var(--ff-text-primary);
}
.etdx-palette__hint {
  display: flex;
  justify-content: space-between;
  padding: var(--ff-space-2) var(--ff-space-4);
  font-size: var(--ff-fs-caption);
  color: var(--ff-text-tertiary);
  border-bottom: 1px solid var(--ff-border-subtle);
}
.etdx-palette__body {
  flex: 1;
  overflow-y: auto;
  padding: var(--ff-space-2);
}
.etdx-palette__group {
  margin-bottom: var(--ff-space-2);
}
.etdx-palette__group-head {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: var(--ff-space-1) var(--ff-space-2);
  font-size: var(--ff-fs-caption);
  font-weight: 700;
  color: var(--ff-text-secondary);
}
.etdx-palette__item {
  display: flex;
  align-items: center;
  gap: var(--ff-space-2);
  padding: 9px 12px;
  border-radius: var(--ff-radius-sm);
  cursor: pointer;
  transition: background var(--ff-dur-fast);
}
.etdx-palette__item:hover {
  background: var(--ff-bg-hover);
}
.etdx-palette__item-label {
  flex: 1;
  font-size: var(--ff-fs-body-sm);
  color: var(--ff-text-primary);
}
.etdx-palette__item-tag {
  font-size: var(--ff-fs-caption);
  color: var(--ff-text-tertiary);
  background: var(--ff-bg-subtle);
  border-radius: var(--ff-radius-pill);
  padding: 0 8px;
}
.etdx-palette__item-run {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  font-size: var(--ff-fs-caption);
  color: var(--ff-text-brand);
  opacity: 0;
  transition: opacity var(--ff-dur-fast);
}
.etdx-palette__item:hover .etdx-palette__item-run {
  opacity: 1;
}
.etdx-palette__empty {
  text-align: center;
  color: var(--ff-text-tertiary);
  padding: var(--ff-space-8);
  font-size: var(--ff-fs-body-sm);
}

/* ── 移动端适配（D4 · 根容器自适应）── */
@media (max-width: 768px) {
  .etdx-palette {
    max-width: 100%;
  }
  .etdx-palette > * {
    min-width: 0;
  }
}
</style>
