<script setup>
/**
 * AppTabs — 标签页
 */
import { computed } from 'vue'

const props = defineProps({
  modelValue: { type: [String, Number], default: '' },
  items: { type: Array, default: () => [] }, // { label, value, disabled, badge }
  type: { type: String, default: 'line' }, // line | pill
  size: { type: String, default: 'md' },
})

const emit = defineEmits(['update:modelValue', 'change'])

const cls = computed(() => [
  'ff-tabs',
  `ff-tabs--${props.type}`,
  `ff-tabs--${props.size}`,
])

function select(v) {
  if (v === props.modelValue) return
  emit('update:modelValue', v)
  emit('change', v)
}
</script>

<template>
  <nav :class="cls" role="tablist">
    <button
      v-for="item in items"
      :key="item.value"
      type="button"
      class="ff-tabs__tab"
      :class="[
        modelValue === item.value && 'ff-tabs__tab--active',
        item.disabled && 'ff-tabs__tab--disabled',
      ]"
      role="tab"
      :aria-selected="modelValue === item.value"
      :disabled="item.disabled"
      @click="select(item.value)"
    >
      {{ item.label }}
      <span v-if="item.badge" class="ff-tabs__badge">{{ item.badge }}</span>
    </button>
  </nav>
</template>
