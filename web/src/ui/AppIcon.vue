<script setup>
/**
 * AppIcon — 统一矢量图标出口
 * 全站唯一的图标渲染入口，禁止直接内联 <svg> 或使用 emoji。
 *
 * <AppIcon name="search" />                    默认 18px
 * <AppIcon name="star" size="sm" />            尺寸令牌 xs|sm|md|lg|xl
 * <AppIcon name="flame" :size="28" tone="up" />数字尺寸 + 语义色
 * <AppIcon name="refresh" spin />              旋转（加载态）
 */
import { computed } from 'vue'
import { ICONS } from './icons'

const props = defineProps({
  name: { type: String, required: true },
  size: { type: [String, Number], default: 'md' },
  stroke: { type: [String, Number], default: null },
  tone: { type: String, default: '' }, // '' | brand | up | down | warn | muted | inverse
  color: { type: String, default: '' }, // 任意 CSS 颜色（如 var(--ff-brand)），优先级高于 tone
  spin: { type: Boolean, default: false },
  label: { type: String, default: '' }, // 提供后视为语义图标，暴露给读屏
})

const SIZE_TOKENS = { xs: 14, sm: 16, md: 18, lg: 20, xl: 24 }

const px = computed(() => {
  if (typeof props.size === 'number') return props.size
  return SIZE_TOKENS[props.size] ?? SIZE_TOKENS.md
})

const colorStyle = computed(() => (props.color ? { color: props.color } : null))

// 小尺寸自动加粗描边，避免视觉过淡
const strokeWidth = computed(() => {
  if (props.stroke != null) return props.stroke
  if (px.value <= 14) return 2
  if (px.value >= 28) return 1.6
  return 1.75
})

const body = computed(() => ICONS[props.name] || ICONS.dot)
</script>

<template>
  <svg
    class="ff-icon"
    :class="[tone ? `ff-icon--${tone}` : '', { 'ff-icon--spin': spin }]"
    :style="colorStyle"
    :width="px"
    :height="px"
    viewBox="0 0 24 24"
    fill="none"
    stroke="currentColor"
    :stroke-width="strokeWidth"
    stroke-linecap="round"
    stroke-linejoin="round"
    :role="label ? 'img' : 'presentation'"
    :aria-label="label || undefined"
    :aria-hidden="label ? undefined : 'true'"
    focusable="false"
    v-html="body"
  />
</template>

<style scoped>
.ff-icon {
  display: inline-block;
  flex-shrink: 0;
  vertical-align: middle;
  overflow: visible;
}
.ff-icon--brand {
  color: var(--ff-brand);
}
.ff-icon--up {
  color: var(--ff-up);
}
.ff-icon--down {
  color: var(--ff-down);
}
.ff-icon--warn {
  color: var(--ff-warn);
}
.ff-icon--muted {
  color: var(--ff-text-tertiary);
}
.ff-icon--inverse {
  color: var(--ff-text-inverse);
}
.ff-icon--spin {
  animation: ff-spin 900ms linear infinite;
}
</style>
