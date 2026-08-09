<script setup>
import { ref, onMounted, watch, computed } from 'vue'
import { api } from '../api/client'
import EmptyState from '../components/EmptyState.vue'

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

// 表头中文化映射（覆盖行情各子模块返回字段）
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
const OVERVIEW_MAP = { tables: '数据表', boards: '板块数量', health: '系统健康度' }
function header(k) {
  return HEADER_MAP[k] || k
}
function summaryLabel(k) {
  return SUMMARY_MAP[k] || k
}
// 单元格格式化：涨跌幅保留 2 位小数
function fmt(k, v) {
  if (k === 'pct_chg' && typeof v === 'number') return v.toFixed(2)
  return v
}
// 市场情绪：单条对象逐字段展示
const sentimentKeys = computed(() =>
  active.value === 'sentiment' && data.value
    ? Object.keys(data.value).filter((k) => k !== 'created_at')
    : [],
)
// 总览：健康度概览计数
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
  { key: 'snapshot', label: '采集行情快照' },
  { key: 'bars', label: '采集K线' },
  { key: 'universe', label: '初始化股票池' },
  { key: 'calibrate', label: '校准情绪模型' },
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
  <div class="market">
    <div class="toolbar card">
      <div class="row">
        <span class="lbl">交易日</span>
        <input class="date" type="date" v-model="date" />
        <input v-if="active === 'search'" class="kw" v-model="kw" @keyup.enter="load" placeholder="股票代码/名称" />
        <button class="btn" @click="load">刷新</button>
      </div>
      <div class="row actions">
        <button v-for="a in actions" :key="a.key" class="btn" @click="runAction(a)">{{ a.label }}</button>
        <span v-if="actionStatus" class="astat text-2">{{ actionStatus }}</span>
      </div>
    </div>

    <div class="tabs">
      <button
        v-for="t in tabs"
        :key="t.key"
        class="tab"
        :class="{ active: active === t.key }"
        @click="active = t.key"
      >
        {{ t.label }}
      </button>
    </div>

    <div class="panel card">
      <div v-if="summary" class="summary">
        <span v-for="(v, k) in summary" :key="k" class="sc"><b>{{ summaryLabel(k) }}</b> {{ v }}</span>
      </div>
      <div v-if="loading" class="loading"><span class="spinner"></span></div>
      <div v-else-if="err" class="err">加载失败：{{ err }}</div>

      <!-- 总览：三大区块独立渲染 -->
      <div v-else-if="active === 'overview' && data" class="ov">
        <section class="ov-sec">
          <h3>数据表</h3>
          <table class="tbl">
            <thead>
              <tr><th>表名</th><th>标签</th><th>记录数</th><th>最新日期</th><th>标的数量</th></tr>
            </thead>
            <tbody>
              <tr v-for="t in data.tables" :key="t.table">
                <td>{{ t.table }}</td>
                <td>{{ t.label }}</td>
                <td>{{ t.rows }}</td>
                <td>{{ t.latest || '—' }}</td>
                <td>{{ t.subjects }}</td>
              </tr>
            </tbody>
          </table>
        </section>
        <section class="ov-sec">
          <h3>板块数量</h3>
          <table class="tbl">
            <thead>
              <tr><th>板块</th><th>总数</th><th>活跃</th></tr>
            </thead>
            <tbody>
              <tr v-for="b in data.boards" :key="b.board">
                <td>{{ b.board }}</td>
                <td>{{ b.n }}</td>
                <td>{{ b.active }}</td>
              </tr>
            </tbody>
          </table>
        </section>
        <section class="ov-sec" v-if="healthSummary">
          <h3>系统健康度（共 {{ healthSummary.total }} 个数据源，正常 {{ healthSummary.ok }} / 熔断 {{ healthSummary.fused }}）</h3>
          <table class="tbl">
            <thead>
              <tr><th>数据源</th><th>请求数</th><th>成功</th><th>失败</th><th>平均延迟(s)</th><th>状态</th></tr>
            </thead>
            <tbody>
              <tr v-for="h in data.health" :key="h.source_name">
                <td>{{ h.source_name }}</td>
                <td>{{ h.total_requests }}</td>
                <td>{{ h.success_count }}</td>
                <td>{{ h.failure_count }}</td>
                <td>{{ h.avg_latency?.toFixed(2) }}</td>
                <td :class="h.is_circuit_open ? 'bad' : 'good'">{{ h.is_circuit_open ? '熔断' : '正常' }}</td>
              </tr>
            </tbody>
          </table>
        </section>
      </div>

      <!-- 市场情绪：单条快照逐字段卡片 -->
      <div v-else-if="active === 'sentiment' && sentimentKeys.length" class="sent-cards">
        <div class="sent-card" v-for="k in sentimentKeys" :key="k">
          <div class="sl">{{ header(k) }}</div>
          <div class="sv" :class="{ neg: k === 'down_limit' }">{{ fmt(k, data[k]) }}</div>
        </div>
      </div>

      <table v-else-if="rows.length" class="tbl">
        <thead>
          <tr>
            <th v-for="(v, k) in rows[0]" :key="k">{{ header(k) }}</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="(r, i) in rows" :key="i">
            <td v-for="(v, k) in r" :key="k">{{ fmt(k, v) }}</td>
          </tr>
        </tbody>
      </table>
      <EmptyState v-else text="暂无数据（可能需要先采集行情）" />
    </div>
  </div>
</template>

<style scoped>
.market {
  max-width: var(--content-max);
  margin: 0 auto;
}
.toolbar {
  padding: var(--sp-4) var(--sp-5);
  margin-bottom: var(--sp-4);
  display: flex;
  flex-direction: column;
  gap: 12px;
}
.row {
  display: flex;
  align-items: center;
  gap: 12px;
  flex-wrap: wrap;
}
.lbl {
  font-weight: 600;
  color: var(--text-2);
  font-size: var(--fs-sm);
}
.date,
.kw {
  border: 1px solid var(--border);
  border-radius: var(--r-sm);
  padding: 8px 10px;
  font-size: var(--fs-sm);
  background: var(--bg-surface);
  color: var(--text-1);
}
.astat {
  font-size: var(--fs-sm);
}
.tabs {
  display: flex;
  gap: 6px;
  flex-wrap: wrap;
  margin-bottom: var(--sp-4);
}
.tab {
  border: 1px solid var(--border);
  background: var(--bg-surface);
  color: var(--text-2);
  border-radius: var(--r-pill);
  padding: 7px 16px;
  font-size: var(--fs-sm);
  font-weight: 500;
}
.tab.active {
  background: var(--primary);
  color: var(--primary-text);
  border-color: var(--primary);
}
.panel {
  padding: var(--sp-4) var(--sp-5);
  overflow-x: auto;
}
.summary {
  display: flex;
  flex-wrap: wrap;
  gap: 14px;
  margin-bottom: var(--sp-4);
  font-size: var(--fs-sm);
}
.summary .sc b {
  color: var(--text-2);
  margin-right: 4px;
}
.tbl {
  width: 100%;
  border-collapse: separate;
  border-spacing: 0;
  font-size: var(--fs-sm);
}
.tbl th {
  text-align: left;
  padding: 10px 12px;
  background: var(--bg-surface-2);
  border-bottom: 2px solid var(--border);
  position: sticky;
  top: 0;
  white-space: nowrap;
}
.tbl td {
  padding: 9px 12px;
  border-bottom: 1px solid var(--border);
  white-space: nowrap;
}
.tbl tbody tr:hover {
  background: var(--bg-hover);
}
.tbl td.good {
  color: var(--down);
  font-weight: 600;
}
.tbl td.bad {
  color: var(--up);
  font-weight: 600;
}
/* 总览区块 */
.ov {
  display: flex;
  flex-direction: column;
  gap: var(--sp-5);
}
.ov-sec h3 {
  font-size: var(--fs-base);
  margin: 0 0 var(--sp-3);
  color: var(--text-1);
}
/* 市场情绪卡片 */
.sent-cards {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(150px, 1fr));
  gap: var(--sp-3);
}
.sent-card {
  border: 1px solid var(--border);
  border-radius: var(--r-md);
  padding: var(--sp-4) var(--sp-4);
  background: var(--bg-surface-2);
}
.sent-card .sl {
  font-size: var(--fs-sm);
  color: var(--text-2);
  margin-bottom: 6px;
}
.sent-card .sv {
  font-size: var(--fs-xl);
  font-weight: 700;
  color: var(--text-1);
  font-variant-numeric: tabular-nums;
}
.sent-card .sv.neg {
  color: var(--up);
}
.loading,
.err {
  text-align: center;
  padding: var(--sp-5);
}
.err {
  color: var(--up);
}
</style>
