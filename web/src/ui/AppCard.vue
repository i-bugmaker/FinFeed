<script setup>
/**
 * AppCard — 卡片容器
 */
defineProps({
  title: { type: String, default: '' },
  subtitle: { type: String, default: '' },
  interactive: { type: Boolean, default: false },
  flat: { type: Boolean, default: false },
  elevated: { type: Boolean, default: false },
  noPadding: { type: Boolean, default: false },
})
</script>

<template>
  <div
    class="ff-card"
    :class="[
      interactive && 'ff-card--interactive',
      flat && 'ff-card--flat',
      elevated && 'ff-card--elevated',
    ]"
  >
    <div v-if="title || subtitle || $slots.header || $slots.actions" class="ff-card__header">
      <div class="ff-card__meta">
        <h3 v-if="title" class="ff-card__title">{{ title }}</h3>
        <p v-if="subtitle" class="ff-card__subtitle">{{ subtitle }}</p>
        <slot name="header" />
      </div>
      <div v-if="$slots.actions" class="ff-card__actions">
        <slot name="actions" />
      </div>
    </div>
    <div class="ff-card__body" :class="noPadding && 'ff-card__body--no-padding'">
      <slot />
    </div>
    <div v-if="$slots.footer" class="ff-card__footer">
      <slot name="footer" />
    </div>
  </div>
</template>
