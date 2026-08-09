<script setup>
/**
 * AppSegmented — 分段控制器（用于紧凑的筛选/视图切换）
 */
import { computed } from 'vue'

const props = defineProps({
  modelValue: { type: [String, Number], default: '' },
  options: { type: Array, default: () => [] }, // { label, value, disabled }
  size: { type: String, default: 'md' },
})

const emit = defineEmits(['update:modelValue', 'change'])

const cls = computed(() => ['ff-segmented', `ff-segmented--${props.size}`])

function select(v) {
  if (v === props.modelValue) return
  emit('update:modelValue', v)
  emit('change', v)
}
</script>

<template>
  <div :class="cls" role="tablist">
    <button
      v-for="opt in options"
      :key="opt.value"
      type="button"
      class="ff-segmented__item"
      :class="[
        modelValue === opt.value && 'ff-segmented__item--active',
        opt.disabled && 'ff-segmented__item--disabled',
      ]"
      role="tab"
      :aria-selected="modelValue === opt.value"
      :disabled="opt.disabled"
      @click="select(opt.value)"
    >
      {{ opt.label }}
    </button>
  </div>
</template>
