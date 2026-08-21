<script setup>
/**
 * ThsLimitUp — 同花顺「涨停聚焦」四模块入口组件。
 *
 * 对应后端 /api/market/thslimitup?section=<intensity|ladder|wind|sentiment>
 * 与 /api/market/thslimitup_dates（历史交易日清单）。
 *
 * 四模块：
 *   - 涨停强度 intensity：涨停 / 炸板 / 跌停池 + 炸板率 / 封板率
 *   - 连板天梯 ladder：连板高度梯队（强势股）
 *   - 最强风口 wind：涨停简图（题材板块榜：题材名 / 涨停数 / 连板高度 / 涨停个股）
 *   - 市场情绪 sentiment：情绪总览 + 风向标股（高位股/板块龙头/异动股）
 *
 * 数据经 FinFeed 后端同源代理，规避浏览器跨域。红涨绿跌（--ff-text-up / --ff-down-text）。
 */
import { ref, computed, onMounted, watch } from 'vue'
import { api } from '../api/client'
import { todayStr } from '../composables/useAutoToday'
import AppTabs from '../ui/AppTabs.vue'
import AppSkeleton from '../ui/AppSkeleton.vue'
import AppEmpty from '../ui/AppEmpty.vue'
import AppButton from '../ui/AppButton.vue'
import AppIcon from '../ui/AppIcon.vue'
import AppDatePicker from '../ui/AppDatePicker.vue'

// 四大模块切换
const SECTIONS = [
  { value: 'intensity', label: '涨停强度' },
  { value: 'ladder', label: '连板天梯' },
  { value: 'wind', label: '最强风口' },
  { value: 'sentiment', label: '市场情绪' },
]
const section = ref('intensity')

// 涨停强度内的子池（涨停 / 炸板 / 跌停）
const POOLS = [
  { value: 'up', label: '涨停' },
  { value: 'open', label: '炸板' },
  { value: 'lower', label: '跌停' },
]
const poolTab = ref('up')

const loading = ref(false)
const err = ref('')
const noDataForDate = ref('')
const data = ref(null)

// 日期：空串 = 实时/当日；选择过去交易日 = 只读该日已采集快照
const selectedDate = ref('')
const availableDates = ref([])

const dateMax = todayStr()
const dateMin = computed(() => {
  const ds = availableDates.value
  return ds.length ? ds[ds.length - 1] : ''
})

// 数据来源标识：实时 / 历史快照 / 缓存兜底
const isLive = computed(() => data.value?.source === 'live')
const sourceLabel = computed(() => {
  const d = data.value
  if (!d) return ''
  const s = d.source
  if (s === 'db') return `历史快照 · 采集于 ${d.trade_date || d.date || ''}`
  if (s === 'cache') return `实时获取失败 · 展示最近快照（${d.cached_date || ''}）`
  return '实时数据'
})

// ---------------- 格式化 ----------------
function fmtNum(v) {
  if (v == null || v === '') return '—'
  if (typeof v === 'number') return v.toLocaleString('en-US')
  return String(v)
}
function fmtChg(v) {
  if (v == null || v === '') return '—'
  const n = Number(v)
  return (n > 0 ? '+' : '') + n.toFixed(2) + '%'
}
function fmtRate(v) {
  if (v == null) return '—'
  return (Number(v) * 100).toFixed(1) + '%'
}
function fmtYi(v) {
  if (v == null || v === '') return '—'
  const yi = Number(v) / 1e8
  return (yi > 0 ? '+' : '') + yi.toFixed(2) + '亿'
}
function chgClass(v) {
  if (v == null || v === '') return 'is-flat'
  const n = Number(v)
  return n > 0 ? 'is-up' : n < 0 ? 'is-down' : 'is-flat'
}
function boardLabel(b) {
  if (!b) return ''
  const m = {
    sh: '沪', sz: '深', cyb: '创业板', kcb: '科创板', bj: '北交',
  }
  return m[String(b).toLowerCase()] || b
}

// ---------------- 强度指标 ----------------
const intensityMetrics = computed(() => {
  const d = data.value
  if (!d || section.value !== 'intensity') return null
  const m = d.metrics || {}
  return {
    up: d.up_total ?? (d.up ? d.up.length : 0),
    open: d.open_total ?? (d.open ? d.open.length : 0),
    lower: d.lower_total ?? (d.lower ? d.lower.length : 0),
    brokenRate: fmtRate(m.broken_rate),
    sealRate: fmtRate(m.seal_rate),
  }
})
const activePoolRows = computed(() => {
  const d = data.value
  if (!d || section.value !== 'intensity') return []
  return d[poolTab.value] || []
})

// ---------------- 连板天梯 ----------------
const ladderTiers = computed(() => {
  const d = data.value
  if (!d || section.value !== 'ladder') return []
  return d.ladder || []
})

// ---------------- 最强风口（涨停简图 · 题材板块榜） ----------------
const windBlocks = computed(() => {
  const d = data.value
  if (!d || section.value !== 'wind') return []
  return d.blocks || []
})
const windSummary = computed(() => {
  const blocks = windBlocks.value
  if (!blocks.length) return null
  let total = 0
  let maxPlate = 0
  let maxHigh = ''
  for (const b of blocks) {
    total += b.limit_up_num || 0
    if ((b.limit_up_num || 0) > maxPlate) {
      maxPlate = b.limit_up_num
      maxHigh = b.high || ''
    }
  }
  return { topics: blocks.length, total, maxPlate, maxHigh }
})
const selectedTopic = ref('')
const selectedBlock = computed(() => {
  const blocks = windBlocks.value
  if (!blocks.length) return null
  const hit = blocks.find((b) => b.code === selectedTopic.value)
  return hit || blocks[0]
})
// squarified treemap（面积 ∝ 涨停数），坐标空间取容器宽高比，输出百分比矩形
const TREE_W = 100
const TREE_H = 62
function squarify(values, W, H) {
  // values: [{ key, area }] 按 area 降序；返回 [{ key, x, y, w, h }]
  const result = []
  let x = 0, y = 0, w = W, h = H
  let row = []
  let i = 0
  const areas = values.map((v) => ({ key: v.key, area: v.area * ((W * H) / (values.reduce((s, a) => s + a.area, 0) || 1)) }))
  const worst = (r, side) => {
    const s = r.reduce((a, b) => a + b.area, 0)
    const t = s / side
    let mx = 0
    for (const it of r) {
      const len = it.area / t
      const ar = Math.max(len, t) / Math.min(len, t)
      if (ar > mx) mx = ar
    }
    return mx
  }
  const layout = (r) => {
    const s = r.reduce((a, b) => a + b.area, 0)
    if (w >= h) {
      const t = s / h
      let cx = x
      for (const it of r) {
        const cw = it.area / t
        result.push({ key: it.key, x: cx, y, w: cw, h: t })
        cx += cw
      }
      y += t; h -= t
    } else {
      const t = s / w
      let cy = y
      for (const it of r) {
        const ch = it.area / t
        result.push({ key: it.key, x, y: cy, w: t, h: ch })
        cy += ch
      }
      x += t; w -= t
    }
  }
  while (i < areas.length) {
    const side = Math.min(w, h)
    if (!row.length) {
      row.push(areas[i]); i++
    } else if (worst(row.concat([areas[i]]), side) <= worst(row, side)) {
      row.push(areas[i]); i++
    } else {
      layout(row)
      row = []
    }
  }
  if (row.length) layout(row)
  return result
}
function tileColor(b) {
  const c = Number(b.change) || 0
  const a = Math.min(0.5, 0.16 + (Math.abs(c) / 0.1) * 0.34).toFixed(3)
  return c >= 0 ? `rgba(230, 60, 60, ${a})` : `rgba(22, 160, 90, ${a})`
}
const windTree = computed(() => {
  const blocks = windBlocks.value
  if (section.value !== 'wind' || !blocks.length) return []
  const values = blocks
    .map((b) => ({ key: b.code, area: b.limit_up_num || 0 }))
    .sort((a, b) => b.area - a.area)
  const rects = squarify(values, TREE_W, TREE_H)
  const map = Object.fromEntries(rects.map((r) => [r.key, r]))
  return blocks.map((b) => {
    const r = map[b.code]
    const left = Math.max(0, (r.x / TREE_W) * 100)
    const top = Math.max(0, (r.y / TREE_H) * 100)
    return {
      code: b.code,
      name: b.name,
      limit_up_num: b.limit_up_num,
      change: b.change,
      high: b.high,
      left,
      top,
      width: Math.min(100 - left, (r.w / TREE_W) * 100),
      height: Math.min(62 - top, (r.h / TREE_H) * 100),
      color: tileColor(b),
    }
  })
})

// ---------------- 市场情绪 ----------------
const sentimentCards = computed(() => {
  const d = data.value
  if (!d || section.value !== 'sentiment') return []
  const rf = d.rise_fall || {}
  const lu = d.limit_up || {}
  const to = d.turnover || {}
  const nf = d.north_flow
  const cards = [
    { label: '涨停家数', value: fmtNum(lu.now ?? rf.limit_up), sub: lu.pre != null ? `昨 ${lu.pre}` : '', tone: 'up' },
    { label: '跌停家数', value: fmtNum(rf.limit_down), sub: '', tone: 'down' },
    { label: '上涨家数', value: fmtNum(rf.rise), sub: '', tone: 'up' },
    { label: '下跌家数', value: fmtNum(rf.fall), sub: '', tone: 'down' },
    { label: '平盘', value: fmtNum(rf.deuce), sub: '', tone: 'flat' },
    { label: '成交额', value: fmtNum(to.now), sub: to.pre != null ? `昨 ${to.pre}` : '', tone: 'flat' },
  ]
  if (nf != null) {
    if (typeof nf === 'object') {
      cards.push({ label: '北向资金', value: fmtNum(nf.now), sub: nf.pre != null ? `昨 ${nf.pre}` : '', tone: 'flat' })
    } else {
      cards.push({ label: '北向资金', value: fmtNum(nf), sub: '', tone: 'flat' })
    }
  }
  return cards
})
const tradeStatusText = computed(() => {
  const d = data.value
  if (!d || section.value !== 'sentiment') return ''
  const ts = d.trade_status || {}
  const stat = ts.stat || ''
  const hgt = d.hgt_market_status || ''
  return [stat, hgt].filter(Boolean).join(' · ')
})

// ---------------- 市场情绪 · 风向标股 ----------------
const windVaneTabs = computed(() => {
  const d = data.value
  if (!d || section.value !== 'sentiment') return []
  return (d.wind_vane && d.wind_vane.tabs) || []
})
const windVaneTab = ref('')
const activeWindVane = computed(() => {
  const tabs = windVaneTabs.value
  if (!tabs.length) return null
  if (!windVaneTab.value || !tabs.find((t) => t.tab_name === windVaneTab.value)) {
    return tabs[0]
  }
  return tabs.find((t) => t.tab_name === windVaneTab.value)
})
watch(windVaneTabs, (t) => {
  if (t && t.length && !t.find((x) => x.tab_name === windVaneTab.value)) {
    windVaneTab.value = t[0].tab_name
  }
})

// ---------------- 加载 ----------------
async function load() {
  loading.value = true
  err.value = ''
  noDataForDate.value = ''
  data.value = null
  poolTab.value = 'up'
  try {
    const params = { section: section.value }
    if (selectedDate.value) params.date = selectedDate.value
    const r = await api.market('thslimitup', params)
    const d = r.data || r
    if (d && d.error) {
      if (typeof d.error === 'string' && d.error.includes('暂无')) noDataForDate.value = d.error
      else err.value = d.error
      return
    }
    data.value = d
    if (section.value === 'wind' && windBlocks.value.length) {
      selectedTopic.value = windBlocks.value[0].code
    }
  } catch (e) {
    err.value = e.message || String(e)
  } finally {
    loading.value = false
  }
}

async function loadDates() {
  try {
    const r = await api.market('thslimitup_dates')
    const d = r.data || r
    if (d && Array.isArray(d.dates)) {
      availableDates.value = d.dates
    }
  } catch (e) {
    /* 日期清单不可用时静默降级，仍可正常实时查看 */
  }
}

watch(section, load)
watch(poolTab, () => {})
watch(selectedDate, load)

onMounted(async () => {
  await loadDates()
  await load()
})
</script>

<template>
  <div class="lu">
    <header class="lu__hero">
      <div class="lu__hero-title">
        <AppIcon name="flame" size="lg" />
        <span>涨停聚焦</span>
      </div>
      <p class="lu__hero-sub">同花顺涨停强度 · 连板天梯 · 最强风口 · 市场情绪</p>
    </header>

    <div class="lu__controls">
      <AppTabs :items="SECTIONS" v-model="section" type="pill" class="lu__sections" />
      <div class="lu__controls-right">
        <AppDatePicker
          v-model="selectedDate"
          clearable
          size="sm"
          class="lu__datepicker"
          placeholder="实时（留空）"
          :min="dateMin"
          :max="dateMax"
          hint=""
        />
        <AppButton variant="tonal" size="sm" icon="refresh" :loading="loading" @click="load">
          刷新
        </AppButton>
      </div>
    </div>

    <div
      v-if="data && (data.source === 'db' || data.source === 'cache')"
      class="lu__banner"
      :class="data.source === 'cache' ? 'lu__banner--warn' : 'lu__banner--hist'"
    >
      <AppIcon :name="data.source === 'cache' ? 'alert-triangle' : 'history'" size="sm" />
      <span>{{ sourceLabel }}</span>
    </div>

    <div v-if="loading" class="lu__loading">
      <AppSkeleton variant="text" :lines="10" />
    </div>

    <div v-else-if="err" class="ff-alert ff-alert--danger">
      <AppIcon name="alert-circle" size="md" /> {{ err }}
    </div>

    <div v-else-if="noDataForDate" class="lu__notice">
      <AppIcon name="calendar" size="md" />
      <span>{{ noDataForDate }}。请选择其它日期，或清除日期查看实时数据。</span>
    </div>

    <!-- ============ 涨停强度 ============ -->
    <template v-else-if="section === 'intensity' && data">
      <div class="lu__metrics">
        <div class="lu__metric lu__metric--up">
          <span class="lu__metric-label">涨停</span>
          <span class="lu__metric-val">{{ intensityMetrics.up }}</span>
        </div>
        <div class="lu__metric lu__metric--open">
          <span class="lu__metric-label">炸板</span>
          <span class="lu__metric-val">{{ intensityMetrics.open }}</span>
        </div>
        <div class="lu__metric lu__metric--lower">
          <span class="lu__metric-label">跌停</span>
          <span class="lu__metric-val">{{ intensityMetrics.lower }}</span>
        </div>
        <div class="lu__metric">
          <span class="lu__metric-label">炸板率</span>
          <span class="lu__metric-val">{{ intensityMetrics.brokenRate }}</span>
        </div>
        <div class="lu__metric">
          <span class="lu__metric-label">封板率</span>
          <span class="lu__metric-val">{{ intensityMetrics.sealRate }}</span>
        </div>
      </div>

      <div class="lu__subtabs">
        <AppTabs :items="POOLS" v-model="poolTab" type="pill" size="sm" />
      </div>

      <div v-if="activePoolRows.length" class="lu__list">
        <div class="lu__list-head">
          <span class="lu__col-rank">#</span>
          <span class="lu__col-stock">名称 / 代码</span>
          <span class="lu__col-board">板块</span>
          <span class="lu__col-mid">连板</span>
          <span class="lu__col-time">封板时间</span>
          <span class="lu__col-chg">涨跌幅</span>
          <span class="lu__col-money">主力净额</span>
        </div>
        <div v-for="(row, i) in activePoolRows" :key="(row.code || '') + '-' + i" class="lu__row">
          <span class="lu__col-rank ff-num">{{ i + 1 }}</span>
          <div class="lu__col-stock">
            <div class="lu__stock-main">
              <span class="lu__name">{{ row.name }}</span>
              <span class="lu__code">{{ row.code }}</span>
            </div>
            <div v-if="row.reason" class="lu__tag">{{ row.reason }}</div>
          </div>
          <span class="lu__col-board">{{ boardLabel(row.board) }}</span>
          <span class="lu__col-mid ff-num" :class="row.continue_day_cnt > 1 ? 'is-up' : 'is-flat'">
            {{ row.continue_day_cnt > 1 ? row.continue_day_cnt + '板' : '首板' }}
          </span>
          <span class="lu__col-time ff-num">{{ row.limit_up_time || '—' }}</span>
          <span class="lu__col-chg ff-num" :class="chgClass(row.change_pct)">{{ fmtChg(row.change_pct) }}</span>
          <span class="lu__col-money ff-num" :class="chgClass(row.main_net_amount)">{{ fmtYi(row.main_net_amount) }}</span>
        </div>
      </div>
      <AppEmpty v-else icon="inbox" :title="`暂无${POOLS.find(p => p.value === poolTab)?.label || ''}数据`" />
    </template>

    <!-- ============ 连板天梯 ============ -->
    <template v-else-if="section === 'ladder' && data">
      <div v-if="ladderTiers.length" class="lu__ladder">
        <div v-for="tier in ladderTiers" :key="tier.height" class="lu__tier">
          <div class="lu__tier-head">
            <span class="lu__tier-height" :class="tier.height >= 5 ? 'is-hot' : ''">{{ tier.height }}板</span>
            <span class="lu__tier-count">{{ tier.number }}只</span>
          </div>
          <div class="lu__tier-stocks">
            <div v-for="s in tier.stocks" :key="(s.code || '') + '-' + s.name" class="lu__chip">
              <div class="lu__chip-row">
                <span class="lu__chip-name">{{ s.name }}</span>
                <span class="lu__chip-code">{{ s.code }}</span>
                <span class="lu__chip-chg ff-num" :class="chgClass(s.change_pct)">{{ fmtChg(s.change_pct) }}</span>
              </div>
              <span v-if="s.reason" class="lu__chip-reason" :title="s.reason">{{ s.reason }}</span>
            </div>
          </div>
        </div>
      </div>
      <AppEmpty v-else icon="layers" title="暂无连板天梯数据" />
    </template>

    <!-- ============ 最强风口（涨停简图） ============ -->
    <template v-else-if="section === 'wind' && data">
      <div v-if="windBlocks.length" class="lu__wind">
        <!-- 概览指标 -->
        <div class="lu__wind-summary" v-if="windSummary">
          <div class="lu__ws">
            <span class="lu__ws-val ff-num">{{ windSummary.topics }}</span>
            <span class="lu__ws-label">题材数</span>
          </div>
          <div class="lu__ws">
            <span class="lu__ws-val ff-num is-up">{{ windSummary.total }}</span>
            <span class="lu__ws-label">涨停合计</span>
          </div>
          <div class="lu__ws">
            <span class="lu__ws-val ff-num is-up">{{ windSummary.maxPlate }}</span>
            <span class="lu__ws-label">最多涨停题材</span>
          </div>
          <div class="lu__ws">
            <span class="lu__ws-val">{{ windSummary.maxHigh || '—' }}</span>
            <span class="lu__ws-label">最高板</span>
          </div>
        </div>

        <!-- 涨停简图：squarified treemap，矩形面积 ∝ 涨停数，色深 ∝ 题材涨幅 -->
        <div class="lu__tree">
          <button
            v-for="cell in windTree"
            :key="cell.code"
            class="lu__cell"
            :class="{ 'is-active': selectedBlock && selectedBlock.code === cell.code }"
            :style="{
              left: cell.left + '%',
              top: cell.top + '%',
              width: cell.width + '%',
              height: cell.height + '%',
              background: cell.color,
            }"
            @click="selectedTopic = cell.code"
          >
            <span class="lu__cell-name">{{ cell.name }}</span>
            <span class="lu__cell-num ff-num">{{ cell.limit_up_num }}<i>板</i></span>
            <span v-if="cell.height > 15" class="lu__cell-high">{{ cell.high }}</span>
            <span v-if="cell.width > 15" class="lu__cell-chg ff-num" :class="chgClass(cell.change)">{{ fmtChg(cell.change) }}</span>
          </button>
        </div>

        <!-- 选中题材的涨停个股 -->
        <div v-if="selectedBlock" class="lu__topic">
          <div class="lu__topic-head">
            <span class="lu__topic-name">{{ selectedBlock.name }}</span>
            <span class="lu__topic-num is-up">{{ selectedBlock.limit_up_num }}只涨停</span>
            <span class="lu__topic-high">连板高度 {{ selectedBlock.high || '—' }}</span>
          </div>
          <div v-if="selectedBlock.stocks.length" class="lu__chips">
            <div
              v-for="(s, i) in selectedBlock.stocks"
              :key="(s.code || '') + '-' + i"
              class="lu__sc"
              :class="{ 'is-st': s.is_st }"
            >
              <div class="lu__sc-row">
                <span class="lu__sc-name">{{ s.name }}</span>
                <span class="lu__sc-code">{{ s.code }}</span>
                <span class="lu__sc-chg ff-num" :class="chgClass(s.change_rate)">{{ fmtChg(s.change_rate) }}</span>
              </div>
              <div class="lu__sc-sub">
                <span class="lu__sc-plate" v-if="s.high">{{ s.high }}</span>
                <span class="lu__sc-reason">{{ s.reason_type || '—' }}</span>
              </div>
            </div>
          </div>
          <AppEmpty v-else icon="wind" title="该题材暂无涨停个股" />
        </div>
      </div>
      <AppEmpty v-else icon="wind" title="暂无涨停简图数据" />
    </template>

    <!-- ============ 市场情绪 ============ -->
    <template v-else-if="section === 'sentiment' && data">
      <div v-if="tradeStatusText" class="lu__status">
        <AppIcon name="activity" size="sm" />
        <span>{{ tradeStatusText }}</span>
      </div>
      <div v-if="sentimentCards.length" class="lu__sent">
        <div v-for="c in sentimentCards" :key="c.label" class="lu__sent-card" :class="`is-${c.tone}`">
          <span class="lu__sent-label">{{ c.label }}</span>
          <span class="lu__sent-val ff-num">{{ c.value }}</span>
          <span v-if="c.sub" class="lu__sent-sub">{{ c.sub }}</span>
        </div>
      </div>

      <!-- 风向标股：高位股 / 板块龙头 / 异动股 / 前期高位 -->
      <div v-if="windVaneTabs.length" class="lu__vane">
        <div class="lu__vane-head">
          <AppIcon name="compass" size="sm" />
          <span class="lu__vane-title">风向标股</span>
          <span class="lu__vane-hint">市场核心情绪标杆</span>
        </div>
        <div class="lu__vane-tabs">
          <AppTabs
            :items="windVaneTabs.map(t => ({ value: t.tab_name, label: t.tab_name }))"
            v-model="windVaneTab"
            type="pill"
            size="sm"
          />
        </div>
        <div v-if="activeWindVane" class="lu__vane-body">
          <div class="lu__vane-sub">
            <span class="lu__vane-sub-name">{{ activeWindVane.tab_name }}</span>
            <span class="lu__vane-sub-num ff-num">{{ activeWindVane.stock_num }}只</span>
            <span class="lu__vane-sub-chg ff-num" :class="chgClass(activeWindVane.average_change)">
              均值 {{ fmtChg(activeWindVane.average_change) }}
            </span>
          </div>
          <div v-if="activeWindVane.stocks.length" class="lu__vane-list">
            <div
              v-for="(s, i) in activeWindVane.stocks"
              :key="(s.stock_code || '') + '-' + i"
              class="lu__vane-item"
            >
              <span class="lu__vane-rank ff-num">{{ i + 1 }}</span>
              <div class="lu__vane-stock">
                <div class="lu__vane-stock-row">
                  <span class="lu__vane-name">{{ s.stock_name }}</span>
                  <span class="lu__vane-code">{{ s.stock_code }}</span>
                  <span class="lu__vane-chg ff-num" :class="chgClass(s.change)">{{ fmtChg(s.change) }}</span>
                </div>
                <div
                  v-if="s.tags || s.reason || (s.five_rise != null && s.five_rise !== '')"
                  class="lu__vane-stock-sub"
                >
                  <span v-if="s.tags" class="lu__vane-tags">{{ s.tags }}</span>
                  <span v-if="s.reason" class="lu__vane-reason">{{ s.reason }}</span>
                  <span
                    v-if="s.five_rise != null && s.five_rise !== ''"
                    class="lu__vane-5rise ff-num"
                    :class="chgClass(s.five_rise)"
                  >5日 {{ fmtChg(s.five_rise) }}</span>
                </div>
              </div>
            </div>
          </div>
          <AppEmpty v-else icon="compass" title="该分类暂无风向标股" />
        </div>
      </div>

      <AppEmpty
        v-if="!sentimentCards.length && !windVaneTabs.length"
        icon="activity"
        title="暂无市场情绪数据"
      />
    </template>

    <AppEmpty v-else icon="flame" title="暂无涨停聚焦数据" />
  </div>
</template>

<style scoped>
.lu {
  display: flex;
  flex-direction: column;
}

/* ---------- 头部 ---------- */
.lu__hero {
  padding: var(--ff-space-5) var(--ff-space-5) var(--ff-space-3);
}
.lu__hero-title {
  display: flex;
  align-items: center;
  gap: var(--ff-space-2);
  font-size: var(--ff-fs-h3);
  font-weight: var(--ff-fw-semibold);
  color: var(--ff-text-primary);
}
.lu__hero-title :deep(.ff-icon) {
  color: #ff6a3d;
}
.lu__hero-sub {
  margin: var(--ff-space-1) 0 0;
  font-size: var(--ff-fs-caption);
  color: var(--ff-text-tertiary);
}

/* ---------- 控制条 ---------- */
.lu__controls {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--ff-space-3);
  flex-wrap: wrap;
  padding: var(--ff-space-3) var(--ff-space-5);
  border-bottom: 1px solid var(--ff-border-subtle);
}
.lu__controls-right {
  display: flex;
  align-items: center;
  gap: var(--ff-space-2);
}
.lu__datepicker {
  width: 168px;
  flex: 0 0 auto;
}
.lu__sections {
  flex: 1 1 auto;
  min-width: 0;
  overflow-x: auto;
}

/* ---------- 横幅 / 状态 ---------- */
.lu__banner {
  display: flex;
  align-items: center;
  gap: var(--ff-space-2);
  margin: var(--ff-space-2) var(--ff-space-5);
  padding: var(--ff-space-2) var(--ff-space-4);
  border-radius: var(--ff-radius-md);
  font-size: var(--ff-fs-body-sm);
  color: var(--ff-text-secondary);
}
.lu__banner--hist {
  background: color-mix(in srgb, var(--ff-brand) 8%, transparent);
}
.lu__banner--hist :deep(.ff-icon) {
  color: var(--ff-brand-text);
}
.lu__banner--warn {
  background: color-mix(in srgb, #ff9f2e 12%, transparent);
  color: #b9701a;
}
.lu__banner--warn :deep(.ff-icon) {
  color: #d98324;
}
.lu__loading {
  padding: var(--ff-space-5);
}
.lu__notice {
  display: flex;
  align-items: center;
  gap: var(--ff-space-2);
  margin: var(--ff-space-4) var(--ff-space-5);
  padding: var(--ff-space-3) var(--ff-space-4);
  border-radius: var(--ff-radius-md);
  background: color-mix(in srgb, var(--ff-brand) 8%, transparent);
  color: var(--ff-text-secondary);
  font-size: var(--ff-fs-body-sm);
}
.lu__notice :deep(.ff-icon) {
  color: var(--ff-brand-text);
  flex: 0 0 auto;
}
.lu__status {
  display: flex;
  align-items: center;
  gap: var(--ff-space-2);
  margin: var(--ff-space-3) var(--ff-space-5) 0;
  padding: var(--ff-space-2) var(--ff-space-4);
  border-radius: var(--ff-radius-md);
  background: var(--ff-bg-hover);
  color: var(--ff-text-secondary);
  font-size: var(--ff-fs-body-sm);
  font-weight: var(--ff-fw-medium);
}

/* ---------- 强度指标条 ---------- */
.lu__metrics {
  display: grid;
  grid-template-columns: repeat(5, 1fr);
  gap: var(--ff-space-3);
  padding: var(--ff-space-4) var(--ff-space-5) 0;
}
.lu__metric {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 2px;
  padding: var(--ff-space-3);
  border-radius: var(--ff-radius-md);
  background: var(--ff-bg-hover);
  border: 1px solid var(--ff-border-subtle);
}
.lu__metric-label {
  font-size: var(--ff-fs-caption);
  color: var(--ff-text-tertiary);
}
.lu__metric-val {
  font-size: var(--ff-fs-h3);
  font-weight: var(--ff-fw-bold);
  font-variant-numeric: tabular-nums;
  color: var(--ff-text-primary);
}
.lu__metric--up .lu__metric-val {
  color: var(--ff-text-up);
}
.lu__metric--open .lu__metric-val {
  color: #d98324;
}
.lu__metric--lower .lu__metric-val {
  color: var(--ff-down-text);
}

/* ---------- 子榜切换 ---------- */
.lu__subtabs {
  padding: var(--ff-space-3) var(--ff-space-5) 0;
  overflow-x: auto;
}

/* ---------- 列表（强度 / 风口） ---------- */
.lu__list {
  display: flex;
  flex-direction: column;
  margin-top: var(--ff-space-3);
}
.lu__list-head,
.lu__row {
  display: grid;
  grid-template-columns: 44px 1fr 64px 56px 92px 84px 96px;
  align-items: center;
  gap: var(--ff-space-3);
  padding: var(--ff-space-2-5) var(--ff-space-5);
}
.lu__list-head {
  font-size: var(--ff-fs-caption);
  color: var(--ff-text-tertiary);
  border-bottom: 1px solid var(--ff-border-subtle);
}
.lu__row {
  border-bottom: 1px solid var(--ff-border-subtle);
  transition: background-color var(--ff-dur-fast) var(--ff-ease-standard);
}
.lu__row:hover {
  background: var(--ff-bg-hover);
}
.lu__col-rank {
  color: var(--ff-text-tertiary);
  font-weight: var(--ff-fw-semibold);
}
.lu__stock-main {
  display: flex;
  align-items: baseline;
  gap: var(--ff-space-2);
  min-width: 0;
}
.lu__name {
  font-size: var(--ff-fs-body);
  font-weight: var(--ff-fw-semibold);
  color: var(--ff-text-primary);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
.lu__code {
  font-size: var(--ff-fs-caption);
  color: var(--ff-text-tertiary);
  font-variant-numeric: tabular-nums;
  flex: 0 0 auto;
}
.lu__tag {
  display: inline-block;
  margin-top: 4px;
  max-width: 100%;
  font-size: 11px;
  line-height: 1.6;
  padding: 0 6px;
  border-radius: var(--ff-radius-sm);
  background: color-mix(in srgb, #ff6a3d 14%, transparent);
  color: #d9431f;
  white-space: normal;
  word-break: break-all;
}
.lu__col-board,
.lu__col-time,
.lu__col-reason {
  font-size: var(--ff-fs-body-sm);
  color: var(--ff-text-secondary);
}
.lu__col-reason {
  line-height: 1.4;
  word-break: break-all;
  white-space: normal;
}
.lu__col-mid,
.lu__col-chg,
.lu__col-money {
  text-align: right;
  justify-self: end;
  font-weight: var(--ff-fw-semibold);
  font-size: var(--ff-fs-body);
}
.lu__col-money {
  font-size: var(--ff-fs-body-sm);
}

/* ---------- 连板天梯 ---------- */
.lu__ladder {
  display: flex;
  flex-direction: column;
  gap: var(--ff-space-2);
  padding: var(--ff-space-4) var(--ff-space-5);
}
.lu__tier {
  display: flex;
  align-items: flex-start;
  gap: var(--ff-space-3);
  padding: var(--ff-space-3);
  border-radius: var(--ff-radius-md);
  border: 1px solid var(--ff-border-subtle);
  background: var(--ff-bg-surface);
}
.lu__tier-head {
  flex: 0 0 auto;
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 2px;
  width: 56px;
}
.lu__tier-height {
  font-size: var(--ff-fs-h3);
  font-weight: var(--ff-fw-bold);
  color: var(--ff-text-up);
  font-variant-numeric: tabular-nums;
}
.lu__tier-height.is-hot {
  background: linear-gradient(135deg, #ff7a45, #ff4d4f);
  color: #fff;
  border-radius: var(--ff-radius-sm);
  padding: 2px 8px;
}
.lu__tier-count {
  font-size: var(--ff-fs-caption);
  color: var(--ff-text-tertiary);
}
.lu__tier-stocks {
  display: flex;
  flex-wrap: wrap;
  gap: var(--ff-space-2);
  flex: 1 1 auto;
}
.lu__chip {
  display: flex;
  flex-direction: column;
  align-items: flex-start;
  gap: 2px;
  max-width: 100%;
  padding: 4px 10px;
  border-radius: var(--ff-radius-pill);
  background: var(--ff-bg-hover);
  border: 1px solid var(--ff-border-subtle);
}
.lu__chip-row {
  display: flex;
  align-items: center;
  gap: 6px;
  min-width: 0;
}
.lu__chip-name {
  font-size: var(--ff-fs-body-sm);
  font-weight: var(--ff-fw-semibold);
  color: var(--ff-text-primary);
  white-space: nowrap;
}
.lu__chip-code {
  font-size: var(--ff-fs-caption);
  color: var(--ff-text-tertiary);
  font-variant-numeric: tabular-nums;
}
.lu__chip-chg {
  font-size: var(--ff-fs-caption);
  font-weight: var(--ff-fw-semibold);
}
.lu__chip-reason {
  display: block;
  width: 100%;
  font-size: 11px;
  color: var(--ff-text-secondary);
  line-height: 1.4;
  word-break: break-all;
  white-space: normal;
}

/* ---------- 最强风口（涨停简图） ---------- */
.lu__wind {
  display: flex;
  flex-direction: column;
  gap: var(--ff-space-4);
  padding: var(--ff-space-4) 0;
}

/* 概览指标 */
.lu__wind-summary {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: var(--ff-space-3);
  padding: 0 var(--ff-space-5);
}
.lu__ws {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 2px;
  padding: var(--ff-space-3);
  border-radius: var(--ff-radius-md);
  background: var(--ff-bg-surface);
  border: 1px solid var(--ff-border-subtle);
}
.lu__ws-val {
  font-size: var(--ff-fs-h3);
  font-weight: var(--ff-fw-bold);
  color: var(--ff-text-primary);
  font-variant-numeric: tabular-nums;
}
.lu__ws-label {
  font-size: var(--ff-fs-caption);
  color: var(--ff-text-tertiary);
}

/* 涨停简图：squarified treemap */
.lu__tree {
  position: relative;
  aspect-ratio: 100 / 62;
  margin: 0 var(--ff-space-5);
  border-radius: var(--ff-radius-md);
  overflow: hidden;
  border: 1px solid var(--ff-border-subtle);
  background: var(--ff-bg-hover);
}
.lu__cell {
  position: absolute;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 1px;
  padding: 2px;
  border: 1px solid color-mix(in srgb, var(--ff-text-primary) 12%, transparent);
  border-radius: 3px;
  color: var(--ff-text-primary);
  cursor: pointer;
  text-align: center;
  overflow: hidden;
  transition: box-shadow var(--ff-dur-fast) var(--ff-ease-standard),
    transform var(--ff-dur-fast) var(--ff-ease-standard);
}
.lu__cell:hover {
  transform: scale(1.015);
  z-index: 2;
  box-shadow: var(--ff-shadow-sm);
}
.lu__cell.is-active {
  z-index: 3;
  border-color: #ff6a3d;
  box-shadow: 0 0 0 2px #ff6a3d;
}
.lu__cell-name {
  font-size: var(--ff-fs-caption);
  font-weight: var(--ff-fw-semibold);
  line-height: 1.1;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  max-width: 100%;
}
.lu__cell-num {
  font-size: var(--ff-fs-body);
  font-weight: var(--ff-fw-bold);
  font-variant-numeric: tabular-nums;
  color: var(--ff-text-up);
}
.lu__cell-num i {
  font-size: 10px;
  font-style: normal;
  font-weight: var(--ff-fw-medium);
  margin-left: 1px;
}
.lu__cell-high {
  font-size: 10px;
  line-height: 1.1;
  color: var(--ff-text-secondary);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  max-width: 100%;
}
.lu__cell-chg {
  font-size: 10px;
  font-weight: var(--ff-fw-semibold);
}

/* 选中题材的涨停个股 */
.lu__topic {
  margin: 0 var(--ff-space-5);
  padding: var(--ff-space-4);
  border-radius: var(--ff-radius-md);
  background: var(--ff-bg-surface);
  border: 1px solid var(--ff-border-subtle);
}
.lu__topic-head {
  display: flex;
  align-items: baseline;
  gap: var(--ff-space-3);
  flex-wrap: wrap;
  padding-bottom: var(--ff-space-3);
  border-bottom: 1px solid var(--ff-border-subtle);
  margin-bottom: var(--ff-space-3);
}
.lu__topic-name {
  font-size: var(--ff-fs-h3);
  font-weight: var(--ff-fw-semibold);
  color: var(--ff-text-primary);
}
.lu__topic-num {
  font-size: var(--ff-fs-body);
  font-weight: var(--ff-fw-semibold);
}
.lu__topic-high {
  font-size: var(--ff-fs-caption);
  color: var(--ff-text-tertiary);
}
.lu__chips {
  display: flex;
  flex-wrap: wrap;
  gap: var(--ff-space-2);
}
.lu__sc {
  display: flex;
  flex-direction: column;
  gap: 2px;
  min-width: 120px;
  padding: 4px 10px;
  border-radius: var(--ff-radius-pill);
  background: var(--ff-bg-hover);
  border: 1px solid var(--ff-border-subtle);
}
.lu__sc.is-st {
  border-color: color-mix(in srgb, #ff4d4f 45%, transparent);
  background: color-mix(in srgb, #ff4d4f 8%, transparent);
}
.lu__sc-row {
  display: flex;
  align-items: baseline;
  gap: 6px;
  min-width: 0;
}
.lu__sc-name {
  font-size: var(--ff-fs-body-sm);
  font-weight: var(--ff-fw-semibold);
  color: var(--ff-text-primary);
  white-space: nowrap;
}
.lu__sc-code {
  font-size: var(--ff-fs-caption);
  color: var(--ff-text-tertiary);
  font-variant-numeric: tabular-nums;
  flex: 0 0 auto;
}
.lu__sc-chg {
  font-size: var(--ff-fs-caption);
  font-weight: var(--ff-fw-semibold);
}
.lu__sc-sub {
  display: flex;
  align-items: center;
  gap: 6px;
  min-width: 0;
  font-size: 11px;
  color: var(--ff-text-secondary);
}
.lu__sc-plate {
  flex: 0 0 auto;
  color: var(--ff-text-tertiary);
}
.lu__sc-reason {
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

/* ---------- 市场情绪 · 风向标股 ---------- */
.lu__vane {
  display: flex;
  flex-direction: column;
  gap: var(--ff-space-3);
  margin-top: var(--ff-space-3);
  padding: 0 var(--ff-space-5);
}
.lu__vane-head {
  display: flex;
  align-items: center;
  gap: var(--ff-space-2);
  padding-top: var(--ff-space-2);
  border-top: 1px solid var(--ff-border-subtle);
}
.lu__vane-head :deep(.ff-icon) {
  color: var(--ff-brand-text);
}
.lu__vane-title {
  font-size: var(--ff-fs-h3);
  font-weight: var(--ff-fw-semibold);
  color: var(--ff-text-primary);
}
.lu__vane-hint {
  font-size: var(--ff-fs-caption);
  color: var(--ff-text-tertiary);
}
.lu__vane-tabs {
  overflow-x: auto;
}
.lu__vane-body {
  display: flex;
  flex-direction: column;
  gap: var(--ff-space-2);
}
.lu__vane-sub {
  display: flex;
  align-items: center;
  gap: var(--ff-space-3);
}
.lu__vane-sub-name {
  font-size: var(--ff-fs-body);
  font-weight: var(--ff-fw-semibold);
  color: var(--ff-text-primary);
}
.lu__vane-sub-num {
  font-size: var(--ff-fs-caption);
  color: var(--ff-text-tertiary);
}
.lu__vane-sub-chg {
  font-size: var(--ff-fs-caption);
  font-weight: var(--ff-fw-semibold);
}
.lu__vane-list {
  display: flex;
  flex-direction: column;
}
.lu__vane-item {
  display: flex;
  align-items: flex-start;
  gap: var(--ff-space-3);
  padding: var(--ff-space-2-5) 0;
  border-bottom: 1px solid var(--ff-border-subtle);
}
.lu__vane-item:last-child {
  border-bottom: none;
}
.lu__vane-rank {
  flex: 0 0 auto;
  width: 28px;
  text-align: center;
  color: var(--ff-text-tertiary);
  font-weight: var(--ff-fw-semibold);
}
.lu__vane-stock {
  flex: 1 1 auto;
  min-width: 0;
}
.lu__vane-stock-row {
  display: flex;
  align-items: baseline;
  gap: var(--ff-space-2);
}
.lu__vane-name {
  font-size: var(--ff-fs-body);
  font-weight: var(--ff-fw-semibold);
  color: var(--ff-text-primary);
}
.lu__vane-code {
  font-size: var(--ff-fs-caption);
  color: var(--ff-text-tertiary);
  font-variant-numeric: tabular-nums;
}
.lu__vane-chg {
  font-size: var(--ff-fs-body-sm);
  font-weight: var(--ff-fw-semibold);
}
.lu__vane-stock-sub {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 6px;
  margin-top: 2px;
  font-size: 11px;
  color: var(--ff-text-secondary);
}
.lu__vane-tags {
  padding: 0 6px;
  border-radius: var(--ff-radius-sm);
  background: color-mix(in srgb, var(--ff-brand) 12%, transparent);
  color: var(--ff-brand-text);
}
.lu__vane-reason {
  line-height: 1.4;
  word-break: break-all;
}
.lu__vane-5rise {
  flex: 0 0 auto;
  font-weight: var(--ff-fw-semibold);
}

/* ---------- 市场情绪 ---------- */
.lu__sent {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(150px, 1fr));
  gap: var(--ff-space-3);
  padding: var(--ff-space-4) var(--ff-space-5);
}
.lu__sent-card {
  display: flex;
  flex-direction: column;
  gap: 2px;
  padding: var(--ff-space-3) var(--ff-space-4);
  border-radius: var(--ff-radius-md);
  background: var(--ff-bg-surface);
  border: 1px solid var(--ff-border-subtle);
}
.lu__sent-label {
  font-size: var(--ff-fs-caption);
  color: var(--ff-text-tertiary);
}
.lu__sent-val {
  font-size: var(--ff-fs-h3);
  font-weight: var(--ff-fw-bold);
  color: var(--ff-text-primary);
}
.lu__sent-sub {
  font-size: var(--ff-fs-caption);
  color: var(--ff-text-tertiary);
}
.lu__sent-card.is-up .lu__sent-val {
  color: var(--ff-text-up);
}
.lu__sent-card.is-down .lu__sent-val {
  color: var(--ff-down-text);
}

/* ---------- 红涨绿跌 ---------- */
.is-up {
  color: var(--ff-text-up);
}
.is-down {
  color: var(--ff-down-text);
}
.is-flat {
  color: var(--ff-text-tertiary);
}

/* ---------- 响应式 ---------- */
@media (max-width: 640px) {
  .lu__metrics {
    grid-template-columns: repeat(3, 1fr);
  }
  .lu__list-head,
  .lu__row {
    grid-template-columns: 36px 1fr 60px 84px;
  }
  .lu__col-board,
  .lu__col-mid,
  .lu__col-time,
  .lu__col-money,
  .lu__col-reason {
    display: none;
  }
  .lu__list-head {
    grid-template-columns: 36px 1fr 84px;
  }
}
</style>
