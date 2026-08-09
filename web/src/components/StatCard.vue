<script setup>
defineProps({
  label: { type: String, default: '' },
  value: { type: [String, Number], default: '—' },
  sub: { type: String, default: '' },
  tone: { type: String, default: '' }, // '', up, down
})
</script>

<template>
  <div class="stat-card card">
    <div class="label">{{ label }}</div>
    <div class="value num" :class="tone">{{ value }}</div>
    <div v-if="sub" class="sub text-3">{{ sub }}</div>
  </div>
</template>

<style scoped>
.stat-card {
  padding: var(--sp-4) var(--sp-5);
  display: flex;
  flex-direction: column;
  gap: 6px;
}
.label {
  font-size: var(--fs-sm);
  color: var(--text-2);
}
.value {
  font-size: var(--fs-2xl);
  font-weight: 600;
  line-height: 1.2;
}
.sub {
  font-size: var(--fs-xs);
}
</style>
