<script setup>
// 自选股列表：localStorage 持久化，点击即切换全局标的
import { ref, watch, nextTick, onBeforeUnmount } from 'vue'
import AppIcon from '../../ui/AppIcon.vue'
import { searchStocks } from './stockNames'

const props = defineProps({
  stock: { type: Object, default: null }, // 当前全局标的 { market, code, name }
})
const emit = defineEmits(['select'])

const KEY = 'finfeed.easytdx.watchlist'
const DEFAULTS = [
  { name: '贵州茅台', code: '600519', market: 'SH' },
  { name: '五粮液', code: '000858', market: 'SZ' },
  { name: '宁德时代', code: '300750', market: 'SZ' },
  { name: '比亚迪', code: '002594', market: 'SZ' },
  { name: '东方财富', code: '300059', market: 'SZ' },
]

function load() {
  try {
    const raw = localStorage.getItem(KEY)
    const list = raw ? JSON.parse(raw) : null
    if (Array.isArray(list) && list.length) return list
  } catch { /* 降级用默认 */ }
  return DEFAULTS.slice()
}

const list = ref(load())
const adding = ref(false)
const q = ref('')
const results = ref([])
const open = ref(false)
const inputRef = ref(null)
let debounceTimer = null

function save() {
  try { localStorage.setItem(KEY, JSON.stringify(list.value)) } catch { /* 忽略 */ }
}

function isActive(s) {
  return !!props.stock && props.stock.code === s.code && props.stock.market === s.market
}

function pick(s) {
  emit('select', s)
  adding.value = false
  q.value = ''
  results.value = []
  open.value = false
}

function remove(s, e) {
  e.stopPropagation()
  list.value = list.value.filter((x) => !(x.code === s.code && x.market === s.market))
  save()
}

function startAdd() {
  adding.value = true
  nextTick(() => inputRef.value?.focus())
}

function cancelAdd() {
  adding.value = false
  q.value = ''
  results.value = []
  open.value = false
}

watch(q, (val) => {
  if (debounceTimer) clearTimeout(debounceTimer)
  if (!val.trim()) { results.value = []; open.value = false; return }
  debounceTimer = setTimeout(async () => {
    results.value = await searchStocks(val.trim(), 6)
    open.value = true
  }, 120)
})

function addResult(s) {
  if (!list.value.some((x) => x.code === s.code && x.market === s.market)) {
    list.value.push({ name: s.name, code: s.code, market: s.market })
    save()
  }
  pick(s)
}

onBeforeUnmount(() => {
  if (debounceTimer) clearTimeout(debounceTimer)
})
</script>

<template>
  <div class="etdx-watch">
    <div class="etdx-watch__head">
      <span class="etdx-watch__title">
        <AppIcon name="bookmark" size="sm" />
        自选股
      </span>
      <button v-if="!adding" type="button" class="etdx-watch__add" @click="startAdd">
        <AppIcon name="plus" size="xs" /> 添加
      </button>
    </div>

    <div class="etdx-watch__body">
      <!-- 添加模式 -->
      <div v-if="adding" class="etdx-watch__adder">
        <div class="etdx-watch__adder-input">
          <AppIcon name="search" size="sm" class="etdx-watch__adder-ico" />
          <input
            ref="inputRef"
            v-model="q"
            type="text"
            placeholder="名称 / 代码…"
            autocomplete="off"
            @keydown.esc="cancelAdd"
          />
        </div>
        <ul v-if="open && results.length" class="etdx-watch__menu">
          <li v-for="s in results" :key="s.market + s.code" @mousedown.prevent="addResult(s)">
            <span class="etdx-watch__menu-name">{{ s.name }}</span>
            <span class="etdx-watch__menu-code">{{ s.code }}.{{ s.market }}</span>
          </li>
        </ul>
        <div v-else-if="open && !results.length && q.trim()" class="etdx-watch__menu-empty">无匹配股票</div>
        <button v-if="adding" type="button" class="etdx-watch__cancel" title="取消" @click="cancelAdd">
          <AppIcon name="x" size="xs" />
        </button>
      </div>

      <!-- 列表 -->
      <ul class="etdx-watch__list">
        <li v-for="s in list" :key="s.market + s.code">
          <button
            type="button"
            class="etdx-watch__item"
            :class="{ 'is-active': isActive(s) }"
            @click="pick(s)"
          >
            <span class="etdx-watch__item-name">{{ s.name }}</span>
            <span class="etdx-watch__item-code">{{ s.code }}.{{ s.market }}</span>
            <span class="etdx-watch__item-x" title="移除" @click.stop="remove(s, $event)">
              <AppIcon name="x" size="xs" />
            </span>
          </button>
        </li>
      </ul>
    </div>
  </div>
</template>

<style scoped>
.etdx-watch {
  display: flex;
  flex-direction: column;
  gap: 8px;
}
.etdx-watch__head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 0 4px;
}
.etdx-watch__title {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  font-size: 11px;
  font-weight: 600;
  color: var(--ff-text-tertiary);
  letter-spacing: 0.08em;
}
.etdx-watch__add {
  display: inline-flex;
  align-items: center;
  gap: 3px;
  padding: 2px 8px;
  border-radius: var(--ff-radius-pill);
  font-size: 11.5px;
  font-weight: 600;
  color: var(--ff-text-brand);
  transition: background var(--ff-dur-fast);
}
.etdx-watch__add:hover {
  background: var(--ff-bg-brand-subtle);
}
.etdx-watch__body {
  position: relative;
}
.etdx-watch__adder {
  position: relative;
  display: flex;
  align-items: center;
  margin-bottom: 8px;
}
.etdx-watch__adder-input {
  position: relative;
  flex: 1;
  display: flex;
  align-items: center;
}
.etdx-watch__adder-ico {
  position: absolute;
  left: 10px;
  color: var(--ff-icon-muted);
  pointer-events: none;
}
.etdx-watch__adder-input input {
  width: 100%;
  height: 34px;
  padding: 0 10px 0 32px;
  border: 1px solid var(--ff-border);
  border-radius: var(--ff-radius-md);
  background: var(--ff-bg-surface);
  font-size: var(--ff-fs-body-sm);
  color: var(--ff-text-primary);
  outline: none;
  transition: border-color var(--ff-dur-fast), box-shadow var(--ff-dur-fast);
}
.etdx-watch__adder-input input:focus {
  border-color: var(--ff-border-brand);
  box-shadow: var(--ff-focus-ring);
}
.etdx-watch__cancel {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 28px;
  height: 28px;
  margin-left: 6px;
  flex: none;
  border-radius: var(--ff-radius-sm);
  color: var(--ff-icon-muted);
}
.etdx-watch__cancel:hover {
  background: var(--ff-bg-hover);
  color: var(--ff-text-primary);
}
.etdx-watch__menu {
  position: absolute;
  top: 38px;
  left: 0;
  right: 0;
  z-index: 30;
  list-style: none;
  padding: 4px;
  background: var(--ff-bg-surface);
  border: 1px solid var(--ff-border);
  border-radius: var(--ff-radius-md);
  box-shadow: var(--ff-shadow-lg, 0 8px 24px rgba(0, 0, 0, 0.12));
  max-height: 220px;
  overflow-y: auto;
}
.etdx-watch__menu li {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  padding: 7px 10px;
  border-radius: var(--ff-radius-sm);
  cursor: pointer;
  font-size: var(--ff-fs-body-sm);
}
.etdx-watch__menu li:hover {
  background: var(--ff-bg-hover);
}
.etdx-watch__menu-name {
  color: var(--ff-text-primary);
  font-weight: 500;
}
.etdx-watch__menu-code {
  color: var(--ff-text-tertiary);
  font-family: var(--ff-font-mono, monospace);
  font-size: var(--ff-fs-caption);
}
.etdx-watch__menu-empty {
  padding: 8px;
  text-align: center;
  font-size: var(--ff-fs-body-sm);
  color: var(--ff-text-tertiary);
}
.etdx-watch__list {
  list-style: none;
  display: flex;
  flex-direction: column;
  gap: 2px;
}
.etdx-watch__item {
  display: flex;
  align-items: center;
  gap: 8px;
  width: 100%;
  padding: 7px 10px;
  border: 1px solid transparent;
  border-radius: var(--ff-radius-md);
  text-align: left;
  transition: background var(--ff-dur-fast), border-color var(--ff-dur-fast);
}
.etdx-watch__item:hover {
  background: var(--ff-bg-hover);
}
.etdx-watch__item:hover .etdx-watch__item-x {
  opacity: 1;
}
.etdx-watch__item.is-active {
  background: var(--ff-bg-brand-subtle);
  border-color: var(--ff-border-brand);
}
.etdx-watch__item-name {
  flex: 1;
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  font-size: var(--ff-fs-body-sm);
  font-weight: 500;
  color: var(--ff-text-primary);
}
.etdx-watch__item.is-active .etdx-watch__item-name {
  color: var(--ff-text-brand);
  font-weight: 600;
}
.etdx-watch__item-code {
  font-size: var(--ff-fs-caption);
  font-family: var(--ff-font-mono, monospace);
  color: var(--ff-text-tertiary);
  flex: none;
}
.etdx-watch__item-x {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 18px;
  height: 18px;
  flex: none;
  border-radius: 4px;
  color: var(--ff-icon-muted);
  opacity: 0;
  transition: opacity var(--ff-dur-fast);
}
.etdx-watch__item-x:hover {
  background: var(--ff-bg-subtle);
  color: var(--ff-text-primary);
}
</style>
