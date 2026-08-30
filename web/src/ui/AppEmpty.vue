<script setup>
/**
 * AppEmpty — 空状态
 */
import { computed } from 'vue'
import AppIcon from './AppIcon.vue'

const props = defineProps({
  title: { type: String, default: '暂无数据' },
  description: { type: String, default: '' },
  icon: { type: String, default: 'inbox' },
  size: { type: String, default: 'md' }, // xs / sm / md / lg
})

// 样式层只提供 compact 一档，xs/sm 映射过去
const sizeCls = computed(() =>
  ['xs', 'sm'].includes(props.size) ? 'ff-empty--compact' : ''
)
</script>

<template>
  <div class="ff-empty" :class="sizeCls">
    <div class="ff-empty__icon">
      <AppIcon :name="icon" size="xl" />
    </div>
    <h4 class="ff-empty__title">{{ title }}</h4>
    <p v-if="description || $slots.description" class="ff-empty__desc">
      <slot name="description">{{ description }}</slot>
    </p>
    <div v-if="$slots.action" class="ff-empty__action">
      <slot name="action" />
    </div>
  </div>
</template>
