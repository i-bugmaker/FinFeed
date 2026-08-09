<script setup>
defineProps({
  text: { type: String, default: '暂无数据' },
})
</script>

<template>
  <div class="empty">
    <div class="ico">🗂️</div>
    <p class="text-3">{{ text }}</p>
  </div>
</template>

<style scoped>
.empty {
  text-align: center;
  padding: 60px 0;
}
.ico {
  font-size: 40px;
  opacity: 0.5;
}
.empty p {
  margin-top: 12px;
  font-size: var(--fs-base);
}
</style>
