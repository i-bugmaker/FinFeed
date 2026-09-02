<script setup>
// 通用 ECharts 容器：注入统一主题底座（文字/坐标轴/tooltip），
// 主题切换后自动以新令牌重渲染（canvas 无法消费 CSS var）。
import { ref, onMounted, onUnmounted, watch, nextTick } from 'vue'
import { echarts } from '@/shared/lib/echarts'
import { chartBaseTheme, useChartTheme } from '@/composables/useChartTheme'

const props = defineProps({
  option: { type: Object, required: true },
  height: { type: String, default: '300px' },
})
const el = ref(null)
let chart = null
let ro = null

function render() {
  if (!chart) return
  chart.setOption({ ...chartBaseTheme(), ...props.option }, true)
}

function resize() {
  chart && chart.resize()
}

onMounted(async () => {
  await nextTick()
  chart = echarts.init(el.value, null, { renderer: 'canvas' })
  render()
  window.addEventListener('resize', resize)
  ro = new ResizeObserver(resize)
  if (el.value) ro.observe(el.value)
})
onUnmounted(() => {
  window.removeEventListener('resize', resize)
  ro && ro.disconnect()
  chart && chart.dispose()
  chart = null
})
watch(
  () => props.option,
  () => render(),
  { deep: true },
)
// 主题切换 → 以新令牌值重渲染（修复：此前无 watcher，切主题后画布保留旧配色）
useChartTheme(render)
</script>

<template>
  <div ref="el" class="ff-chart" :style="{ height }"></div>
</template>

<style scoped>
.ff-chart {
  width: 100%;
}
</style>
