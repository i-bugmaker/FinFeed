<script setup>
// 八维子分雷达图（ECharts），用于个股下钻：维度画像可视化。
// 颜色经统一主题出口解析语义令牌，并随主题切换重渲染（canvas 无法消费 CSS var）。
import { ref, onMounted, onBeforeUnmount, watch } from 'vue'
import { echarts } from '@/shared/lib/echarts'
import { chartVar, chartFont, hexToRgba, useChartTheme } from '@/composables/useChartTheme'

const props = defineProps({
  dims: { type: Object, default: () => ({}) },
  width: { type: [Number, String], default: '100%' },
  height: { type: Number, default: 200 },
})

const DIM_LABELS = {
  capital: '资金面',
  momentum: '动量趋势',
  valuation: '估值',
  liquidity: '量价活跃',
  quality: '质量稳定',
  sentiment: '情绪/事件',
  growth: '成长性',
  reversal: '反转修复',
}

const elRef = ref(null)
let chart = null

function render() {
  if (!chart) return
  const dims = props.dims || {}
  const indicators = Object.keys(DIM_LABELS).map((k) => ({
    name: DIM_LABELS[k],
    max: 100,
  }))
  const value = Object.keys(DIM_LABELS).map((k) => {
    const v = Number(dims[k])
    return Number.isFinite(v) ? v : 0
  })
  const brand = chartVar('--ff-brand', '#2563eb')
  chart.setOption({
    tooltip: {
      trigger: 'item',
      formatter: (p) => {
        const v = Number(p.value)
        return `${DIM_LABELS[p.name] || p.name}<br/><b>${Number.isFinite(v) ? v.toFixed(1) : '—'}</b> / 100`
      },
    },
    radar: {
      indicator: indicators,
      radius: '62%',
      axisName: { color: chartVar('--ff-text-secondary', '#475569'), fontSize: chartFont(10) },
      splitArea: { areaStyle: { color: [chartVar('--ff-bg-subtle', '#f8fafc'), chartVar('--ff-bg-muted', '#f1f5f9')] } },
      splitLine: { lineStyle: { color: chartVar('--ff-border', '#e2e8f0') } },
      axisLine: { lineStyle: { color: chartVar('--ff-border', '#e2e8f0') } },
    },
    series: [
      {
        type: 'radar',
        symbolSize: 3,
        data: [{ value, name: '维度画像' }],
        areaStyle: { color: hexToRgba(brand, 0.25) },
        lineStyle: { color: brand, width: 2 },
        itemStyle: { color: brand },
      },
    ],
  })
}

function resize() {
  chart && chart.resize()
}

onMounted(() => {
  if (!elRef.value) return
  chart = echarts.init(elRef.value)
  render()
  window.addEventListener('resize', resize)
})

onBeforeUnmount(() => {
  window.removeEventListener('resize', resize)
  if (chart) {
    chart.dispose()
    chart = null
  }
})

watch(
  () => props.dims,
  () => render(),
  { deep: true },
)
// 主题切换后以新令牌值重渲染
useChartTheme(render)
</script>

<template>
  <div ref="elRef" :style="{ width, height: height + 'px' }" class="dim-radar" />
</template>

<style scoped>
.dim-radar {
  flex: none;
}
</style>
