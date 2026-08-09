<script setup>
/**
 * AppSkeleton — 骨架屏
 *
 * 变体：text / title / circle / block / card
 */
defineProps({
  variant: { type: String, default: 'text' },
  lines: { type: Number, default: 1 },
  width: { type: String, default: '' },
  height: { type: String, default: '' },
  rounded: { type: Boolean, default: false },
})
</script>

<template>
  <div class="ff-skeleton" :class="[`ff-skeleton--${variant}`, rounded && 'ff-skeleton--rounded']">
    <div
      v-for="i in (variant === 'text' ? lines : 1)"
      :key="i"
      class="ff-skeleton__item"
      :class="`ff-skeleton__item--${variant}`"
      :style="{ width, height }"
    />
  </div>
</template>
