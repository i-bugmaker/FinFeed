<script setup>
import { ref, onMounted, watch, computed } from 'vue'
import { api } from '../api/client'
import EmptyState from '../components/EmptyState.vue'
import AppCard from '../ui/AppCard.vue'
import AppButton from '../ui/AppButton.vue'
import AppInput from '../ui/AppInput.vue'
import AppDatePicker from '../ui/AppDatePicker.vue'
import AppTabs from '../ui/AppTabs.vue'
import AppBadge from '../ui/AppBadge.vue'
import AppIcon from '../ui/AppIcon.vue'
import AppSkeleton from '../ui/AppSkeleton.vue'

const tabs = [
  { key: 'overview', label: '总览' },
  { key: 'sentiment', label: '市场情绪' },
  { key: 'limitup', label: '涨停' },
  { key: 'limitdown', label: '跌停' },
  { key: 'limitbroken', label: '炸板' },
  { key: 'billboard', label: '龙虎榜' },
  { key: 'moneyflow', label: '资金流' },
  { key: 'margin', label: '两融' },
  { key: 'forecast', label: '业绩预告' },
  { key: 'ipo', label: '新股' },
  { key: 'sectors', label: '板块' },
  { key: 'search', label: '股票搜索' },
]
const active = ref('limitup')
const date = ref('')
const data = ref(null)
const rows = ref([])
const summary = ref(null)
const loading = ref(false)
const err = ref('')
const kw = ref('')

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

const healthSummary = computed(() => {
  if (active.value !== 'overview' || !data.value || !Array.isArray(data.value.health)) return null
  const h = data.value.health
  return {
    total: h.length,
    ok: h.filter((x) => !x.is_circuit_open).length,
    fused: h.filter((x) => x.is_circuit_open).length,
  }
})

const actions = [
  { key: 'snapshot', label: '采集行情快照', icon: 'download' },
  { key: 'bars', label: '采集K线', icon: 'bar-chart' },
  { key: 'universe', label: '初始化股票池', icon: 'database' },
  { key: 'calibrate', label: '校准情绪模型', icon: 'activity' },
]
const actionStatus = ref('')

async function loadDates() {
  try {
    const r = await api.market('dates')
    if (r.success && r.data.default_date) date.value = r.data.default_date
  } catch (e) {}
}

async function load() {
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
  actionStatus.value = '执行中：' + a.label
  api
    .marketAction({ action: a.key, date: date.value || undefined })
    .then((r) => {
      actionStatus.value = r.success ? '已启动：' + a.label : '失败：' + (r.error || '')
    })
    .catch((e) => (actionStatus.value = '错误：' + e.message))
}

watch(active, load)
watch(date, load)

onMounted(async () => {
  await loadDates()
  await load()
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

    <AppCard class="ff-market-view__toolbar">
      <div class="ff-market-view__row">
        <AppDatePicker v-model="date" class="ff-market-view__field" label="交易日" />
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
          @click="runAction(a)"
        >
          {{ a.label }}
        </AppButton>
        <span v-if="actionStatus" class="ff-market-view__status">{{ actionStatus }}</span>
      </div>
    </AppCard>

    <AppTabs v-model="active" type="pill" :items="tabs" class="ff-market-view__tabs" />

    <AppCard class="ff-market-view__panel" :no-padding="true">
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
        <section v-if="healthSummary" class="ff-market-view__section">
          <h3 class="ff-h3">
            系统健康度
            <AppBadge :text="`正常 ${healthSummary.ok} / 熔断 ${healthSummary.fused}`" variant="default" />
          </h3>
          <table class="ff-table">
            <thead>
              <tr>
                <th class="ff-table__header">数据源</th>
                <th class="ff-table__header ff-table__header--right">请求数</th>
                <th class="ff-table__header ff-table__header--right">成功</th>
                <th class="ff-table__header ff-table__header--right">失败</th>
                <th class="ff-table__header ff-table__header--right">平均延迟(s)</th>
                <th class="ff-table__header">状态</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="h in data.health" :key="h.source_name" class="ff-table__row">
                <td class="ff-table__cell">{{ h.source_name }}</td>
                <td class="ff-table__cell ff-table__cell--right ff-num">{{ h.total_requests }}</td>
                <td class="ff-table__cell ff-table__cell--right ff-num">{{ h.success_count }}</td>
                <td class="ff-table__cell ff-table__cell--right ff-num">{{ h.failure_count }}</td>
                <td class="ff-table__cell ff-table__cell--right ff-num">{{ h.avg_latency?.toFixed(2) }}</td>
                <td class="ff-table__cell">
                  <AppBadge :text="h.is_circuit_open ? '熔断' : '正常'" :variant="h.is_circuit_open ? 'danger' : 'success'" />
                </td>
              </tr>
            </tbody>
          </table>
        </section>
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

.ff-market-view__field {
  width: 200px;
}

.ff-market-view__status {
  font-size: var(--ff-fs-sm);
  color: var(--ff-text-secondary);
}

.ff-market-view__tabs {
  margin-bottom: var(--ff-space-4);
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
