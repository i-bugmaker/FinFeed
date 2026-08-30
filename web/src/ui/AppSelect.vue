<script setup>
/**
 * AppSelect — 自定义下拉选择器
 *
 * 纯 JS 定位，不使用 Popper。点击外部自动收起，支持键盘 Esc 关闭。
 */
import { computed, ref, watch, nextTick, onMounted, onUnmounted } from 'vue'
import AppIcon from './AppIcon.vue'

let uid = 0

const props = defineProps({
  modelValue: { type: [String, Number, Array], default: '' },
  options: { type: Array, default: () => [] }, // { label, value, disabled }
  placeholder: { type: String, default: '请选择' },
  size: { type: String, default: 'md' },
  label: { type: String, default: '' },
  hint: { type: String, default: '' },
  error: { type: String, default: '' },
  disabled: { type: Boolean, default: false },
  multiple: { type: Boolean, default: false },
  clearable: { type: Boolean, default: false },
})

const emit = defineEmits(['update:modelValue', 'change'])

const open = ref(false)
const triggerRef = ref(null)
const menuRef = ref(null)
const inputId = `ff-select-${++uid}`
// 键盘导航高亮项（-1 表示未高亮）
const highlight = ref(-1)

const selected = computed(() => {
  if (props.multiple) {
    const vals = Array.isArray(props.modelValue) ? props.modelValue : []
    return props.options.filter(o => vals.includes(o.value))
  }
  return props.options.find(o => String(o.value) === String(props.modelValue)) || null
})

const displayText = computed(() => {
  if (props.multiple) {
    const arr = selected.value
    if (!arr.length) return props.placeholder
    return arr.map(o => o.label).join('，')
  }
  return selected.value ? selected.value.label : props.placeholder
})

const fieldCls = computed(() => [
  'ff-field',
  props.error && 'ff-field--error',
  props.disabled && 'ff-field--disabled',
  open.value && 'ff-field--focused',
])

const triggerCls = computed(() => [
  'ff-select__trigger',
  `ff-select__trigger--${props.size}`,
  open.value && 'ff-select__trigger--open',
  props.disabled && 'ff-select__trigger--disabled',
])

function toggle() {
  if (props.disabled) return
  open.value = !open.value
  if (open.value) nextTick(positionMenu)
}

function close() {
  open.value = false
  highlight.value = -1
}

function selectableIdx(i, dir) {
  // 从 i 出发按 dir 找下一个可选项，跳过 disabled
  const n = props.options.length
  if (!n) return -1
  for (let k = 1; k <= n; k++) {
    const j = ((i + dir * k) % n + n) % n
    if (!props.options[j]?.disabled) return j
  }
  return -1
}

function moveHighlight(dir) {
  if (!props.options.length) return
  const start = highlight.value < 0 ? (dir > 0 ? -1 : 0) : highlight.value
  const next = selectableIdx(start, dir)
  if (next >= 0) highlight.value = next
  nextTick(() => {
    menuRef.value?.querySelector('.is-highlighted')?.scrollIntoView({ block: 'nearest' })
  })
}

function selectOption(opt) {
  if (opt.disabled) return
  if (props.multiple) {
    const current = Array.isArray(props.modelValue) ? [...props.modelValue] : []
    const idx = current.indexOf(opt.value)
    if (idx > -1) current.splice(idx, 1)
    else current.push(opt.value)
    emit('update:modelValue', current)
    emit('change', current)
  } else {
    emit('update:modelValue', opt.value)
    emit('change', opt.value)
    close()
  }
}

function isSelected(opt) {
  if (props.multiple) {
    return Array.isArray(props.modelValue) && props.modelValue.includes(opt.value)
  }
  return String(props.modelValue) === String(opt.value)
}

function onClickOutside(e) {
  if (!triggerRef.value?.contains(e.target) && !menuRef.value?.contains(e.target)) {
    close()
  }
}

// 触发器上的键盘处理：关闭态可展开，展开态做导航
function onTriggerKeydown(e) {
  if (props.disabled) return
  if (!open.value) {
    if (['ArrowDown', 'ArrowUp', 'Enter', ' '].includes(e.key)) {
      e.preventDefault()
      toggle()
      if (e.key === 'ArrowDown' || e.key === 'ArrowUp') {
        nextTick(() => moveHighlight(e.key === 'ArrowDown' ? 1 : -1))
      }
    }
    return
  }
  if (e.key === 'Escape') {
    e.preventDefault()
    e.stopPropagation()
    close()
  } else if (e.key === 'ArrowDown') {
    e.preventDefault()
    moveHighlight(1)
  } else if (e.key === 'ArrowUp') {
    e.preventDefault()
    moveHighlight(-1)
  } else if (e.key === 'Enter') {
    e.preventDefault()
    const opt = props.options[highlight.value]
    if (opt && !opt.disabled) selectOption(opt)
  } else if (e.key === 'Tab') {
    close()
  }
}

// document 级兜底：焦点落在菜单项上时也能 Esc 关闭
function onDocKeydown(e) {
  if (e.key === 'Escape' && open.value) {
    e.preventDefault()
    close()
  }
}

function positionMenu() {
  if (!triggerRef.value || !menuRef.value) return
  const rect = triggerRef.value.getBoundingClientRect()
  const menu = menuRef.value
  const vw = document.documentElement.clientWidth
  const vh = document.documentElement.clientHeight
  const margin = 8

  // 菜单宽度与触发器保持一致，左右边缘与触发器对齐；
  // 在窄视口下按视口宽度裁剪，避免溢出屏幕。
  const menuW = Math.min(rect.width, vw - margin * 2)
  menu.style.width = `${menuW}px`
  menu.style.maxWidth = `${menuW}px`
  menu.style.top = `${rect.bottom + 6}px`

  // 下方空间不足时向上翻转
  const menuH = menu.offsetHeight || 0
  if (rect.bottom + menuH + 6 > vh && rect.top - menuH - 6 > margin) {
    menu.style.top = `${Math.max(margin, rect.top - menuH - 6)}px`
  }

  // 默认左边缘对齐触发器左边缘；若右侧超出视口则右边缘贴紧视口内侧。
  const left = Math.min(Math.max(margin, rect.left), vw - margin - menuW)
  menu.style.left = `${left}px`
}

function onClear(e) {
  e.stopPropagation()
  if (props.multiple) emit('update:modelValue', [])
  else emit('update:modelValue', '')
  emit('change', props.multiple ? [] : '')
}

watch(open, v => {
  if (v) {
    nextTick(positionMenu)
    document.addEventListener('click', onClickOutside, true)
    document.addEventListener('keydown', onDocKeydown)
    window.addEventListener('resize', positionMenu)
  } else {
    document.removeEventListener('click', onClickOutside, true)
    document.removeEventListener('keydown', onDocKeydown)
    window.removeEventListener('resize', positionMenu)
  }
})

onUnmounted(() => {
  document.removeEventListener('click', onClickOutside, true)
  document.removeEventListener('keydown', onKeydown)
  window.removeEventListener('resize', positionMenu)
})
</script>

<template>
  <div :class="fieldCls">
    <label v-if="label" class="ff-field__label" :for="inputId">{{ label }}</label>
    <div class="ff-field__control">
      <div
        :id="inputId"
        ref="triggerRef"
        :class="triggerCls"
        tabindex="0"
        role="combobox"
        :aria-expanded="open"
        :aria-activedescendant="open && highlight >= 0 ? `${inputId}-opt-${highlight}` : undefined"
        @click="toggle"
        @keydown="onTriggerKeydown"
      >
        <span class="ff-select__value" :class="!selected && 'is-placeholder'">
          {{ displayText }}
        </span>
        <span class="ff-select__actions">
          <button
            v-if="clearable && (selected && (Array.isArray(selected) ? selected.length : true))"
            type="button"
            class="ff-select__clear"
            tabindex="-1"
            @click="onClear"
          >
            <AppIcon name="x" size="xs" />
          </button>
          <AppIcon name="chevron-down" size="sm" :class="open && 'ff-select__arrow--open'" class="ff-select__arrow" />
        </span>
      </div>

      <Teleport to="body">
        <Transition name="ff-pop">
          <div
            v-show="open"
            ref="menuRef"
            class="ff-dropdown ff-menu"
            role="listbox"
          >
            <ul class="ff-menu__items">
              <li
                v-for="(opt, i) in options"
                :id="`${inputId}-opt-${i}`"
                :key="opt.value"
                :class="[
                  'ff-menu__item',
                  isSelected(opt) && 'is-selected',
                  i === highlight && 'is-highlighted',
                  opt.disabled && 'is-disabled',
                ]"
                role="option"
                :aria-selected="isSelected(opt)"
                :aria-disabled="opt.disabled || undefined"
                @click="selectOption(opt)"
                @mouseenter="!opt.disabled && (highlight = i)"
              >
                <span class="ff-menu__check">
                  <AppIcon v-if="isSelected(opt)" name="check" size="sm" />
                </span>
                <span class="ff-menu__item-text">{{ opt.label }}</span>
              </li>
            </ul>
            <div v-if="!options.length" class="ff-empty ff-empty--compact">
              暂无选项
            </div>
          </div>
        </Transition>
      </Teleport>
    </div>
    <p v-if="error" class="ff-field__message ff-field__message--error">{{ error }}</p>
    <p v-else-if="hint" class="ff-field__message">{{ hint }}</p>
  </div>
</template>

<style scoped>
.ff-select__actions {
  display: inline-flex;
  align-items: center;
  gap: var(--ff-space-1);
  margin-left: auto;
}

.ff-select__clear {
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

.ff-select__clear:hover {
  background: var(--ff-bg-hover);
  color: var(--ff-text-primary);
}

.ff-select__arrow {
  transition: transform var(--ff-dur-fast) var(--ff-ease-out);
}

.ff-select__arrow--open {
  transform: rotate(180deg);
}
</style>
