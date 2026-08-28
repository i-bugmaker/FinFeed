<script setup>
import { ref, watch, nextTick, onBeforeUnmount } from 'vue'
import AppIcon from '../../ui/AppIcon.vue'
import { searchStocks } from './stockNames'

const props = defineProps({
  stock: { type: Object, default: null }, // { market, code, name }
  placeholder: { type: String, default: '输入股票名称 / 代码，如：茅台、600519' },
})
const emit = defineEmits(['select', 'clear'])

const q = ref('')
const results = ref([])
const open = ref(false)
const loading = ref(false)
const focused = ref(false)
const inputRef = ref(null)
const triggerRef = ref(null)
const menuRef = ref(null)
let debounceTimer = null

defineExpose({ focus: () => inputRef.value?.focus() })

watch(q, (val) => {
  if (debounceTimer) clearTimeout(debounceTimer)
  if (!val.trim()) {
    results.value = []
    open.value = false
    return
  }
  loading.value = true
  debounceTimer = setTimeout(async () => {
    results.value = await searchStocks(val.trim(), 8)
    loading.value = false
    open.value = true
    nextTick(positionMenu)
  }, 120)
})

// 下拉菜单定位：跟随输入框，避免 Teleport 后落在视口默认位置
function positionMenu() {
  if (!triggerRef.value || !menuRef.value) return
  const rect = triggerRef.value.getBoundingClientRect()
  const menu = menuRef.value
  const vw = document.documentElement.clientWidth
  const margin = 8
  const menuW = Math.min(rect.width, vw - margin * 2)
  menu.style.width = `${menuW}px`
  menu.style.top = `${rect.bottom + 6}px`
  const left = Math.min(Math.max(margin, rect.left), vw - margin - menuW)
  menu.style.left = `${left}px`
}

watch(open, (v) => {
  if (v) {
    nextTick(positionMenu)
    window.addEventListener('resize', positionMenu)
    window.addEventListener('scroll', positionMenu, true)
  } else {
    window.removeEventListener('resize', positionMenu)
    window.removeEventListener('scroll', positionMenu, true)
  }
})

function select(s) {
  emit('select', s)
  q.value = ''
  results.value = []
  open.value = false
}

function clear() {
  emit('clear')
  q.value = ''
}

function onBlur() {
  focused.value = false
  setTimeout(() => {
    open.value = false
  }, 150)
}

onBeforeUnmount(() => {
  if (debounceTimer) clearTimeout(debounceTimer)
  window.removeEventListener('resize', positionMenu)
  window.removeEventListener('scroll', positionMenu, true)
})
</script>

<template>
  <div class="etdx-picker" :class="{ 'is-focused': focused }">
    <!-- 已选标的徽章 -->
    <div v-if="stock" class="etdx-picker__chip">
      <span class="etdx-picker__chip-name">{{ stock.name }}</span>
      <span class="etdx-picker__chip-code">{{ stock.code }}.{{ stock.market }}</span>
      <button type="button" class="etdx-picker__chip-x ff-hit" title="清除标的" @click="clear">
        <AppIcon name="x" size="xs" />
      </button>
    </div>

    <!-- 搜索框 -->
    <div ref="triggerRef" v-else class="etdx-picker__input">
      <AppIcon name="search" size="sm" class="etdx-picker__icon" />
      <input
        ref="inputRef"
        v-model="q"
        type="text"
        class="etdx-picker__field"
        :placeholder="placeholder"
        autocomplete="off"
        @focus="focused = true"
        @blur="onBlur"
      />
      <AppIcon
        v-if="loading"
        name="refresh"
        size="sm"
        spin
        class="etdx-picker__icon etdx-picker__icon--spin"
      />
    </div>

    <!-- 下拉 -->
    <Teleport to="body">
      <Transition name="ff-pop">
        <ul v-if="open && results.length" ref="menuRef" class="etdx-picker__menu" role="listbox">
          <li
            v-for="s in results"
            :key="s.code + s.market"
            class="etdx-picker__item"
            role="option"
            @mousedown.prevent="select(s)"
          >
            <span class="etdx-picker__item-name">{{ s.name }}</span>
            <span class="etdx-picker__item-code">{{ s.code }}.{{ s.market }}</span>
          </li>
        </ul>
        <div v-else-if="open && !results.length && q.trim()" class="etdx-picker__empty">无匹配股票</div>
      </Transition>
    </Teleport>
  </div>
</template>

<style scoped>
.etdx-picker {
  position: relative;
  min-width: 280px;
}
.etdx-picker__chip {
  display: inline-flex;
  align-items: center;
  gap: var(--ff-space-2);
  padding: 6px 8px 6px 12px;
  background: var(--ff-bg-brand-subtle);
  border: 1px solid var(--ff-border-brand-subtle);
  border-radius: var(--ff-radius-pill);
  font-size: var(--ff-fs-body-sm);
  max-width: 100%;
}
.etdx-picker__chip-name {
  font-weight: 600;
  color: var(--ff-text-brand);
}
.etdx-picker__chip-code {
  color: var(--ff-text-secondary);
  font-family: var(--ff-font-mono, monospace);
  font-size: var(--ff-fs-caption);
}
.etdx-picker__chip-x {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 18px;
  height: 18px;
  padding: 0;
  border: none;
  border-radius: var(--ff-radius-xs);
  background: transparent;
  color: var(--ff-icon-muted);
  cursor: pointer;
}
.etdx-picker__chip-x:hover {
  background: var(--ff-bg-hover);
  color: var(--ff-text-primary);
}
.etdx-picker__input {
  position: relative;
  display: flex;
  align-items: center;
}
.etdx-picker__icon {
  position: absolute;
  left: 10px;
  color: var(--ff-icon-muted);
  pointer-events: none;
}
.etdx-picker__icon--spin {
  right: 10px;
  left: auto;
}
.etdx-picker__field {
  width: 100%;
  height: 38px;
  padding: 0 32px 0 34px;
  border: 1px solid var(--ff-border);
  border-radius: var(--ff-radius-md);
  background: var(--ff-bg-surface);
  color: var(--ff-text-primary);
  font-size: var(--ff-fs-body-sm);
  outline: none;
  transition: border-color var(--ff-dur-fast), box-shadow var(--ff-dur-fast);
}
.etdx-picker.is-focused .etdx-picker__field {
  border-color: var(--ff-border-brand);
  box-shadow: var(--ff-focus-ring);
}
.etdx-picker__menu {
  position: fixed;
  z-index: 300;
  list-style: none;
  margin: 6px 0 0;
  padding: var(--ff-space-1);
  background: var(--ff-bg-surface);
  border: 1px solid var(--ff-border);
  border-radius: var(--ff-radius-md);
  box-shadow: var(--ff-shadow-lg, 0 8px 24px rgba(0, 0, 0, 0.12));
  max-height: 320px;
  overflow-y: auto;
}
.etdx-picker__item {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--ff-space-3);
  padding: 8px 10px;
  border-radius: var(--ff-radius-sm);
  cursor: pointer;
}
.etdx-picker__item:hover {
  background: var(--ff-bg-hover);
}
.etdx-picker__item-name {
  font-size: var(--ff-fs-body-sm);
  color: var(--ff-text-primary);
}
.etdx-picker__item-code {
  font-size: var(--ff-fs-caption);
  color: var(--ff-text-tertiary);
  font-family: var(--ff-font-mono, monospace);
}
.etdx-picker__empty {
  padding: var(--ff-space-3);
  text-align: center;
  color: var(--ff-text-tertiary);
  font-size: var(--ff-fs-body-sm);
}
</style>
