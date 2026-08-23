<script setup>
/**
 * SectorMinuteView — 板块分时（web 左侧导航入口）
 *
 * 核心能力（对齐 板块分时.md）：
 *  - 双标的池：板块（行业/二级/概念/风格/地区）+ 沪深个股，统一搜索勾选
 *  - 双布局：垂直混排 / 板块-个股左右分屏
 *  - 涨跌幅归一化对比 + 均价线 + 昨收线 + 成交量
 *  - 后台自动刷新（15/30/60s 档位）+ 手动强制刷新
 *  - 多图悬停联动 + 按涨幅排序 + 亮暗主题自适应
 */
import { ref, computed, watch, onMounted, onUnmounted } from 'vue'
import { useAppStore } from '../store/app'
import { sectorMinuteApi } from '../api/sectorMinute'
import AppIcon from '../ui/AppIcon.vue'
import AppSegmented from '../ui/AppSegmented.vue'
import SectorMinuteChart from '../components/sectorMinute/SectorMinuteChart.vue'

const app = useAppStore()

// ---------------- 布局 / 显示偏好 ----------------
const layout = ref('rows') // rows 垂直混排 | columns 左右分屏
const refreshInterval = ref(30) // 15 / 30 / 60
const normalized = ref(true) // Y 轴：涨跌幅归一化 / 绝对价格
const showAvg = ref(true)
const showPreClose = ref(true)
const sortByPct = ref(false)
const hoverIndex = ref(-1)

// ---------------- 标的池 ----------------
const activeTab = ref('board') // board | stock
const boardType = ref('hy') // hy/hy2/gn/fg/dq
const stockKw = ref('')
const stockMarket = ref('') // '' 全部 | '1' 沪 | '0' 深
const boards = ref([])
const stocks = ref([])
const selected = ref([]) // [{kind,market,code,name,board_type}]

const BOARD_TYPES = [
  { value: 'hy', label: '行业' },
  { value: 'hy2', label: '二级' },
  { value: 'gn', label: '概念' },
  { value: 'fg', label: '风格' },
  { value: 'dq', label: '地区' },
]
const MARKETS = [
  { value: '', label: '全部' },
  { value: '1', label: '沪市' },
  { value: '0', label: '深市' },
]
const INTERVALS = [
  { value: 15, label: '15s' },
  { value: 30, label: '30s' },
  { value: 60, label: '60s' },
]

// ---------------- 数据状态 ----------------
const charts = ref([])
const health = ref({})
const lastUpdateLabel = ref('')
const loadingBoards = ref(false)
const loadingStocks = ref(false)
const refreshing = ref(false)
const errorMsg = ref('')

let pollTimer = null
let stockSearchTimer = null
let catchUpTimer = null // 数据补齐轮询：勾选/刷新后快速拉取直到全部到位
let stockReqSeq = 0 // 请求序号：忽略过期响应，避免快速输入时结果乱序

const selectedKeys = computed(() => new Set(selected.value.map((s) => `${s.kind}:${s.market}:${s.code}`)))
const selectedCount = computed(() => selected.value.length)
const trading = computed(() => health.value?.trading)

// 垂直混排：全部选中标的；左右分屏：左板右股
const rowsCharts = computed(() =>
  layout.value === 'columns'
    ? charts.value.filter((c) => c.kind === 'board')
    : charts.value,
)
const colsStockCharts = computed(() => charts.value.filter((c) => c.kind === 'stock'))

// ---------------- 工具 ----------------
const pctCls = (v) => (v > 0 ? 'is-up' : v < 0 ? 'is-down' : 'is-flat')
const fmtPct = (v) =>
  v === null || v === undefined ? '—' : (v > 0 ? '+' : '') + Number(v).toFixed(2) + '%'
const fmtNum = (v, d = 2) =>
  v === null || v === undefined || !Number.isFinite(v) ? '—' : Number(v).toFixed(d)

// ---------------- 数据加载 ----------------
async function loadBoards() {
  loadingBoards.value = true
  try {
    const data = await sectorMinuteApi.boards(boardType.value)
    boards.value = data.items || []
  } catch (e) {
    errorMsg.value = e.message || String(e)
  } finally {
    loadingBoards.value = false
  }
}

async function loadStocks() {
  const seq = ++stockReqSeq
  loadingStocks.value = true
  try {
    const data = await sectorMinuteApi.stocks(stockKw.value)
    if (seq !== stockReqSeq) return // 过期响应直接丢弃
    stocks.value = data.items || []
  } catch (e) {
    if (seq === stockReqSeq) errorMsg.value = e.message || String(e)
  } finally {
    if (seq === stockReqSeq) loadingStocks.value = false
  }
}

// 个股关键词输入：防抖自动搜索（支持中文名称/代码）
function onStockInput() {
  if (activeTab.value !== 'stock') return
  clearTimeout(stockSearchTimer)
  stockSearchTimer = setTimeout(() => {
    if (stockKw.value.trim()) loadStocks()
  }, 350)
}

async function loadCharts() {
  try {
    const data = await sectorMinuteApi.charts()
    const items = data.items || []
    const byKey = new Map(items.map((c) => [`${c.kind}:${c.market}:${c.code}`, c]))
    // 未取到数据的标的生成占位卡片（名称可见、图表区不缺失），数据到位后自动填充
    let list = selected.value.map((s) => {
      const k = `${s.kind}:${s.market}:${s.code}`
      return (
        byKey.get(k) || {
          kind: s.kind,
          market: s.market,
          code: s.code,
          name: s.name,
          board_type: s.board_type || '',
          pre_close: 0,
          open: null,
          high: null,
          low: null,
          close: null,
          change_pct: null,
          change_amt: null,
          points: [],
          ts: '',
        }
      )
    })
    if (sortByPct.value) {
      // 按涨幅降序；无数据占位（null）沉底
      list = [...list].sort(
        (a, b) => (b.change_pct ?? -Infinity) - (a.change_pct ?? -Infinity),
      )
    }
    charts.value = list
    if (data.ts) {
      lastUpdateLabel.value = new Date(data.ts * 1000).toLocaleTimeString('zh-CN', { hour12: false })
    }
  } catch (e) {
    errorMsg.value = e.message || String(e)
  }
}

async function loadHealth() {
  try {
    health.value = await sectorMinuteApi.health()
  } catch (e) {
    errorMsg.value = e.message || String(e)
  }
}

async function syncSubscriptions() {
  if (!selected.value.length) return
  try {
    await sectorMinuteApi.setSubscriptions(
      selected.value.map((s) => ({
        kind: s.kind,
        market: s.market,
        code: s.code,
        name: s.name,
        board_type: s.board_type,
      })),
    )
    // 后台线程异步抓取中：启动补齐轮询，数据到位后自动填充
    startCatchUp()
  } catch (e) {
    errorMsg.value = e.message || String(e)
  }
}

// 数据补齐轮询：每 1.5s 拉取一次 charts，直到所有已选标的均有分时数据
// （后台自动抓取到位后即停止；上限 20 次防无限轮询）
function startCatchUp() {
  clearTimeout(catchUpTimer)
  let tries = 0
  const tick = async () => {
    await loadCharts()
    const withData = new Set(
      charts.value
        .filter((c) => c.points && c.points.length)
        .map((c) => `${c.kind}:${c.market}:${c.code}`),
    )
    const allReady = selected.value.every((s) =>
      withData.has(`${s.kind}:${s.market}:${s.code}`),
    )
    if (allReady || ++tries >= 20) {
      catchUpTimer = null
      return
    }
    catchUpTimer = setTimeout(tick, 1500)
  }
  tick()
}

function stopCatchUp() {
  if (catchUpTimer) {
    clearTimeout(catchUpTimer)
    catchUpTimer = null
  }
}

// ---------------- 交互 ----------------
function toggleTarget(t) {
  const key = `${t.kind}:${t.market}:${t.code}`
  if (selectedKeys.value.has(key)) {
    selected.value = selected.value.filter((s) => `${s.kind}:${s.market}:${s.code}` !== key)
  } else {
    if (selected.value.length >= 15) {
      errorMsg.value = '单屏最多对比 15 个标的'
      return
    }
    selected.value.push({
      kind: t.kind,
      market: t.market,
      code: t.code,
      name: t.name,
      board_type: t.board_type || '',
    })
  }
  persistSelected()
  syncSubscriptions()
}

function removeTarget(key) {
  selected.value = selected.value.filter((s) => `${s.kind}:${s.market}:${s.code}` !== key)
  persistSelected()
  if (selected.value.length) syncSubscriptions()
  else {
    charts.value = []
    sectorMinuteApi.setSubscriptions([]).catch(() => {})
  }
}

function persistSelected() {
  localStorage.setItem('sectorMinute_selected', JSON.stringify(selected.value))
}

async function manualRefresh() {
  refreshing.value = true
  errorMsg.value = ''
  try {
    await sectorMinuteApi.refresh()
  } catch (e) {
    errorMsg.value = e.message || String(e)
  }
  await Promise.all([loadCharts(), loadHealth()])
  refreshing.value = false
  startCatchUp()
}

function onHover(i) {
  hoverIndex.value = i
}

function changeBoardType(t) {
  boardType.value = t
  loadBoards()
}

function onStockSearch() {
  loadStocks()
}

// ---------------- 生命周期 ----------------
async function init() {
  errorMsg.value = ''
  // 恢复自选（localStorage 为准，同步到服务端）
  try {
    const saved = JSON.parse(localStorage.getItem('sectorMinute_selected') || '[]')
    if (Array.isArray(saved)) {
      selected.value = saved.filter((s) => s && s.code)
    }
  } catch (e) {
    /* ignore */
  }
  await Promise.all([loadBoards(), loadHealth()])
  if (selected.value.length) syncSubscriptions()
  await loadCharts()
  if (selected.value.length) startCatchUp() // 兜底：恢复自选后若数据未齐，快速补齐
  startPolling()
}

function startPolling() {
  stopPolling()
  pollTimer = setInterval(() => {
    loadCharts()
  }, refreshInterval.value * 1000)
}

function stopPolling() {
  if (pollTimer) {
    clearInterval(pollTimer)
    pollTimer = null
  }
}

watch(refreshInterval, () => startPolling())
watch(sortByPct, () => loadCharts())
watch(stockMarket, () => loadStocks())

onMounted(init)
onUnmounted(() => {
  stopPolling()
  stopCatchUp()
  if (stockSearchTimer) clearTimeout(stockSearchTimer)
})

// ---------------- 过滤后的展示列表 ----------------
const visibleBoards = computed(() => {
  if (!stockKw.value) return boards.value
  const kw = stockKw.value.trim()
  return boards.value.filter((b) => b.code.includes(kw) || b.name.includes(kw))
})
const visibleStocks = computed(() => {
  if (!stockMarket.value) return stocks.value
  return stocks.value.filter((s) => String(s.market) === stockMarket.value)
})
</script>

<template>
  <div class="smm">
    <!-- ══════ 顶部工具栏 ══════ -->
    <header class="smm__top">
      <div class="smm__title">
        <span class="smm__mark"><AppIcon name="activity" size="md" /></span>
        <div>
          <h1 class="smm__name">板块分时</h1>
          <p class="smm__sub">多标的垂直分时对比 · 板块/个股分屏对标</p>
        </div>
      </div>

      <div class="smm__controls">
        <AppSegmented
          v-model="layout"
          :options="[
            { value: 'rows', label: '垂直混排' },
            { value: 'columns', label: '左右分屏' },
          ]"
          size="sm"
        />
        <span class="smm__sep"></span>
        <AppSegmented
          v-model="normalized"
          :options="[
            { value: true, label: '涨跌幅' },
            { value: false, label: '绝对价' },
          ]"
          size="sm"
        />
        <span class="smm__sep"></span>
        <button
          type="button"
          class="smm__chip"
          :class="{ 'is-on': sortByPct }"
          title="按当前涨幅排序"
          @click="sortByPct = !sortByPct"
        >
          <AppIcon name="trending-up" size="sm" />
          涨幅排序
        </button>
        <span class="smm__sep"></span>
        <span class="smm__lbl">刷新</span>
        <AppSegmented v-model="refreshInterval" :options="INTERVALS" size="sm" />
        <button
          type="button"
          class="smm__chip smm__chip--refresh"
          :class="{ 'is-spinning': refreshing }"
          title="手动强制刷新"
          @click="manualRefresh"
        >
          <AppIcon name="refresh" size="sm" :spin="refreshing" />
          刷新
        </button>
      </div>

      <div class="smm__status">
        <span class="smm__dot" :class="trading ? 'is-live' : ''"></span>
        <span class="smm__time">最后更新 {{ lastUpdateLabel || '--:--:--' }}</span>
        <span class="smm__count">{{ selectedCount }} / 15</span>
      </div>
    </header>

    <!-- ══════ 主体：左面板 + 主显示区 ══════ -->
    <div class="smm__body">
      <!-- 左面板 -->
      <aside class="smm__panel">
        <div class="smm__tabs">
          <button
            type="button"
            class="smm__tab"
            :class="activeTab === 'board' && 'is-active'"
            @click="activeTab = 'board'"
          >
            板块
          </button>
          <button
            type="button"
            class="smm__tab"
            :class="activeTab === 'stock' && 'is-active'"
            @click="activeTab = 'stock'"
          >
            个股
          </button>
        </div>

        <!-- 板块池 -->
        <template v-if="activeTab === 'board'">
          <AppSegmented
            v-model="boardType"
            :options="BOARD_TYPES"
            size="sm"
            class="smm__btype"
            @change="changeBoardType"
          />
          <div class="smm__search">
            <AppIcon name="search" size="sm" class="smm__search-icon" />
            <input
              v-model="stockKw"
              type="text"
              placeholder="搜索板块名称 / 代码"
              class="smm__input"
            />
          </div>
          <div v-if="loadingBoards" class="smm__hint">加载中…</div>
          <div v-else class="smm__list">
            <button
              v-for="b in visibleBoards"
              :key="b.code"
              type="button"
              class="smm__item"
              :class="{ 'is-on': selectedKeys.has('board:1:' + b.code) }"
              @click="toggleTarget({ kind: 'board', market: 1, code: b.code, name: b.name, board_type: b.board_type })"
            >
              <span class="smm__check">
                <AppIcon v-if="selectedKeys.has('board:1:' + b.code)" name="check" size="xs" />
              </span>
              <span class="smm__item-name">{{ b.name }}</span>
              <span class="smm__item-code">{{ b.code }}</span>
              <span class="smm__item-pct" :class="pctCls(b.rise_pct)">{{ fmtPct(b.rise_pct) }}</span>
            </button>
            <div v-if="!visibleBoards.length" class="smm__empty">暂无板块数据</div>
          </div>
        </template>

        <!-- 个股池 -->
        <template v-else>
          <div class="smm__search">
            <AppIcon name="search" size="sm" class="smm__search-icon" />
            <input
              v-model="stockKw"
              type="text"
              placeholder="搜索个股名称 / 代码"
              class="smm__input"
              @input="onStockInput"
              @keyup.enter="onStockSearch"
            />
          </div>
          <div class="smm__mkrow">
            <AppSegmented v-model="stockMarket" :options="MARKETS" size="sm" />
            <button type="button" class="smm__chip" @click="onStockSearch">
              <AppIcon name="search" size="xs" /> 查询
            </button>
          </div>
          <div v-if="loadingStocks" class="smm__hint">加载中…</div>
          <div v-else class="smm__list">
            <button
              v-for="s in visibleStocks"
              :key="s.code"
              type="button"
              class="smm__item"
              :class="{ 'is-on': selectedKeys.has('stock:' + s.market + ':' + s.code) }"
              @click="toggleTarget({ kind: 'stock', market: s.market, code: s.code, name: s.name })"
            >
              <span class="smm__check">
                <AppIcon v-if="selectedKeys.has('stock:' + s.market + ':' + s.code)" name="check" size="xs" />
              </span>
              <span class="smm__item-name">{{ s.name }}</span>
              <span class="smm__item-code">{{ s.code }}</span>
              <span class="smm__item-pct" :class="pctCls(s.change_pct)">{{ fmtPct(s.change_pct) }}</span>
            </button>
            <div v-if="!visibleStocks.length" class="smm__empty">输入关键词后点「查询」</div>
          </div>
        </template>

        <!-- 底部：已选 + 状态 -->
        <div class="smm__panel-foot">
          <div v-if="selected.length" class="smm__sel">
            <div class="smm__sel-label">已选（{{ selected.length }}）</div>
            <div class="smm__sel-list">
              <span
                v-for="s in selected"
                :key="`${s.kind}:${s.market}:${s.code}`"
                class="smm__sel-chip"
              >
                <span class="smm__sel-kind" :class="s.kind === 'stock' ? 'is-stock' : 'is-board'">
                  {{ s.kind === 'stock' ? '股' : '板' }}
                </span>
                {{ s.name }}
                <button
                  type="button"
                  class="smm__sel-x"
                  title="移除"
                  @click="removeTarget(`${s.kind}:${s.market}:${s.code}`)"
                >
                  <AppIcon name="x" size="xs" />
                </button>
              </span>
            </div>
          </div>
          <div class="smm__status-line">
            <span class="smm__dot" :class="trading ? 'is-live' : ''"></span>
            <span>{{ trading ? '交易时段' : '非交易时段' }}</span>
            <span class="smm__sp"></span>
            <span>更新 {{ lastUpdateLabel || '--:--:--' }}</span>
          </div>
        </div>
      </aside>

      <!-- 主显示区 -->
      <main class="smm__main">
        <div v-if="errorMsg" class="smm__alert">
          <AppIcon name="alert-circle" size="sm" /> {{ errorMsg }}
        </div>

        <!-- 空状态 -->
        <div v-if="!selected.length" class="smm__empty-main">
          <AppIcon name="activity" size="xl" />
          <p>在左侧勾选板块或个股，开始多标的分时对比</p>
          <p class="smm__empty-sub">支持板块-个股混合排列与左右分屏对标</p>
        </div>

        <!-- 垂直混排 -->
        <div v-else-if="layout === 'rows'" class="smm__rows">
          <div v-for="c in rowsCharts" :key="`${c.kind}:${c.market}:${c.code}`" class="smm__card">
            <SectorMinuteChart
              :chart="c"
              :normalized="normalized"
              :show-avg="showAvg"
              :show-pre-close="showPreClose"
              :theme="app.theme"
              :hover-index="hoverIndex"
              @hover="onHover"
              @remove="removeTarget(`${c.kind}:${c.market}:${c.code}`)"
            />
          </div>
        </div>

        <!-- 左右分屏：左板右股 -->
        <div v-else class="smm__cols">
          <div class="smm__col">
            <div class="smm__col-head">板块</div>
            <div v-if="rowsCharts.length" class="smm__col-list">
              <div v-for="c in rowsCharts" :key="`b${c.code}`" class="smm__card">
                <SectorMinuteChart
                  :chart="c"
                  :normalized="normalized"
                  :show-avg="showAvg"
                  :show-pre-close="showPreClose"
                  :theme="app.theme"
                  :hover-index="hoverIndex"
                  @hover="onHover"
                  @remove="removeTarget(`${c.kind}:${c.market}:${c.code}`)"
                />
              </div>
            </div>
            <div v-else class="smm__col-empty">未选择板块</div>
          </div>
          <div class="smm__col">
            <div class="smm__col-head">个股</div>
            <div v-if="colsStockCharts.length" class="smm__col-list">
              <div v-for="c in colsStockCharts" :key="`s${c.code}`" class="smm__card">
                <SectorMinuteChart
                  :chart="c"
                  :normalized="normalized"
                  :show-avg="showAvg"
                  :show-pre-close="showPreClose"
                  :theme="app.theme"
                  :hover-index="hoverIndex"
                  @hover="onHover"
                  @remove="removeTarget(`${c.kind}:${c.market}:${c.code}`)"
                />
              </div>
            </div>
            <div v-else class="smm__col-empty">未选择个股</div>
          </div>
        </div>
      </main>
    </div>
  </div>
</template>

<style scoped>
.smm {
  height: 100%;
  min-height: 0;
  display: flex;
  flex-direction: column;
}

/* ═══════ 顶部工具栏 ═══════ */
.smm__top {
  flex: none;
  display: flex;
  align-items: center;
  gap: var(--ff-space-4);
  padding: var(--ff-space-3) var(--ff-space-4);
  background: var(--ff-bg-surface);
  border: 1px solid var(--ff-border);
  border-radius: var(--ff-radius-lg);
  box-shadow: var(--ff-shadow-sm, none);
  margin-bottom: var(--ff-space-3);
  flex-wrap: wrap;
}
.smm__title {
  display: flex;
  align-items: center;
  gap: var(--ff-space-3);
  min-width: 200px;
}
.smm__mark {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 34px;
  height: 34px;
  flex: none;
  border-radius: 10px;
  background: var(--ff-bg-brand);
  color: var(--ff-brand-fg);
}
.smm__name {
  font-size: var(--ff-fs-h3);
  font-weight: 700;
  line-height: 1.2;
}
.smm__sub {
  font-size: var(--ff-fs-caption);
  color: var(--ff-text-tertiary);
}
.smm__controls {
  display: flex;
  align-items: center;
  gap: var(--ff-space-2);
  flex-wrap: wrap;
}
.smm__sep {
  width: 1px;
  height: 20px;
  background: var(--ff-border);
  margin: 0 2px;
}
.smm__lbl {
  font-size: var(--ff-fs-caption);
  color: var(--ff-text-tertiary);
}
.smm__chip {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 5px 11px;
  border: 1px solid var(--ff-border);
  border-radius: var(--ff-radius-pill);
  font-size: var(--ff-fs-caption);
  font-weight: 500;
  color: var(--ff-text-secondary);
  background: var(--ff-bg-surface);
  transition: background var(--ff-dur-fast), color var(--ff-dur-fast), border-color var(--ff-dur-fast);
}
.smm__chip:hover {
  background: var(--ff-bg-hover);
  color: var(--ff-text-primary);
}
.smm__chip.is-on {
  border-color: var(--ff-brand-border);
  background: var(--ff-bg-brand-subtle);
  color: var(--ff-text-brand);
}
.smm__chip.is-spinning {
  opacity: 0.7;
}
.smm__status {
  margin-left: auto;
  display: flex;
  align-items: center;
  gap: var(--ff-space-3);
  font-size: var(--ff-fs-caption);
  color: var(--ff-text-tertiary);
  white-space: nowrap;
}
.smm__dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  background: var(--ff-icon-muted);
  flex: none;
}
.smm__dot.is-live {
  background: var(--ff-down);
  box-shadow: 0 0 0 3px rgba(18, 161, 80, 0.15);
}
.smm__time {
  font-family: var(--ff-font-mono, monospace);
}
.smm__count {
  font-family: var(--ff-font-mono, monospace);
  padding: 2px 8px;
  border-radius: var(--ff-radius-pill);
  background: var(--ff-bg-subtle);
  color: var(--ff-text-secondary);
}

/* ═══════ 主体 ═══════ */
.smm__body {
  flex: 1;
  min-height: 0;
  display: flex;
  gap: var(--ff-space-3);
}

/* —— 左面板 —— */
.smm__panel {
  width: 264px;
  flex: none;
  display: flex;
  flex-direction: column;
  min-height: 0;
  background: var(--ff-bg-surface);
  border: 1px solid var(--ff-border);
  border-radius: var(--ff-radius-lg);
  overflow: hidden;
}
.smm__tabs {
  flex: none;
  display: flex;
  border-bottom: 1px solid var(--ff-border);
}
.smm__tab {
  flex: 1;
  padding: 9px 0;
  text-align: center;
  font-size: var(--ff-fs-body-sm);
  font-weight: 500;
  color: var(--ff-text-secondary);
  border-bottom: 2px solid transparent;
  transition: color var(--ff-dur-fast), border-color var(--ff-dur-fast);
}
.smm__tab.is-active {
  color: var(--ff-text-brand);
  font-weight: 600;
  border-bottom-color: var(--ff-brand);
}
.smm__btype {
  flex: none;
  margin: var(--ff-space-2) var(--ff-space-3) 0;
}
.smm__search {
  flex: none;
  display: flex;
  align-items: center;
  gap: 6px;
  margin: var(--ff-space-2) var(--ff-space-3);
  padding: 0 10px;
  height: 34px;
  border: 1px solid var(--ff-border);
  border-radius: var(--ff-radius-md);
  background: var(--ff-bg-subtle);
}
.smm__search-icon {
  color: var(--ff-icon-muted);
  flex: none;
}
.smm__input {
  flex: 1;
  min-width: 0;
  background: transparent;
  border: none;
  outline: none;
  color: var(--ff-text-primary);
  font-size: var(--ff-fs-body-sm);
}
.smm__mkrow {
  flex: none;
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 0 var(--ff-space-3) var(--ff-space-2);
}
.smm__hint {
  flex: none;
  padding: var(--ff-space-3);
  text-align: center;
  color: var(--ff-text-tertiary);
  font-size: var(--ff-fs-caption);
}
.smm__list {
  flex: 1;
  min-height: 0;
  overflow-y: auto;
  padding: 0 var(--ff-space-2) var(--ff-space-2);
}
.smm__item {
  display: flex;
  align-items: center;
  gap: 8px;
  width: 100%;
  padding: 7px 8px;
  border-radius: var(--ff-radius-sm);
  font-size: var(--ff-fs-body-sm);
  text-align: left;
  transition: background var(--ff-dur-fast);
}
.smm__item:hover {
  background: var(--ff-bg-hover);
}
.smm__item.is-on {
  background: var(--ff-bg-brand-subtle);
}
.smm__check {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 16px;
  height: 16px;
  flex: none;
  border: 1px solid var(--ff-border-strong);
  border-radius: 4px;
  color: #fff;
  background: transparent;
}
.smm__item.is-on .smm__check {
  background: var(--ff-brand);
  border-color: var(--ff-brand);
}
.smm__item-name {
  flex: 1;
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  color: var(--ff-text-primary);
  font-weight: 500;
}
.smm__item-code {
  font-family: var(--ff-font-mono, monospace);
  font-size: 11px;
  color: var(--ff-text-tertiary);
}
.smm__item-pct {
  font-family: var(--ff-font-mono, monospace);
  font-size: var(--ff-fs-caption);
  font-weight: 600;
  width: 58px;
  text-align: right;
  font-variant-numeric: tabular-nums;
}
.smm__empty {
  padding: 20px 8px;
  text-align: center;
  color: var(--ff-text-tertiary);
  font-size: var(--ff-fs-caption);
}
.smm__panel-foot {
  flex: none;
  border-top: 1px solid var(--ff-border-subtle);
  padding: var(--ff-space-2) var(--ff-space-3);
  display: flex;
  flex-direction: column;
  gap: var(--ff-space-2);
}
.smm__sel-label {
  font-size: var(--ff-fs-caption);
  color: var(--ff-text-tertiary);
}
.smm__sel-list {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  max-height: 96px;
  overflow-y: auto;
}
.smm__sel-chip {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  padding: 3px 6px 3px 3px;
  border-radius: var(--ff-radius-pill);
  background: var(--ff-bg-subtle);
  font-size: 11.5px;
  color: var(--ff-text-secondary);
}
.smm__sel-kind {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 16px;
  height: 16px;
  border-radius: 50%;
  font-size: 10px;
  font-weight: 700;
  color: #fff;
  flex: none;
}
.smm__sel-kind.is-board { background: var(--ff-brand); }
.smm__sel-kind.is-stock { background: var(--ff-accent-teal); }
.smm__sel-x {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 16px;
  height: 16px;
  border-radius: 50%;
  color: var(--ff-icon-muted);
  transition: background var(--ff-dur-fast), color var(--ff-dur-fast);
}
.smm__sel-x:hover {
  background: var(--ff-bg-hover);
  color: var(--ff-up-text);
}
.smm__status-line {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: var(--ff-fs-caption);
  color: var(--ff-text-tertiary);
  border-top: 1px solid var(--ff-border-subtle);
  padding-top: var(--ff-space-2);
}
.smm__sp {
  flex: 1;
}

/* —— 主显示区 —— */
.smm__main {
  flex: 1;
  min-width: 0;
  min-height: 0;
  display: flex;
  flex-direction: column;
  gap: var(--ff-space-3);
  overflow-y: auto;
}
.smm__alert {
  flex: none;
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 9px 14px;
  border-radius: var(--ff-radius-md);
  background: var(--ff-bg-down-subtle, #fdecea);
  color: var(--ff-down-text, #c0392b);
  font-size: var(--ff-fs-body-sm);
}
.smm__empty-main {
  flex: 1;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 10px;
  color: var(--ff-text-tertiary);
  font-size: var(--ff-fs-body);
  min-height: 280px;
}
.smm__empty-sub {
  font-size: var(--ff-fs-caption);
}

/* 垂直混排 */
.smm__rows {
  display: flex;
  flex-direction: column;
  gap: var(--ff-space-3);
}
.smm__card {
  flex: none;
  height: 236px;
  padding: var(--ff-space-2) var(--ff-space-3);
  background: var(--ff-bg-surface);
  border: 1px solid var(--ff-border);
  border-radius: var(--ff-radius-lg);
  box-shadow: var(--ff-shadow-sm, none);
}

/* 左右分屏 */
.smm__cols {
  flex: 1;
  min-height: 0;
  display: flex;
  gap: var(--ff-space-3);
}
.smm__col {
  flex: 1;
  min-width: 0;
  min-height: 0;
  display: flex;
  flex-direction: column;
  border: 1px solid var(--ff-border);
  border-radius: var(--ff-radius-lg);
  background: var(--ff-bg-surface);
  overflow: hidden;
}
.smm__col-head {
  flex: none;
  padding: 8px 14px;
  font-size: var(--ff-fs-body-sm);
  font-weight: 600;
  color: var(--ff-text-secondary);
  border-bottom: 1px solid var(--ff-border-subtle);
}
.smm__col-list {
  flex: 1;
  min-height: 0;
  overflow-y: auto;
  display: flex;
  flex-direction: column;
  gap: var(--ff-space-3);
  padding: var(--ff-space-3);
}
.smm__col-empty {
  flex: 1;
  display: flex;
  align-items: center;
  justify-content: center;
  color: var(--ff-text-tertiary);
  font-size: var(--ff-fs-body-sm);
}

/* ═══════ 响应式 ═══════ */
@media (max-width: 1180px) {
  .smm__panel { width: 232px; }
}
@media (max-width: 980px) {
  .smm__panel { display: none; }
  .smm__cols { flex-direction: column; }
}
</style>
