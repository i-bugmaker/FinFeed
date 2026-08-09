<script setup>
/**
 * AppSelect — 自定义下拉选择器
 *
 * 纯 JS 定位，不使用 Popper。点击外部自动收起，支持键盘 Esc 关闭。
 */
import { computed, ref, watch, nextTick, onMounted, onUnmounted } from 'vue'
import AppIcon from './AppIcon.vue'

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

function onKeydown(e) {
  if (e.key === 'Escape' && open.value) {
    e.preventDefault()
    close()
  }
}

function positionMenu() {
  if (!triggerRef.value || !menuRef.value) return
  const rect = triggerRef.value.getBoundingClientRect()
  const menu = menuRef.value
  menu.style.width = `${rect.width}px`
  menu.style.top = `${rect.bottom + 6}px`
  menu.style.left = `${rect.left}px`
}

function onClear(e) {
  e.stopPropagation()
  if (props.multiple) emit('update:modelValue', [])
  else emit('update:modelValue', '')
}

watch(open, v => {
  if (v) {
    nextTick(positionMenu)
    document.addEventListener('click', onClickOutside, true)
    document.addEventListener('keydown', onKeydown)
    window.addEventListener('resize', positionMenu)
  } else {
    document.removeEventListener('click', onClickOutside, true)
    document.removeEventListener('keydown', onKeydown)
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
    <label v-if="label" class="ff-field__label">{{ label }}</label>
    <div class="ff-field__control">
      <div
        ref="triggerRef"
        :class="triggerCls"
        tabindex="0"
        role="combobox"
        :aria-expanded="open"
        @click="toggle"
      >
        <span class="ff-select__value" :class="!selected && 'ff-select__value--placeholder'">
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
                v-for="opt in options"
                :key="opt.value"
                :class="[
                  'ff-menu__item',
                  isSelected(opt) && 'ff-menu__item--active',
                  opt.disabled && 'ff-menu__item--disabled',
                ]"
                role="option"
                :aria-selected="isSelected(opt)"
                @click="selectOption(opt)"
              >
                <span class="ff-menu__check">
                  <AppIcon v-if="isSelected(opt)" name="check" size="sm" />
                </span>
                <span class="ff-menu__label">{{ opt.label }}</span>
              </li>
            </ul>
            <div v-if="!options.length" class="ff-empty ff-empty--xs">
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
