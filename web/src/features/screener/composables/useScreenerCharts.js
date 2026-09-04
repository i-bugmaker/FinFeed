// ScreenerView 图表层：ECharts 实例管理 + 六张图的 option 构造 + 渲染编排。
// 从 1,945 行的 ScreenerView.vue 抽出（阶段3-b 示范拆分）：
// 视图保留布局与业务编排，图表细节全部下沉本组合式函数。
import { ref, watch, nextTick } from 'vue'
import { echarts } from '@/shared/lib/echarts'
import { chartVar, chartFont, axisLabelStyle, useChartTheme } from '@/composables/useChartTheme'

/**
 * @param {object} ctx
 * @param {import('vue').ComputedRef} ctx.result          评分结果（store.task?.result）
 * @param {() => any} ctx.getEvalResult                   评估闭环结果（store.evalResult）
 * @param {import('vue').Ref<string>} ctx.activeTab       当前页签
 * @param {string[]} ctx.dimOrder                         维度顺序
 * @param {Record<string,string>} ctx.DIM_LABELS          维度中文名
 * @param {Record<string,string>} ctx.BOARD_LABEL         板块中文名
 * @param {import('vue').Ref<boolean>} ctx.panelOpen      窄屏抽屉开关（resize 时联动收起）
 */
export function useScreenerCharts({ result, getEvalResult, activeTab, dimOrder, DIM_LABELS, BOARD_LABEL, panelOpen }) {
  const scoreDistRef = ref(null)
  const boardPieRef = ref(null)
  const tierBarRef = ref(null)
  const dimAvgRef = ref(null)
  const evalLayersRef = ref(null)
  const evalDimRef = ref(null)
  const chartMap = {}

  function setChart(id, el, option) {
    if (!el) return
    if (!chartMap[id]) chartMap[id] = echarts.init(el)
    chartMap[id].setOption(option, true)
    chartMap[id].resize()
  }
  function resizeAll() {
    Object.values(chartMap).forEach((c) => c.resize())
    // 跨回桌面断点时收起抽屉态，避免残留遮罩
    if (window.innerWidth >= 1181 && panelOpen.value) panelOpen.value = false
  }
  function disposeCharts() {
    Object.values(chartMap).forEach((c) => c.dispose())
  }

  function scoreDistOption(res) {
    const vals = res.scores.map((s) => s.total_score)
    const min = Math.floor(Math.min(...vals) / 5) * 5
    const max = Math.ceil(Math.max(...vals) / 5) * 5
    const bins = []
    for (let b = min; b < max; b += 5) bins.push({ from: b, to: b + 5 })
    const counts = bins.map((b) => vals.filter((v) => v >= b.from && v < b.to).length)
    return {
      tooltip: { trigger: 'axis', axisPointer: { type: 'shadow' } },
      grid: { left: 40, right: 12, top: 16, bottom: 28 },
      xAxis: { type: 'category', data: bins.map((b) => `${b.from}-${b.to}`), axisLabel: axisLabelStyle() },
      yAxis: { type: 'value', minInterval: 1, axisLabel: axisLabelStyle() },
      series: [{
        name: '数量', type: 'bar', data: counts, barWidth: '70%',
        itemStyle: { color: chartVar('--ff-brand', '#2563eb'), borderRadius: [3, 3, 0, 0] },
      }],
    }
  }
  function boardPieOption(res) {
    const counts = {}
    res.scores.forEach((s) => { counts[BOARD_LABEL[s.board] || s.board] = (counts[BOARD_LABEL[s.board] || s.board] || 0) + 1 })
    const data = Object.entries(counts).map(([name, value]) => ({ name, value }))
    return {
      tooltip: { trigger: 'item', formatter: '{b}: {c} ({d}%)' },
      legend: { bottom: 0, textStyle: { fontSize: chartFont(11), color: chartVar('--ff-text-secondary', '#475569') } },
      series: [{
        type: 'pie', radius: ['42%', '68%'], center: ['50%', '44%'],
        itemStyle: { borderColor: chartVar('--ff-bg-surface', '#ffffff'), borderWidth: 2 },
        data,
      }],
    }
  }
  function tierBarOption(res) {
    const names = ['入选', '关注', '观察', '不入选']
    const keys = ['strong', 'watch', 'observe', 'none']
    const counts = keys.map((k) => res.scores.filter((s) => s.tier === k).length)
    return {
      tooltip: { trigger: 'axis', axisPointer: { type: 'shadow' } },
      grid: { left: 40, right: 12, top: 16, bottom: 28 },
      xAxis: { type: 'category', data: names, axisLabel: { fontSize: chartFont(11), color: chartVar('--ff-text-secondary', '#475569') } },
      yAxis: { type: 'value', minInterval: 1, axisLabel: axisLabelStyle() },
      series: [{
        type: 'bar', data: counts, barWidth: '46%',
        itemStyle: { color: chartVar('--ff-brand', '#2563eb'), borderRadius: [3, 3, 0, 0] },
      }],
    }
  }
  // 「入选组 vs 全体」的八维平均分对比：直接回答「入选的股票强在哪」，
  // 替代信息价值有限的原「综合分×当日涨跌」散点图
  function dimAvgOption(res) {
    const strong = res.scores.filter((s) => s.tier === 'strong')
    const avg = (arr) => dimOrder.map((d) => (
      arr.length
        ? arr.reduce((s, r) => s + (Number(r[`${d}_score`]) || 0), 0) / arr.length
        : 0
    ))
    return {
      tooltip: { trigger: 'axis', valueFormatter: (v) => Number(v).toFixed(1) },
      legend: { top: 0, textStyle: { fontSize: chartFont(11), color: chartVar('--ff-text-secondary', '#475569') } },
      grid: { left: 44, right: 16, top: 30, bottom: 30 },
      xAxis: { type: 'category', data: dimOrder.map((d) => DIM_LABELS[d]), axisLabel: axisLabelStyle() },
      yAxis: { type: 'value', max: 100, axisLabel: axisLabelStyle() },
      series: [
        {
          name: '入选组均分', type: 'bar', data: avg(strong), barWidth: '32%',
          itemStyle: { color: chartVar('--ff-brand', '#2563eb'), borderRadius: [3, 3, 0, 0] },
        },
        {
          name: '全体均分', type: 'bar', data: avg(res.scores), barWidth: '32%',
          itemStyle: { color: chartVar('--ff-text-tertiary', '#94a3b8'), borderRadius: [3, 3, 0, 0] },
        },
      ],
    }
  }
  function layersOption(ev) {
    const keys = Object.keys(ev.layers || {})
    return {
      tooltip: { trigger: 'axis', axisPointer: { type: 'shadow' } },
      grid: { left: 44, right: 12, top: 16, bottom: 28 },
      xAxis: { type: 'category', data: keys, axisLabel: { fontSize: chartFont(11), color: chartVar('--ff-text-secondary', '#475569') } },
      yAxis: { type: 'value', name: '前瞻收益 %', axisLabel: axisLabelStyle() },
      series: [{
        type: 'bar', data: keys.map((k) => ev.layers[k]), barWidth: '52%',
        itemStyle: {
          color: (p) => (p.data >= 0 ? chartVar('--ff-up', '#e11d48') : chartVar('--ff-down', '#059669')),
          borderRadius: [3, 3, 0, 0],
        },
      }],
    }
  }
  function dimIcOption(ev) {
    const pd = ev.per_dimension || {}
    const dims = Object.keys(pd)
    const colors = dims.map((d) => {
      const icir = pd[d].icir
      if (icir < 0.5) return chartVar('--ff-danger', '#dc2626')
      if (icir < 1.0) return chartVar('--ff-warn', '#d97706')
      return chartVar('--ff-brand', '#2563eb')
    })
    return {
      tooltip: { trigger: 'axis', axisPointer: { type: 'shadow' } },
      grid: { left: 44, right: 12, top: 16, bottom: 28 },
      xAxis: { type: 'category', data: dims.map((d) => DIM_LABELS[d] || d), axisLabel: { fontSize: chartFont(11), color: chartVar('--ff-text-secondary', '#475569') } },
      yAxis: { type: 'value', name: 'ICIR', axisLabel: axisLabelStyle() },
      series: [{
        type: 'bar', data: dims.map((d) => pd[d].icir), barWidth: '46%',
        itemStyle: { color: (p) => colors[p.dataIndex], borderRadius: [3, 3, 0, 0] },
      }],
    }
  }

  function renderCharts() {
    const res = result.value
    if (!res || !res.scores?.length) return
    setChart('scoreDist', scoreDistRef.value, scoreDistOption(res))
    setChart('boardPie', boardPieRef.value, boardPieOption(res))
    setChart('tierBar', tierBarRef.value, tierBarOption(res))
    setChart('dimAvg', dimAvgRef.value, dimAvgOption(res))
  }
  function renderEvalCharts() {
    const ev = getEvalResult()
    if (!ev || ev.error) return
    if (ev.layers && Object.keys(ev.layers).length) setChart('evalLayers', evalLayersRef.value, layersOption(ev))
    if (ev.per_dimension && Object.keys(ev.per_dimension).length) setChart('evalDim', evalDimRef.value, dimIcOption(ev))
  }

  watch(activeTab, (t) => {
    nextTick(() => {
      if (t === 'charts') renderCharts()
      if (t === 'evaluate') renderEvalCharts()
    })
  })
  watch(result, () => { if (activeTab.value === 'charts') nextTick(renderCharts) })
  watch(() => getEvalResult(), () => { if (activeTab.value === 'evaluate') nextTick(renderEvalCharts) })

  // 主题切换后以新令牌值重渲染当前可见图表（统一主题出口，canvas 无法消费 CSS var）
  useChartTheme(() => {
    if (activeTab.value === 'charts') renderCharts()
    if (activeTab.value === 'evaluate') renderEvalCharts()
  })

  return {
    scoreDistRef, boardPieRef, tierBarRef, dimAvgRef, evalLayersRef, evalDimRef,
    resizeAll, renderCharts, renderEvalCharts, disposeCharts,
  }
}
