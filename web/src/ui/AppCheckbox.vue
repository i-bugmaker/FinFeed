<script setup>
/**
 * AppCheckbox / AppRadio — 自定义复选框与单选按钮
 *
 * 使用原生 input 保证表单、键盘与 a11y 行为，视觉完全覆盖。
 */
import { computed } from 'vue'

const props = defineProps({
  modelValue: { type: [Boolean, Array, String, Number], default: false },
  value: { type: [String, Number, Boolean], default: true },
  label: { type: String, default: '' },
  disabled: { type: Boolean, default: false },
  indeterminate: { type: Boolean, default: false },
  radio: { type: Boolean, default: false },
})

const emit = defineEmits(['update:modelValue', 'change'])

const isChecked = computed(() => {
  if (props.radio) return String(props.modelValue) === String(props.value)
  if (Array.isArray(props.modelValue)) return props.modelValue.includes(props.value)
  return Boolean(props.modelValue)
})

function onChange(e) {
  const checked = e.target.checked
  if (props.radio) {
    emit('update:modelValue', props.value)
    emit('change', props.value)
    return
  }
  if (Array.isArray(props.modelValue)) {
    const arr = [...props.modelValue]
    const idx = arr.indexOf(props.value)
    if (checked && idx === -1) arr.push(props.value)
    if (!checked && idx > -1) arr.splice(idx, 1)
    emit('update:modelValue', arr)
    emit('change', arr)
  } else {
    emit('update:modelValue', checked)
    emit('change', checked)
  }
}
</script>

<template>
  <label
    class="ff-check"
    :class="[
      radio ? 'ff-check--radio' : 'ff-check--checkbox',
      disabled && 'ff-check--disabled',
      isChecked && 'ff-check--checked',
      indeterminate && !radio && 'ff-check--indeterminate',
    ]"
  >
    <input
      :type="radio ? 'radio' : 'checkbox'"
      :checked="isChecked"
      :value="value"
      :disabled="disabled"
      class="ff-check__input"
      @change="onChange"
    />
    <span class="ff-check__box" aria-hidden="true">
      <svg v-if="!radio" class="ff-check__tick" viewBox="0 0 16 16" fill="none">
        <path d="M3.5 8L6.5 11L12.5 5" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round" />
      </svg>
      <span v-else class="ff-check__dot" />
    </span>
    <span v-if="label || $slots.default" class="ff-check__label">
      <slot>{{ label }}</slot>
    </span>
  </label>
</template>
