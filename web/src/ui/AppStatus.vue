<script setup>
/**
 * AppStatus — 状态点
 */
defineProps({
  text: { type: String, default: '' },
  tone: { type: String, default: 'neutral' }, // neutral / success / warn / danger / brand / up / down
  pulse: { type: Boolean, default: false },
})
</script>

<template>
  <span class="ff-status" :class="`ff-status--${tone}`">
    <span class="ff-status__dot" :class="pulse && 'ff-status__dot--pulse'" />
    <span v-if="text || $slots.default" class="ff-status__label">
      <slot>{{ text }}</slot>
    </span>
  </span>
</template>
