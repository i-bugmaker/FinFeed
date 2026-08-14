<script setup>
defineProps({
  text: { type: String, default: '暂无数据' },
  icon: { type: String, default: 'inbox' },
})
</script>

<template>
  <AppEmpty class="ff-empty-state" :title="text" :icon="icon">
    <template v-if="$slots.description" #description>
      <slot name="description" />
    </template>
    <template v-if="$slots.action" #action>
      <slot name="action" />
    </template>
  </AppEmpty>
</template>

<style scoped>
.ff-empty-state {
  padding: var(--ff-space-16) 0;
}
</style>
