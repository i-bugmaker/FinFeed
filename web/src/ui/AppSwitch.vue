<script setup>
/**
 * AppSwitch — 自定义开关
 */
import { computed } from 'vue'

const props = defineProps({
  modelValue: { type: Boolean, default: false },
  label: { type: String, default: '' },
  disabled: { type: Boolean, default: false },
})

const emit = defineEmits(['update:modelValue', 'change'])

const cls = computed(() => [
  'ff-switch',
  props.modelValue && 'ff-switch--checked',
  props.disabled && 'ff-switch--disabled',
])

function toggle() {
  if (props.disabled) return
  const v = !props.modelValue
  emit('update:modelValue', v)
  emit('change', v)
}
</script>

<template>
  <label :class="cls">
    <input
      type="checkbox"
      class="ff-switch__input"
      :checked="modelValue"
      :disabled="disabled"
      @change="toggle"
    />
    <span class="ff-switch__track" aria-hidden="true">
      <span class="ff-switch__thumb" />
    </span>
    <span v-if="label || $slots.default" class="ff-switch__label">
      <slot>{{ label }}</slot>
    </span>
  </label>
</template>
