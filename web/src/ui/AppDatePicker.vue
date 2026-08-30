<script setup>
/**
 * AppDatePicker — 自定义日历日期选择器
 *
 * 触发器点击后展开自绘月历（月份导航 / 今日高亮 / 选中态 / min-max 禁用），
 * 替代原生 input[type=date]，视觉与设计系统一致。输出 ISO（yyyy-mm-dd）。
 *
 * 无头模式：trigger=false 时不渲染输入框，仅保留弹层，由外部通过 openPopup()/
 * closePopup() 控制（AppDateNav 复用本弹层，保持全站日期选择体验一致）。
 */
import { computed, ref, watch, onMounted, onUnmounted } from 'vue'
import AppIcon from './AppIcon.vue'

const props = defineProps({
  modelValue: { type: String, default: '' },
  size: { type: String, default: 'md' },
  label: { type: String, default: '' },
  hint: { type: String, default: '' },
  error: { type: String, default: '' },
  placeholder: { type: String, default: '选择日期' },
  disabled: { type: Boolean, default: false },
  readonly: { type: Boolean, default: false },
  clearable: { type: Boolean, default: false },
  min: { type: String, default: '' },
  max: { type: String, default: '' },
  /** 是否渲染输入框触发器；false = 仅弹层（外部控制开合） */
  trigger: { type: Boolean, default: true },
})

const emit = defineEmits(['update:modelValue', 'change'])

const DOW = ['日', '一', '二', '三', '四', '五', '六']
const rootEl = ref(null)
const open = ref(false)
const viewDate = ref(new Date())

const hasValue = computed(() => !!props.modelValue)

const fieldCls = computed(() => [
  'ff-field',
  props.error && 'ff-field--error',
  props.disabled && 'ff-field--disabled',
  open.value && 'ff-field--focused',
])

const wrapperCls = computed(() => [
  'ff-date-input',
  `ff-date-input--${props.size}`,
  open.value && 'ff-date-input--open',
])

function toDate(iso) {
  if (!iso) return null
  const [y, m, d] = iso.split('-').map(Number)
  if (!y || !m || !d) return null
  return new Date(y, m - 1, d)
}
function toISO(dt) {
  const p = (n) => String(n).padStart(2, '0')
  return `${dt.getFullYear()}-${p(dt.getMonth() + 1)}-${p(dt.getDate())}`
}

function syncView() {
  const dt = toDate(props.modelValue) || new Date()
  viewDate.value = new Date(dt.getFullYear(), dt.getMonth(), 1)
}
watch(
  () => props.modelValue,
  (v) => {
    const dt = toDate(v)
    if (dt) viewDate.value = new Date(dt.getFullYear(), dt.getMonth(), 1)
  },
)

function isDisabled(iso) {
  if (props.disabled || props.readonly) return true
  if (props.min && iso < props.min) return true
  if (props.max && iso > props.max) return true
  return false
}

const title = computed(() => `${viewDate.value.getFullYear()}年${viewDate.value.getMonth() + 1}月`)

const calendar = computed(() => {
  const y = viewDate.value.getFullYear()
  const m = viewDate.value.getMonth()
  const startOffset = new Date(y, m, 1).getDay() // 0=周日
  const todayISO = toISO(new Date())
  const selectedISO = props.modelValue
  const cells = []
  for (let i = 0; i < 42; i++) {
    const dt = new Date(y, m, 1 - startOffset + i)
    const iso = toISO(dt)
    cells.push({
      key: iso,
      day: dt.getDate(),
      date: iso,
      muted: dt.getMonth() !== m,
      isToday: iso === todayISO,
      isSelected: iso === selectedISO,
      disabled: isDisabled(iso),
    })
  }
  return cells
})

function shiftMonth(n) {
  viewDate.value = new Date(viewDate.value.getFullYear(), viewDate.value.getMonth() + n, 1)
}

function toggleOpen() {
  if (props.disabled || props.readonly) return
  if (open.value) closePopup()
  else openPopup()
}

/** 外部控制：展开弹层（无头模式 trigger=false 时使用） */
function openPopup() {
  if (props.disabled || props.readonly) return
  syncView()
  open.value = true
}
/** 外部控制：收起弹层 */
function closePopup() {
  open.value = false
}

function selectDay(iso) {
  if (isDisabled(iso)) return
  emit('update:modelValue', iso)
  emit('change', iso)
  open.value = false
}

function pickToday() {
  const t = toISO(new Date())
  emit('update:modelValue', t)
  emit('change', t)
  open.value = false
}

function onClear() {
  emit('update:modelValue', '')
  open.value = false
}

function onDocClick(e) {
  if (rootEl.value && !rootEl.value.contains(e.target)) open.value = false
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

defineExpose({ focus: () => {}, openPopup, closePopup })
</script>

<template>
  <div ref="rootEl" :class="fieldCls">
    <label v-if="label" class="ff-field__label">{{ label }}</label>
    <div class="ff-field__control">
      <div v-if="trigger" :class="wrapperCls" @click="toggleOpen">
        <span class="ff-date-input__icon">
          <AppIcon name="calendar" size="sm" />
        </span>
        <span v-if="!hasValue && !open" class="ff-date-input__placeholder">{{ placeholder }}</span>
        <span v-else class="ff-date-input__value">{{ modelValue }}</span>
        <button
          v-if="clearable && hasValue && !disabled && !readonly"
          type="button"
          class="ff-date-input__clear"
          tabindex="-1"
          aria-label="清除日期"
          @click.stop="onClear"
        >
          <AppIcon name="x" size="xs" />
        </button>
        <span v-else class="ff-date-input__caret">
          <AppIcon name="chevron-down" size="xs" />
        </span>
      </div>

      <div v-if="open" class="ff-datepicker">
        <div class="ff-datepicker__header">
          <button type="button" class="ff-datepicker__nav" aria-label="上一月" @click="shiftMonth(-1)">
            <AppIcon name="chevron-left" size="sm" />
          </button>
          <span class="ff-datepicker__title">{{ title }}</span>
          <button type="button" class="ff-datepicker__nav" aria-label="下一月" @click="shiftMonth(1)">
            <AppIcon name="chevron-right" size="sm" />
          </button>
        </div>
        <div class="ff-datepicker__grid">
          <span v-for="d in DOW" :key="d" class="ff-datepicker__dow">{{ d }}</span>
          <button
            v-for="cell in calendar"
            :key="cell.key"
            type="button"
            class="ff-datepicker__day"
            :class="{
              'is-muted': cell.muted,
              'is-today': cell.isToday,
              'is-selected': cell.isSelected,
            }"
            :disabled="cell.disabled"
            @click="selectDay(cell.date)"
          >
            {{ cell.day }}
          </button>
        </div>
        <div class="ff-datepicker__footer">
          <button type="button" class="ff-datepicker__foot-btn" @click="pickToday">
            今天
          </button>
          <button v-if="clearable && hasValue" type="button" class="ff-datepicker__foot-btn" @click="onClear">
            清除
          </button>
        </div>
      </div>
    </div>
    <p v-if="error" class="ff-field__message ff-field__message--error">{{ error }}</p>
    <p v-else-if="hint" class="ff-field__message">{{ hint }}</p>
  </div>
</template>

<style scoped>
.ff-field__control {
  position: relative; /* 日历弹层定位锚点 */
}

.ff-date-input {
  position: relative;
  display: inline-flex;
  align-items: center;
  width: 100%;
  min-height: var(--ff-control-h-md);
  padding: 0 var(--ff-space-3);
  gap: var(--ff-space-2);
  border: 1px solid var(--ff-border);
  border-radius: var(--ff-radius-md);
  background: var(--ff-bg-surface);
  color: var(--ff-text-primary);
  cursor: pointer;
  transition: border-color var(--ff-dur-fast), box-shadow var(--ff-dur-fast), background var(--ff-dur-fast);
}

.ff-date-input:hover {
  border-color: var(--ff-border-hover);
}

.ff-date-input:focus-within,
.ff-date-input--open {
  border-color: var(--ff-border-focus);
  box-shadow: var(--ff-focus-ring);
  outline: none;
}

.ff-date-input--sm { min-height: var(--ff-control-h-sm); }
.ff-date-input--lg { min-height: var(--ff-control-h-lg); }

.ff-date-input__icon,
.ff-date-input__caret,
.ff-date-input__clear {
  display: inline-flex;
  color: var(--ff-icon-muted);
  flex-shrink: 0;
}

.ff-date-input__clear {
  align-items: center;
  justify-content: center;
  width: 20px;
  height: 20px;
  padding: 0;
  border: none;
  border-radius: var(--ff-radius-xs);
  background: transparent;
  cursor: pointer;
  transition: background var(--ff-dur-fast), color var(--ff-dur-fast);
}

.ff-date-input__clear:hover {
  background: var(--ff-bg-hover);
  color: var(--ff-text-primary);
}

.ff-date-input__value,
.ff-date-input__placeholder {
  flex: 1 1 auto;
  min-width: 0;
  font-size: var(--ff-fs-body);
  font-variant-numeric: tabular-nums;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  pointer-events: none;
}

.ff-date-input__value {
  color: var(--ff-text-primary);
}

.ff-date-input__placeholder {
  color: var(--ff-text-placeholder);
}

/* 弹层底部按钮 */
.ff-datepicker__footer {
  justify-content: space-between;
}
.ff-datepicker__foot-btn {
  height: 28px;
  padding: 0 var(--ff-space-2-5);
  border: 1px solid var(--ff-border);
  border-radius: var(--ff-radius-sm);
  background: var(--ff-bg-surface);
  color: var(--ff-text-secondary);
  font-size: var(--ff-fs-body-sm);
  font-weight: var(--ff-fw-medium);
  cursor: pointer;
  transition:
    background-color var(--ff-dur-fast) var(--ff-ease-standard),
    border-color var(--ff-dur-fast) var(--ff-ease-standard),
    color var(--ff-dur-fast) var(--ff-ease-standard);
}
.ff-datepicker__foot-btn:hover {
  background: var(--ff-bg-hover);
  border-color: var(--ff-border-strong);
  color: var(--ff-text-primary);
}

.ff-field--disabled .ff-date-input {
  background: var(--ff-bg-disabled);
  color: var(--ff-text-disabled);
  cursor: not-allowed;
}

.ff-field--error .ff-date-input {
  border-color: var(--ff-border-error);
  background: var(--ff-bg-error);
}

.ff-field--error .ff-date-input:focus-within {
  box-shadow: var(--ff-focus-ring-error);
}
</style>
