<script setup>
/**
 * AppDateRange — 单一日期区间选择器
 *
 * 顶部仅一个触发器显示当前区间；展开后提供快捷预设（全部 / 今日 / 近3日 /
 * 近7日 / 近30日 / 本月）与可选自定义区间。v-model 结构为 { start, end }，
 * 日期均为 ISO（yyyy-mm-dd），空字符串表示不限制。
 */
import { ref, computed, watch, onMounted, onUnmounted } from 'vue'
import AppIcon from './AppIcon.vue'

const props = defineProps({
  modelValue: { type: Object, default: () => ({ start: '', end: '' }) },
  size: { type: String, default: 'md' },
  disabled: { type: Boolean, default: false },
})
const emit = defineEmits(['update:modelValue', 'change'])

const root = ref(null)
const open = ref(false)
const customStart = ref(props.modelValue.start || '')
const customEnd = ref(props.modelValue.end || '')

const presets = [
  { k: 'all', label: '全部' },
  { k: 'today', label: '今日' },
  { k: '3d', label: '近3日' },
  { k: '7d', label: '近7日' },
  { k: '30d', label: '近30日' },
  { k: 'month', label: '本月' },
]

function iso(dt) {
  const p = (n) => String(n).padStart(2, '0')
  return `${dt.getFullYear()}-${p(dt.getMonth() + 1)}-${p(dt.getDate())}`
}
function presetRange(k) {
  const today = new Date()
  if (k === 'all') return { start: '', end: '' }
  if (k === 'today') {
    const t = iso(today)
    return { start: t, end: t }
  }
  const d = new Date(today)
  const days = k === '3d' ? 2 : k === '7d' ? 6 : k === '30d' ? 29 : 0
  if (k === 'month') {
    d.setDate(1)
    return { start: iso(d), end: iso(today) }
  }
  d.setDate(d.getDate() - days)
  return { start: iso(d), end: iso(today) }
}

const activePreset = computed(() => {
  const { start, end } = props.modelValue
  for (const p of presets) {
    const r = presetRange(p.k)
    if (r.start === start && r.end === end) return p.k
  }
  return ''
})

const label = computed(() => {
  const { start, end } = props.modelValue
  if (!start && !end) return '全部时间'
  if (start && end && start === end) return start
  if (start && end) return `${start} ~ ${end}`
  if (start) return `${start} 起`
  if (end) return `至 ${end}`
  return '自定义'
})

function push(r) {
  emit('update:modelValue', { ...r })
  emit('change', { ...r })
}

function choosePreset(k) {
  const r = presetRange(k)
  customStart.value = r.start
  customEnd.value = r.end
  push(r)
  open.value = false
}

function applyCustom() {
  push({ start: customStart.value, end: customEnd.value })
  open.value = false
}

function onDocClick(e) {
  if (root.value && !root.value.contains(e.target)) open.value = false
}
function onEsc(e) {
  if (e.key === 'Escape') open.value = false
}
onMounted(() => {
  document.addEventListener('click', onDocClick)
  document.addEventListener('keydown', onEsc)
})
onUnmounted(() => {
  document.removeEventListener('click', onDocClick)
  document.removeEventListener('keydown', onEsc)
})

watch(
  () => props.modelValue,
  (v) => {
    customStart.value = v.start || ''
    customEnd.value = v.end || ''
  },
  { deep: true },
)
</script>

<template>
  <div ref="root" class="ff-daterange" :class="`ff-daterange--${size}`">
    <button
      type="button"
      class="ff-daterange__trigger"
      :class="{ 'is-open': open }"
      :disabled="disabled"
      :aria-expanded="open"
      @click="open = !open"
    >
      <AppIcon name="calendar" size="sm" class="ff-daterange__icon" />
      <span class="ff-daterange__label">{{ label }}</span>
      <AppIcon name="chevron-down" size="xs" class="ff-daterange__caret" :class="{ 'is-open': open }" />
    </button>

    <div v-if="open" class="ff-daterange__panel ff-menu ff-menu--bottom ff-menu--right">
      <div class="ff-daterange__presets">
        <button
          v-for="p in presets"
          :key="p.k"
          type="button"
          class="ff-daterange__preset"
          :class="{ 'is-active': activePreset === p.k }"
          @click="choosePreset(p.k)"
        >
          {{ p.label }}
        </button>
      </div>
      <div class="ff-daterange__custom">
        <div class="ff-daterange__custom-head">自定义区间</div>
        <div class="ff-daterange__custom-row">
          <label class="ff-daterange__custom-label">开始</label>
          <input v-model="customStart" type="date" class="ff-daterange__input" :max="customEnd || undefined" />
        </div>
        <div class="ff-daterange__custom-row">
          <label class="ff-daterange__custom-label">结束</label>
          <input v-model="customEnd" type="date" class="ff-daterange__input" :min="customStart || undefined" />
        </div>
        <button type="button" class="ff-daterange__apply" @click="applyCustom">应用</button>
      </div>
    </div>
  </div>
</template>

<style scoped>
.ff-daterange {
  position: relative;
  display: inline-flex;
}
.ff-daterange__trigger {
  display: inline-flex;
  align-items: center;
  gap: var(--ff-space-2);
  min-height: var(--ff-control-h-md);
  padding: 0 var(--ff-space-3);
  border: 1px solid var(--ff-border);
  border-radius: var(--ff-radius-md);
  background: var(--ff-bg-surface);
  color: var(--ff-text-primary);
  cursor: pointer;
  transition:
    border-color var(--ff-dur-fast) var(--ff-ease-standard),
    box-shadow var(--ff-dur-fast) var(--ff-ease-standard),
    background-color var(--ff-dur-fast) var(--ff-ease-standard);
}
.ff-daterange__trigger:hover {
  border-color: var(--ff-border-hover);
}
.ff-daterange__trigger:focus-visible {
  outline: none;
  border-color: var(--ff-border-focus);
  box-shadow: var(--ff-focus-ring);
}
.ff-daterange__trigger.is-open {
  border-color: var(--ff-border-focus);
  box-shadow: var(--ff-focus-ring);
}
.ff-daterange__trigger:disabled {
  background: var(--ff-bg-disabled);
  color: var(--ff-text-disabled);
  cursor: not-allowed;
}
.ff-daterange--sm .ff-daterange__trigger {
  min-height: var(--ff-control-h-sm);
}
.ff-daterange__icon {
  color: var(--ff-icon-muted);
  flex-shrink: 0;
}
.ff-daterange__label {
  font-size: var(--ff-fs-body-sm);
  font-variant-numeric: tabular-nums;
  white-space: nowrap;
}
.ff-daterange__caret {
  color: var(--ff-icon-muted);
  flex-shrink: 0;
  transition: transform var(--ff-dur-fast) var(--ff-ease-standard);
}
.ff-daterange__caret.is-open {
  transform: rotate(180deg);
}
.ff-daterange__panel {
  width: 264px;
  padding: var(--ff-space-2);
}
.ff-daterange__presets {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: var(--ff-space-1);
  padding: var(--ff-space-1);
}
.ff-daterange__preset {
  height: 30px;
  border: 1px solid transparent;
  border-radius: var(--ff-radius-sm);
  background: transparent;
  color: var(--ff-text-secondary);
  font-size: var(--ff-fs-body-sm);
  cursor: pointer;
  transition:
    background-color var(--ff-dur-fast) var(--ff-ease-standard),
    color var(--ff-dur-fast) var(--ff-ease-standard),
    border-color var(--ff-dur-fast) var(--ff-ease-standard);
}
.ff-daterange__preset:hover {
  background: var(--ff-bg-hover);
  color: var(--ff-text-primary);
}
.ff-daterange__preset.is-active {
  background: var(--ff-brand-subtle);
  border-color: var(--ff-brand-border);
  color: var(--ff-brand-text);
  font-weight: var(--ff-fw-semibold);
}
.ff-daterange__custom {
  margin-top: var(--ff-space-2);
  padding: var(--ff-space-2-5) var(--ff-space-2-5) var(--ff-space-2);
  border-top: 1px solid var(--ff-border-subtle);
}
.ff-daterange__custom-head {
  font-size: var(--ff-fs-caption);
  font-weight: var(--ff-fw-semibold);
  color: var(--ff-text-tertiary);
  letter-spacing: var(--ff-ls-wide);
  margin-bottom: var(--ff-space-2);
}
.ff-daterange__custom-row {
  display: flex;
  align-items: center;
  gap: var(--ff-space-2);
  margin-bottom: var(--ff-space-2);
}
.ff-daterange__custom-label {
  width: 34px;
  flex-shrink: 0;
  font-size: var(--ff-fs-body-sm);
  color: var(--ff-text-secondary);
}
.ff-daterange__input {
  flex: 1;
  min-width: 0;
  height: 32px;
  padding: 0 var(--ff-space-2);
  border: 1px solid var(--ff-border);
  border-radius: var(--ff-radius-sm);
  background: var(--ff-bg-surface);
  color: var(--ff-text-primary);
  font: inherit;
  font-size: var(--ff-fs-body-sm);
  outline: none;
  transition: border-color var(--ff-dur-fast) var(--ff-ease-standard), box-shadow var(--ff-dur-fast) var(--ff-ease-standard);
}
.ff-daterange__input:focus {
  border-color: var(--ff-border-focus);
  box-shadow: var(--ff-focus-ring);
}
.ff-daterange__apply {
  width: 100%;
  height: 32px;
  margin-top: var(--ff-space-1);
  border: none;
  border-radius: var(--ff-radius-sm);
  background: var(--ff-brand);
  color: var(--ff-brand-fg);
  font-size: var(--ff-fs-body-sm);
  font-weight: var(--ff-fw-semibold);
  cursor: pointer;
  transition: background-color var(--ff-dur-fast) var(--ff-ease-standard);
}
.ff-daterange__apply:hover {
  background: var(--ff-brand-hover);
}
</style>
