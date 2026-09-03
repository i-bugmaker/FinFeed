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
import AppBadge from '../ui/AppBadge.vue'
import AppIcon from '../ui/AppIcon.vue'
import AppSkeleton from '../ui/AppSkeleton.vue'
import AppDrawer from '../ui/AppDrawer.vue'
import AppSegmented from '../ui/AppSegmented.vue'

const route = useRoute()
const router = useRouter()

// tab 语义元数据：icon 用于视图头；desc 用于视图头副文案
const TAB_META = {
  overview: { icon: 'dashboard', desc: '事实层数据就绪度：各表记录数、最新日期与板块覆盖' },
  sentiment: { icon: 'activity', desc: '市场温度与情绪宽度（涨跌停家数、涨跌家数比）' },
  limitup: { icon: 'flame', desc: '涨停池（含连板数与封板质量）' },
  limitdown: { icon: 'x', desc: '跌停池' },
  limitbroken: { icon: 'eye', desc: '炸板（盘中曾涨停后开板）' },
  billboard: { icon: 'star', desc: '龙虎榜（席位净额、上榜原因）' },
  moneyflow: { icon: 'coins', desc: '主力/超大单/大单资金流排行' },
  margin: { icon: 'layers', desc: '融资融券余额与净买入排行' },
  sectors: { icon: 'columns', desc: '概念/行业板块热度聚合，点击板块查看成分股' },
  forecast: { icon: 'calendar', desc: '业绩预告（预增/预减分布与明细）' },
  ipo: { icon: 'sparkles', desc: '新股申购/上市日历' },
  search: { icon: 'search', desc: '按代码 / 名称 / 别名检索标的，回车查询' },
}

// 各 tab 的列语义优先级（动态表按此顺序排布；未列出的键按后端顺序追加尾部）
const TAB_COL_ORDER = {
  limitup: ['code', 'name', 'limit_streak', 'pct_chg', 'price', 'amount', 'turnover', 'total_mv', 'limit_amount', 'circ_mv', 'first_limit_time', 'last_limit_time', 'open_times', 'reason', 'trade_date'],
  limitdown: ['code', 'name', 'pct_chg', 'price', 'amount', 'turnover', 'limit_amount', 'total_mv', 'circ_mv', 'open_times', 'first_limit_time', 'last_limit_time', 'reason', 'trade_date'],
  limitbroken: ['code', 'name', 'limit_streak', 'pct_chg', 'price', 'open_times', 'amount', 'turnover', 'last_limit_time', 'limit_amount', 'total_mv', 'circ_mv', 'reason', 'trade_date'],
  billboard: ['code', 'name', 'pct_chg', 'net_amount', 'buy_amount', 'sell_amount', 'turnover_ratio', 'deal_amount', 'accum_amount', 'free_mv', 'reason', 'detail', 'close_price', 'trade_date'],
  moneyflow: ['code', 'name', 'close_price', 'pct_chg', 'main_net', 'main_ratio', 'super_net', 'big_net', 'mid_net', 'small_net', 'turnover', 'org_participate', 'source', 'trade_date'],
  margin: ['code', 'name', 'pct_chg', 'fin_net', 'fin_balance', 'fin_buy', 'total_balance', 'balance_ratio', 'short_balance', 'short_volume', 'market', 'trade_date'],
  sectors: ['sector_name', 'members', 'avg_pct', 'up_limit', 'up_cnt', 'down_cnt', 'main_net', 'top_pct', 'sector_type'],
  sectorstocks: ['code', 'name', 'pct_chg', 'close_price', 'main_net', 'turnover', 'org_participate'],
  forecast: ['code', 'name', 'forecast_type', 'increase_high', 'increase_low', 'profit_high', 'profit_low', 'notice_date', 'report_date', 'is_latest', 'forecast_content', 'change_reason'],
  ipo: ['apply_code', 'name', 'industry', 'issue_price', 'issue_pe', 'apply_upper', 'ballot_rate', 'apply_date', 'listing_date', 'ballot_date', 'pay_date', 'code', 'market'],
  search: ['code', 'name', 'board', 'sw_industry_l1', 'is_active'],
}

// 长文本列：单元格超宽截断（保留悬停 title 全量查看）
const CLIP_KEYS = new Set(['reason', 'detail', 'change_reason', 'forecast_content'])

// 展示顺序按业务语义分组排列：全景 → 情绪打板 → 资金筹码 → 板块 → 日历 → 检索
const tabs = [
  { value: 'overview', label: '总览' },
  { value: 'sentiment', label: '市场情绪' },
  { value: 'limitup', label: '涨停' },
  { value: 'limitdown', label: '跌停' },
  { value: 'limitbroken', label: '炸板' },
  { value: 'billboard', label: '龙虎榜' },
  { value: 'moneyflow', label: '资金流' },
  { value: 'margin', label: '两融' },
  { value: 'sectors', label: '板块' },
  { value: 'forecast', label: '业绩预告' },
  { value: 'ipo', label: '新股' },
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
// 板块视图：概念/行业切换 + 成分股下钻抽屉
const stype = ref('concept')
const sectorOpen = ref(false)
const sectorState = ref({ name: '', type: '', loading: false, rows: [], trade_date: '' })
// 业绩预告类型分布（统计条）
const forecastStats = ref([])
// 数据维护抽屉（采集动作/进度/历史收纳，默认收起）
const maintainOpen = ref(false)

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
  const qStype = route.query.stype
  if (typeof qStype === 'string' && ['concept', 'industry'].includes(qStype)) stype.value = qStype
}
watch([active, date, kw, stype], ([a, d, k, s]) => {
  const q = {}
  if (a && a !== 'overview') q.tab = a
  if (d && d !== todayStr()) q.date = d // 当日为默认态，不写 URL
  if (k) q.kw = k
  if (s && s !== 'concept') q.stype = s
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
  members: '成分数', avg_pct: '平均涨跌', up_cnt: '上涨', down_cnt: '下跌',
  top_pct: '领涨', board: '板块', sw_industry_l1: '申万行业', is_active: '状态',
}
function header(k) {
  return HEADER_MAP[k] || k
}

// ── 动态数据表的列语义分组：百分比列 / 带符号金额列 / 普通数值列 ──
const PCT_KEYS = new Set([
  'pct_chg', 'turnover_ratio', 'turnover', 'main_ratio', 'amplitude',
  'increase_low', 'increase_high', 'ballot_rate', 'balance_ratio',
  'org_participate', 'weight', 'avg_pct', 'top_pct',
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

// 单元格样式：数值右对齐 + 涨跌着色（红涨绿跌，仅用于带涨跌语义的列）+ 长文本截断
function cellClass(k, v, r) {
  const cls = []
  if (PCT_KEYS.has(k) || SIGNED_KEYS.has(k) || NUM_KEYS.has(k) || typeof v === 'number') cls.push('is-numeric', 'ff-num')
  if (typeof v === 'number' && (PCT_KEYS.has(k) || SIGNED_KEYS.has(k))) {
    if (v > 0) cls.push('ff-t-up')
    else if (v < 0) cls.push('ff-t-down')
  }
  if (CLIP_KEYS.has(k) && typeof v === 'string') cls.push('is-clip')
  return cls
}

// ── 视图头：当前 tab 标题/图标/徽标 ──
const activeLabel = computed(() => tabs.find((t) => t.value === active.value)?.label || active.value)
const activeMeta = computed(() => TAB_META[active.value] || { icon: 'dashboard', desc: '' })
const viewBadges = computed(() => {
  const b = []
  const n = rows.value.length
  if (n) {
    const isMf = active.value === 'moneyflow'
    const isMg = active.value === 'margin'
    const unit = isMf || isMg ? ' 只' : ' 条'
    b.push({ text: `${n}${unit}`, variant: 'muted' })
  }
  if (active.value === 'moneyflow' && summary.value) {
    const s = summary.value
    if (s.in_cnt != null) b.push({ text: `流入 ${s.in_cnt} / 流出 ${s.out_cnt ?? 0}`, variant: 'default' })
  } else if (active.value === 'margin' && summary.value) {
    const s = summary.value
    if (s.net_in_cnt != null) b.push({ text: `净买入 ${s.net_in_cnt} / ${s.total ?? 0} 只`, variant: 'default' })
  } else if (active.value === 'forecast') {
    const total = forecastStats.value.reduce((acc, x) => acc + (x.n || 0), 0)
    if (total) b.push({ text: `共 ${total} 份预告`, variant: 'default' })
  }
  const td = data.value && data.value.trade_date
  if (td && active.value !== 'overview') b.push({ text: `数据日 ${td}`, variant: 'default' })
  return b
})
// 空态文案：区分「未检索 / 无结果 / 未采集」
const emptyText = computed(() => {
  if (active.value === 'search') {
    return kw.value ? `未找到匹配「${kw.value}」的标的` : '输入股票代码 / 名称 / 别名，回车检索'
  }
  return '暂无数据（可能需要先采集行情）'
})

// 带符号金额：+12,345 / -1,234（用于摘要大字）
function signedNum(v) {
  if (typeof v !== 'number' || Number.isNaN(v)) return '—'
  return (v > 0 ? '+' : '') + fmtThousand(v)
}
function numClsOf(v) {
  if (typeof v !== 'number' || Number.isNaN(v)) return ''
  return v > 0 ? 'ff-t-up' : v < 0 ? 'ff-t-down' : ''
}

// ── 摘要可视条：资金流（主力合计大字 + 超大/大/中/小单双向结构条） ──
const FLOW_BUCKETS = [
  { key: 'super_net', label: '超大单' },
  { key: 'big_net', label: '大单' },
  { key: 'mid_net', label: '中单' },
  { key: 'small_net', label: '小单' },
]
const flowMetrics = computed(() => {
  const s = summary.value || {}
  const max = spanMax(...FLOW_BUCKETS.map((bk) => s[bk.key]))
  return { s, max }
})
// 两融（融资/融券余额同向占比条，全程共用 total_balance_sum 作分母）
const marginMetrics = computed(() => {
  const s = summary.value || {}
  const tb = s.total_balance_sum || 0
  const fin = s.fin_balance_sum || 0
  const short = s.short_balance_sum || 0
  return {
    s,
    tb,
    finPct: tb > 0 ? Math.min((fin / tb) * 100, 100) : 0,
    shortPct: tb > 0 ? Math.min((short / tb) * 100, 100) : 0,
    finShare: tb > 0 ? Math.round((fin / tb) * 100) : 0,
    shortShare: tb > 0 ? Math.round((short / tb) * 100) : 0,
  }
})
// 双向条：正负各从轨道中线向两侧延伸
function fillStyle(v, max) {
  const w = barWidth(v, max)
  return (v || 0) >= 0
    ? { left: '50%', width: `${w / 2}%` }
    : { right: '50%', width: `${w / 2}%` }
}
// 业绩预告类型着色（含「增/盈/亏」关键词语义映射）
function fcTypeVariant(t) {
  const s = String(t || '')
  if (/预增|略增|续盈|扭亏|减亏/.test(s)) return 'up'
  if (/预减|略减|首亏|续亏|增亏/.test(s)) return 'down'
  return 'muted'
}
// 涨停连板徽标
function streakMeta(v) {
  if (!v || v < 1) return null
  return v >= 2 ? { text: `${v} 连板`, variant: 'up' } : { text: '首板', variant: 'default' }
}
// 表格行 key：优先主键；列表存在重复标的（如龙虎榜一票多因）时退回索引防复用
function rowKeyOf(r, i) {
  const pk = r.code || r.sector_name || ''
  return pk ? `${pk}_${i}` : `r_${i}`
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

// 当前视图的列顺序：语义优先级键前置，未知键按后端原序补尾。
// 让「代码/名称/核心指标」始终靠前，长文本/流水字段自然靠后，不再受后端 SELECT 顺序支配。
const tableCols = computed(() => {
  const first = sortedRows.value[0]
  if (!first) return []
  const order = TAB_COL_ORDER[active.value] || TAB_COL_ORDER.sectorstocks
  const seen = new Set()
  const cols = []
  for (const k of order) {
    if (Object.prototype.hasOwnProperty.call(first, k) && !seen.has(k)) {
      seen.add(k)
      cols.push(k)
    }
  }
  for (const k of Object.keys(first)) {
    if (!seen.has(k)) {
      seen.add(k)
      cols.push(k)
    }
  }
  return cols
})

// 组件下钻目标与操作类型：sector 行（无 code）→ 板块成分抽屉
function rowAction(r) {
  if (rowStock(r)) return 'stock'
  if (active.value === 'sectors' && r.sector_name) return 'sector'
  return null
}
function rowClickable(r) {
  return !!rowAction(r)
}
function rowHint(r) {
  return rowAction(r) === 'sector' ? '查看板块成分股' : '点击在 easy-tdx 中查看该标的'
}
function onRowClick(r) {
  const act = rowAction(r)
  if (act === 'stock') openRowInEasytdx(r)
  else if (act === 'sector') openSector(r)
}

// 板块下钻：拉取该板块当日成分股表现（money_flow 聚合，走既有 sectorstocks 接口）
async function openSector(r) {
  const td = (data.value && data.value.trade_date) || date.value || todayStr()
  sectorState.value = {
    name: r.sector_name,
    type: r.sector_type || stype.value,
    loading: true,
    rows: [],
    err: '',
    trade_date: td,
  }
  sectorOpen.value = true
  try {
    const res = await api.market('sectorstocks', { sector: r.sector_name, date: td })
    const d = res.data || res
    sectorState.value.rows = Array.isArray(d) ? d : Array.isArray(d.rows) ? d.rows : []
  } catch (e) {
    sectorState.value.err = e.message || String(e)
  } finally {
    sectorState.value.loading = false
  }
}
// 关闭板块抽屉（供懒加载视图头在切走 sectors 时也可安全调用）
function closeSector() {
  sectorOpen.value = false
}

// summary 可视条辅助：把带符号数值归一化为 0..100 的双向比例
function barWidth(v, maxAbs) {
  if (!maxAbs) return 0
  return Math.min(Math.abs(v) / maxAbs, 1) * 100
}
function spanMax(...vals) {
  return Math.max(...vals.map((v) => Math.abs(v || 0)), 1e-9)
}

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
    if (active.value === 'sectors') params = { stype: stype.value }
    if (active.value === 'forecast') params = {}
    const r = await api.market(active.value, params)
    const d = r.data || r
    data.value = d
    forecastStats.value = []
    if (active.value === 'moneyflow') {
      summary.value = d.summary
      rows.value = [...(d.inflow || []), ...(d.outflow || [])]
    } else if (active.value === 'margin') {
      summary.value = d.summary
      rows.value = [...(d.top || []), ...(d.bottom || [])]
    } else if (active.value === 'forecast') {
      forecastStats.value = d.stats || []
      rows.value = Array.isArray(d.rows) ? d.rows : []
    } else if (active.value === 'sectors') {
      rows.value = Array.isArray(d.rows) ? d.rows : []
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
watch(stype, () => {
  if (active.value === 'sectors') load()
})
// 离开板块视图时收起成分抽屉，避免残留上个板块的展开态
watch(active, (v) => {
  if (v !== 'sectors') closeSector()
})

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

    <!-- ── 顶部工具行：交易日 / 检索输入（仅搜索视图）/ 数据新鲜度 · 维护入口 ──
         采集动作、自动调度状态、任务进度与历史收纳于右侧「数据维护」抽屉，
         主查看区不再被低频运维控件挤占。 -->
    <AppCard class="ff-market-view__toolbar ff-glass">
      <div class="ff-market-view__row">
        <AppDatePicker v-model="date" class="ff-market-view__field" label="交易日" @change="markTouched" />
        <template v-if="active === 'search'">
          <AppInput
            v-model="kw"
            class="ff-market-view__field ff-market-view__kw"
            label="股票代码 / 名称 / 别名"
            prefix-icon="search"
            placeholder="如 600519 / 贵州茅台"
            @keyup.enter="load"
          />
          <AppButton variant="tonal" size="sm" icon="search" :loading="loading" @click="load">查询</AppButton>
        </template>
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
        <span class="ff-market-view__spacer" />
        <span v-if="lastUpdated" class="ff-market-view__autorefresh-time">更新于 {{ lastUpdated }}</span>
        <AppButton
          variant="ghost"
          size="sm"
          :icon="runningAction ? 'activity' : 'settings'"
          :loading="!!runningAction"
          @click="maintainOpen = true"
        >数据维护</AppButton>
      </div>
    </AppCard>

    <!-- ── 主面板：分组导航 + 视图头 + 视图内容 ── -->
    <AppCard class="ff-market-view__panel" :no-padding="true">
      <div class="ff-market-view__nav">
        <AppTabs v-model="active" type="line" :items="tabs" class="ff-market-view__tabs" />
      </div>

      <!-- 视图头：当前视图 / 一句话说明 / 行数与数据日徽标（统一信息层级） -->
      <div class="ff-market-view__viewhead">
        <span class="ff-market-view__viewhead-ic"><AppIcon :name="activeMeta.icon" size="sm" /></span>
        <div class="ff-market-view__viewhead-meta">
          <div class="ff-market-view__viewhead-title">{{ activeLabel }}</div>
          <div class="ff-market-view__viewhead-desc">{{ activeMeta.desc }}</div>
        </div>
        <div class="ff-market-view__viewhead-badges">
          <AppBadge v-for="(bd, i) in viewBadges" :key="i" :variant="bd.variant">{{ bd.text }}</AppBadge>
        </div>
        <AppSegmented
          v-if="active === 'sectors'"
          v-model="stype"
          class="ff-market-view__stype"
          size="sm"
          :options="[
            { label: '概念板块', value: 'concept' },
            { label: '行业板块', value: 'industry' },
          ]"
        />
      </div>

      <AppSkeleton v-if="loading" variant="text" :lines="10" />
      <div v-else-if="err" class="ff-alert ff-alert--danger ff-market-view__err">
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
                <td class="ff-table__cell ff-num">{{ t.table }}</td>
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
        <AppCard
          v-for="k in sentimentKeys"
          :key="k"
          flat
          class="ff-market-view__sentcard"
          :class="{
            'ff-market-view__sentcard--key': k === 'sentiment_index',
            'is-up': k === 'up_limit' || k === 'breadth_up',
            'is-down': k === 'down_limit' || k === 'breadth_down',
          }"
        >
          <div class="ff-metric">
            <span class="ff-metric__label">{{ header(k) }}</span>
            <span
              class="ff-metric__value"
              :class="{ 'ff-t-up': k === 'up_limit', 'ff-t-down': k === 'down_limit' }"
            >{{ fmt(k, data[k]) }}</span>
          </div>
        </AppCard>
      </div>

      <!-- 其余数据视图：摘要可视区 + 通用语义表 -->
      <div v-else class="ff-market-view__data">
        <!-- 资金流摘要：主力合计大字 + 超大/大/中/小单双向结构条 -->
        <div v-if="active === 'moneyflow' && flowMetrics.s.total" class="ff-market-view__sum">
          <div class="ff-market-view__sum-main">
            <span class="ff-market-view__sum-label">全市场主力净流入</span>
            <span class="ff-market-view__sum-big ff-num" :class="numClsOf(flowMetrics.s.main_sum)">
              {{ signedNum(flowMetrics.s.main_sum) }}
            </span>
            <span class="ff-market-view__sum-sub">
              样本 {{ flowMetrics.s.total }} 只 · 流入 {{ flowMetrics.s.in_cnt }} / 流出 {{ flowMetrics.s.out_cnt }}
              <template v-if="flowMetrics.s.org_avg"> · 机构参与度均值 {{ fmt('org_participate', flowMetrics.s.org_avg) }}</template>
            </span>
          </div>
          <div class="ff-market-view__sum-track">
            <div v-for="bk in FLOW_BUCKETS" :key="bk.key" class="ff-market-view__sum-row">
              <span class="ff-market-view__sum-row-label">{{ bk.label }}</span>
              <div class="ff-market-view__sum-trackline">
                <div
                  class="ff-market-view__sum-fill"
                  :class="(flowMetrics.s[bk.key] || 0) >= 0 ? 'is-up' : 'is-down'"
                  :style="fillStyle(flowMetrics.s[bk.key], flowMetrics.max)"
                />
              </div>
              <span class="ff-market-view__sum-row-val ff-num" :class="numClsOf(flowMetrics.s[bk.key])">
                {{ signedNum(flowMetrics.s[bk.key]) }}
              </span>
            </div>
          </div>
        </div>

        <!-- 两融摘要：余额合计 + 融资/融券占比条 -->
        <div v-else-if="active === 'margin' && marginMetrics.tb" class="ff-market-view__sum">
          <div class="ff-market-view__sum-main">
            <span class="ff-market-view__sum-label">两融余额合计</span>
            <span class="ff-market-view__sum-big ff-num">{{ fmtSummary('total_balance_sum', marginMetrics.s.total_balance_sum) }}</span>
            <span class="ff-market-view__sum-sub">
              融资净买入
              <b class="ff-num" :class="numClsOf(marginMetrics.s.fin_net_sum)">{{ signedNum(marginMetrics.s.fin_net_sum) }}</b>
              · 标的 {{ marginMetrics.s.total }} 只 · 净买入家数 {{ marginMetrics.s.net_in_cnt }}
            </span>
          </div>
          <div class="ff-market-view__sum-track">
            <div class="ff-market-view__sum-trackline">
              <div class="ff-market-view__sum-fill is-fin" :style="{ width: marginMetrics.finPct + '%' }" />
              <div class="ff-market-view__sum-fill is-short" :style="{ width: marginMetrics.shortPct + '%' }" />
            </div>
            <div class="ff-market-view__sum-legend">
              <span><i class="ff-market-view__sum-lg is-fin" />融资余额 {{ marginMetrics.finShare }}%</span>
              <span><i class="ff-market-view__sum-lg is-short" />融券余额 {{ marginMetrics.shortShare }}%</span>
            </div>
          </div>
        </div>

        <!-- 业绩预告类型分布 -->
        <div v-else-if="active === 'forecast' && forecastStats.length" class="ff-market-view__sum ff-market-view__sum--flat">
          <div class="ff-market-view__sum-track ff-market-view__sum-track--stats">
            <AppBadge
              v-for="st in forecastStats"
              :key="st.forecast_type"
              :variant="fcTypeVariant(st.forecast_type)"
            >{{ st.forecast_type }} <b class="ff-num">{{ st.n }}</b></AppBadge>
          </div>
        </div>

        <!-- 通用语义表 -->
        <div v-if="tableCols.length" class="ff-market-view__table-scroll">
          <table class="ff-table ff-table--sticky ff-table--zebra">
            <thead>
              <tr>
                <th
                  v-for="k in tableCols"
                  :key="k"
                  class="ff-table__header"
                  :class="[cellClass(k, sortedRows[0][k], sortedRows[0]).includes('is-numeric') ? 'is-numeric' : '', 'is-sortable']"
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
                :key="rowKeyOf(r, i)"
                class="ff-table__row"
                :class="{ 'is-clickable': rowClickable(r) }"
                :title="rowClickable(r) ? rowHint(r) : undefined"
                @click="onRowClick(r)"
              >
                <td
                  v-for="k in tableCols"
                  :key="k"
                  class="ff-table__cell"
                  :class="cellClass(k, r[k], r)"
                  :title="CLIP_KEYS.has(k) && typeof r[k] === 'string' ? r[k] : undefined"
                >
                  <!-- 涨停/炸板连板徽标 -->
                  <AppBadge
                    v-if="(active === 'limitup' || active === 'limitbroken') && k === 'limit_streak' && streakMeta(r[k])"
                    :variant="streakMeta(r[k]).variant"
                  >{{ streakMeta(r[k]).text }}</AppBadge>
                  <!-- 业绩预告类型徽标 -->
                  <AppBadge v-else-if="active === 'forecast' && k === 'forecast_type'" :variant="fcTypeVariant(r[k])">
                    {{ r[k] }}
                  </AppBadge>
                  <!-- 板块名称（可下钻 → 主色 + 右箭头） -->
                  <span v-else-if="active === 'sectors' && k === 'sector_name'" class="ff-market-view__sector-name">
                    {{ r[k] }}<AppIcon name="chevron-right" size="xs" />
                  </span>
                  <!-- 搜索：在市/停用状态 -->
                  <AppBadge
                    v-else-if="active === 'search' && k === 'is_active' && (r[k] === 1 || r[k] === 0)"
                    :variant="r[k] === 1 ? 'success' : 'muted'"
                  >{{ r[k] === 1 ? '在市' : '停用' }}</AppBadge>
                  <template v-else>{{ fmt(k, r[k]) }}</template>
                </td>
              </tr>
            </tbody>
          </table>
        </div>
        <EmptyState
          v-else
          :text="emptyText"
          :icon="active === 'search' ? 'search' : 'bar-chart'"
        />
      </div>
    </AppCard>

    <!-- ── 数据维护抽屉：采集动作 / 自动调度状态 / 进度 / 历史 ── -->
    <AppDrawer v-model="maintainOpen" placement="right" size="md" title="数据维护">
      <div class="ff-market-view__maint">
        <p class="ff-market-view__maint-help">
          采集任务在后台执行，可随时关闭本面板；同一时间仅允许一个任务运行，其他按钮将禁用。
        </p>
        <div class="ff-market-view__maint-actions">
          <AppButton
            v-for="a in actions"
            :key="a.key"
            variant="tonal"
            :icon="a.icon"
            :title="a.help"
            :loading="runningAction === a.key"
            :disabled="!!runningAction && runningAction !== a.key"
            @click="runAction(a)"
          >
            {{ a.label }}
          </AppButton>
        </div>
        <div v-if="actions.length" class="ff-market-view__maint-helps">
          <p v-for="a in actions" :key="a.key" class="ff-market-view__maint-helps-item">
            <b>{{ a.label }}</b> · {{ a.help }}
          </p>
        </div>

        <div class="ff-market-view__autocollect">
          <AppIcon name="clock" size="xs" />
          <span class="ff-market-view__autocollect-next">下次快照 ~{{ autoNext.snapshot || '—' }}</span>
          <span v-if="autoLast.snapshot" class="ff-market-view__autocollect-last">· 上次快照 {{ autoLast.snapshot.message }}</span>
          <span v-if="autoLast.universe" class="ff-market-view__autocollect-last">· 股票池 {{ autoLast.universe.message }}</span>
        </div>

        <div class="ff-market-view__progress">
          <div v-if="runningAction" class="ff-market-view__progress-current">
            <div class="ff-market-view__progress-current-meta">
              <span class="ff-market-view__progress-current-name">{{ activeActionLabel }}</span>
              <span class="ff-market-view__progress-current-stage">{{ progressText(runningAction) || '已启动…' }}</span>
              <span class="ff-market-view__progress-current-pct">{{ progressOf(runningAction).pct || 0 }}%</span>
            </div>
            <div
              class="ff-progress ff-progress--lg"
              role="progressbar"
              :aria-valuenow="progressOf(runningAction).pct || 0"
              :aria-valuemin="0"
              :aria-valuemax="100"
            >
              <div class="ff-progress__bar" :style="{ width: (progressOf(runningAction).pct || 0) + '%' }" />
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
              <AppIcon :name="r.status === 'done' ? 'check-circle' : 'alert-circle'" size="xs" />
              <span class="ff-market-view__history-name">{{ r.label }}</span>
              <span class="ff-market-view__history-time">{{ r.started }}</span>
              <span class="ff-market-view__history-msg">{{ r.message }}</span>
            </li>
          </ul>
        </div>
      </div>
    </AppDrawer>

    <!-- ── 板块成分抽屉：板块下钻 ── -->
    <AppDrawer v-model="sectorOpen" placement="right" size="lg" :title="sectorState.name || '板块成分'">
      <div class="ff-market-view__sector">
        <div class="ff-market-view__sector-meta">
          <AppBadge variant="brand">{{ sectorState.type === 'industry' ? '行业' : '概念' }}</AppBadge>
          <span class="ff-market-view__sector-sub">数据日 {{ sectorState.trade_date || '—' }}</span>
          <span class="ff-market-view__sector-count ff-num" v-if="sectorState.rows.length">{{ sectorState.rows.length }} 只</span>
        </div>

        <AppSkeleton v-if="sectorState.loading" variant="text" :lines="8" />
        <div v-else-if="sectorState.err" class="ff-alert ff-alert--danger ff-market-view__err">
          <AppIcon name="alert-circle" size="md" /> {{ sectorState.err }}
        </div>
        <div v-else-if="sectorState.rows.length" class="ff-market-view__table-scroll">
          <table class="ff-table ff-table--sticky ff-table--zebra ff-table--compact">
            <thead>
              <tr>
                <th v-for="k in TAB_COL_ORDER.sectorstocks" :key="k" class="ff-table__header" :class="{ 'is-numeric': cellClass(k, sectorState.rows[0][k], sectorState.rows[0]).includes('is-numeric') }">
                  {{ header(k) }}
                </th>
              </tr>
            </thead>
            <tbody>
              <tr
                v-for="(r, i) in sectorState.rows"
                :key="rowKeyOf(r, i)"
                class="ff-table__row"
                :class="{ 'is-clickable': rowClickable(r) }"
                :title="rowClickable(r) ? rowHint(r) : undefined"
                @click="onRowClick(r)"
              >
                <td v-for="k in TAB_COL_ORDER.sectorstocks" :key="k" class="ff-table__cell" :class="cellClass(k, r[k], r)">
                  {{ fmt(k, r[k]) }}
                </td>
              </tr>
            </tbody>
          </table>
        </div>
        <EmptyState v-else text="该板块当日暂无成分股行情（可能缺资金流数据）" icon="inbox" />
      </div>
    </AppDrawer>
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

.ff-market-view__row {
  display: flex;
  align-items: flex-end;
  gap: var(--ff-space-3);
  flex-wrap: wrap;
}
.ff-market-view__spacer {
  flex: 1 1 auto;
}
.ff-market-view__autorefresh-time {
  font-size: var(--ff-fs-caption);
  font-family: var(--ff-font-mono);
  color: var(--ff-text-tertiary);
  white-space: nowrap;
}
.ff-market-view__latest {
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
.ff-market-view__kw {
  width: 240px;
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
.ff-market-view__sector-name {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  color: var(--ff-text-brand);
  font-weight: var(--ff-fw-medium);
}

/* ---------------- 面板与导航 ---------------- */
.ff-market-view__panel {
  overflow-x: hidden;
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
.ff-market-view__panel :deep(.ff-card__body) {
  padding: 0;
}
.ff-market-view__panel :deep(.ff-empty-state) {
  padding: var(--ff-space-10) 0;
}
.ff-market-view__nav {
  padding: 0 var(--ff-space-3);
  border-bottom: 1px solid var(--ff-border-subtle);
  flex-shrink: 0;
}
.ff-market-view__tabs {
  margin-bottom: 0;
}
.ff-market-view__tabs :deep(.ff-tabs__tab) {
  height: 48px;
  padding: 0 var(--ff-space-3);
  font-size: var(--ff-fs-body-sm);
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

/* ---------------- 视图头：统一的信息层级入口 ---------------- */
.ff-market-view__viewhead {
  display: flex;
  align-items: center;
  gap: var(--ff-space-3);
  padding: var(--ff-space-3) var(--ff-space-4);
  background: var(--ff-bg-subtle);
  border-bottom: 1px solid var(--ff-border-subtle);
  flex-shrink: 0;
  flex-wrap: wrap;
}
.ff-market-view__viewhead-ic {
  width: 28px;
  height: 28px;
  border-radius: var(--ff-radius-md);
  display: inline-flex;
  align-items: center;
  justify-content: center;
  background: var(--ff-brand-subtle);
  color: var(--ff-brand-text);
  flex-shrink: 0;
}
.ff-market-view__viewhead-meta {
  display: flex;
  flex-direction: column;
  min-width: 0;
}
.ff-market-view__viewhead-title {
  font-size: var(--ff-fs-body);
  font-weight: var(--ff-fw-semibold);
  color: var(--ff-text-primary);
  line-height: 1.3;
}
.ff-market-view__viewhead-desc {
  font-size: var(--ff-fs-caption);
  color: var(--ff-text-tertiary);
  line-height: 1.4;
}
.ff-market-view__viewhead-badges {
  display: inline-flex;
  align-items: center;
  gap: var(--ff-space-1-5);
  flex-wrap: wrap;
}
.ff-market-view__stype {
  margin-left: auto;
}

/* ---------------- 摘要可视区（资金流 / 两融 / 预告统计） ---------------- */
.ff-market-view__sum {
  padding: var(--ff-space-4) var(--ff-space-5);
  border-bottom: 1px solid var(--ff-border);
  display: flex;
  flex-direction: column;
  gap: var(--ff-space-3);
  flex-shrink: 0;
  background: var(--ff-bg-surface);
}
.ff-market-view__sum-main {
  display: flex;
  align-items: baseline;
  gap: var(--ff-space-3);
  flex-wrap: wrap;
}
.ff-market-view__sum-label {
  font-size: var(--ff-fs-caption);
  color: var(--ff-text-secondary);
  letter-spacing: var(--ff-ls-wide);
}
.ff-market-view__sum-big {
  font-size: 22px;
  font-weight: var(--ff-fw-bold);
  line-height: 1;
}
.ff-market-view__sum-sub {
  font-size: var(--ff-fs-caption);
  color: var(--ff-text-tertiary);
}
.ff-market-view__sum-row {
  display: grid;
  grid-template-columns: 56px 1fr 110px;
  align-items: center;
  gap: var(--ff-space-3);
  font-size: var(--ff-fs-caption);
}
.ff-market-view__sum-row-label {
  color: var(--ff-text-secondary);
}
.ff-market-view__sum-trackline {
  position: relative;
  height: 8px;
  background: var(--ff-bg-subtle);
  border-radius: var(--ff-radius-pill);
  overflow: hidden;
}
/* 资金流：双向条（自中线向两侧延伸，由 JS 注入 left/right/width） */
.ff-market-view__sum-fill {
  position: absolute;
  top: 0;
  bottom: 0;
  min-width: 2px;
}
.ff-market-view__sum-fill.is-up {
  background: var(--ff-up);
}
.ff-market-view__sum-fill.is-down {
  background: var(--ff-down);
}
/* 两融：融资/融券同向分段条（flex 布局静态条） */
.ff-market-view__sum-fill.is-fin {
  position: static;
  height: 100%;
  background: var(--ff-brand);
}
.ff-market-view__sum-fill.is-short {
  position: static;
  height: 100%;
  background: var(--ff-down);
}
.ff-market-view__sum-legend {
  display: flex;
  align-items: center;
  gap: var(--ff-space-4);
  font-size: var(--ff-fs-caption);
  color: var(--ff-text-secondary);
  margin-top: 4px;
}
.ff-market-view__sum-lg {
  display: inline-block;
  width: 8px;
  height: 8px;
  border-radius: 2px;
  margin-right: 6px;
  vertical-align: -1px;
}
.ff-market-view__sum-lg.is-fin {
  background: var(--ff-brand);
}
.ff-market-view__sum-lg.is-short {
  background: var(--ff-down);
}
.ff-market-view__sum--flat {
  flex-direction: row;
}
.ff-market-view__sum-track--stats {
  display: flex;
  flex-wrap: wrap;
  gap: var(--ff-space-2);
}
.ff-market-view__sum-track--stats :deep(.ff-badge) {
  gap: 4px;
  font-weight: var(--ff-fw-medium);
  height: 22px;
}

/* ---------------- 表格区 ---------------- */
.ff-market-view__table-scroll {
  overflow-x: auto;
  flex: 1 1 auto;
}
.ff-market-view__table-scroll :deep(.is-clip),
.ff-market-view__sector .is-clip {
  max-width: 320px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.ff-market-view__err {
  margin: var(--ff-space-4);
}

/* ---------------- 数据视图内容 ---------------- */
.ff-market-view__ov {
  display: flex;
  flex-direction: column;
  overflow-y: auto;
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

/* 市场情绪指标网格 */
.ff-market-view__sentcards {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(180px, 1fr));
  gap: var(--ff-space-3);
  padding: var(--ff-space-4);
  overflow-y: auto;
}
.ff-market-view__sentcard {
  text-align: center;
}
.ff-market-view__sentcard--key {
  border-color: var(--ff-border-brand);
  background: var(--ff-brand-subtle);
}
.ff-market-view__sentcard--key :deep(.ff-metric__value) {
  font-size: 28px;
}

/* ---------------- 数据维护抽屉 ---------------- */
.ff-market-view__maint {
  display: flex;
  flex-direction: column;
  gap: var(--ff-space-4);
}
.ff-market-view__maint-help {
  margin: 0;
  font-size: var(--ff-fs-caption);
  color: var(--ff-text-tertiary);
  line-height: 1.6;
}
.ff-market-view__maint-actions {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: var(--ff-space-2);
}
.ff-market-view__maint-actions :deep(.ff-btn) {
  width: 100%;
}
.ff-market-view__maint-helps {
  margin: 0;
}
.ff-market-view__maint-helps-item {
  margin: 2px 0;
  font-size: var(--ff-fs-caption);
  color: var(--ff-text-tertiary);
  line-height: 1.6;
}
.ff-market-view__maint-helps-item b {
  color: var(--ff-text-secondary);
  font-weight: var(--ff-fw-medium);
}

/* 自动采集状态行（收纳于抽屉） */
.ff-market-view__autocollect {
  padding-top: var(--ff-space-3);
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

/* 进度区（收纳于抽屉） */
.ff-market-view__progress {
  padding-top: var(--ff-space-3);
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
.ff-progress--lg {
  height: 8px;
}
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
  color: var(--ff-text-primary);
}
.ff-market-view__history-name {
  font-weight: var(--ff-fw-medium);
  white-space: nowrap;
}
.ff-market-view__history-time {
  color: var(--ff-text-tertiary);
  font-size: var(--ff-fs-xs);
  font-variant-numeric: tabular-nums;
  white-space: nowrap;
}
.ff-market-view__history-msg {
  flex: 1;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  color: var(--ff-text-tertiary);
}

/* ---------------- 板块成分抽屉 ---------------- */
.ff-market-view__sector {
  display: flex;
  flex-direction: column;
  gap: var(--ff-space-3);
  min-height: 100%;
}
.ff-market-view__sector-meta {
  display: flex;
  align-items: center;
  gap: var(--ff-space-2);
  font-size: var(--ff-fs-caption);
  color: var(--ff-text-secondary);
}
.ff-market-view__sector-count {
  margin-left: auto;
  color: var(--ff-brand-text);
  font-weight: var(--ff-fw-medium);
}

/* ── 移动端适配（D4 · 基础断点）── */
@media (max-width: 768px) {
  .ff-market-view__toolbar {
    padding: var(--ff-space-3);
  }
  .ff-market-view__field {
    flex: 1 1 100%;
  }
  .ff-market-view__kw {
    flex: 1 1 100%;
    width: auto;
  }
  .ff-market-view__tabs {
    overflow-x: auto;
    padding-bottom: 2px;
  }
  .ff-market-view__viewhead-desc {
    display: none;
  }
  .ff-market-view__sum-row {
    grid-template-columns: 48px 1fr 96px;
  }
}
</style>

