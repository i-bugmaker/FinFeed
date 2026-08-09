<script setup>
defineProps({
  label: { type: String, default: '' },
  value: { type: [String, Number], default: '—' },
  sub: { type: String, default: '' },
  tone: { type: String, default: '' }, // '', up, down
})
</script>

<template>
  <div class="ff-statcard">
    <div class="ff-statcard__label">{{ label }}</div>
    <div class="ff-statcard__value ff-num" :class="tone && `ff-t-${tone}`">{{ value }}</div>
    <div v-if="sub" class="ff-statcard__sub">{{ sub }}</div>
  </div>
</template>

<style scoped>
.ff-statcard {
  padding: var(--ff-space-4) var(--ff-space-5);
  display: flex;
  flex-direction: column;
  gap: var(--ff-space-1);
  background: var(--ff-bg-surface);
  border: 1px solid var(--ff-border);
  border-radius: var(--ff-radius-lg);
  box-shadow: var(--ff-shadow-sm);
}

.ff-statcard__label {
  font-size: var(--ff-fs-sm);
  color: var(--ff-text-secondary);
}

.ff-statcard__value {
  font-size: var(--ff-fs-2xl);
  font-weight: 600;
  line-height: var(--ff-lh-tight);
  color: var(--ff-text-primary);
}

.ff-statcard__sub {
  font-size: var(--ff-fs-xs);
  color: var(--ff-text-tertiary);
}
</style>
