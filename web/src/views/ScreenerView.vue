<script setup>
// 智能选股 · Web 工作台（P4 重构版）
// 左侧：策略配置面板（引擎/权重/过滤/输出/模板/对比）；右侧：结果/图表/评估 三个页签。
// 引擎支持：线性固定 / IC 客观加权 / 自动 / ML / 混合（后端 engine.mode 特性开关）。
import { ref, reactive, computed, watch, nextTick, onMounted, onBeforeUnmount } from 'vue'
import { echarts } from '@/shared/lib/echarts'
import { useScreenerStore } from '../store/screener'
import AppIcon from '../ui/AppIcon.vue'
import AppButton from '../ui/AppButton.vue'
import AppBadge from '../ui/AppBadge.vue'
import AppSwitch from '../ui/AppSwitch.vue'
import AppTabs from '../ui/AppTabs.vue'
import AppSelect from '../ui/AppSelect.vue'
import AppModal from '../ui/AppModal.vue'
import MarkdownView from '../components/ai/MarkdownView.vue'
import DimensionRadar from '../features/screener/components/DimensionRadar.vue'

const store = useScreenerStore()

// ═════════════════════════════ 策略配置 ═════════════════════════════
const ENGINE_MODES = [
  { value: 'linear', label: '线性固定' },
  { value: 'ic', label: 'IC 加权' },
  { value: 'auto', label: '自动' },
  { value: 'ml', label: 'ML' },
  { value: 'blend', label: '混合' },
]
const ENGINE_HINTS = {
  linear: '经验固定权重（零风险默认）',
  ic: '滚动 RankIC 客观权重（需历史快照）',
  auto: '有历史用 IC，否则回退固定',
  ml: 'ML 概率直接排序（需历史训练）',
  blend: '线性×α + ML×(1-α) 混合',
}
const engineMode = ref('linear')
const orthogonalize = ref(false)
const blendAlpha = ref(0.5)
const topQuantile = ref(0.3)
const horizon = ref(20)

const dimOrder = ['capital', 'momentum', 'valuation', 'liquidity', 'quality', 'sentiment']
const DIM_LABELS = {
  capital: '资金面', momentum: '动量趋势', valuation: '估值',
  liquidity: '量价活跃', quality: '质量稳定', sentiment: '情绪/事件',
}
const dimWeights = reactive({ capital: 20, momentum: 25, valuation: 18, liquidity: 15, quality: 12, sentiment: 10 })
const userTouchedWeights = ref(false)

// 输出与过滤
const top = ref(50)
const technical = ref(false)
const BOARD_OPTIONS = [
  { key: 'main', label: '主板' }, { key: 'kcb', label: '科创板' },
  { key: 'cyb', label: '创业板' }, { key: 'bj', label: '北交所' },
]
const BOARD_LABEL = { main: '主板', kcb: '科创板', cyb: '创业板', bj: '北交所' }
const boards = reactive({ main: true, kcb: true, cyb: true, bj: false })
const excludeSt = ref(true)
const minPrice = ref(3)
const maxPrice = ref(300)
const peMax = ref(100)
const minAmount = ref(1e8)
const minTurnover = ref(0.3)
const minCircCap = ref(3e9)

// 模板 / 对比
const templateName = ref('')
const loadTemplateName = ref('')
const compareTemplate = ref('')
const showCompare = ref(false)
const showStrategy = ref(false)   // 选股策略说明弹窗

// 表格
const activeTab = ref('result')
const sortKey = ref('total_score')
const sortDir = ref(-1)
const searchText = ref('')
const tierFilter = ref('all')
const selectedStock = ref(null)
const showDetail = computed({
  get: () => !!selectedStock.value,
  set: (v) => { if (!v) selectedStock.value = null },
})

// ═════════════════════════════ 本地固化（prefs）═════════════════════════════
// 用户配置持久化到 localStorage：引擎/权重/过滤/输出，下次打开自动恢复，无需重选。
const PREFS_KEY = 'finfeed.screener.prefs.v1'

function collectPrefs() {
  return {
    engineMode: engineMode.value,
    orthogonalize: orthogonalize.value,
    blendAlpha: blendAlpha.value,
    topQuantile: topQuantile.value,
    horizon: horizon.value,
    dimWeights: { ...dimWeights },
    userTouchedWeights: userTouchedWeights.value,
    top: top.value,
    technical: technical.value,
    boards: { ...boards },
    excludeSt: excludeSt.value,
    minPrice: minPrice.value,
    maxPrice: maxPrice.value,
    peMax: peMax.value,
    minAmount: minAmount.value,
    minTurnover: minTurnover.value,
    minCircCap: minCircCap.value,
  }
}
function readPrefs() {
  try {
    return JSON.parse(localStorage.getItem(PREFS_KEY) || 'null')
  } catch {
    return null
  }
}
function savePrefs() {
  try {
    localStorage.setItem(PREFS_KEY, JSON.stringify(collectPrefs()))
  } catch {
    /* 隐私模式等场景静默降级 */
  }
}
function applyPrefs(p) {
  if (!p) return
  if (ENGINE_MODES.some((m) => m.value === p.engineMode)) engineMode.value = p.engineMode
  if (typeof p.orthogonalize === 'boolean') orthogonalize.value = p.orthogonalize
  if (typeof p.blendAlpha === 'number') blendAlpha.value = p.blendAlpha
  if (typeof p.topQuantile === 'number') topQuantile.value = p.topQuantile
  if (typeof p.horizon === 'number') horizon.value = p.horizon
  if (p.dimWeights) {
    for (const d of dimOrder) {
      if (typeof p.dimWeights[d] === 'number') dimWeights[d] = p.dimWeights[d]
    }
  }
  if (typeof p.userTouchedWeights === 'boolean') userTouchedWeights.value = p.userTouchedWeights
  if (typeof p.top === 'number') top.value = p.top
  if (typeof p.technical === 'boolean') technical.value = p.technical
  if (p.boards) for (const k of Object.keys(boards)) if (typeof p.boards[k] === 'boolean') boards[k] = p.boards[k]
  if (typeof p.excludeSt === 'boolean') excludeSt.value = p.excludeSt
  if (typeof p.minPrice === 'number') minPrice.value = p.minPrice
  if (typeof p.maxPrice === 'number') maxPrice.value = p.maxPrice
  if (typeof p.peMax === 'number') peMax.value = p.peMax
  if (typeof p.minAmount === 'number') minAmount.value = p.minAmount
  if (typeof p.minTurnover === 'number') minTurnover.value = p.minTurnover
  if (typeof p.minCircCap === 'number') minCircCap.value = p.minCircCap
}
// 任一配置变化即持久化（对象 getter 依赖变化时触发）
watch(collectPrefs, savePrefs, { deep: true })

// 由后端默认配置初始化（权重 / 板块），之后用本地固化覆盖
watch(
  () => store.config,
  (cfg) => {
    if (!cfg) return
    if (cfg.weights) {
      for (const d of dimOrder) {
        if (typeof cfg.weights[d] === 'number') dimWeights[d] = Math.round(cfg.weights[d] * 1000) / 10
      }
    }
    const b = cfg.filters?.boards
    if (b && typeof b === 'object') {
      for (const k of Object.keys(boards)) if (typeof b[k] === 'boolean') boards[k] = b[k]
    }
    if (cfg.filters?.exclude_st === false) excludeSt.value = false
    if (typeof cfg.filters?.min_price === 'number') minPrice.value = cfg.filters.min_price
    if (typeof cfg.filters?.max_price === 'number') maxPrice.value = cfg.filters.max_price
    if (typeof cfg.filters?.pe_max === 'number') peMax.value = cfg.filters.pe_max
    if (typeof cfg.filters?.min_amount === 'number') minAmount.value = cfg.filters.min_amount
    if (typeof cfg.filters?.min_turnover === 'number') minTurnover.value = cfg.filters.min_turnover
    if (typeof cfg.filters?.min_circ_cap === 'number') minCircCap.value = cfg.filters.min_circ_cap
    if (cfg.engine?.blend_alpha != null) blendAlpha.value = cfg.engine.blend_alpha
    if (cfg.engine?.top_quantile != null) topQuantile.value = cfg.engine.top_quantile
    if (cfg.engine?.horizon != null) horizon.value = cfg.engine.horizon
    // 后端默认已就位后，用本地固化覆盖（用户偏好优先级最高）
    applyPrefs(readPrefs())
  },
  { immediate: true },
)

// 权重归一化：拖动单个滑块后整体归一化到 100%
function normalizeWeights() {
  const tot = dimOrder.reduce((s, d) => s + (Number(dimWeights[d]) || 0), 0)
  if (tot > 0) {
    for (const d of dimOrder) dimWeights[d] = Math.round((dimWeights[d] / tot) * 1000) / 10
  }
}
function onDimChange() {
  userTouchedWeights.value = true
  normalizeWeights()
}
function resetWeights() {
  if (!store.config?.weights) return
  for (const d of dimOrder) {
    if (typeof store.config.weights[d] === 'number') dimWeights[d] = Math.round(store.config.weights[d] * 1000) / 10
  }
  userTouchedWeights.value = false
}

// ═════════════════════════════ 请求构造 ═════════════════════════════
function buildRequest() {
  const strategy = {
    mode: engineMode.value,
    orthogonalize: orthogonalize.value,
    ml: { horizon: horizon.value, top_quantile: topQuantile.value },
  }
  if (engineMode.value === 'blend') strategy.blend_alpha = blendAlpha.value
  if (engineMode.value === 'linear' && userTouchedWeights.value) {
    strategy.dim_weights = {}
    for (const d of dimOrder) strategy.dim_weights[d] = Math.round(((dimWeights[d] || 0) / 100) * 10000) / 10000
  }
  return {
    universe: {
      boards: { ...boards },
      exclude_st: excludeSt.value,
      exclude_suspended: true,
      min_amount: minAmount.value,
      min_turnover: minTurnover.value,
      price_range: [minPrice.value, maxPrice.value],
      pe_ttm_range: [null, peMax.value],
      float_cap_range: [minCircCap.value, null],
    },
    strategy,
    output: { top: top.value },
  }
}

async function onRun() {
  store.errMsg = ''
  expandedRows.value = new Set()
  await store.run({ top: top.value, technical: technical.value, request: buildRequest() })
}

// ═════════════════════════════ 模板 ═════════════════════════════
const templateOptions = computed(() => store.templates.map((t) => ({ label: t.name, value: t.name })))

async function onSaveTemplate() {
  const name = templateName.value.trim()
  if (!name) {
    store.errMsg = '请输入模板名'
    return
  }
  try {
    await store.saveTemplate(name, buildRequest())
    store.errMsg = ''
  } catch (e) {
    store.errMsg = '保存模板失败：' + (e.message || e)
  }
}

function applyRequest(req) {
  if (!req) return
  const u = req.universe || {}
  const s = req.strategy || {}
  const o = req.output || {}
  if (u.boards) for (const k of Object.keys(boards)) if (typeof u.boards[k] === 'boolean') boards[k] = u.boards[k]
  if ('exclude_st' in u) excludeSt.value = !!u.exclude_st
  if (Array.isArray(u.price_range) && u.price_range.length === 2) {
    if (u.price_range[0] != null) minPrice.value = u.price_range[0]
    if (u.price_range[1] != null) maxPrice.value = u.price_range[1]
  }
  if (Array.isArray(u.pe_ttm_range) && u.pe_ttm_range.length === 2 && u.pe_ttm_range[1] != null) peMax.value = u.pe_ttm_range[1]
  if (u.min_amount != null) minAmount.value = u.min_amount
  if (u.min_turnover != null) minTurnover.value = u.min_turnover
  if (Array.isArray(u.float_cap_range) && u.float_cap_range.length === 2 && u.float_cap_range[0] != null) minCircCap.value = u.float_cap_range[0]
  if (s.mode) engineMode.value = s.mode
  if ('orthogonalize' in s) orthogonalize.value = !!s.orthogonalize
  if (s.blend_alpha != null) blendAlpha.value = s.blend_alpha
  const ml = s.ml || {}
  if (ml.horizon != null) horizon.value = ml.horizon
  if (ml.top_quantile != null) topQuantile.value = ml.top_quantile
  if (s.dim_weights) {
    userTouchedWeights.value = true
    for (const d of dimOrder) if (s.dim_weights[d] != null) dimWeights[d] = Math.round(s.dim_weights[d] * 1000) / 10
  }
  if (o.top != null) top.value = o.top
}

function onLoadTemplate() {
  const tpl = store.templates.find((t) => t.name === loadTemplateName.value)
  if (tpl) applyRequest(tpl.request)
}
async function onDeleteTemplate() {
  if (!loadTemplateName.value) return
  await store.deleteTemplate(loadTemplateName.value)
  loadTemplateName.value = ''
}

async function onCompare() {
  if (!compareTemplate.value) {
    store.errMsg = '请选择对比模板'
    return
  }
  const tpl = store.templates.find((t) => t.name === compareTemplate.value)
  if (!tpl) return
  store.errMsg = ''
  await store.compare(buildRequest(), tpl.request)
  showCompare.value = true
}

async function onEvaluate() {
  await store.evaluate({ request: buildRequest() })
  activeTab.value = 'evaluate'
}

// ═════════════════════════════ 表格 ═════════════════════════════
const result = computed(() => store.task?.result)
const task = computed(() => store.task)
const loading = computed(() => store.running)
const errMsg = computed(() => store.errMsg)
const logs = computed(() => task.value?.logs || [])
const latestLog = computed(() => (logs.value.length ? logs.value[logs.value.length - 1].msg : ''))
const expandedRows = ref(new Set())

const tierMeta = {
  strong: { label: '入选', variant: 'success' },
  watch: { label: '关注', variant: 'warn' },
  observe: { label: '观察', variant: 'muted' },
  none: { label: '不入选', variant: 'default' },
}

const headers = [
  { key: 'rank', label: '排名', w: '52px' },
  { key: 'code', label: '代码', w: '92px', sortable: true },
  { key: 'name', label: '名称', w: '104px', sortable: true },
  { key: 'board', label: '板块', w: '64px', sortable: true },
  { key: 'price', label: '现价', w: '76px', align: 'right', sortable: true },
  { key: 'change_pct', label: '涨跌幅', w: '84px', align: 'right', sortable: true },
  { key: 'total_score', label: '综合分', w: '78px', align: 'right', sortable: true },
  { key: 'ml_prob', label: 'ML 概率', w: '74px', align: 'right', sortable: true, mlOnly: true },
  { key: 'tier', label: '评级', w: '68px', sortable: true },
  { key: 'capital_score', label: '资金', w: '66px', align: 'right', sortable: true },
  { key: 'momentum_score', label: '动量', w: '66px', align: 'right', sortable: true },
  { key: 'valuation_score', label: '估值', w: '66px', align: 'right', sortable: true },
  { key: 'liquidity_score', label: '量价', w: '66px', align: 'right', sortable: true },
  { key: 'quality_score', label: '质量', w: '66px', align: 'right', sortable: true },
  { key: 'sentiment_score', label: '情绪', w: '66px', align: 'right', sortable: true },
]

const hasMlProb = computed(() => (result.value?.scores || []).some((r) => r.ml_prob != null))

const sortedScores = computed(() => {
  let arr = (result.value?.scores || []).slice()
  const t = searchText.value.trim().toLowerCase()
  if (t) arr = arr.filter((r) => r.code.includes(t) || (r.name || '').toLowerCase().includes(t))
  if (tierFilter.value !== 'all') arr = arr.filter((r) => r.tier === tierFilter.value)
  const k = sortKey.value
  const dir = sortDir.value
  arr.sort((a, b) => {
    if (k === 'rank') return dir * (a._rank - b._rank)
    const va = a[k]
    const vb = b[k]
    if (va == null) return 1
    if (vb == null) return -1
    if (typeof va === 'string') return dir * String(va).localeCompare(String(vb), 'zh')
    return dir * (Number(va) - Number(vb))
  })
  return arr
})

function toggleSort(k) {
  if (!k) return
  if (sortKey.value === k) sortDir.value = -sortDir.value
  else {
    sortKey.value = k
    sortDir.value = ['code', 'name', 'board', 'tier'].includes(k) ? 1 : -1
  }
}
function sortIcon(k) {
  if (sortKey.value !== k) return ''
  return sortDir.value === -1 ? '▼' : '▲'
}
function toggleRow(code) {
  const next = new Set(expandedRows.value)
  if (next.has(code)) next.delete(code)
  else next.add(code)
  expandedRows.value = next
}
function openDetail(row) {
  selectedStock.value = row
}

// 对比摘要行（配置差异 + 结果差异）
const cmpRows = computed(() => {
  const r = store.compareResult
  if (!r) return []
  const cd = r.config_diff || {}
  const rows = []
  const push = (label, a, b) => rows.push({ label, a: a ?? '—', b: b ?? '—' })
  push('A 入选数', r.delta?.summary_a?.tier_counts?.strong, null)
  push('B 入选数', null, r.delta?.summary_b?.tier_counts?.strong)
  push('A 平均分', r.delta?.summary_a?.avg_total_score, null)
  push('B 平均分', null, r.delta?.summary_b?.avg_total_score)
  if (cd.engine_mode) push('引擎模式', cd.engine_mode[0], cd.engine_mode[1])
  if (cd.orthogonalize) push('正交化', cd.orthogonalize[0], cd.orthogonalize[1])
  if (cd.weights && Object.keys(cd.weights).length) {
    for (const [d, w] of Object.entries(cd.weights)) push(`权重 ${d}`, w[0], w[1])
  }
  return rows
})

// ═════════════════════════════ 导出 CSV ═════════════════════════════
function exportCsv() {
  const rows = sortedScores.value
  if (!rows.length) return
  const hdrs = ['排名', '代码', '名称', '板块', '现价', '涨跌幅', '综合分', 'ML概率', '评级',
    '资金', '动量', '估值', '量价', '质量', '情绪', '成交额', 'PE_TTM', '入选逻辑']
  const lines = [hdrs.join(',')]
  rows.forEach((r, i) => {
    lines.push([
      i + 1, r.code, `"${r.name}"`, r.board, r.price, r.change_pct, r.total_score,
      r.ml_prob ?? '', r.tier, r.capital_score, r.momentum_score, r.valuation_score,
      r.liquidity_score, r.quality_score, r.sentiment_score, r.amount, r.pe_ttm,
      `"${(r.rationale || '').replace(/"/g, '""')}"`,
    ].join(','))
  })
  const blob = new Blob(['\ufeff' + lines.join('\n')], { type: 'text/csv;charset=utf-8' })
  const a = document.createElement('a')
  a.href = URL.createObjectURL(blob)
  a.download = `智能选股_${new Date().toISOString().slice(0, 10)}.csv`
  a.click()
  URL.revokeObjectURL(a.href)
}

// ═════════════════════════════ 格式化 ═════════════════════════════
function fmtScore(v) {
  if (v === null || v === undefined || !Number.isFinite(v)) return '—'
  return v.toFixed(1)
}
function fmtPrice(v) {
  if (v === null || v === undefined || !Number.isFinite(v)) return '—'
  return v.toFixed(2)
}
function fmtPct(v) {
  if (v === null || v === undefined || !Number.isFinite(v)) return '—'
  const sign = v > 0 ? '+' : ''
  return `${sign}${v.toFixed(2)}%`
}
function fmtAmount(v) {
  if (v === null || v === undefined || !Number.isFinite(v) || v <= 0) return '—'
  if (v >= 1e8) return `${(v / 1e8).toFixed(2)}亿`
  if (v >= 1e4) return `${(v / 1e4).toFixed(2)}万`
  return v.toFixed(0)
}
function fmtWeight(w) {
  return `${Math.round((w || 0) * 1000) / 10}%`
}
function chgClass(v) {
  if (v === null || v === undefined || !Number.isFinite(v)) return ''
  return v > 0 ? 'is-up' : v < 0 ? 'is-down' : ''
}
const engineModeLabel = computed(() => ENGINE_MODES.find((m) => m.value === engineMode.value)?.label || engineMode.value)

// ═════════════════════════════ ECharts ═════════════════════════════
const scoreDistRef = ref(null)
const boardPieRef = ref(null)
const tierBarRef = ref(null)
const scatterRef = ref(null)
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
    xAxis: { type: 'category', data: bins.map((b) => `${b.from}-${b.to}`), axisLabel: { fontSize: 10, color: '#64748b' } },
    yAxis: { type: 'value', minInterval: 1, axisLabel: { fontSize: 10, color: '#64748b' } },
    series: [{
      name: '数量', type: 'bar', data: counts, barWidth: '70%',
      itemStyle: { color: '#2f7d5b', borderRadius: [3, 3, 0, 0] },
    }],
  }
}
function boardPieOption(res) {
  const counts = {}
  res.scores.forEach((s) => { counts[BOARD_LABEL[s.board] || s.board] = (counts[BOARD_LABEL[s.board] || s.board] || 0) + 1 })
  const data = Object.entries(counts).map(([name, value]) => ({ name, value }))
  return {
    tooltip: { trigger: 'item', formatter: '{b}: {c} ({d}%)' },
    legend: { bottom: 0, textStyle: { fontSize: 11, color: '#64748b' } },
    series: [{
      type: 'pie', radius: ['42%', '68%'], center: ['50%', '44%'],
      itemStyle: { borderColor: '#fff', borderWidth: 2 },
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
    xAxis: { type: 'category', data: names, axisLabel: { fontSize: 11, color: '#64748b' } },
    yAxis: { type: 'value', minInterval: 1, axisLabel: { fontSize: 10, color: '#64748b' } },
    series: [{
      type: 'bar', data: counts, barWidth: '46%',
      itemStyle: { color: '#2f7d5b', borderRadius: [3, 3, 0, 0] },
    }],
  }
}
function scatterOption(res) {
  const tierColors = { strong: '#e11d48', watch: '#b45309', observe: '#0f766e', none: '#cbd5e1' }
  const series = []
  const tierOrder = ['strong', 'watch', 'observe', 'none']
  tierOrder.forEach((tier) => {
    const pts = res.scores.filter((s) => s.tier === tier)
    if (!pts.length) return
    series.push({
      name: tierMeta[tier].label, type: 'scatter', symbolSize: 7,
      itemStyle: { color: tierColors[tier], opacity: 0.75 },
      data: pts.map((s) => [s.total_score, s.change_pct ?? 0]),
    })
  })
  return {
    tooltip: { trigger: 'item', formatter: (p) => `${p.seriesName}<br/>综合分 ${p.value[0].toFixed(1)} · 涨跌 ${p.value[1].toFixed(2)}%` },
    legend: { top: 0, textStyle: { fontSize: 11, color: '#64748b' } },
    grid: { left: 44, right: 16, top: 30, bottom: 30 },
    xAxis: { name: '综合分', type: 'value', min: 0, max: 100, axisLabel: { fontSize: 10, color: '#64748b' } },
    yAxis: { name: '当日涨跌%', type: 'value', axisLabel: { fontSize: 10, color: '#64748b' } },
    series,
  }
}
function layersOption(ev) {
  const keys = Object.keys(ev.layers || {})
  return {
    tooltip: { trigger: 'axis', axisPointer: { type: 'shadow' } },
    grid: { left: 44, right: 12, top: 16, bottom: 28 },
    xAxis: { type: 'category', data: keys, axisLabel: { fontSize: 11, color: '#64748b' } },
    yAxis: { type: 'value', name: '前瞻收益 %', axisLabel: { fontSize: 10, color: '#64748b' } },
    series: [{
      type: 'bar', data: keys.map((k) => ev.layers[k]), barWidth: '52%',
      itemStyle: {
        color: (p) => (p.data >= 0 ? '#e11d48' : '#15803d'),
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
    if (icir < 0.5) return '#e11d48'
    if (icir < 1.0) return '#b45309'
    return '#2f7d5b'
  })
  return {
    tooltip: { trigger: 'axis', axisPointer: { type: 'shadow' } },
    grid: { left: 44, right: 12, top: 16, bottom: 28 },
    xAxis: { type: 'category', data: dims.map((d) => DIM_LABELS[d] || d), axisLabel: { fontSize: 11, color: '#64748b' } },
    yAxis: { type: 'value', name: 'ICIR', axisLabel: { fontSize: 10, color: '#64748b' } },
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
  setChart('scatter', scatterRef.value, scatterOption(res))
}
function renderEvalCharts() {
  const ev = store.evalResult
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
watch(() => store.evalResult, () => { if (activeTab.value === 'evaluate') nextTick(renderEvalCharts) })

// 引擎诊断展示
const engineDiag = computed(() => {
  const r = result.value
  if (!r) return null
  return {
    mode: r.engine_mode || 'fixed',
    status: r.model_status || 'linear',
    weights: r.engine_weights || store.config?.weights || {},
    diag: r.engine_diagnostics || {},
  }
})

onMounted(() => {
  applyPrefs(readPrefs()) // 打开即恢复上次配置，无需重新选择
  store.loadConfig()
  store.loadRecent()
  window.addEventListener('resize', resizeAll)
})
onBeforeUnmount(() => {
  store.stopPolling()
  window.removeEventListener('resize', resizeAll)
  Object.values(chartMap).forEach((c) => c.dispose())
})
</script>

<template>
  <div class="screener-shell">
    <header class="ff-page__header">
      <div class="ff-page__heading">
        <h1 class="ff-page__title">智能选股</h1>
        <p class="ff-page__desc">五维因子打分与条件筛选引擎</p>
      </div>
    </header>

    <!-- ═══════ 顶部 ═══════ -->
    <header class="screener-top ff-glass">
      <div class="screener-controls">
        <button type="button" class="screener-strategy-btn" @click="showStrategy = true">
          <AppIcon name="info" size="xs" /> 选股策略
        </button>
        <label class="screener-field">
          <span class="screener-field__label">显示前</span>
          <input v-model.number="top" type="number" min="10" max="300" class="screener-field__input screener-field__input--sm" />
          <span class="screener-field__unit">只</span>
        </label>
        <label class="screener-field screener-field--switch" title="开启后对候选股额外抓取日K线，计算年化已实现波动率、均线多头排列（MA20/MA60）、距52周高点回撤等技术指标，用于质量维度评分与详情展示；每只标的一次网络请求，耗时更长（仅富化前 N 只）。关闭则用当日振幅作波动率代理，速度快。">
          <AppSwitch v-model="technical" />
          <span class="screener-field__label">技术面富化</span>
          <AppIcon name="info" size="xs" class="screener-field__hint" />
        </label>
        <AppButton variant="primary" icon="play" :loading="loading" :disabled="loading" @click="onRun">
          {{ loading ? '选股中…' : '开始选股' }}
        </AppButton>
      </div>
    </header>

    <!-- ═══════ 状态 / 进度 ═══════ -->
    <div v-if="loading || latestLog || errMsg" class="screener-status">
      <div v-if="loading" class="screener-status__progress">
        <span class="screener-status__bar"><span class="screener-status__fill" :style="{ width: (task?.progress || 0) + '%' }" /></span>
        <span class="screener-status__pct">{{ task?.progress || 0 }}%</span>
      </div>
      <span v-if="latestLog" class="screener-status__log">
        <AppIcon name="refresh" :spin="loading" size="xs" />
        {{ latestLog }}
      </span>
      <span v-if="errMsg" class="screener-status__err">
        <AppIcon name="alert-circle" size="xs" />
        {{ errMsg }}
      </span>
    </div>

    <!-- ═══════ 主体：左配置 + 右结果 ═══════ -->
    <div class="screener-body">
      <!-- ── 左：配置面板 ── -->
      <aside class="screener-panel">
        <!-- 引擎模式 -->
        <section class="panel-sec">
          <h3 class="panel-sec__title"><AppIcon name="settings" size="xs" /> 引擎模式</h3>
          <div class="panel-seg">
            <button
              v-for="m in ENGINE_MODES"
              :key="m.value"
              type="button"
              class="panel-seg__btn"
              :class="{ 'is-on': engineMode === m.value }"
              @click="engineMode = m.value"
            >
              {{ m.label }}
            </button>
          </div>
          <p class="panel-sec__hint">{{ ENGINE_HINTS[engineMode] }}</p>
        </section>

        <!-- 维度权重（线性模式可调） -->
        <section class="panel-sec">
          <h3 class="panel-sec__title">
            <AppIcon name="sliders" size="xs" /> 维度权重
            <span class="panel-sec__sp" />
            <button type="button" class="panel-link" @click="resetWeights">重置</button>
          </h3>
          <div v-for="d in dimOrder" :key="d" class="dim-row">
            <span class="dim-row__label">{{ DIM_LABELS[d] }}</span>
            <input
              type="range"
              min="0"
              max="60"
              step="0.5"
              :disabled="engineMode !== 'linear'"
              :value="dimWeights[d]"
              class="dim-row__slider"
              @input="dimWeights[d] = Number($event.target.value); onDimChange()"
            />
            <span class="dim-row__val">{{ dimWeights[d].toFixed(1) }}%</span>
          </div>
          <p v-if="engineMode !== 'linear'" class="panel-sec__hint">
            非线性模式下权重由引擎客观计算（IC/ML），此处禁用。
          </p>
        </section>

        <!-- 引擎参数 -->
        <section class="panel-sec">
          <h3 class="panel-sec__title"><AppIcon name="zap" size="xs" /> 引擎参数</h3>
          <label class="panel-switch">
            <AppSwitch v-model="orthogonalize" />
            <span class="panel-switch__label">维度正交化（去冗余，提升 ICIR）</span>
          </label>
          <label class="panel-field">
            <span class="panel-field__label">前瞻期 horizon</span>
            <input v-model.number="horizon" type="number" min="5" max="60" class="panel-field__input" />
            <span class="panel-field__unit">日</span>
          </label>
          <label class="panel-field">
            <span class="panel-field__label">ML 强势分位 top</span>
            <input v-model.number="topQuantile" type="number" min="0.1" max="0.5" step="0.05" class="panel-field__input" />
          </label>
          <label v-if="engineMode === 'blend'" class="panel-field">
            <span class="panel-field__label">混合系数 α</span>
            <input v-model.number="blendAlpha" type="number" min="0" max="1" step="0.05" class="panel-field__input" />
            <span class="panel-field__unit">线性占比</span>
          </label>
        </section>

        <!-- 股票池过滤 -->
        <section class="panel-sec">
          <h3 class="panel-sec__title"><AppIcon name="target" size="xs" /> 股票池过滤</h3>
          <div class="panel-boards">
            <button
              v-for="b in BOARD_OPTIONS"
              :key="b.key"
              type="button"
              class="screener-board-chip"
              :class="{ 'is-on': boards[b.key] }"
              @click="boards[b.key] = !boards[b.key]"
            >
              {{ b.label }}
            </button>
          </div>
          <label class="panel-switch">
            <AppSwitch v-model="excludeSt" />
            <span class="panel-switch__label">剔除 ST / 退市</span>
          </label>
          <div class="panel-grid2">
            <label class="panel-field">
              <span class="panel-field__label">价格下限</span>
              <input v-model.number="minPrice" type="number" class="panel-field__input" />
            </label>
            <label class="panel-field">
              <span class="panel-field__label">价格上限</span>
              <input v-model.number="maxPrice" type="number" class="panel-field__input" />
            </label>
            <label class="panel-field">
              <span class="panel-field__label">PE_TTM 上限</span>
              <input v-model.number="peMax" type="number" class="panel-field__input" />
            </label>
            <label class="panel-field">
              <span class="panel-field__label">成交额下限</span>
              <input v-model.number="minAmount" type="number" class="panel-field__input" />
              <span class="panel-field__unit">元</span>
            </label>
            <label class="panel-field">
              <span class="panel-field__label">换手率下限</span>
              <input v-model.number="minTurnover" type="number" step="0.1" class="panel-field__input" />
              <span class="panel-field__unit">%</span>
            </label>
            <label class="panel-field">
              <span class="panel-field__label">流通市值下限</span>
              <input v-model.number="minCircCap" type="number" class="panel-field__input" />
              <span class="panel-field__unit">元</span>
            </label>
          </div>
        </section>

        <!-- 模板 -->
        <section class="panel-sec">
          <h3 class="panel-sec__title"><AppIcon name="save" size="xs" /> 模板</h3>
          <div class="panel-tpl-row">
            <input v-model="templateName" type="text" placeholder="新模板名" class="panel-field__input" />
            <AppButton variant="secondary" size="sm" icon="save" @click="onSaveTemplate">保存</AppButton>
          </div>
          <div class="panel-tpl-row">
            <AppSelect v-model="loadTemplateName" :options="templateOptions" placeholder="选择模板" size="sm" class="panel-tpl-select" />
            <AppButton variant="secondary" size="sm" @click="onLoadTemplate">应用</AppButton>
            <button type="button" class="panel-icon-btn" title="删除模板" @click="onDeleteTemplate">
              <AppIcon name="trash" size="xs" />
            </button>
          </div>
          <div class="panel-tpl-row">
            <AppSelect v-model="compareTemplate" :options="templateOptions" placeholder="对比模板" size="sm" class="panel-tpl-select" />
            <AppButton variant="secondary" size="sm" icon="bar-chart" :loading="store.comparing" @click="onCompare">对比</AppButton>
          </div>
          <button type="button" class="panel-eval-btn" :disabled="store.evaluating" @click="onEvaluate">
            <AppIcon name="target" size="xs" />
            {{ store.evaluating ? '评估中…' : '运行评估闭环' }}
          </button>
        </section>
      </aside>

      <!-- ── 右：结果区 ── -->
      <main class="screener-main">
        <!-- 统计卡片 -->
        <div v-if="result" class="screener-stats">
          <div class="screener-stat">
            <span class="screener-stat__label">全市场</span>
            <span class="screener-stat__value">{{ result.universe_size }}</span>
          </div>
          <div class="screener-stat">
            <span class="screener-stat__label">通过过滤</span>
            <span class="screener-stat__value">{{ result.screened_size }}</span>
          </div>
          <div class="screener-stat screener-stat--strong">
            <span class="screener-stat__label">入选</span>
            <span class="screener-stat__value">{{ store.strongCount }}</span>
          </div>
          <div class="screener-stat screener-stat--watch">
            <span class="screener-stat__label">关注</span>
            <span class="screener-stat__value">{{ store.watchCount }}</span>
          </div>
          <div v-if="result.snapshot_time" class="screener-stat">
            <span class="screener-stat__label">快照时间</span>
            <span class="screener-stat__value screener-stat__value--sm">{{ result.snapshot_time }}</span>
          </div>
          <div v-if="result.data_source" class="screener-stat">
            <span class="screener-stat__label">数据源</span>
            <span class="screener-stat__value screener-stat__value--sm">{{ result.data_source }}</span>
          </div>
        </div>

        <!-- 引擎诊断条 -->
        <div v-if="engineDiag" class="engine-diag">
          <AppBadge :text="`引擎：${engineDiag.mode}`" variant="brand" />
          <AppBadge :text="`模型：${engineDiag.status}`" :variant="engineDiag.status === 'trained' ? 'success' : engineDiag.status === 'degraded' ? 'warn' : 'muted'" />
          <span class="engine-diag__weights">
            <span v-for="(w, d) in engineDiag.weights" :key="d" class="engine-diag__w" :title="`${DIM_LABELS[d] || d} ${fmtWeight(w)}`">
              <span class="engine-diag__w-label">{{ DIM_LABELS[d] || d }}</span>
              <span class="engine-diag__w-bar"><span class="engine-diag__w-fill" :style="{ width: fmtWeight(w) }" /></span>
            </span>
          </span>
        </div>

        <!-- 页签 -->
        <div class="screener-tabs">
          <AppTabs v-model="activeTab" :items="[
            { label: '评分结果', value: 'result', badge: result?.scores?.length || 0 },
            { label: '图表', value: 'charts' },
            { label: '评估闭环', value: 'evaluate' },
          ]" type="pill" />
          <span class="screener-tabs__sp" />
          <button v-if="result?.scores?.length" type="button" class="screener-card__toggle" @click="exportCsv">
            <AppIcon name="download" size="xs" /> 导出 CSV
          </button>
        </div>

        <!-- 结果页签 -->
        <section v-show="activeTab === 'result'" class="screener-card screener-card--grow">
          <div class="screener-card__body screener-card__body--table">
            <div v-if="!result" class="screener-empty">
              <AppIcon name="filter" size="xl" />
              <p>点击「开始选股」运行引擎</p>
              <p class="screener-empty__hint">支持线性固定 / IC 客观加权 / ML / 混合引擎，模板可保存复用</p>
            </div>
            <template v-else>
              <!-- 筛选工具条 -->
              <div class="screener-toolbar">
                <span class="screener-toolbar__search">
                  <AppIcon name="search" size="xs" />
                  <input v-model="searchText" type="text" placeholder="搜索代码 / 名称" class="screener-toolbar__input" />
                </span>
                <div class="screener-toolbar__tiers">
                  <button
                    v-for="t in [{ v: 'all', l: '全部' }, { v: 'strong', l: '入选' }, { v: 'watch', l: '关注' }, { v: 'observe', l: '观察' }]"
                    :key="t.v"
                    type="button"
                    class="screener-board-chip"
                    :class="{ 'is-on': tierFilter === t.v }"
                    @click="tierFilter = t.v"
                  >{{ t.l }}</button>
                </div>
                <span class="screener-toolbar__count">共 {{ sortedScores.length }} / {{ result.scores.length }} 只</span>
              </div>
              <div class="screener-table-wrap">
                <table class="screener-table">
                  <thead>
                    <tr>
                      <th
                        v-for="h in headers"
                        :key="h.key"
                        :style="{ width: h.w }"
                        :class="[h.align && `is-${h.align}`, h.sortable && 'is-sortable']"
                        :title="h.sortable ? '点击排序' : ''"
                        @click="h.sortable && toggleSort(h.key)"
                      >
                        {{ h.label }}
                        <span v-if="h.sortable" class="screener-table__sort">{{ sortIcon(h.key) }}</span>
                      </th>
                      <th style="width: 40px"></th>
                    </tr>
                  </thead>
                  <tbody>
                    <template v-for="(row, idx) in sortedScores" :key="row.code">
                      <tr
                        :class="[
                          'screener-row',
                          `screener-row--${row.tier}`,
                          expandedRows.has(row.code) && 'screener-row--expanded',
                        ]"
                        @click="toggleRow(row.code)"
                      >
                        <td class="is-center">{{ idx + 1 }}</td>
                        <td class="screener-table__code">{{ row.code }}</td>
                        <td class="screener-table__name">{{ row.name }}</td>
                        <td>
                          <span class="screener-table__board" :class="`is-${row.board || 'main'}`">
                            {{ BOARD_LABEL[row.board] || '—' }}
                          </span>
                        </td>
                        <td class="is-right">{{ fmtPrice(row.price) }}</td>
                        <td class="is-right" :class="chgClass(row.change_pct)">{{ fmtPct(row.change_pct) }}</td>
                        <td class="is-right screener-table__score">{{ fmtScore(row.total_score) }}</td>
                        <td v-if="hasMlProb" class="is-right">
                          <span v-if="row.ml_prob != null" class="ml-prob">{{ (row.ml_prob * 100).toFixed(0) }}%</span>
                          <span v-else>—</span>
                        </td>
                        <td>
                          <AppBadge :text="tierMeta[row.tier]?.label || row.tier" :variant="tierMeta[row.tier]?.variant || 'default'" />
                        </td>
                        <td class="is-right">{{ fmtScore(row.capital_score) }}</td>
                        <td class="is-right">{{ fmtScore(row.momentum_score) }}</td>
                        <td class="is-right">{{ fmtScore(row.valuation_score) }}</td>
                        <td class="is-right">{{ fmtScore(row.liquidity_score) }}</td>
                        <td class="is-right">{{ fmtScore(row.quality_score) }}</td>
                        <td class="is-right">{{ fmtScore(row.sentiment_score) }}</td>
                        <td class="is-center">
                          <AppIcon :name="expandedRows.has(row.code) ? 'chevron-up' : 'chevron-down'" size="xs" />
                        </td>
                      </tr>
                      <tr v-if="expandedRows.has(row.code)" class="screener-detail">
                        <td :colspan="headers.length + 1">
                          <div class="screener-detail__body">
                            <div class="screener-detail__meta">
                              <span>成交额 {{ fmtAmount(row.amount) }}</span>
                              <span>振幅 {{ fmtScore(row.amplitude) }}%</span>
                              <span>PE_TTM {{ fmtScore(row.pe_ttm) }}</span>
                              <span v-if="row.ml_prob != null" class="ml-prob">ML 概率 {{ (row.ml_prob * 100).toFixed(1) }}%</span>
                              <span v-if="row.realized_vol_ann != null">年化波动 {{ fmtScore(row.realized_vol_ann) }}%</span>
                              <span v-if="row.drawdown_from_high != null">距高点回撤 {{ fmtScore(row.drawdown_from_high) }}%</span>
                              <AppBadge v-if="row.ma_align" text="均线多头排列" variant="success" />
                              <AppButton variant="secondary" size="sm" @click.stop="openDetail(row)">详情</AppButton>
                            </div>
                            <div class="screener-detail__cols">
                              <div class="screener-detail__left">
                                <p v-if="row.rationale" class="screener-detail__text">
                                  <strong>入选逻辑：</strong>{{ row.rationale }}
                                </p>
                                <div v-if="row.highlights?.length" class="screener-detail__tags">
                                  <span class="screener-detail__tag-title">亮点</span>
                                  <span v-for="tag in row.highlights" :key="tag" class="screener-detail__tag screener-detail__tag--good">{{ tag }}</span>
                                </div>
                                <div v-if="row.guardrail_failures?.length" class="screener-detail__tags">
                                  <span class="screener-detail__tag-title">护栏降级</span>
                                  <span v-for="tag in row.guardrail_failures" :key="tag" class="screener-detail__tag screener-detail__tag--warn">{{ tag }}</span>
                                </div>
                                <div class="screener-detail__factor" v-if="row.factor_exposure && Object.keys(row.factor_exposure).length">
                                  <span class="screener-detail__tag-title">因子暴露</span>
                                  <span
                                    v-for="(v, d) in row.factor_exposure"
                                    :key="d"
                                    class="screener-detail__tag"
                                  >{{ DIM_LABELS[d] || d }} {{ fmtScore(v) }}</span>
                                </div>
                              </div>
                              <DimensionRadar :dims="{
                                capital: row.capital_score, momentum: row.momentum_score,
                                valuation: row.valuation_score, liquidity: row.liquidity_score,
                                quality: row.quality_score, sentiment: row.sentiment_score,
                              }" :height="180" />
                            </div>
                          </div>
                        </td>
                      </tr>
                    </template>
                  </tbody>
                </table>
              </div>
            </template>
          </div>
        </section>

        <!-- 图表页签 -->
        <section v-show="activeTab === 'charts'" class="screener-card screener-card--grow">
          <div class="screener-card__body">
            <div v-if="!result?.scores?.length" class="screener-empty screener-empty--sm">
              <p>先运行选股，再查看图表</p>
            </div>
            <div v-else class="charts-grid">
              <div class="chart-box">
                <h4 class="chart-box__title">综合分分布</h4>
                <div ref="scoreDistRef" class="chart-box__canvas" />
              </div>
              <div class="chart-box">
                <h4 class="chart-box__title">板块分布</h4>
                <div ref="boardPieRef" class="chart-box__canvas" />
              </div>
              <div class="chart-box">
                <h4 class="chart-box__title">评级分布</h4>
                <div ref="tierBarRef" class="chart-box__canvas" />
              </div>
              <div class="chart-box">
                <h4 class="chart-box__title">综合分 × 当日涨跌（按评级着色）</h4>
                <div ref="scatterRef" class="chart-box__canvas" />
              </div>
            </div>
          </div>
        </section>

        <!-- 评估页签 -->
        <section v-show="activeTab === 'evaluate'" class="screener-card screener-card--grow">
          <div class="screener-card__body screener-eval">
            <div v-if="store.evalErr" class="screener-status__err">{{ store.evalErr }}</div>
            <div v-else-if="!store.evalResult" class="screener-empty screener-empty--sm">
              <p>点击左侧「运行评估闭环」，对当前引擎做无未来函数的历史验证</p>
            </div>
            <template v-else-if="store.evalResult.error">
              <div class="screener-empty screener-empty--sm">
                <p>{{ store.evalResult.error }}</p>
                <p class="screener-empty__hint">快照库需持续积累历史交易日，评估自动启用</p>
              </div>
            </template>
            <template v-else>
              <div class="eval-stats">
                <div class="screener-stat">
                  <span class="screener-stat__label">复合 RankIC</span>
                  <span class="screener-stat__value screener-stat__value--sm">{{ store.evalResult.composite?.ic_mean }}</span>
                </div>
                <div class="screener-stat">
                  <span class="screener-stat__label">复合 ICIR</span>
                  <span class="screener-stat__value screener-stat__value--sm">{{ store.evalResult.composite?.icir }}</span>
                </div>
                <div class="screener-stat">
                  <span class="screener-stat__label">多空价差 IR</span>
                  <span class="screener-stat__value screener-stat__value--sm">{{ store.evalResult.spread?.information_ratio }}</span>
                </div>
                <div class="screener-stat">
                  <span class="screener-stat__label">有效截面</span>
                  <span class="screener-stat__value screener-stat__value--sm">{{ store.evalResult.n_periods }}</span>
                </div>
              </div>
              <div v-if="store.evalResult.factor_health?.length" class="eval-alert">
                <AppIcon name="alert-triangle" size="xs" />
                <span>因子失效监控：{{ store.evalResult.factor_health.map((f) => `${DIM_LABELS[f.dim] || f.dim}(${f.status})`).join('、') }}</span>
              </div>
              <div v-if="store.evalResult.recommendation?.actions?.length" class="eval-alert eval-alert--info">
                <AppIcon name="target" size="xs" />
                <span>重算建议：{{ store.evalResult.recommendation.actions.map((a) => `${a.action} → ${a.target_mode}`).join('；') }}</span>
              </div>
              <div class="charts-grid">
                <div class="chart-box">
                  <h4 class="chart-box__title">五分位分层前瞻收益（%）</h4>
                  <div ref="evalLayersRef" class="chart-box__canvas" />
                </div>
                <div class="chart-box">
                  <h4 class="chart-box__title">分维度 ICIR（红=失效 &lt;0.5）</h4>
                  <div ref="evalDimRef" class="chart-box__canvas" />
                </div>
              </div>
              <div v-if="store.evalResult.per_dimension" class="eval-table">
                <table class="screener-table">
                  <thead>
                    <tr>
                      <th>维度</th><th>IC 均值</th><th>ICIR</th><th>正截面</th>
                    </tr>
                  </thead>
                  <tbody>
                    <tr v-for="(v, d) in store.evalResult.per_dimension" :key="d">
                      <td>{{ DIM_LABELS[d] || d }}</td>
                      <td>{{ v.ic_mean }}</td>
                      <td :class="v.icir < 0.5 ? 'is-down' : v.icir < 1 ? 'is-warn' : 'is-up'">{{ v.icir }}</td>
                      <td>{{ v.hit_rate }}</td>
                    </tr>
                  </tbody>
                </table>
              </div>
            </template>
          </div>
        </section>
      </main>
    </div>

    <!-- ═══════ 选股策略说明弹窗 ═══════ -->
    <AppModal v-model="showStrategy" title="选股策略说明" size="lg" :show-ok="false" cancel-text="关闭">
      <div class="strategy-doc">
        <MarkdownView :content="store.config?.methodology || '策略说明加载中…'" />
      </div>
    </AppModal>

    <!-- ═══════ 对比结果弹窗 ═══════ -->
    <AppModal v-model="showCompare" title="策略对比结果" size="lg" :show-ok="false" cancel-text="关闭">
      <div v-if="store.compareResult" class="cmp">
        <div class="cmp-stats">
          <div class="screener-stat">
            <span class="screener-stat__label">A 引擎</span>
            <span class="screener-stat__value screener-stat__value--sm">{{ store.compareResult.a.engine_mode }}</span>
          </div>
          <div class="screener-stat">
            <span class="screener-stat__label">B 引擎</span>
            <span class="screener-stat__value screener-stat__value--sm">{{ store.compareResult.b.engine_mode }}</span>
          </div>
          <div class="screener-stat">
            <span class="screener-stat__label">入选∩关注 重合</span>
            <span class="screener-stat__value screener-stat__value--sm">{{ store.compareResult.delta.overlap_strong_watch }}</span>
          </div>
          <div class="screener-stat">
            <span class="screener-stat__label">Jaccard</span>
            <span class="screener-stat__value screener-stat__value--sm">{{ store.compareResult.delta.jaccard ?? '—' }}</span>
          </div>
        </div>
        <div class="cmp-table-wrap">
          <table class="screener-table">
            <thead>
              <tr><th>项目</th><th>策略 A</th><th>策略 B</th></tr>
            </thead>
            <tbody>
              <tr v-for="(row, i) in cmpRows" :key="i">
                <td>{{ row.label }}</td>
                <td>{{ row.a }}</td>
                <td>{{ row.b }}</td>
              </tr>
            </tbody>
          </table>
        </div>
      </div>
    </AppModal>

    <!-- ═══════ 个股下钻弹窗 ═══════ -->
    <AppModal v-model="showDetail" title="个股详情" size="lg" :show-ok="false" cancel-text="关闭">
      <div v-if="selectedStock" class="drill">
        <div class="drill__head">
          <h3 class="drill__name">{{ selectedStock.name }}</h3>
          <span class="drill__code">{{ selectedStock.code }}</span>
          <AppBadge :text="tierMeta[selectedStock.tier]?.label || selectedStock.tier" :variant="tierMeta[selectedStock.tier]?.variant || 'default'" />
        </div>
        <div class="drill__cols">
          <div class="drill__left">
            <div class="drill__kv"><span>现价</span><b :class="chgClass(selectedStock.change_pct)">{{ fmtPrice(selectedStock.price) }}</b></div>
            <div class="drill__kv"><span>涨跌幅</span><b :class="chgClass(selectedStock.change_pct)">{{ fmtPct(selectedStock.change_pct) }}</b></div>
            <div class="drill__kv"><span>综合分</span><b class="drill__score">{{ fmtScore(selectedStock.total_score) }}</b></div>
            <div class="drill__kv"><span>ML 概率</span><b>{{ selectedStock.ml_prob != null ? (selectedStock.ml_prob * 100).toFixed(1) + '%' : '—' }}</b></div>
            <div class="drill__kv"><span>成交额</span><b>{{ fmtAmount(selectedStock.amount) }}</b></div>
            <div class="drill__kv"><span>PE_TTM</span><b>{{ fmtScore(selectedStock.pe_ttm) }}</b></div>
            <div class="drill__kv"><span>振幅</span><b>{{ fmtScore(selectedStock.amplitude) }}%</b></div>
            <div class="drill__kv"><span>年化波动</span><b>{{ selectedStock.realized_vol_ann != null ? fmtScore(selectedStock.realized_vol_ann) + '%' : '—' }}</b></div>
          </div>
          <div class="drill__radar">
            <DimensionRadar :dims="{
              capital: selectedStock.capital_score, momentum: selectedStock.momentum_score,
              valuation: selectedStock.valuation_score, liquidity: selectedStock.liquidity_score,
              quality: selectedStock.quality_score, sentiment: selectedStock.sentiment_score,
            }" :height="260" />
          </div>
        </div>
        <p class="drill__text"><strong>入选逻辑：</strong>{{ selectedStock.rationale || '无显著亮点' }}</p>
        <div class="drill__tags" v-if="selectedStock.highlights?.length">
          <span v-for="tag in selectedStock.highlights" :key="tag" class="screener-detail__tag screener-detail__tag--good">{{ tag }}</span>
        </div>
      </div>
    </AppModal>
  </div>
</template>

<style scoped>
.screener-shell {
  height: 100%;
  min-height: 0;
  display: flex;
  flex-direction: column;
  gap: var(--ff-space-4);
  padding: var(--ff-page-pad-y) var(--ff-page-pad-x);
  overflow: hidden;
}

/* ── 顶部（仅操作控件，右对齐）── */
.screener-top {
  flex: none;
  display: flex;
  align-items: center;
  justify-content: flex-end;
  gap: var(--ff-space-4);
  padding: var(--ff-space-3) var(--ff-space-4);
  background: var(--ff-bg-surface);
  border: 1px solid var(--ff-border);
  border-radius: var(--ff-radius-lg);
  box-shadow: var(--ff-shadow-sm);
}
.screener-controls { display: flex; align-items: center; gap: var(--ff-space-4); }
.screener-field { display: flex; align-items: center; gap: var(--ff-space-2); font-size: var(--ff-fs-body-sm); color: var(--ff-text-secondary); }
.screener-field__label { font-weight: 500; white-space: nowrap; }
.screener-field__input {
  height: 36px; border: 1px solid var(--ff-border); border-radius: var(--ff-radius-md);
  padding: 0 10px; font-size: var(--ff-fs-body); color: var(--ff-text-primary);
  background: var(--ff-bg-surface); transition: border-color var(--ff-dur-fast);
}
.screener-field__input:focus { outline: none; border-color: var(--ff-border-focus); }
.screener-field__input--sm { width: 64px; text-align: center; }
.screener-field__unit { color: var(--ff-text-tertiary); font-size: var(--ff-fs-caption); }
.screener-field__hint { color: var(--ff-text-tertiary); cursor: help; opacity: 0.7; }
.screener-strategy-btn {
  display: inline-flex; align-items: center; gap: 6px; height: 36px; padding: 0 14px;
  border: 1px solid var(--ff-border-strong); border-radius: var(--ff-radius-md);
  background: var(--ff-bg-subtle); color: var(--ff-text-brand);
  font-size: var(--ff-fs-body-sm); font-weight: 600; cursor: pointer;
  transition: background-color var(--ff-dur-fast) var(--ff-ease-standard), border-color var(--ff-dur-fast) var(--ff-ease-standard), color var(--ff-dur-fast) var(--ff-ease-standard), box-shadow var(--ff-dur-fast) var(--ff-ease-standard), transform var(--ff-dur-fast) var(--ff-ease-standard); white-space: nowrap;
}
.screener-strategy-btn:hover { border-color: var(--ff-brand); background: var(--ff-bg-hover); }
.screener-field--switch { gap: var(--ff-space-1-5); cursor: pointer; }

/* ── 板块 chip ── */
.screener-board-chip {
  height: 26px; padding: 0 12px; border: 1px solid var(--ff-border);
  border-radius: 999px; background: var(--ff-bg-surface);
  color: var(--ff-text-secondary); font-size: var(--ff-fs-caption);
  font-weight: 500; cursor: pointer; transition: background-color var(--ff-dur-fast) var(--ff-ease-standard), border-color var(--ff-dur-fast) var(--ff-ease-standard), color var(--ff-dur-fast) var(--ff-ease-standard), box-shadow var(--ff-dur-fast) var(--ff-ease-standard), transform var(--ff-dur-fast) var(--ff-ease-standard);
  white-space: nowrap;
}
.screener-board-chip:hover { border-color: var(--ff-brand); color: var(--ff-brand); }
.screener-board-chip.is-on { background: var(--ff-brand); border-color: var(--ff-brand); color: var(--ff-bg-surface); }

/* ── 状态条 ── */
.screener-status {
  flex: none; display: flex; align-items: center; gap: var(--ff-space-4);
  padding: 10px var(--ff-space-4); background: var(--ff-bg-surface);
  border: 1px solid var(--ff-border); border-radius: var(--ff-radius-lg);
  font-size: var(--ff-fs-body-sm); color: var(--ff-text-secondary);
}
.screener-status__progress { display: flex; align-items: center; gap: var(--ff-space-3); width: 160px; flex: none; }
.screener-status__bar { flex: 1; height: 6px; border-radius: var(--ff-radius-pill); background: var(--ff-bg-subtle); overflow: hidden; }
.screener-status__fill { height: 100%; border-radius: var(--ff-radius-pill); background: linear-gradient(90deg, var(--ff-brand), var(--ff-brand-hover)); transition: width 0.4s var(--ff-ease-standard); }
.screener-status__pct { font-variant-numeric: tabular-nums; font-weight: 600; color: var(--ff-text-brand); min-width: 38px; text-align: right; }
.screener-status__log { display: inline-flex; align-items: center; gap: 6px; color: var(--ff-text-tertiary); min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.screener-status__err { display: inline-flex; align-items: center; gap: 6px; color: var(--ff-danger-text); background: var(--ff-danger-subtle); border: 1px solid var(--ff-danger-border); border-radius: var(--ff-radius-md); padding: 4px 10px; margin-left: auto; }

/* ── 主体布局 ── */
.screener-body { flex: 1; min-height: 0; display: flex; gap: var(--ff-space-4); overflow: hidden; }
.screener-main { flex: 1; min-width: 0; display: flex; flex-direction: column; gap: var(--ff-space-2); overflow: hidden; }

/* ── 左侧配置面板 ── */
.screener-panel {
  flex: none; width: 348px; overflow-y: auto;
  background: var(--ff-bg-surface); border: 1px solid var(--ff-border);
  border-radius: var(--ff-radius-lg); box-shadow: var(--ff-shadow-sm);
  display: flex; flex-direction: column; gap: 2px; padding: var(--ff-space-2) 0;
}
.panel-sec { padding: var(--ff-space-3) var(--ff-space-4); border-bottom: 1px solid var(--ff-border-subtle); display: flex; flex-direction: column; gap: var(--ff-space-2); }
.panel-sec:last-child { border-bottom: none; }
.panel-sec__title { display: flex; align-items: center; gap: 6px; font-size: var(--ff-fs-body-sm); font-weight: 600; color: var(--ff-text-secondary); margin: 0 0 2px; }
.panel-sec__title > svg { color: var(--ff-text-brand); }
.panel-sec__sp { margin-left: auto; }
.panel-sec__hint { font-size: var(--ff-fs-caption); color: var(--ff-text-tertiary); line-height: 1.5; margin: 0; }
.panel-link { background: none; border: none; color: var(--ff-brand); font-size: var(--ff-fs-caption); cursor: pointer; padding: 0; }
.panel-link:hover { text-decoration: underline; }

.panel-seg { display: grid; grid-template-columns: repeat(5, 1fr); gap: 4px; }
.panel-seg__btn {
  height: 30px; padding: 0 2px; border: 1px solid var(--ff-border);
  border-radius: var(--ff-radius-md); background: var(--ff-bg-surface);
  color: var(--ff-text-secondary); font-size: 12px;
  font-weight: 500; cursor: pointer; transition: background-color var(--ff-dur-fast) var(--ff-ease-standard), border-color var(--ff-dur-fast) var(--ff-ease-standard), color var(--ff-dur-fast) var(--ff-ease-standard), box-shadow var(--ff-dur-fast) var(--ff-ease-standard), transform var(--ff-dur-fast) var(--ff-ease-standard);
  white-space: nowrap; overflow: hidden; text-overflow: ellipsis; line-height: 1;
}
.panel-seg__btn:hover { border-color: var(--ff-brand); color: var(--ff-brand); }
.panel-seg__btn.is-on { background: var(--ff-brand); border-color: var(--ff-brand); color: #fff; }

.dim-row { display: flex; align-items: center; gap: 8px; }
.dim-row__label { width: 56px; font-size: var(--ff-fs-caption); color: var(--ff-text-secondary); flex: none; }
.dim-row__slider { flex: 1; accent-color: var(--ff-brand); height: 4px; }
.dim-row__slider:disabled { opacity: 0.4; }
.dim-row__val { width: 44px; text-align: right; font-size: var(--ff-fs-caption); font-variant-numeric: tabular-nums; color: var(--ff-text-primary); flex: none; }

.panel-switch { display: flex; align-items: center; gap: 8px; font-size: var(--ff-fs-body-sm); color: var(--ff-text-secondary); cursor: pointer; }
.panel-switch__label { font-size: var(--ff-fs-caption); }

.panel-field { display: flex; align-items: center; gap: 6px; font-size: var(--ff-fs-caption); color: var(--ff-text-secondary); }
.panel-field__label { min-width: 78px; white-space: nowrap; }
.panel-field__input {
  width: 92px; height: 28px; border: 1px solid var(--ff-border); border-radius: var(--ff-radius-md);
  padding: 0 8px; font-size: var(--ff-fs-body-sm); color: var(--ff-text-primary);
  background: var(--ff-bg-surface);
}
.panel-field__input:focus { outline: none; border-color: var(--ff-border-focus); }
.panel-field__unit { color: var(--ff-text-tertiary); white-space: nowrap; }
.panel-grid2 { display: grid; grid-template-columns: 1fr 1fr; gap: var(--ff-space-2); }
/* 两列布局：标签在上、输入框全宽在下，避免 label+input 横向溢出 */
.panel-grid2 .panel-field { flex-direction: column; align-items: stretch; gap: 2px; }
.panel-grid2 .panel-field__label { min-width: 0; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.panel-grid2 .panel-field__input { width: 100%; box-sizing: border-box; }
.panel-grid2 .panel-field__unit { display: none; }

.panel-boards { display: flex; flex-wrap: wrap; gap: 6px; }

.panel-tpl-row { display: flex; align-items: center; gap: 6px; }
.panel-tpl-row .panel-field__input { flex: 1; width: auto; }
.panel-tpl-select { flex: 1; min-width: 0; }
.panel-icon-btn {
  width: 30px; height: 30px; flex: none; display: inline-flex; align-items: center; justify-content: center;
  border: 1px solid var(--ff-border); border-radius: var(--ff-radius-md); background: var(--ff-bg-surface);
  color: var(--ff-text-tertiary); cursor: pointer; transition: background-color var(--ff-dur-fast) var(--ff-ease-standard), border-color var(--ff-dur-fast) var(--ff-ease-standard), color var(--ff-dur-fast) var(--ff-ease-standard), box-shadow var(--ff-dur-fast) var(--ff-ease-standard), transform var(--ff-dur-fast) var(--ff-ease-standard);
}
.panel-icon-btn:hover { color: var(--ff-danger-text); border-color: var(--ff-danger-border); }
.panel-eval-btn {
  display: inline-flex; align-items: center; justify-content: center; gap: 6px;
  height: 32px; border: 1px dashed var(--ff-border-strong); border-radius: var(--ff-radius-md);
  background: var(--ff-bg-subtle); color: var(--ff-text-brand); font-size: var(--ff-fs-caption);
  font-weight: 600; cursor: pointer; transition: background-color var(--ff-dur-fast) var(--ff-ease-standard), border-color var(--ff-dur-fast) var(--ff-ease-standard), color var(--ff-dur-fast) var(--ff-ease-standard), box-shadow var(--ff-dur-fast) var(--ff-ease-standard), transform var(--ff-dur-fast) var(--ff-ease-standard);
}
.panel-eval-btn:hover { border-color: var(--ff-brand); background: var(--ff-bg-hover); }
.panel-eval-btn:disabled { opacity: 0.5; cursor: not-allowed; }

/* ── 统计卡（紧凑，给结果表留空间）── */
.screener-stats { flex: none; display: grid; grid-template-columns: repeat(6, 1fr); gap: var(--ff-space-2); }
.screener-stat {
  display: flex; flex-direction: column; gap: 2px;
  padding: 6px 10px; background: var(--ff-bg-surface);
  border: 1px solid var(--ff-border); border-radius: var(--ff-radius-md);
  min-height: 0;
}
.screener-stat__label { font-size: 11px; color: var(--ff-text-tertiary); }
.screener-stat__value { font-size: 17px; font-weight: 700; font-family: var(--ff-font-mono); font-variant-numeric: tabular-nums; color: var(--ff-text-primary); line-height: 1.15; }
.screener-stat__value--sm { font-size: 12px; font-weight: 600; line-height: 1.35; }
.screener-stat--strong .screener-stat__value { color: var(--ff-up-text); }
.screener-stat--watch .screener-stat__value { color: var(--ff-warn-text); }
.screener-stat--observe .screener-stat__value { color: var(--ff-neutral-text); }

/* ── 引擎诊断条（紧凑）── */
.engine-diag {
  flex: none; display: flex; align-items: center; gap: var(--ff-space-2);
  padding: 5px 12px; background: var(--ff-bg-surface);
  border: 1px solid var(--ff-border); border-radius: var(--ff-radius-md);
  flex-wrap: wrap;
}
.engine-diag__weights { display: flex; align-items: center; gap: 8px; flex: 1; min-width: 180px; }
.engine-diag__w { display: flex; align-items: center; gap: 4px; min-width: 56px; }
.engine-diag__w-label { font-size: 11px; color: var(--ff-text-tertiary); }
.engine-diag__w-bar { flex: 1; height: 3px; border-radius: var(--ff-radius-pill); background: var(--ff-bg-subtle); overflow: hidden; min-width: 34px; }
.engine-diag__w-fill { display: block; height: 100%; border-radius: var(--ff-radius-pill); background: var(--ff-brand); }

/* ── 页签 ── */
.screener-tabs { flex: none; display: flex; align-items: center; gap: var(--ff-space-2); }
.screener-tabs__sp { margin-left: auto; }

/* ── 卡片 ── */
.screener-card { background: var(--ff-bg-surface); border: 1px solid var(--ff-border); border-radius: var(--ff-radius-lg); box-shadow: var(--ff-shadow-sm); overflow: hidden; display: flex; flex-direction: column; }
.screener-card--grow { flex: 1; min-height: 0; }
.screener-card__body { padding: var(--ff-space-3) var(--ff-space-4); overflow-y: auto; }
.screener-card__body--table { padding: 0; flex: 1; min-height: 0; overflow: hidden; display: flex; flex-direction: column; }
.screener-card__toggle {
  display: inline-flex; align-items: center; gap: 4px; padding: 4px 10px;
  border-radius: var(--ff-radius-md); font-size: var(--ff-fs-caption); font-weight: 500;
  color: var(--ff-text-secondary); background: transparent; border: 1px solid var(--ff-border);
  cursor: pointer; transition: background var(--ff-dur-fast), color var(--ff-dur-fast);
}
.screener-card__toggle:hover { background: var(--ff-bg-hover); color: var(--ff-text-primary); }

/* ── 空状态 ── */
.screener-empty { flex: 1; display: flex; flex-direction: column; align-items: center; justify-content: center; gap: var(--ff-space-3); padding: var(--ff-space-10) var(--ff-space-4); color: var(--ff-text-tertiary); font-size: var(--ff-fs-body); text-align: center; }
.screener-empty__hint { font-size: var(--ff-fs-caption); color: var(--ff-text-tertiary); }
.screener-empty--sm { padding: var(--ff-space-6) var(--ff-space-4); font-size: var(--ff-fs-body-sm); }

/* ── 工具栏 ── */
.screener-toolbar { flex: none; display: flex; align-items: center; gap: var(--ff-space-3); padding: 8px var(--ff-space-4); border-bottom: 1px solid var(--ff-border-subtle); flex-wrap: wrap; }
.screener-toolbar__search { display: inline-flex; align-items: center; gap: 6px; border: 1px solid var(--ff-border); border-radius: var(--ff-radius-md); padding: 0 10px; height: 30px; color: var(--ff-text-tertiary); }
.screener-toolbar__input { border: none; outline: none; background: transparent; font-size: var(--ff-fs-body-sm); width: 140px; color: var(--ff-text-primary); }
.screener-toolbar__tiers { display: flex; gap: 6px; }
.screener-toolbar__count { margin-left: auto; font-size: var(--ff-fs-caption); color: var(--ff-text-tertiary); }

/* ── 表格 ── */
.screener-table-wrap { flex: 1; min-height: 0; overflow: auto; }
.screener-table { width: 100%; border-collapse: collapse; font-size: var(--ff-fs-body-sm); }
.screener-table thead { position: sticky; top: 0; z-index: 1; background: var(--ff-bg-surface); }
.screener-table th { padding: 10px 8px; font-weight: 600; color: var(--ff-text-secondary); text-align: left; border-bottom: 1px solid var(--ff-border-subtle); white-space: nowrap; font-size: var(--ff-fs-caption); }
.screener-table td { padding: 10px 8px; border-bottom: 1px solid var(--ff-border-subtle); color: var(--ff-text-primary); white-space: nowrap; vertical-align: middle; }
.screener-table th.is-right, .screener-table td.is-right { text-align: right; }
.screener-table th.is-center, .screener-table td.is-center { text-align: center; }
.screener-table th.is-sortable { cursor: pointer; user-select: none; }
.screener-table th.is-sortable:hover { color: var(--ff-text-brand); }
.screener-table__sort { font-size: 9px; margin-left: 2px; color: var(--ff-text-brand); }
.screener-row { cursor: pointer; transition: background var(--ff-dur-fast); }
.screener-row:hover { background: var(--ff-bg-hover); }
.screener-row--strong { background: var(--ff-up-subtle); }
.screener-row--watch { background: var(--ff-warn-subtle); }
.screener-row--strong:hover, .screener-row--watch:hover { filter: brightness(0.98); }
.screener-table__code { font-family: var(--ff-font-mono); font-variant-numeric: tabular-nums; color: var(--ff-text-secondary); }
.screener-table__name { font-weight: 600; }
.screener-table__score { font-weight: 700; color: var(--ff-text-brand); font-family: var(--ff-font-mono); font-variant-numeric: tabular-nums; }
.screener-table__board { display: inline-block; padding: 1px 8px; border-radius: 999px; font-size: var(--ff-fs-caption); font-weight: 500; border: 1px solid var(--ff-border); color: var(--ff-text-secondary); background: var(--ff-bg-muted); white-space: nowrap; }
.screener-table__board.is-kcb { color: var(--ff-brand); border-color: var(--ff-border-strong); background: color-mix(in srgb, var(--ff-brand) 8%, transparent); }
.screener-table__board.is-cyb { color: var(--ff-warn-text); border-color: var(--ff-border-strong); background: color-mix(in srgb, var(--ff-warn-text) 8%, transparent); }
.is-up { color: var(--ff-up-text); }
.is-down { color: var(--ff-down-text); }
.is-warn { color: var(--ff-warn-text); }
.ml-prob { display: inline-block; padding: 1px 6px; border-radius: var(--ff-radius-pill); background: var(--ff-bg-brand-soft, var(--ff-bg-subtle)); color: var(--ff-text-brand); font-size: var(--ff-fs-caption); font-weight: 600; }

/* ── 展开详情 ── */
.screener-detail td { padding: 0; border-bottom: 1px solid var(--ff-border); background: var(--ff-bg-subtle); }
.screener-detail__body { padding: var(--ff-space-3) var(--ff-space-4); display: flex; flex-direction: column; gap: var(--ff-space-3); }
.screener-detail__meta { display: flex; flex-wrap: wrap; align-items: center; gap: var(--ff-space-2) var(--ff-space-4); font-size: var(--ff-fs-caption); color: var(--ff-text-secondary); }
.screener-detail__cols { display: flex; gap: var(--ff-space-4); align-items: flex-start; }
.screener-detail__left { flex: 1; min-width: 0; display: flex; flex-direction: column; gap: var(--ff-space-2); }
.screener-detail__text { font-size: var(--ff-fs-body-sm); color: var(--ff-text-secondary); line-height: 1.6; margin: 0; }
.screener-detail__text strong { color: var(--ff-text-primary); }
.screener-detail__tags { display: flex; flex-wrap: wrap; align-items: center; gap: var(--ff-space-2); }
.screener-detail__tag-title { font-size: var(--ff-fs-caption); color: var(--ff-text-tertiary); font-weight: 500; }
.screener-detail__tag { display: inline-flex; align-items: center; padding: 3px 8px; border-radius: var(--ff-radius-pill); font-size: var(--ff-fs-caption); font-weight: 500; background: var(--ff-bg-muted); color: var(--ff-text-secondary); }
.screener-detail__tag--good { background: var(--ff-up-subtle); color: var(--ff-up-text); }
.screener-detail__tag--warn { background: var(--ff-warn-subtle); color: var(--ff-warn-text); }

/* ── 图表 ── */
.charts-grid { display: grid; grid-template-columns: 1fr 1fr; gap: var(--ff-space-4); }
.chart-box { border: 1px solid var(--ff-border); border-radius: var(--ff-radius-lg); padding: var(--ff-space-3); background: var(--ff-bg-surface); }
.chart-box__title { margin: 0 0 var(--ff-space-2); font-size: var(--ff-fs-body-sm); font-weight: 600; color: var(--ff-text-secondary); }
.chart-box__canvas { width: 100%; height: 240px; }

/* ── 评估 ── */
.screener-eval { display: flex; flex-direction: column; gap: var(--ff-space-4); }
.eval-stats { display: grid; grid-template-columns: repeat(4, 1fr); gap: var(--ff-space-3); }
.eval-alert { display: flex; align-items: center; gap: 8px; padding: 8px 12px; border-radius: var(--ff-radius-md); background: var(--ff-warn-subtle); color: var(--ff-warn-text); border: 1px solid var(--ff-warn-border); font-size: var(--ff-fs-caption); }
.eval-alert--info { background: var(--ff-bg-subtle); color: var(--ff-text-brand); border-color: var(--ff-border-strong); }
.eval-table { overflow: auto; }

/* ── 策略说明弹窗 ── */
.strategy-doc { max-height: 62vh; overflow-y: auto; padding-right: 4px; }
.strategy-doc :deep(table) { width: 100%; border-collapse: collapse; margin: var(--ff-space-3) 0; }
.strategy-doc :deep(th), .strategy-doc :deep(td) { padding: 6px 8px; border: 1px solid var(--ff-border); text-align: left; font-size: var(--ff-fs-caption); }
.strategy-doc :deep(th) { background: var(--ff-bg-subtle); font-weight: 600; }
.strategy-doc :deep(blockquote) { margin: var(--ff-space-3) 0; padding: var(--ff-space-3) var(--ff-space-4); border-left: 3px solid var(--ff-brand); background: var(--ff-bg-subtle); color: var(--ff-text-secondary); border-radius: 0 var(--ff-radius-md) var(--ff-radius-md) 0; }
.strategy-doc :deep(code) { background: var(--ff-bg-subtle); padding: 1px 5px; border-radius: 4px; font-size: 12px; }

/* ── 对比弹窗 ── */
.cmp { display: flex; flex-direction: column; gap: var(--ff-space-4); }
.cmp-stats { display: grid; grid-template-columns: repeat(4, 1fr); gap: var(--ff-space-3); }
.cmp-table-wrap { max-height: 320px; overflow: auto; }

/* ── 下钻弹窗 ── */
.drill { display: flex; flex-direction: column; gap: var(--ff-space-4); }
.drill__head { display: flex; align-items: center; gap: var(--ff-space-3); }
.drill__name { margin: 0; font-size: var(--ff-fs-h3); font-weight: 700; }
.drill__code { font-family: var(--ff-font-mono); color: var(--ff-text-tertiary); font-size: var(--ff-fs-caption); }
.drill__cols { display: flex; gap: var(--ff-space-4); align-items: stretch; }
.drill__left { flex: 1; min-width: 0; display: grid; grid-template-columns: 1fr 1fr; gap: 6px 18px; align-content: start; }
.drill__kv { display: flex; justify-content: space-between; align-items: center; border-bottom: 1px dashed var(--ff-border-subtle); padding-bottom: 4px; font-size: var(--ff-fs-body-sm); }
.drill__radar { flex: none; width: 360px; max-width: 42%; }
.drill__kv span { color: var(--ff-text-tertiary); }
.drill__kv b { font-variant-numeric: tabular-nums; }
.drill__score { color: var(--ff-text-brand); font-size: var(--ff-fs-h3); }
.drill__text { font-size: var(--ff-fs-body-sm); color: var(--ff-text-secondary); line-height: 1.6; margin: 0; }
.drill__tags { display: flex; flex-wrap: wrap; gap: 6px; }

/* ── 响应式 ── */
@media (max-width: 1180px) {
  .screener-stats { grid-template-columns: repeat(3, 1fr); }
  .charts-grid { grid-template-columns: 1fr; }
  .eval-stats { grid-template-columns: repeat(2, 1fr); }
}
@media (max-width: 860px) {
  .screener-body { flex-direction: column; overflow-y: auto; }
  .screener-panel { width: 100%; }
  .screener-top { flex-direction: column; align-items: flex-start; }
  .screener-controls { flex-wrap: wrap; }
}
</style>
