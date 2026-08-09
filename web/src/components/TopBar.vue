<script setup>
import { ref, onMounted, onUnmounted } from 'vue'
import { useAppStore } from '../store/app'

const store = useAppStore()
const clock = ref('')
let timer = null

function tick() {
  const d = new Date()
  const p = (n) => String(n).padStart(2, '0')
  clock.value = `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())} ${p(d.getHours())}:${p(d.getMinutes())}:${p(d.getSeconds())}`
}

onMounted(() => {
  tick()
  timer = setInterval(tick, 1000)
})
onUnmounted(() => clearInterval(timer))
</script>

<template>
  <header class="topbar">
    <div class="left">
      <span class="status" :class="{ on: store.live }">
        <span class="dot"></span>{{ store.live ? '实时连接' : '连接中…' }}
      </span>
      <span class="clock num">{{ clock }}</span>
    </div>
    <div class="right">
      <button class="theme-btn" @click="store.toggleTheme()" :title="store.theme === 'light' ? '切换暗色' : '切换亮色'">
        {{ store.theme === 'light' ? '🌙' : '☀️' }}
      </button>
    </div>
  </header>
</template>

<style scoped>
.topbar {
  height: var(--header-h);
  flex-shrink: 0;
  background: var(--bg-surface);
  border-bottom: 1px solid var(--border);
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 0 var(--sp-5);
}
.left {
  display: flex;
  align-items: center;
  gap: var(--sp-4);
}
.status {
  display: inline-flex;
  align-items: center;
  gap: 7px;
  font-size: var(--fs-sm);
  color: var(--text-3);
}
.status .dot {
  width: 9px;
  height: 9px;
  border-radius: 50%;
  background: var(--text-3);
}
.status.on {
  color: var(--down);
}
.status.on .dot {
  background: var(--down);
  box-shadow: 0 0 0 4px var(--down-subtle);
}
.clock {
  font-size: var(--fs-sm);
  color: var(--text-1);
}
.right {
  display: flex;
  align-items: center;
  gap: var(--sp-3);
}
.theme-btn {
  width: 40px;
  height: 40px;
  border-radius: var(--r-sm);
  border: 1px solid var(--border);
  background: var(--bg-surface);
  font-size: 18px;
}
.theme-btn:hover {
  border-color: var(--primary);
}
</style>
