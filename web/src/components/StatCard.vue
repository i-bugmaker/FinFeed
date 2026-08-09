<script setup>
defineProps({
  label: { type: String, default: '' },
  value: { type: [String, Number], default: '—' },
  sub: { type: String, default: '' },
  tone: { type: String, default: '' }, // '', up, down
})
</script>

<template>
  <div class="ff-statcard" :class="tone && `ff-statcard--${tone}`">
    <div class="ff-statcard__label">{{ label }}</div>
    <div class="ff-statcard__value ff-num" :class="tone && `ff-t-${tone}`">{{ value }}</div>
    <div v-if="sub" class="ff-statcard__sub">{{ sub }}</div>
  </div>
</template>

<style scoped>
.ff-statcard {
  position: relative;
  padding: var(--ff-space-4) var(--ff-space-5);
  display: flex;
  flex-direction: column;
  gap: var(--ff-space-2);
  background: var(--ff-bg-surface);
  border: 1px solid var(--ff-border);
  border-radius: var(--ff-radius-lg);
  box-shadow: var(--ff-shadow-sm);
  overflow: hidden;
  transition:
    transform var(--ff-dur-fast) var(--ff-ease-standard),
    box-shadow var(--ff-dur-fast) var(--ff-ease-standard);
}
.ff-statcard::before {
  content: '';
  position: absolute;
  left: 0;
  top: 0;
  bottom: 0;
  width: 3px;
  background: var(--ff-border-strong);
}
.ff-statcard--up::before {
  background: var(--ff-up);
}
.ff-statcard--down::before {
  background: var(--ff-down);
}
.ff-statcard:hover {
  box-shadow: var(--ff-shadow-md);
}

.ff-statcard__label {
  font-size: var(--ff-fs-body-sm);
  color: var(--ff-text-secondary);
  font-weight: 500;
}

.ff-statcard__value {
  font-size: var(--ff-fs-2xl);
  font-weight: 600;
  line-height: var(--ff-lh-tight);
  color: var(--ff-text-primary);
  letter-spacing: var(--ff-ls-tight);
}

.ff-statcard__sub {
  font-size: var(--ff-fs-caption);
  color: var(--ff-text-tertiary);
}
</style>