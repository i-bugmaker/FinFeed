<script setup>
/**
 * AppBadge — 徽标
 */
defineProps({
  text: { type: [String, Number], default: '' },
  variant: { type: String, default: 'default' }, // default / up / down / warn / success / muted / brand
  dot: { type: Boolean, default: false },
})
</script>

<template>
  <span class="ff-badge" :class="`ff-badge--${variant}`">
    <span v-if="dot" class="ff-badge__dot" />
    <slot>{{ text }}</slot>
  </span>
</template>
