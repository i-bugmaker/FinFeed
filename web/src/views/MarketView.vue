<script setup>
import { ref, onMounted, onBeforeUnmount, watch, computed } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { api } from '../api/client'
import { useAutoToday, todayStr } from '../composables/useAutoToday'
import EmptyState from '../components/EmptyState.vue'
import AppCard from '../ui/AppCard.vue'
import AppButton from '../ui/AppButton.vue'
import AppInput from '../ui/AppInput.vue'
import AppDatePicker from '../ui/AppDatePicker.vue'
import AppTabs from '../ui/AppTabs.vue'
import AppIcon from '../ui/AppIcon.vue'
import AppSkeleton from '../ui/AppSkeleton.vue'

const route = useRoute()
const router = useRouter()

const tabs = [
  { value: 'overview', label: '总览' },
  { value: 'sentiment', label: '市场情绪' },
  { value: 'limitup', label: '涨停' },
  { value: 'limitdown', label: '跌停' },
  { value: 'limitbroken', label: '炸板' },
  { value: 'billboard', label: '龙虎榜' },
  { value: 'moneyflow', label: '资金流' },
  { value: 'margin', label: '两融' },
  { value: 'forecast', label: '业绩预告' },
  { value: 'ipo', label: '新股' },
  { value: 'sectors', label: '板块' },
  { value: 'search', label: '股票搜索' },
]
const active = ref('overview')
// 默认选中当日；用户未手动改日期时随时间自动滚动到当前日期
const { date, markTouched } = useAutoToday()
const data = ref(null)
const rows = ref([])
const summary = ref(null)
const loading = ref(false)
const err = ref('')
const kw = ref('')

// ── URL 状态同步：tab/日期/搜索词落入 query，刷新与分享后不丢 ──
{
  const qTab = route.query.tab
  if (typeof qTab === 'string' && tabs.some((t) => t.value === qTab)) active.value = qTab
  const qDate = route.query.date
  if (typeof qDate === 'string' && /^\d{4}-\d{2}-\d{2}$/.test(qDate)) {
    date.value = qDate
    markTouched()
  }
  const qKw = route.query.kw
  if (typeof qKw === 'string') kw.value = qKw
}
watch([active, date, kw], ([a, d, k]) => {
  const q = {}
  if (a && a !== 'overview') q.tab = a
  if (d && d !== todayStr()) q.date = d // 当日为默认态，不写 URL
  if (k) q.kw = k
  router.replace({ query: q }).catch(() => {})
})

// 后台自动采集调度状态（仅用于展示下次/上次执行时间，开关已移除）
const autoLast = ref({})
const autoNext = ref({})
let statusTimer = null

// 行情数据自动刷新：固定 30 秒，后台静默执行，无任何交互控件
// （日期类 tab 数据盘后变化低频，30s 轮询足够）
const AUTO_REFRESH_MS = 30 * 1000
const lastUpdated = ref('')
let refreshTimer = null
// 搜索结果由用户输入驱动，不参与自动刷新
const REFRESH_SKIP_TABS = new Set(['search'])

function fmtClock(d = new Date()) {
  const p = (n) => String(n).padStart(2, '0')
  return `${p(d.getHours())}:${p(d.getMinutes())}:${p(d.getSeconds())}`
}

function startAutoRefresh() {
  stopAutoRefresh()
  refreshTimer = setInterval(() => {
    if (document.hidden || loading.value || runningAction.value) return
    if (REFRESH_SKIP_TABS.has(active.value)) return
    load()
  }, AUTO_REFRESH_MS)
}
function stopAutoRefresh() {
  if (refreshTimer) {
    clearInterval(refreshTimer)
    refreshTimer = null
  }
}
function onVisibilityChange() {
  // 切回页面时立即刷新一次，避免看到陈旧盘面
  if (!document.hidden && !REFRESH_SKIP_TABS.has(active.value)) {
    load()
  }
}

const HEADER_MAP = {
  code: '代码', name: '名称', trade_date: '交易日', date: '日期', reason: '涨停原因',
  buy_amount: '买入额', sell_amount: '卖出额', net_amount: '净额', turnover_ratio: '换手率',
  detail: '明细', close_price: '收盘价', pct_chg: '涨跌幅', deal_amount: '成交额',
  accum_amount: '累计额', free_mv: '自由市值', direction: '方向', first_limit_time: '首次封板',
  last_limit_time: '最后封板', open_times: '开板次数', limit_amount: '封板额',
  circ_mv: '流通市值', limit_streak: '连板', price: '现价', turnover: '换手率',
  amount: '成交额', total_mv: '总市值', main_net: '主力净流入', super_net: '超大单净流入',
  big_net: '大单净流入', mid_net: '中单净流入', small_net: '小单净流入', main_ratio: '主力占比',
  org_participate: '机构参与度', source: '来源', market: '市场', fin_balance: '融资余额',
  fin_buy: '融资买入', fin_net: '融资净买', short_balance: '融券余额', short_volume: '融券卖出',
  total_balance: '两融余额', balance_ratio: '两融占比', report_date: '报告期',
  notice_date: '公告日', forecast_type: '预告类型', forecast_content: '预告内容',
  profit_low: '净利下限', profit_high: '净利上限', increase_low: '增幅下限',
  increase_high: '增幅上限', change_reason: '变动原因', is_latest: '最新',
  apply_code: '申购代码', apply_date: '申购日', listing_date: '上市日', ballot_date: '中签日',
  pay_date: '缴款日', issue_price: '发行价', apply_upper: '申购上限', industry: '行业',
  issue_pe: '发行市盈率', ballot_rate: '中签率', sector_code: '板块代码',
  sector_name: '板块名称', sector_type: '板块类型', weight: '权重',
  sentiment_index: '情绪指数', up_limit: '涨停家数', down_limit: '跌停家数',
  breadth: '涨跌家数', forum_heat: '论坛热度', news_sentiment: '新闻情绪',
  high: '最高', low: '最低', open: '开盘', close: '收盘', volume: '成交量',
  amplitude: '振幅', fq_type: '复权类型',
}
const SUMMARY_MAP = {
  total: '总数', in_cnt: '流入数', out_cnt: '流出数', main_sum: '主力净流入合计',
  super_sum: '超大单合计', big_sum: '大单合计', org_avg: '机构参与度均值',
  turnover_avg: '换手率均值', fin_balance_sum: '融资余额合计', fin_buy_sum: '融资买入合计',
  fin_net_sum: '融资净买合计', short_balance_sum: '融券余额合计',
  total_balance_sum: '两融余额合计', net_in_cnt: '净买入家数',
}
function header(k) {
  return HEADER_MAP[k] || k
}
function summaryLabel(k) {
  return SUMMARY_MAP[k] || k
}

// ── 动态数据表的列语义分组：百分比列 / 带符号金额列 / 普通数值列 ──
const PCT_KEYS = new Set([
  'pct_chg', 'turnover_ratio', 'turnover', 'main_ratio', 'amplitude',
  'increase_low', 'increase_high', 'ballot_rate', 'balance_ratio',
  'org_participate', 'weight',
])
const SIGNED_KEYS = new Set([
  'net_amount', 'main_net', 'super_net', 'big_net', 'mid_net', 'small_net', 'fin_net',
])
const NUM_KEYS = new Set([
  'buy_amount', 'sell_amount', 'deal_amount', 'accum_amount', 'amount',
  'free_mv', 'circ_mv', 'total_mv', 'limit_amount', 'close_price', 'price',
  'issue_price', 'high', 'low', 'open', 'close', 'fin_balance', 'fin_buy',
  'short_balance', 'total_balance', 'profit_low', 'profit_high', 'volume',
])

function fmtThousand(v) {
  return Number(v).toLocaleString('zh-CN', { maximumFractionDigits: 2 })
}

function fmt(k, v) {
  if (typeof v !== 'number') return v
  if (PCT_KEYS.has(k)) return `${v > 0 ? '+' : ''}${v.toFixed(2)}%`
  if (SIGNED_KEYS.has(k) || NUM_KEYS.has(k)) return fmtThousand(v)
  if (k === 'pct_chg') return v.toFixed(2)
  return v
}

// 单元格样式：数值右对齐 + 涨跌着色（红涨绿跌，仅用于带涨跌语义的列）
function cellClass(k, v) {
  const cls = []
  if (PCT_KEYS.has(k) || SIGNED_KEYS.has(k) || NUM_KEYS.has(k) || typeof v === 'number') cls.push('is-numeric', 'ff-num')
  if (typeof v === 'number' && (PCT_KEYS.has(k) || SIGNED_KEYS.has(k))) {
    if (v > 0) cls.push('ff-t-up')
    else if (v < 0) cls.push('ff-t-down')
  }
  return cls
}

// 摘要卡数值加千分位
function fmtSummary(k, v) {
  if (typeof v === 'number') return fmtThousand(v)
  return v
}

// ── 动态表客户端排序：点表头切换 降序 → 升序 → 取消 ──
const sortKey = ref('')
const sortDir = ref(-1)
function toggleSort(k) {
  if (sortKey.value === k) {
    if (sortDir.value === -1) sortDir.value = 1
    else {
      sortKey.value = ''
      sortDir.value = -1
    }
  } else {
    sortKey.value = k
    sortDir.value = -1
  }
}
const sortedRows = computed(() => {
  if (!sortKey.value) return rows.value
  const k = sortKey.value
  const dir = sortDir.value
  return [...rows.value].sort((a, b) => {
    const av = a[k]
    const bv = b[k]
    const aNum = av != null && av !== '' ? Number(av) : NaN
    const bNum = bv != null && bv !== '' ? Number(bv) : NaN
    let cmp
    if (!Number.isNaN(aNum) && !Number.isNaN(bNum)) cmp = aNum - bNum
    else cmp = String(av ?? '').localeCompare(String(bv ?? ''), 'zh-CN')
    return cmp * dir
  })
})

// ── 个股行下钻：带 6 位代码的行可点击，跳 easy-tdx 查看该标的 ──
const STOCK_CODE_RE = /^\d{6}/
function rowStock(row) {
  const raw = row?.code
  if (typeof raw !== 'string' && typeof raw !== 'number') return null
  const s = String(raw).trim()
  const m = s.match(STOCK_CODE_RE)
  if (!m) return null
  const code = m[0]
  const market = code.startsWith('6')
    ? 'SH'
    : code.startsWith('4') || code.startsWith('8')
      ? 'BJ'
      : 'SZ'
  return { code, name: row.name || code, market }
}
function rowClickable(row) {
  return !!rowStock(row)
}
function openRowInEasytdx(row) {
  const s = rowStock(row)
  if (!s) return
  // 与智能选股「看行情」相同的交接机制：easy-tdx 挂载时消费 pendingStock
  try {
    localStorage.setItem('finfeed.easytdx.pendingStock', JSON.stringify(s))
  } catch { /* 存储不可用时仍跳转，模块内可手动搜索 */ }
  router.push('/easytdx')
}

const sentimentKeys = computed(() =>
  active.value === 'sentiment' && data.value
    ? Object.keys(data.value).filter((k) => k !== 'created_at')
    : [],
)

const actions = [
  { key: 'snapshot', label: '采集行情快照', icon: 'download',
    help: '全市场快照+宽度、龙虎榜、两融/预告/IPO' },
  { key: 'bars', label: '采集K线', icon: 'bar-chart',
    help: '逐只拉取在市 A 股日线（受 push2his 限流保护）' },
  { key: 'universe', label: '初始化股票池', icon: 'database',
    help: 'A 股名录、在市标记、概念/行业板块' },
  { key: 'calibrate', label: '校准情绪模型', icon: 'activity',
    help: 'T+1 收益回测校准各情感标签/来源' },
]
// 当前正在跑后台任务的 action key；用于按钮 loading 态
const runningAction = ref('')
// 各 action 的最新进度快照：{ key: { stage_index, stage_total, stage_name, done, total, pct } }
const actionProgress = ref({})
// 终态/失败结果：{ key: { status, message, result, started } } 一次性展示
const actionResults = ref({})
let pollTimer = null
// 轮询健壮性：连续失败/任务失联计数 + 启动时间（用于超时释放，防止按钮永久锁死）
let pollMissCount = 0
let pollStartedAt = 0
const POLL_MAX_MS = 60 * 60 * 1000

async function loadDates() {
  try {
    const r = await api.market('dates')
    if (r.success && r.data.default_date) latestDate.value = r.data.default_date
  } catch (e) {}
}

const latestDate = ref('')

async function loadAutoStatus() {
  try {
    const r = await api.market('autostatus')
    if (r && r.success) {
      autoLast.value = r.data.last_run || {}
      autoNext.value = r.data.next_run || {}
    }
  } catch (e) {
    /* 自动采集状态不可用时静默降级 */
  }
}

async function load() {
  loading.value = true
  err.value = ''
  sortKey.value = '' // 换数据源后排序状态失效
  rows.value = []
  summary.value = null
  data.value = null
  try {
    let params = { date: date.value || undefined }
    if (active.value === 'search') params = { kw: kw.value || undefined }
    if (active.value === 'sectors') params = { stype: 'concept' }
    if (active.value === 'forecast') params = {}
    const r = await api.market(active.value, params)
    const d = r.data || r
    data.value = d
    if (active.value === 'moneyflow') {
      summary.value = d.summary
      rows.value = [...(d.inflow || []), ...(d.outflow || [])]
    } else if (active.value === 'margin') {
      summary.value = d.summary
      rows.value = [...(d.top || []), ...(d.bottom || [])]
    } else if (Array.isArray(d)) {
      rows.value = d
    } else if (Array.isArray(d.rows)) {
      rows.value = d.rows
    } else if (Array.isArray(d.list)) {
      rows.value = d.list
    } else {
      rows.value = []
    }
  } catch (e) {
    err.value = e.message || String(e)
  } finally {
    loading.value = false
    lastUpdated.value = fmtClock()
  }
}

function runAction(a) {
  // 触发新一轮：清掉上一轮结果并立即进入 loading 态，按钮即时反馈
  runningAction.value = a.key
  pollMissCount = 0
  pollStartedAt = Date.now()
  actionResults.value = { ...actionResults.value, [a.key]: null }
  actionProgress.value = {
    ...actionProgress.value,
    [a.key]: { stage_index: 0, stage_total: 0, stage_name: '已启动…', done: null, total: null, pct: 0 },
  }
  api
    .marketAction({ action: a.key, date: date.value || undefined })
    .then(() => {
      // 立即返回不代表任务成功——状态以轮询为准
      startPolling()
    })
    .catch((e) => {
      runningAction.value = ''
      actionResults.value = {
        ...actionResults.value,
        [a.key]: { status: 'error', message: '请求失败：' + (e.message || e) },
      }
    })
}

function startPolling() {
  if (pollTimer) return
  pollTimer = setInterval(pollActions, 1000)
  // 立即拉一次，避免 1 秒空窗
  pollActions()
}

function stopPolling() {
  if (pollTimer) {
    clearInterval(pollTimer)
    pollTimer = null
  }
}

// 释放 runningAction 并写入一条结果，避免按钮永久锁死
function releaseRunning(status, message) {
  const key = runningAction.value
  if (!key) return
  runningAction.value = ''
  actionResults.value = {
    ...actionResults.value,
    [key]: { status, message },
  }
  stopPolling()
}

async function pollActions() {
  if (!runningAction.value) return
  // 硬超时：异常情况下保证 UI 最终可恢复（任务本身可能仍在后台跑）
  if (pollStartedAt && Date.now() - pollStartedAt > POLL_MAX_MS) {
    releaseRunning('error', '状态轮询超时（任务可能仍在后台运行），请稍后刷新数据确认结果')
    return
  }
  try {
    const r = await api.marketAction({ action: 'status' })
    if (!r || !r.success) {
      pollMissCount += 1
      if (pollMissCount >= 10) releaseRunning('error', '任务状态查询连续失败，已解除锁定，请重新执行')
      return
    }
    const tasks = r.data || {}
    const key = runningAction.value
    const t = tasks[key]
    if (!t) {
      // 任务 key 消失通常是后端重启导致；连续 5 次缺失判定任务失联
      pollMissCount += 1
      if (pollMissCount >= 5) releaseRunning('error', '任务状态失联（服务可能已重启），请重新执行')
      return
    }
    pollMissCount = 0
    actionProgress.value = { ...actionProgress.value, [key]: t.progress }
    if (t.status === 'running') return
    // 终态：done / error
    runningAction.value = ''
    actionResults.value = {
      ...actionResults.value,
      [key]: {
        status: t.status, message: t.message, result: t.result, started: t.started,
      },
    }
    stopPolling()
  } catch (e) {
    // 单次拉取失败不打断轮询；连续失败达到阈值后释放 UI
    pollMissCount += 1
    if (pollMissCount >= 10) releaseRunning('error', '任务状态查询连续失败，已解除锁定，请重新执行')
  }
}

// 进度条辅助渲染
function progressOf(key) {
  return actionProgress.value[key] || { stage_index: 0, stage_total: 0, stage_name: '', done: null, total: null, pct: 0 }
}

function resultOf(key) {
  return actionResults.value[key]
}

function progressText(key) {
  const p = progressOf(key)
  if (!p.stage_name) return ''
  if (p.done != null && p.total) return `${p.stage_name}  ${p.done}/${p.total}`
  return p.stage_name
}

// 当前正在运行 action 的中文标签（用于进度条上方）
const activeActionLabel = computed(() => {
  if (!runningAction.value) return ''
  return actions.find((a) => a.key === runningAction.value)?.label || runningAction.value
})

// 历史结果列表：按 action 顺序稳定展示，跳过仍处 running 的项
const completedList = computed(() => {
  return actions
    .map((a) => {
      const r = actionResults.value[a.key]
      if (!r) return null
      return { key: a.key, label: a.label, ...r }
    })
    .filter(Boolean)
})

watch(active, load)
watch(date, load)

onMounted(async () => {
  await loadDates()
  await loadAutoStatus()
  statusTimer = setInterval(loadAutoStatus, 30000)
  await load()
  startAutoRefresh()
  document.addEventListener('visibilitychange', onVisibilityChange)
})

onBeforeUnmount(() => {
  stopPolling()
  stopAutoRefresh()
  document.removeEventListener('visibilitychange', onVisibilityChange)
  if (statusTimer) {
    clearInterval(statusTimer)
    statusTimer = null
  }
})
</script>

<template>
  <div class="ff-page ff-market-view">
    <!-- 页面标题按产品要求移除，h1 保留 sr-only 保文档语义 -->
    <h1 class="ff-sr-only">全景行情</h1>

    <AppCard class="ff-market-view__toolbar ff-glass">
      <div class="ff-market-view__row">
        <AppDatePicker v-model="date" class="ff-market-view__field" label="交易日" @change="markTouched" />
        <AppInput
          v-if="active === 'search'"
          v-model="kw"
          class="ff-market-view__field"
          label="股票代码 / 名称"
          prefix-icon="search"
          @enter="load"
        />
        <!-- 30 秒后台自动刷新：无任何按钮/下拉/开关，仅保留最后更新时间作数据新鲜度提示 -->
        <span v-if="lastUpdated" class="ff-market-view__autorefresh-time">更新于 {{ lastUpdated }}</span>
      </div>
      <div class="ff-market-view__row ff-market-view__row--actions">
        <AppButton
          v-for="a in actions"
          :key="a.key"
          variant="tonal"
          size="sm"
          :icon="a.icon"
          :title="a.help"
          :loading="runningAction === a.key"
          :disabled="!!runningAction && runningAction !== a.key"
          @click="runAction(a)"
        >
          {{ a.label }}
        </AppButton>
      </div>

      <!-- 后台自动采集状态（默认常开、不可关闭；仅展示下次/上次执行时间 + 跳到最新数据日期） -->
      <div class="ff-market-view__autocollect">
        <AppIcon name="clock" size="xs" />
        <span class="ff-market-view__autocollect-next">
          下次快照 ~{{ autoNext.snapshot || '—' }}
        </span>
        <span v-if="autoLast.snapshot" class="ff-market-view__autocollect-last">
          · 上次快照 {{ autoLast.snapshot.message }}
        </span>
        <span v-if="autoLast.universe" class="ff-market-view__autocollect-last">
          · 股票池 {{ autoLast.universe.message }}
        </span>
        <button
          v-if="latestDate"
          type="button"
          class="ff-market-view__latest"
          :disabled="date === latestDate"
          :title="date === latestDate ? '已是最新数据日期' : `跳到最新数据日期 ${latestDate}`"
          @click="date = latestDate; markTouched()"
        >
          <AppIcon name="history" size="xs" /> 最新数据 {{ latestDate }}
        </button>
      </div>
      <!-- 进度区：单一运行中进度条 + 紧凑历史结果列表
           - 进行中：只渲染当前那一条，避免四进度条无意义占位
           - 动画只在按钮内（AppButton loading），进度条不再叠 spin 图标 -->
      <div class="ff-market-view__progress">
        <div v-if="runningAction" class="ff-market-view__progress-current">
          <div class="ff-market-view__progress-current-meta">
            <span class="ff-market-view__progress-current-name">{{ activeActionLabel }}</span>
            <span class="ff-market-view__progress-current-stage">
              {{ progressText(runningAction) || '已启动…' }}
            </span>
            <span class="ff-market-view__progress-current-pct">
              {{ progressOf(runningAction).pct || 0 }}%
            </span>
          </div>
          <div
            class="ff-progress ff-progress--lg"
            role="progressbar"
            :aria-valuenow="progressOf(runningAction).pct || 0"
            :aria-valuemin="0"
            :aria-valuemax="100"
          >
            <div
              class="ff-progress__bar"
              :style="{ width: (progressOf(runningAction).pct || 0) + '%' }"
            />
          </div>
        </div>

        <ul v-if="completedList.length" class="ff-market-view__history">
          <li
            v-for="r in completedList"
            :key="r.key"
            class="ff-market-view__history-item"
            :class="{
              'ff-market-view__history-item--done': r.status === 'done',
              'ff-market-view__history-item--error': r.status === 'error',
            }"
          >
            <AppIcon
              :name="r.status === 'done' ? 'check-circle' : 'alert-circle'"
              size="xs"
            />
            <span class="ff-market-view__history-name">{{ r.label }}</span>
            <span class="ff-market-view__history-time">{{ r.started }}</span>
            <span class="ff-market-view__history-msg">{{ r.message }}</span>
          </li>
        </ul>
      </div>
    </AppCard>

      <AppCard class="ff-market-view__panel" :no-padding="true">
        <div class="ff-market-view__nav">
          <AppTabs v-model="active" type="line" :items="tabs" class="ff-market-view__tabs" />
        </div>

        <template>
          <div v-if="summary" class="ff-market-view__summary">
          <div v-for="(v, k) in summary" :key="k" class="ff-kv">
            <span class="ff-kv__key">{{ summaryLabel(k) }}</span>
            <span class="ff-kv__value ff-num">{{ fmtSummary(k, v) }}</span>
          </div>
        </div>

        <AppSkeleton v-if="loading" variant="text" :lines="8" />
        <div v-else-if="err" class="ff-alert ff-alert--danger">
          <AppIcon name="alert-circle" size="md" /> {{ err }}
          <AppButton variant="ghost" size="sm" icon="refresh" class="ff-market-view__retry" @click="load">重试</AppButton>
        </div>

        <!-- 总览 -->
        <div v-else-if="active === 'overview' && data" class="ff-market-view__ov">
        <section class="ff-market-view__section">
          <h3 class="ff-h3">数据表</h3>
          <table class="ff-table">
            <thead>
              <tr>
                <th class="ff-table__header">表名</th>
                <th class="ff-table__header">标签</th>
                <th class="ff-table__header ff-table__header--right">记录数</th>
                <th class="ff-table__header">最新日期</th>
                <th class="ff-table__header ff-table__header--right">标的数量</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="t in data.tables" :key="t.table" class="ff-table__row">
                <td class="ff-table__cell">{{ t.table }}</td>
                <td class="ff-table__cell">{{ t.label }}</td>
                <td class="ff-table__cell ff-table__cell--right ff-num">{{ t.rows }}</td>
                <td class="ff-table__cell ff-num">{{ t.latest || '—' }}</td>
                <td class="ff-table__cell ff-table__cell--right ff-num">{{ t.subjects }}</td>
              </tr>
            </tbody>
          </table>
        </section>
        <section class="ff-market-view__section">
          <h3 class="ff-h3">板块数量</h3>
          <table class="ff-table">
            <thead>
              <tr>
                <th class="ff-table__header">板块</th>
                <th class="ff-table__header ff-table__header--right">总数</th>
                <th class="ff-table__header ff-table__header--right">活跃</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="b in data.boards" :key="b.board" class="ff-table__row">
                <td class="ff-table__cell">{{ b.board }}</td>
                <td class="ff-table__cell ff-table__cell--right ff-num">{{ b.n }}</td>
                <td class="ff-table__cell ff-table__cell--right ff-num">{{ b.active }}</td>
              </tr>
            </tbody>
          </table>
        </section>
        <!-- 系统健康度属于 SRE 监控指标，不再暴露在行情产品页 (2026-08-10) -->
      </div>

      <!-- 市场情绪 -->
      <div v-else-if="active === 'sentiment' && sentimentKeys.length" class="ff-market-view__sentcards">
        <AppCard v-for="k in sentimentKeys" :key="k" flat class="ff-market-view__sentcard">
          <div class="ff-metric">
            <span class="ff-metric__label">{{ header(k) }}</span>
            <span class="ff-metric__value" :class="k === 'down_limit' && 'ff-t-down'">{{ fmt(k, data[k]) }}</span>
          </div>
        </AppCard>
      </div>

      <table v-else-if="rows.length" class="ff-table ff-table--sticky ff-table--zebra">
        <thead>
          <tr>
            <th
              v-for="(v, k) in rows[0]"
              :key="k"
              class="ff-table__header"
              :class="[cellClass(k, v).includes('is-numeric') && 'is-numeric', 'is-sortable']"
              @click="toggleSort(k)"
            >
              {{ header(k) }}
              <AppIcon v-if="sortKey === k" :name="sortDir === 1 ? 'chevron-up' : 'chevron-down'" size="xs" />
            </th>
          </tr>
        </thead>
        <tbody>
          <tr
            v-for="(r, i) in sortedRows"
            :key="i"
            class="ff-table__row"
            :class="{ 'is-clickable': rowClickable(r) }"
            :title="rowClickable(r) ? '点击在 easy-tdx 中查看该标的' : undefined"
            @click="rowClickable(r) && openRowInEasytdx(r)"
          >
            <td v-for="(v, k) in r" :key="k" class="ff-table__cell" :class="cellClass(k, v)">{{ fmt(k, v) }}</td>
          </tr>
        </tbody>
      </table>
        <EmptyState v-else text="暂无数据（可能需要先采集行情）" icon="bar-chart" />
        </template>
    </AppCard>
  </div>
</template>

<style scoped>
.ff-market-view {
  width: 100%;
  max-width: var(--ff-container-max);
  margin: 0 auto;
  display: flex;
  flex-direction: column;
  gap: var(--ff-space-3);
  min-height: 100%;
}

.ff-market-view__toolbar {
  /* .ff-glass 的 backdrop-filter 会创建独立 stacking context，
     否则 .ff-datepicker 的 z-index 仅作用于该 context 内，被同级 AppTabs
     按 DOM 顺序覆盖（总览/市场情绪/... 横穿日历浮层）。
     在 root context 中显式抬高 z-index，让整张工具栏卡片盖住 tabs。 */
  position: relative;
  z-index: var(--ff-z-raised);
}

.ff-market-view__retry {
  margin-left: auto;
  flex-shrink: 0;
}

/* 可下钻行：鼠标手型 + 代码列主色提示 */
.ff-table__row.is-clickable {
  cursor: pointer;
}
.ff-table__row.is-clickable .ff-table__cell:first-child {
  color: var(--ff-text-brand);
}

.ff-market-view__row {
  display: flex;
  align-items: flex-end;
  gap: var(--ff-space-3);
  flex-wrap: wrap;
}

.ff-market-view__row--actions {
  padding-top: var(--ff-space-3);
  border-top: 1px solid var(--ff-border);
}

.ff-market-view__autorefresh-time {
  margin-left: auto;
  font-size: var(--ff-fs-caption);
  font-family: var(--ff-font-mono);
  color: var(--ff-text-tertiary);
  white-space: nowrap;
}

/* ---------------- 后台自动采集状态行（默认常开、不可关闭，仅做信息展示） ---------------- */
.ff-market-view__autocollect {
  margin-top: var(--ff-space-1-5);
  padding-top: var(--ff-space-1-5);
  border-top: 1px dashed var(--ff-border-subtle);
  display: flex;
  align-items: center;
  gap: var(--ff-space-2);
  flex-wrap: wrap;
  font-size: var(--ff-fs-caption);
  color: var(--ff-text-tertiary);
}
.ff-market-view__autocollect-next {
  color: var(--ff-text-secondary);
  font-variant-numeric: tabular-nums;
}
.ff-market-view__autocollect-last {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.ff-market-view__latest {
  margin-left: auto;
  display: inline-flex;
  align-items: center;
  gap: 4px;
  height: 28px;
  padding: 0 var(--ff-space-2-5);
  border: 1px solid var(--ff-border);
  border-radius: var(--ff-radius-pill);
  background: var(--ff-bg-surface);
  color: var(--ff-text-secondary);
  font-size: var(--ff-fs-caption);
  font-weight: 500;
  cursor: pointer;
  transition:
    background-color var(--ff-dur-fast) var(--ff-ease-standard),
    border-color var(--ff-dur-fast) var(--ff-ease-standard),
    color var(--ff-dur-fast) var(--ff-ease-standard);
}
.ff-market-view__latest:hover:not(:disabled) {
  background: var(--ff-bg-hover);
  border-color: var(--ff-border-strong);
  color: var(--ff-text-primary);
}
.ff-market-view__latest:disabled {
  opacity: 0.5;
  cursor: default;
}

.ff-market-view__field {
  width: 200px;
}

/* ---------------- 进度区（单条当前进度 + 紧凑历史） ---------------- */
.ff-market-view__progress {
  margin-top: var(--ff-space-2);
  padding-top: var(--ff-space-2);
  border-top: 1px dashed var(--ff-border-subtle);
  display: flex;
  flex-direction: column;
  gap: var(--ff-space-2);
}
.ff-market-view__progress-current {
  display: flex;
  flex-direction: column;
  gap: var(--ff-space-2);
}
.ff-market-view__progress-current-meta {
  display: flex;
  align-items: center;
  gap: var(--ff-space-3);
  font-size: var(--ff-fs-sm);
}
.ff-market-view__progress-current-name {
  color: var(--ff-brand-text);
  font-weight: var(--ff-fw-medium);
}
.ff-market-view__progress-current-stage {
  flex: 1;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  color: var(--ff-text-secondary);
}
.ff-market-view__progress-current-pct {
  font-variant-numeric: tabular-nums;
  font-weight: var(--ff-fw-medium);
  color: var(--ff-brand-text);
  min-width: 48px;
  text-align: right;
}
/* 大进度条：比通用 ff-progress(6px) 更高，更显眼 */
.ff-progress--lg {
  height: 8px;
}
/* ---------- 历史结果 ---------- */
.ff-market-view__history {
  list-style: none;
  margin: 0;
  padding: 0;
  display: flex;
  flex-direction: column;
  gap: 2px;
}
.ff-market-view__history-item {
  display: flex;
  align-items: center;
  gap: var(--ff-space-2);
  padding: 4px 0;
  font-size: var(--ff-fs-sm);
  color: var(--ff-text-secondary);
}
.ff-market-view__history-item--done {
  color: var(--ff-text-primary);
}
.ff-market-view__history-item--error {
  color: var(--ff-text-primary);
}
.ff-market-view__history-name {
  font-weight: var(--ff-fw-medium);
}
.ff-market-view__history-time {
  color: var(--ff-text-tertiary);
  font-size: var(--ff-fs-xs);
  font-variant-numeric: tabular-nums;
}
.ff-market-view__history-msg {
  flex: 1;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  color: var(--ff-text-tertiary);
}

.ff-market-view__panel :deep(.ff-card__body) {
  padding: 0;
}

.ff-market-view__nav {
  padding: 0 var(--ff-space-3);
  border-bottom: 1px solid var(--ff-border-subtle);
}

.ff-market-view__tabs {
  margin-bottom: 0;
}

.ff-market-view__tabs :deep(.ff-tabs__tab) {
  height: 48px;
  padding: 0 var(--ff-space-4);
  font-size: var(--ff-fs-body);
  font-weight: var(--ff-fw-medium);
  color: var(--ff-text-secondary);
  letter-spacing: 0.01em;
}

.ff-market-view__tabs :deep(.ff-tabs__tab:hover) {
  color: var(--ff-text-primary);
  background: var(--ff-bg-hover);
}

.ff-market-view__tabs :deep(.ff-tabs__tab--active) {
  color: var(--ff-brand-text);
  font-weight: var(--ff-fw-semibold);
}

.ff-market-view__tabs :deep(.ff-tabs__tab--active::after) {
  height: 3px;
  border-radius: var(--ff-radius-sm);
}

.ff-market-view__panel {
  overflow-x: auto;
  flex: 1 1 auto;
  display: flex;
  flex-direction: column;
  min-height: 0;
}

.ff-market-view__panel > :deep(.ff-card__body) {
  flex: 1 1 auto;
  display: flex;
  flex-direction: column;
  min-height: 0;
}

.ff-market-view__panel :deep(.ff-empty-state) {
  padding: var(--ff-space-8) 0;
}

.ff-market-view__summary {
  display: flex;
  flex-wrap: wrap;
  gap: var(--ff-space-4);
  padding: var(--ff-space-4) var(--ff-space-5);
  border-bottom: 1px solid var(--ff-border);
}

.ff-market-view__section {
  padding: var(--ff-space-4) var(--ff-space-5);
  border-bottom: 1px solid var(--ff-border);
}

.ff-market-view__section:last-child {
  border-bottom: none;
}

.ff-market-view__section h3 {
  display: inline-flex;
  align-items: center;
  gap: var(--ff-space-2);
  margin-bottom: var(--ff-space-3);
}

.ff-market-view__ov {
  display: flex;
  flex-direction: column;
}

.ff-market-view__sentcards {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(150px, 1fr));
  gap: var(--ff-space-3);
  padding: var(--ff-space-4);
}

.ff-market-view__sentcard {
  text-align: center;
}

/* ── 移动端适配（D4 · 基础断点）── */
@media (max-width: 768px) {
  .ff-market-view__toolbar {
    padding: var(--ff-space-3);
  }
  .ff-market-view__field {
    flex: 1 1 100%;
  }
  .ff-market-view__tabs {
    overflow-x: auto;
    padding-bottom: 2px;
  }
}
</style>
