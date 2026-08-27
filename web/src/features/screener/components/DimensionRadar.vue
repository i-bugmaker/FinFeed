<script setup>
// 六维子分雷达图（ECharts），用于个股下钻：维度画像可视化。
import { ref, onMounted, onBeforeUnmount, watch } from 'vue'
import { echarts } from '@/shared/lib/echarts'

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
      axisName: { color: '#64748b', fontSize: 10 },
      splitArea: { areaStyle: { color: ['#f8fafc', '#f1f5f9'] } },
      splitLine: { lineStyle: { color: '#e2e8f0' } },
      axisLine: { lineStyle: { color: '#e2e8f0' } },
    },
    series: [
      {
        type: 'radar',
        symbolSize: 3,
        data: [{ value, name: '维度画像' }],
        areaStyle: { color: 'rgba(47, 125, 91, 0.25)' },
        lineStyle: { color: '#2f7d5b', width: 2 },
        itemStyle: { color: '#2f7d5b' },
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
</script>

<template>
  <div ref="elRef" :style="{ width, height: height + 'px' }" class="dim-radar" />
</template>

<style scoped>
.dim-radar {
  flex: none;
}
</style>
