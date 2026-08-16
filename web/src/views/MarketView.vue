<script setup>
import { ref, onMounted, onBeforeUnmount, watch, computed } from 'vue'
import { api } from '../api/client'
import { useAutoToday, todayStr } from '../composables/useAutoToday'
import EmptyState from '../components/EmptyState.vue'
import AppCard from '../ui/AppCard.vue'
import AppButton from '../ui/AppButton.vue'
import AppInput from '../ui/AppInput.vue'
import AppDatePicker from '../ui/AppDatePicker.vue'
import AppTabs from '../ui/AppTabs.vue'
import AppSwitch from '../ui/AppSwitch.vue'
import AppIcon from '../ui/AppIcon.vue'
import AppSkeleton from '../ui/AppSkeleton.vue'
import ThsHotList from '../components/ThsHotList.vue'

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
  { value: 'hotrank', label: '热榜' },
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

// 后台自动采集调度状态
const autoEnabled = ref(false)
const autoLast = ref({})
const autoNext = ref({})
let statusTimer = null

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
function fmt(k, v) {
  if (k === 'pct_chg' && typeof v === 'number') return v.toFixed(2)
  return v
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
      autoEnabled.value = !!r.data.enabled
      autoLast.value = r.data.last_run || {}
      autoNext.value = r.data.next_run || {}
    }
  } catch (e) {
    /* 自动采集状态不可用时静默降级 */
  }
}

async function toggleAuto(v) {
  try {
    const r = await api.marketAction({ action: 'autocollect', enable: v ? 1 : 0 })
    if (r && r.success) {
      autoEnabled.value = !!r.data.enabled
      autoLast.value = r.data.last_run || {}
      autoNext.value = r.data.next_run || {}
    }
  } catch (e) {
    /* 失败时保持原状态 */
  }
}

async function load() {
  // 热榜由 ThsHotList 组件自行拉取，避免与通用行情快照流程冲突
  if (active.value === 'hotrank') return
  loading.value = true
  err.value = ''
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
  }
}

function runAction(a) {
  // 触发新一轮：清掉上一轮结果并立即进入 loading 态，按钮即时反馈
  runningAction.value = a.key
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

async function pollActions() {
  if (!runningAction.value) return
  try {
    const r = await api.marketAction({ action: 'status' })
    if (!r || !r.success) return
    const tasks = r.data || {}
    const key = runningAction.value
    const t = tasks[key]
    if (!t) return
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
    // 单次拉取失败不打断轮询；连续失败也仅延迟一次，无副作用
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
})

onBeforeUnmount(() => {
  stopPolling()
  if (statusTimer) {
    clearInterval(statusTimer)
    statusTimer = null
  }
})
</script>

<template>
  <div class="ff-page ff-market-view">
    <div class="ff-page__header">
      <div>
        <h1 class="ff-page__title">
          <AppIcon name="trending-up" size="lg" /> 行情
        </h1>
        <p class="ff-page__subtitle">A 股全市场数据、涨停跌停、龙虎榜与资金流向</p>
      </div>
    </div>

    <AppCard class="ff-market-view__toolbar" v-if="active !== 'hotrank'">
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
        <AppButton variant="secondary" size="sm" icon="refresh" @click="load">刷新</AppButton>
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

      <!-- 后台自动采集状态：开关 + 下次/上次执行 + 跳到最新数据 -->
      <div class="ff-market-view__autocollect">
        <div class="ff-market-view__autocollect-main">
          <AppIcon name="clock" size="sm" />
          <span class="ff-market-view__autocollect-label">后台自动采集</span>
          <AppSwitch :model-value="autoEnabled" @change="toggleAuto" />
          <span class="ff-market-view__autocollect-state" :class="autoEnabled ? 'is-on' : 'is-off'">
            {{ autoEnabled ? '已开启' : '已关闭' }}
          </span>
          <span v-if="autoEnabled" class="ff-market-view__autocollect-next">
            下次快照 ~{{ autoNext.snapshot || '—' }}
          </span>
        </div>
        <div class="ff-market-view__autocollect-meta">
          <span v-if="autoLast.snapshot" class="ff-market-view__autocollect-last">
            快照：{{ autoLast.snapshot.message }}
          </span>
          <span v-if="autoLast.universe" class="ff-market-view__autocollect-last">
            股票池：{{ autoLast.universe.message }}
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

        <!-- 同花顺热榜：独立组件，自管数据与布局 -->
        <ThsHotList v-if="active === 'hotrank'" />

        <template v-else>
          <div v-if="summary" class="ff-market-view__summary">
          <div v-for="(v, k) in summary" :key="k" class="ff-kv">
            <span class="ff-kv__key">{{ summaryLabel(k) }}</span>
            <span class="ff-kv__value">{{ v }}</span>
          </div>
        </div>

        <AppSkeleton v-if="loading" variant="text" :lines="8" />
        <div v-else-if="err" class="ff-alert ff-alert--danger">
          <AppIcon name="alert-circle" size="md" /> {{ err }}
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

      <table v-else-if="rows.length" class="ff-table ff-table--sticky">
        <thead>
          <tr>
            <th v-for="(v, k) in rows[0]" :key="k" class="ff-table__header">{{ header(k) }}</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="(r, i) in rows" :key="i" class="ff-table__row">
            <td v-for="(v, k) in r" :key="k" class="ff-table__cell">{{ fmt(k, v) }}</td>
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
  max-width: var(--ff-container-max);
  margin: 0 auto;
}

.ff-market-view__toolbar {
  margin-bottom: var(--ff-space-4);
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

/* ---------------- 后台自动采集状态面板 ---------------- */
.ff-market-view__autocollect {
  margin-top: var(--ff-space-3);
  padding-top: var(--ff-space-3);
  border-top: 1px dashed var(--ff-border-subtle);
  display: flex;
  flex-direction: column;
  gap: var(--ff-space-2);
}
.ff-market-view__autocollect-main {
  display: flex;
  align-items: center;
  gap: var(--ff-space-3);
  flex-wrap: wrap;
  color: var(--ff-text-secondary);
  font-size: var(--ff-fs-body-sm);
}
.ff-market-view__autocollect-label {
  font-weight: 600;
  color: var(--ff-text-primary);
}
.ff-market-view__autocollect-state {
  font-weight: 600;
}
.ff-market-view__autocollect-state.is-on {
  color: var(--ff-down-text);
}
.ff-market-view__autocollect-state.is-off {
  color: var(--ff-text-tertiary);
}
.ff-market-view__autocollect-next {
  color: var(--ff-text-tertiary);
  font-variant-numeric: tabular-nums;
}
.ff-market-view__autocollect-meta {
  display: flex;
  align-items: center;
  gap: var(--ff-space-3);
  flex-wrap: wrap;
  font-size: var(--ff-fs-caption);
  color: var(--ff-text-tertiary);
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
  margin-top: var(--ff-space-3);
  padding-top: var(--ff-space-3);
  border-top: 1px dashed var(--ff-border-subtle);
  display: flex;
  flex-direction: column;
  gap: var(--ff-space-3);
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
</style>
