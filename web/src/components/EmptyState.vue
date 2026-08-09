<script setup>
defineProps({
  text: { type: String, default: '暂无数据' },
  icon: { type: String, default: 'inbox' },
})
</script>

<template>
  <AppEmpty class="ff-empty-state" :title="text" :icon="icon" />
</template>

<style scoped>
.ff-empty-state {
  padding: var(--ff-space-16) 0;
}
</style>
