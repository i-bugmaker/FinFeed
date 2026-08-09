<script setup>
/**
 * AppInput — 自定义输入框
 *
 * 支持前缀/后缀图标、清除按钮、错误态、只读态、密码显隐（可选）。
 * 内部仍使用原生 <input> 以保证表单与 a11y 行为完整，但视觉层完全由 CSS 接管。
 */
import { computed, ref } from 'vue'
import AppIcon from './AppIcon.vue'

const props = defineProps({
  modelValue: { type: [String, Number], default: '' },
  type: { type: String, default: 'text' },
  size: { type: String, default: 'md' },
  placeholder: { type: String, default: '' },
  label: { type: String, default: '' },
  hint: { type: String, default: '' },
  error: { type: String, default: '' },
  disabled: { type: Boolean, default: false },
  readonly: { type: Boolean, default: false },
  clearable: { type: Boolean, default: false },
  prefixIcon: { type: String, default: '' },
  suffixIcon: { type: String, default: '' },
  seamless: { type: Boolean, default: false }, // 无边框背景
})

const emit = defineEmits(['update:modelValue', 'blur', 'focus', 'enter'])

const inputRef = ref(null)
const focused = ref(false)

const localType = ref(props.type)
const showPassword = computed(() => localType.value === 'text')

const hasValue = computed(() => String(props.modelValue || '').length > 0)
const showClear = computed(() => props.clearable && hasValue.value && !props.disabled && !props.readonly)
const showPwToggle = computed(() => props.type === 'password' && !props.disabled && !props.readonly)

const fieldCls = computed(() => [
  'ff-field',
  props.error && 'ff-field--error',
  props.disabled && 'ff-field--disabled',
  focused.value && 'ff-field--focused',
])

const inputCls = computed(() => [
  'ff-input',
  `ff-input--${props.size}`,
  props.seamless && 'ff-input--seamless',
  props.prefixIcon && 'ff-input--prefix',
  (props.suffixIcon || showClear.value || showPwToggle.value) && 'ff-input--suffix',
  focused.value && 'is-focused',
  props.error && 'is-error',
  props.disabled && 'is-disabled',
  props.readonly && 'is-readonly',
])

function onInput(e) {
  emit('update:modelValue', e.target.value)
}

function onClear() {
  emit('update:modelValue', '')
  inputRef.value?.focus()
}

function togglePassword() {
  localType.value = localType.value === 'password' ? 'text' : 'password'
}

function onKeydown(e) {
  if (e.key === 'Enter') emit('enter', e.target.value)
}

defineExpose({ focus: () => inputRef.value?.focus() })
</script>

<template>
  <div :class="fieldCls">
    <label v-if="label" class="ff-field__label">{{ label }}</label>
    <div class="ff-field__control">
      <div :class="inputCls">
        <span v-if="prefixIcon" class="ff-input__affix ff-input__affix--prefix">
          <AppIcon :name="prefixIcon" size="sm" />
        </span>
        <input
          ref="inputRef"
          :type="localType"
          :value="modelValue"
          :placeholder="placeholder"
          :disabled="disabled"
          :readonly="readonly"
          class="ff-input__native"
          @input="onInput"
          @focus="focused = true; $emit('focus', $event)"
          @blur="focused = false; $emit('blur', $event)"
          @keydown="onKeydown"
        />
        <button
          v-if="showPwToggle"
          type="button"
          class="ff-input__suffix-btn"
          tabindex="-1"
          @click="togglePassword"
        >
          <AppIcon :name="showPassword ? 'eye' : 'eye-off'" size="sm" />
        </button>
        <button
          v-else-if="showClear"
          type="button"
          class="ff-input__suffix-btn"
          tabindex="-1"
          @click="onClear"
        >
          <AppIcon name="x" size="xs" />
        </button>
        <span v-else-if="suffixIcon" class="ff-input__affix ff-input__affix--suffix">
          <AppIcon :name="suffixIcon" size="sm" />
        </span>
      </div>
    </div>
    <p v-if="error" class="ff-field__message ff-field__message--error">{{ error }}</p>
    <p v-else-if="hint" class="ff-field__message">{{ hint }}</p>
  </div>
</template>

<style scoped>
.ff-input__suffix-btn {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 22px;
  height: 22px;
  padding: 0;
  border: none;
  border-radius: var(--ff-radius-sm);
  background: transparent;
  color: var(--ff-icon-muted);
  cursor: pointer;
  transition: background var(--ff-dur-fast), color var(--ff-dur-fast);
}

.ff-input__suffix-btn:hover {
  background: var(--ff-bg-hover);
  color: var(--ff-text-primary);
}

.ff-field--disabled .ff-input__suffix-btn {
  cursor: not-allowed;
}
</style>
