<script setup>
/**
 * AppDatePicker — 自定义日期选择器
 *
 * 视觉层完全自定义；底层仍使用原生 `<input type="date">` 以保证跨平台日期解析、
 * 键盘输入与移动端呼出原生日历。日期格式化输出为 ISO（yyyy-mm-dd）。
 */
import { computed, ref } from 'vue'
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
})

const emit = defineEmits(['update:modelValue', 'change'])

const inputRef = ref(null)
const focused = ref(false)

const fieldCls = computed(() => [
  'ff-field',
  props.error && 'ff-field--error',
  props.disabled && 'ff-field--disabled',
  focused.value && 'ff-field--focused',
])

const wrapperCls = computed(() => [
  'ff-date-input',
  `ff-date-input--${props.size}`,
])

const hasValue = computed(() => !!props.modelValue)

function onInput(e) {
  emit('update:modelValue', e.target.value)
  emit('change', e.target.value)
}

function onClear() {
  emit('update:modelValue', '')
  inputRef.value?.focus()
}

function openPicker() {
  if (props.disabled || props.readonly) return
  inputRef.value?.showPicker?.()
}

defineExpose({ focus: () => inputRef.value?.focus() })
</script>

<template>
  <div :class="fieldCls">
    <label v-if="label" class="ff-field__label">{{ label }}</label>
    <div class="ff-field__control">
      <div :class="wrapperCls" @click="openPicker">
        <span class="ff-date-input__icon">
          <AppIcon name="calendar" size="sm" />
        </span>
        <input
          ref="inputRef"
          type="date"
          :value="modelValue"
          :min="min"
          :max="max"
          :disabled="disabled"
          :readonly="readonly"
          class="ff-date-input__native"
          :placeholder="placeholder"
          @focus="focused = true"
          @blur="focused = false"
          @input="onInput"
        />
        <button
          v-if="clearable && hasValue && !disabled && !readonly"
          type="button"
          class="ff-date-input__clear"
          tabindex="-1"
          @click.stop="onClear"
        >
          <AppIcon name="x" size="xs" />
        </button>
        <span v-else class="ff-date-input__caret">
          <AppIcon name="chevron-down" size="xs" />
        </span>
      </div>
    </div>
    <p v-if="error" class="ff-field__message ff-field__message--error">{{ error }}</p>
    <p v-else-if="hint" class="ff-field__message">{{ hint }}</p>
  </div>
</template>

<style scoped>
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

.ff-date-input:focus-within {
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

.ff-date-input__native {
  flex: 1 1 auto;
  min-width: 0;
  height: 100%;
  padding: 0;
  border: none;
  background: transparent;
  color: inherit;
  font: inherit;
  outline: none;
  cursor: pointer;
}

.ff-date-input__native::-webkit-calendar-picker-indicator {
  position: absolute;
  inset: 0;
  width: 100%;
  height: 100%;
  margin: 0;
  padding: 0;
  opacity: 0;
  cursor: pointer;
}

.ff-date-input__native::placeholder {
  color: var(--ff-text-placeholder);
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
