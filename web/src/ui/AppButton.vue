<script setup>
/**
 * AppButton — 自绘按钮组件
 *
 * 变体：primary / secondary / tonal / ghost / danger / danger-ghost
 * 尺寸：xs / sm / md / lg / block / icon
 * 状态：loading / disabled / active
 */
import { computed, useSlots } from 'vue'
import AppIcon from './AppIcon.vue'

const slots = useSlots()
const props = defineProps({
  variant: { type: String, default: 'primary' },
  size: { type: String, default: 'md' },
  type: { type: String, default: 'button' },
  disabled: { type: Boolean, default: false },
  loading: { type: Boolean, default: false },
  active: { type: Boolean, default: false },
  block: { type: Boolean, default: false },
  pill: { type: Boolean, default: false },
  icon: { type: String, default: '' },
  iconRight: { type: String, default: '' },
  href: { type: String, default: '' },
  target: { type: String, default: '' },
})

const emit = defineEmits(['click'])

const cls = computed(() => [
  'ff-btn',
  `ff-btn--${props.variant}`,
  `ff-btn--${props.size}`,
  props.block && 'ff-btn--block',
  props.pill && 'ff-btn--pill',
  props.loading && 'ff-btn--loading',
  props.active && 'ff-btn--active',
])

const isIconOnly = computed(() => {
  return props.icon && !slots.default && !props.iconRight
})

function onClick(e) {
  if (props.loading || props.disabled) return
  emit('click', e)
}
</script>

<template>
  <component
    :is="href ? 'a' : 'button'"
    :type="href ? undefined : type"
    :href="href || undefined"
    :target="target || undefined"
    :class="[cls, isIconOnly && 'ff-btn--icon']"
    :disabled="disabled || loading"
    :aria-disabled="disabled || loading"
    @click="onClick"
  >
    <span v-if="loading" class="ff-btn__spinner" aria-hidden="true">
      <AppIcon name="refresh" :size="size === 'xs' ? 12 : size === 'lg' ? 18 : 14" spin />
    </span>
    <AppIcon v-else-if="icon" :name="icon" :size="size === 'xs' ? 12 : size === 'lg' ? 18 : 14" />
    <span v-if="$slots.default" class="ff-btn__label"><slot /></span>
    <AppIcon v-if="iconRight" :name="iconRight" :size="size === 'xs' ? 12 : size === 'lg' ? 18 : 14" />
  </component>
</template>
