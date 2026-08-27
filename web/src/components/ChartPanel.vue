<script setup>
import { ref, onMounted, onUnmounted, watch, nextTick } from 'vue'
import { echarts } from '@/shared/lib/echarts'

const props = defineProps({
  option: { type: Object, required: true },
  height: { type: String, default: '300px' },
})
const el = ref(null)
let chart = null
let ro = null

function themeColor(name) {
  return getComputedStyle(document.documentElement).getPropertyValue(name).trim() || undefined
}

function baseTheme() {
  const text = themeColor('--ff-text-primary')
  const muted = themeColor('--ff-text-secondary')
  const border = themeColor('--ff-border')
  return {
    backgroundColor: 'transparent',
    textStyle: { color: text },
    title: { textStyle: { color: text }, subtextStyle: { color: muted } },
    legend: { textStyle: { color: muted } },
    tooltip: {
      backgroundColor: themeColor('--ff-bg-surface'),
      borderColor: border,
      textStyle: { color: text },
    },
    xAxis: { axisLine: { lineStyle: { color: border } }, axisLabel: { color: muted }, splitLine: { lineStyle: { color: themeColor('--ff-bg-subtle') } } },
    yAxis: { axisLine: { lineStyle: { color: border } }, axisLabel: { color: muted }, splitLine: { lineStyle: { color: themeColor('--ff-bg-subtle') } } },
  }
}

function render() {
  if (!chart) return
  chart.setOption({ ...baseTheme(), ...props.option }, true)
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
</script>

<template>
  <div ref="el" class="ff-chart" :style="{ height }"></div>
</template>

<style scoped>
.ff-chart {
  width: 100%;
}
</style>
