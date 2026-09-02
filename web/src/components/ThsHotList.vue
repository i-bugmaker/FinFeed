<script setup>
/**
 * ThsHotList — 同花顺热榜（热股）移植组件。
 *
 * 布局与原始「同花顺热榜」(thsTopRank) 保持一致：
 *   - 顶部类目导航：热股 / 板块 / ETF / 热门 / 可转债 / 港美 / 热基 / 期货 / 保险
 *   - 热股下：1 小时 / 24 小时 切换 + 子榜单切换（大家都在看 / 快速飙升中 /
 *     新股热度榜 / 技术交易派 / 价值投资派 / 趋势投资派）
 *   - 排名列表：名次 + 股票名称/代码 + 概念/人气标签 + 热度条 + 涨跌幅（红涨绿跌）
 *
 * 数据经 FinFeed 后端同源代理（/api/market/hotrank），规避浏览器跨域。
 */
import { ref, computed, onMounted, watch } from 'vue'
import { api } from '../api/client'
import { todayStr } from '../composables/useAutoToday'
import AppTabs from '../ui/AppTabs.vue'
import AppSegmented from '../ui/AppSegmented.vue'
import AppSkeleton from '../ui/AppSkeleton.vue'
import AppEmpty from '../ui/AppEmpty.vue'
import AppButton from '../ui/AppButton.vue'
import AppIcon from '../ui/AppIcon.vue'
import AppDatePicker from '../ui/AppDatePicker.vue'

const CATEGORIES = [
  { value: 'stock', title: '热股' },
  { value: 'plate', title: '板块' },
  { value: 'etf', title: 'ETF' },
  { value: 'hot', title: '热门' },
  { value: 'bond', title: '可转债' },
  { value: 'hkus', title: '港美' },
  { value: 'fund', title: '热基' },
  { value: 'future', title: '期货' },
  { value: 'insurance', title: '保险' },
]

// 子榜单配置（list_type 与后端 ths_hotrank.SUB_LISTS 对齐）
const SUB_LISTS = {
  normal: { title: '大家都在看', periods: ['hour', 'day'] },
  skyrocket: { title: '快速飙升中', periods: ['hour', 'day'] },
  new_stock: { title: '新股热度榜', periods: ['day'] },
  tech: { title: '技术交易派', periods: ['day'] },
  value: { title: '价值投资派', periods: ['day'] },
  trend: { title: '趋势投资派', periods: ['day'] },
}
// 板块（plate）子榜单（与后端 ths_hotrank.PLATE_TYPES 对齐）
const PLATE_SUB_LISTS = {
  concept: { title: '概念', periods: [] },
  industry: { title: '行业', periods: [] },
}
// 其余类目子榜（与后端 ths_hotrank.CAT_SUB_TYPES 对齐）
const CAT_SUB_TYPES = {
  etf:    { day: { title: 'ETF热门', periods: ['day', 'hour'] } },
  hot:    { day: { title: '热门话题', periods: ['day', 'hour'] } },
  bond:   { day: { title: '可转债', periods: ['day', 'hour'] } },
  future: { day: { title: '期货', periods: ['day', 'hour'] } },
  hkus:   { hk: { title: '港股', periods: ['day'] }, us: { title: '美股', periods: ['day'] } },
  fund:   { day: { title: '人气榜', periods: ['day'] } },
  insurance: {},
}

const category = ref('stock')
const subList = ref('normal')
const period = ref('hour')
const loading = ref(false)
const err = ref('')
const unsupported = ref(false)
const data = ref(null)
// 日期：空串 = 实时/当日；选择过去交易日 = 只读该日已采集快照
const selectedDate = ref('')
const availableDates = ref([])
const latestCollected = ref('')
const noDataForDate = ref('')

// 当前类目可用的子榜单集合（统一映射 stock/plate/其余类目）
const allSubs = computed(() => {
  const c = category.value
  if (c === 'stock') return SUB_LISTS
  if (c === 'plate') return PLATE_SUB_LISTS
  return CAT_SUB_TYPES[c] || {}
})
const activeSubTabs = computed(() =>
  Object.entries(allSubs.value).map(([value, m]) => ({ value, label: m.title })),
)
const currentSub = computed(() => allSubs.value[subList.value] || {})
// 仅具备时间维度的类目显示 hour/day 切换
const showPeriod = computed(() => (currentSub.value?.periods?.length || 0) > 0)
const periodOptions = computed(() =>
  (currentSub.value?.periods || ['day']).map((p) => ({
    value: p,
    label: p === 'hour' ? '1小时' : '24小时',
  })),
)
// 渲染模式：stock(个股/基金型) / topic(话题)
const renderMode = computed(() => {
  if (category.value === 'hot') return 'topic'
  return 'stock'
})
// 东方财富替代源模式：美股（港美-美股）/ 保险 由东方财富实时行情提供，非同花顺原榜
const eastmoneyMode = computed(
  () => category.value === 'insurance' || (category.value === 'hkus' && subList.value === 'us'),
)
// 数据来源标识（动态）
const providerLabel = computed(() =>
  eastmoneyMode.value ? '数据来源：东方财富（实时行情）' : '数据来源：同花顺',
)
// 东方财富替代源无历史快照，隐藏日期选择器
const showDatePicker = computed(() => !eastmoneyMode.value)
// 个股列标题：保险/美股时为「保险股」/「美股」
const stockColLabel = computed(() => {
  if (category.value === 'insurance') return '保险股'
  if (category.value === 'hkus' && subList.value === 'us') return '美股'
  return category.value === 'fund' ? '基金' : '股票'
})
const updatedText = computed(() => {
  const ts = data.value?.updated_at
  if (!ts) return ''
  const d = new Date(ts * 1000)
  const p = (n) => String(n).padStart(2, '0')
  return `更新于 ${p(d.getHours())}:${p(d.getMinutes())}:${p(d.getSeconds())}`
})

function heatPct(row) {
  const max = data.value?.max_heat || 0
  if (!max || !row.heat) return 0
  return Math.max(2, Math.round((row.heat / max) * 100))
}
function fmtHeat(v) {
  if (v == null) return '—'
  return Math.round(v).toLocaleString('en-US')
}
function fmtChg(v) {
  if (v == null) return '—'
  return (v > 0 ? '+' : '') + v.toFixed(2) + '%'
}
function fmtFund(v) {
  if (v == null) return ''
  const yi = v / 1e8
  return (yi > 0 ? '+' : '') + yi.toFixed(2) + '亿'
}
// 成交额 / 主力净流入：美股为美元计价，A股保险为人民币，单位需区分
function _amtUnit() {
  return eastmoneyMode.value && category.value === 'hkus' && subList.value === 'us' ? '亿美元' : '亿'
}
function fmtAmount(row) {
  if (row.amount == null) return ''
  return fmtFund(row.amount).replace('亿', _amtUnit())
}
function fmtInflow(row) {
  if (row.main_inflow == null) return ''
  return fmtFund(row.main_inflow).replace('亿', _amtUnit())
}
function chgClass(v) {
  if (v == null) return 'is-flat'
  return v > 0 ? 'is-up' : v < 0 ? 'is-down' : 'is-flat'
}
function rankClass(rank) {
  if (rank === 1) return 'is-1'
  if (rank === 2) return 'is-2'
  if (rank === 3) return 'is-3'
  return 'is-n'
}
function rankChgText(v) {
  if (v == null || v === 0) return ''
  return v > 0 ? `▲${v}` : `▼${-v}`
}
function catTitle(v) {
  return CATEGORIES.find((c) => c.value === v)?.title || ''
}

// 日期选择器范围：上限为今天，下限为最早一个已采集日期（无数据时放开）
const dateMax = todayStr()
const dateMin = computed(() => {
  const ds = availableDates.value
  return ds.length ? ds[ds.length - 1] : ''
})

// 数据来源标识：实时 / 历史快照 / 缓存兜底
const isLive = computed(() => data.value?.source === 'live')
const sourceLabel = computed(() => {
  const s = data.value?.source
  if (s === 'db') return `历史快照 · 采集于 ${data.value?.collected_at || data.value?.trade_date || ''}`
  if (s === 'cache') return `实时获取失败 · 展示最近快照（${data.value?.cached_date || ''}）`
  return ''
})

async function load() {
  loading.value = true
  err.value = ''
  unsupported.value = false
  noDataForDate.value = ''
  data.value = null
  try {
    const params = {
      category: category.value,
      list: subList.value,
      period: period.value,
    }
    // 选择历史日期时按日期只读快照；留空则为实时/当日
    if (selectedDate.value) params.date = selectedDate.value
    const r = await api.market('hotrank', params)
    const d = r.data || r
    if (d.error) {
      if (d.unsupported) unsupported.value = true
      else if (typeof d.error === 'string' && d.error.includes('暂无')) noDataForDate.value = d.error
      else err.value = d.error
      return
    }
    data.value = d
  } catch (e) {
    err.value = e.message || String(e)
  } finally {
    loading.value = false
  }
}

async function loadDates() {
  try {
    const r = await api.market('hotrank_dates')
    const d = r.data || r
    if (d && Array.isArray(d.dates)) {
      availableDates.value = d.dates
      latestCollected.value = d.latest || ''
    }
  } catch (e) {
    /* 日期清单不可用时静默降级，仍可正常实时查看 */
  }
}

watch(subList, (v) => {
  const periods = currentSub.value?.periods || ['day']
  if (!periods.includes(period.value)) period.value = periods[0] || 'day'
  load()
})
watch(period, load)
watch(category, (v) => {
  // 切换类目时重置到该类的第一个子榜单；若子榜未变则手动加载
  const first = Object.keys(allSubs.value)[0] || 'day'
  if (subList.value !== first) subList.value = first
  else load()
})
watch(selectedDate, load)

onMounted(async () => {
  await loadDates()
  await load()
})
</script>

<template>
  <div class="ths">
    <header class="ths__hero">
      <div class="ths__hero-title">
        <AppIcon name="flame" size="lg" />
        <span>同花顺热榜</span>
      </div>
      <p class="ths__hero-sub">同花顺用户都关注的标的 · {{ providerLabel }}</p>
    </header>

    <nav class="ths__cats" aria-label="热榜类目">
      <button
        v-for="c in CATEGORIES"
        :key="c.value"
        type="button"
        class="ths__cat"
        :class="category === c.value && 'is-active'"
        @click="category = c.value"
      >
        {{ c.title }}
      </button>
    </nav>

    <div class="ths__controls">
      <AppTabs v-if="activeSubTabs.length" :items="activeSubTabs" v-model="subList" type="pill" class="ths__subtabs" />
      <div class="ths__controls-right">
        <AppDatePicker
          v-if="showDatePicker"
          v-model="selectedDate"
          clearable
          size="sm"
          class="ths__datepicker"
          placeholder="实时（留空）"
          :min="dateMin"
          :max="dateMax"
          hint=""
        />
        <AppSegmented v-if="showPeriod" :options="periodOptions" v-model="period" size="sm" />
        <AppButton variant="tonal" size="sm" icon="refresh" :loading="loading" @click="load">
          刷新
        </AppButton>
      </div>
    </div>

    <div
      v-if="data && (data.source === 'db' || data.source === 'cache')"
      class="ths__banner"
      :class="data.source === 'cache' ? 'ths__banner--warn' : 'ths__banner--hist'"
    >
      <AppIcon :name="data.source === 'cache' ? 'alert-triangle' : 'history'" size="sm" />
      <span>{{ sourceLabel }}</span>
    </div>

    <div v-if="eastmoneyMode && data && data.note" class="ths__banner ths__banner--em">
      <AppIcon name="info" size="sm" />
      <span>{{ data.note }}</span>
    </div>

    <div v-if="loading" class="ths__loading">
      <AppSkeleton variant="text" :lines="10" />
    </div>

    <div v-else-if="unsupported" class="ths__notice">
      <AppIcon name="info" size="md" />
      <span>{{ catTitle(category) }}榜单数据源需同花顺账号登录后查看，其余榜单正常可用。</span>
    </div>

    <div v-else-if="err" class="ff-alert ff-alert--danger">
      <AppIcon name="alert-circle" size="md" /> {{ err }}
    </div>

    <div v-else-if="noDataForDate" class="ths__notice">
      <AppIcon name="calendar" size="md" />
      <span>{{ noDataForDate }}。请选择其它日期，或清除日期查看实时热榜。</span>
    </div>

    <!-- 个股 / 基金型榜单（热股 / 板块 / ETF / 可转债 / 期货 / 港美 / 热基 / 美股 / 保险） -->
    <div
      v-else-if="renderMode === 'stock' && data && data.rows && data.rows.length"
      class="ths__list"
      :class="[category === 'fund' && 'ths__list--fund', eastmoneyMode && 'ths__list--em']"
    >
      <div class="ths__list-head">
        <span class="ths__col-rank">排名</span>
        <span class="ths__col-stock">{{ stockColLabel }}</span>
        <span class="ths__col-heat">热度</span>
        <span class="ths__col-chg ths__chg-align">涨幅</span>
      </div>
      <div
        v-for="row in data.rows"
        :key="(row.code || '') + '-' + row.rank"
        class="ths__row"
      >
        <div class="ths__col-rank">
          <span class="ths__rank" :class="rankClass(row.rank)">{{ row.rank }}</span>
          <span
            v-if="rankChgText(row.rank_chg)"
            class="ths__rank-chg"
            :class="row.rank_chg > 0 ? 'is-up' : 'is-down'"
          >{{ rankChgText(row.rank_chg) }}</span>
        </div>

        <div class="ths__col-stock">
          <div class="ths__stock-main">
            <span class="ths__name">{{ row.name }}</span>
            <span class="ths__code">{{ row.code }}</span>
          </div>
          <div
            v-if="row.popularity_tag || (row.concept_tags && row.concept_tags.length) || row.etf_name || row.fund_type || row.nav != null || row.funds != null || (row.rel_stocks && row.rel_stocks.length) || row.amount != null || row.main_inflow != null"
            class="ths__tags"
          >
            <span v-if="row.popularity_tag" class="ths__tag ths__tag--pop">{{ row.popularity_tag }}</span>
            <span v-for="t in row.concept_tags" :key="t" class="ths__tag">{{ t }}</span>
            <span v-if="row.etf_name" class="ths__tag ths__tag--etf">ETF {{ row.etf_name }}<template v-if="row.etf_rise_and_fall != null"> {{ fmtChg(row.etf_rise_and_fall) }}</template></span>
            <span v-if="row.fund_type" class="ths__tag ths__tag--fund">{{ row.fund_type }}</span>
            <span v-if="row.nav != null" class="ths__tag ths__tag--nav">净值 {{ row.nav }}</span>
            <span v-if="row.funds != null" class="ths__tag ths__tag--fund">资金 {{ fmtFund(row.funds) }}</span>
            <span v-if="row.rel_stocks && row.rel_stocks.length" class="ths__tag ths__tag--rel">关联{{ row.rel_stocks.length }}股</span>
            <span v-if="row.amount != null" class="ths__tag ths__tag--amt">成交额 {{ fmtAmount(row) }}</span>
            <span v-if="row.main_inflow != null" class="ths__tag ths__tag--inflow" :class="row.main_inflow > 0 ? 'is-up' : 'is-down'">主力 {{ fmtInflow(row) }}</span>
          </div>
        </div>

        <div class="ths__col-heat">
          <div class="ths__heat-bar">
            <div class="ths__heat-fill" :style="{ width: heatPct(row) + '%' }"></div>
          </div>
          <span class="ths__heat-val ff-num">{{ fmtHeat(row.heat) }}</span>
        </div>

        <div class="ths__col-chg ths__chg-align">
          <span class="ths__chg ff-num" :class="chgClass(row.change_pct)">{{ fmtChg(row.change_pct) }}</span>
        </div>
      </div>

      <p v-if="updatedText" class="ths__updated">{{ updatedText }} · 共 {{ data.count }} 只</p>
    </div>

    <!-- 话题型榜单（热门） -->
    <div
      v-else-if="renderMode === 'topic' && data && data.rows && data.rows.length"
      class="ths__list ths__list--topic"
    >
      <div v-for="row in data.rows" :key="row.code || row.rank" class="ths__topic">
        <div class="ths__topic-head">
          <span class="ths__rank ths__rank--sm" :class="rankClass(row.rank)">{{ row.rank }}</span>
          <span class="ths__topic-title">{{ row.name }}</span>
        </div>
        <p class="ths__topic-desc">{{ row.topic }}</p>
      </div>
      <p v-if="updatedText" class="ths__updated">{{ updatedText }} · 共 {{ data.count }} 条</p>
    </div>

    <AppEmpty v-else icon="flame" title="暂无热榜数据" />
  </div>
</template>

<style scoped>
.ths {
  display: flex;
  flex-direction: column;
}

/* ---------- 头部 ---------- */
.ths__hero {
  padding: var(--ff-space-5) var(--ff-space-5) var(--ff-space-3);
}
.ths__hero-title {
  display: flex;
  align-items: center;
  gap: var(--ff-space-2);
  font-size: var(--ff-fs-h3);
  font-weight: var(--ff-fw-semibold);
  color: var(--ff-text-primary);
}
.ths__hero-title :deep(.ff-icon) {
  color: var(--ff-hot);
}
.ths__hero-sub {
  margin: var(--ff-space-1) 0 0;
  font-size: var(--ff-fs-caption);
  color: var(--ff-text-tertiary);
}

/* ---------- 类目导航 ---------- */
.ths__cats {
  display: flex;
  gap: var(--ff-space-1);
  padding: 0 var(--ff-space-4) var(--ff-space-2);
  overflow-x: auto;
  border-bottom: 1px solid var(--ff-border-subtle);
  scrollbar-width: thin;
}
.ths__cat {
  flex: 0 0 auto;
  height: 36px;
  padding: 0 var(--ff-space-3);
  border: none;
  background: transparent;
  color: var(--ff-text-secondary);
  font-size: var(--ff-fs-body);
  font-weight: var(--ff-fw-medium);
  border-radius: var(--ff-radius-md);
  cursor: pointer;
  white-space: nowrap;
  transition:
    background-color var(--ff-dur-fast) var(--ff-ease-standard),
    color var(--ff-dur-fast) var(--ff-ease-standard);
}
.ths__cat:hover {
  background: var(--ff-bg-hover);
  color: var(--ff-text-primary);
}
.ths__cat.is-active {
  color: var(--ff-brand-text);
  background: color-mix(in srgb, var(--ff-brand) 12%, transparent);
  font-weight: var(--ff-fw-semibold);
}

/* ---------- 控制条 ---------- */
.ths__controls {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--ff-space-3);
  flex-wrap: wrap;
  padding: var(--ff-space-3) var(--ff-space-5);
  border-bottom: 1px solid var(--ff-border-subtle);
}
.ths__controls-right {
  display: flex;
  align-items: center;
  gap: var(--ff-space-2);
}
.ths__datepicker {
  width: 168px;
  flex: 0 0 auto;
}

/* ---------- 数据来源横幅（历史快照 / 缓存兜底） ---------- */
.ths__banner {
  display: flex;
  align-items: center;
  gap: var(--ff-space-2);
  margin: var(--ff-space-2) var(--ff-space-5);
  padding: var(--ff-space-2) var(--ff-space-4);
  border-radius: var(--ff-radius-md);
  font-size: var(--ff-fs-body-sm);
  color: var(--ff-text-secondary);
}
.ths__banner--hist {
  background: color-mix(in srgb, var(--ff-brand) 8%, transparent);
}
.ths__banner--hist :deep(.ff-icon) {
  color: var(--ff-brand-text);
}
.ths__banner--warn {
  background: color-mix(in srgb, var(--ff-hot) 12%, transparent);
  color: var(--ff-hot-text);
}
.ths__banner--warn :deep(.ff-icon) {
  color: var(--ff-hot-text);
}
.ths__subtabs {
  flex: 1 1 auto;
  min-width: 0;
  overflow-x: auto;
}

/* ---------- 状态 ---------- */
.ths__loading {
  padding: var(--ff-space-5);
}
.ths__notice {
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
.ths__notice :deep(.ff-icon) {
  color: var(--ff-brand-text);
  flex: 0 0 auto;
}

/* ---------- 列表 ---------- */
.ths__list {
  display: flex;
  flex-direction: column;
}
.ths__list-head,
.ths__row {
  display: grid;
  grid-template-columns: 60px 1fr 200px 88px;
  align-items: center;
  gap: var(--ff-space-3);
  padding: var(--ff-space-2-5) var(--ff-space-5);
}
.ths__list-head {
  font-size: var(--ff-fs-caption);
  color: var(--ff-text-tertiary);
  border-bottom: 1px solid var(--ff-border-subtle);
}
.ths__row {
  border-bottom: 1px solid var(--ff-border-subtle);
  transition: background-color var(--ff-dur-fast) var(--ff-ease-standard);
}
.ths__row:hover {
  background: var(--ff-bg-hover);
}
.ths__chg-align {
  text-align: right;
  justify-self: end;
}

.ths__col-rank {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 2px;
}
.ths__rank {
  width: 24px;
  height: 24px;
  border-radius: 50%;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  font-weight: var(--ff-fw-bold);
  font-size: var(--ff-fs-body-sm);
  background: var(--ff-bg-hover);
  color: var(--ff-text-tertiary);
  font-variant-numeric: tabular-nums;
}
.ths__rank.is-1 {
  background: var(--ff-hot-strong);
  color: var(--ff-hot-fg);
}
.ths__rank.is-2 {
  background: color-mix(in srgb, var(--ff-hot) 26%, var(--ff-bg-surface));
  color: var(--ff-hot-text);
}
.ths__rank.is-3 {
  background: color-mix(in srgb, var(--ff-hot) 12%, var(--ff-bg-surface));
  color: var(--ff-hot-text);
}
.ths__rank-chg {
  font-size: var(--ff-fs-micro);
  font-weight: var(--ff-fw-semibold);
  font-variant-numeric: tabular-nums;
}
.ths__rank-chg.is-up {
  color: var(--ff-text-up);
}
.ths__rank-chg.is-down {
  color: var(--ff-down-text);
}

.ths__stock-main {
  display: flex;
  align-items: baseline;
  gap: var(--ff-space-2);
  min-width: 0;
}
.ths__name {
  font-size: var(--ff-fs-body);
  font-weight: var(--ff-fw-semibold);
  color: var(--ff-text-primary);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
.ths__code {
  font-size: var(--ff-fs-caption);
  color: var(--ff-text-tertiary);
  font-variant-numeric: tabular-nums;
  flex: 0 0 auto;
}
.ths__tags {
  display: flex;
  flex-wrap: wrap;
  gap: 4px;
  margin-top: 4px;
}
.ths__tag {
  font-size: var(--ff-fs-xs);
  line-height: 1.6;
  padding: 0 6px;
  border-radius: var(--ff-radius-sm);
  background: var(--ff-bg-hover);
  color: var(--ff-text-secondary);
  white-space: nowrap;
}
.ths__tag--pop {
  background: color-mix(in srgb, var(--ff-hot) 16%, transparent);
  color: var(--ff-hot-text);
  font-weight: var(--ff-fw-medium);
}
.ths__tag--etf {
  background: color-mix(in srgb, #2f7df6 14%, transparent);
  color: #1f5fcf;
  font-weight: var(--ff-fw-medium);
}
.ths__tag--fund {
  background: color-mix(in srgb, #7b5cff 14%, transparent);
  color: #5b3fd6;
  font-weight: var(--ff-fw-medium);
}
.ths__tag--nav {
  background: color-mix(in srgb, #2f7df6 12%, transparent);
  color: #1f5fcf;
}
.ths__tag--rel {
  background: var(--ff-bg-hover);
  color: var(--ff-text-secondary);
}

/* 话题型榜单 */
.ths__list--topic {
  padding: var(--ff-space-2) var(--ff-space-5);
}
.ths__topic {
  padding: var(--ff-space-3) 0;
  border-bottom: 1px solid var(--ff-border-subtle);
}
.ths__topic-head {
  display: flex;
  align-items: center;
  gap: var(--ff-space-2);
}
.ths__rank--sm {
  width: 20px;
  height: 20px;
  font-size: var(--ff-fs-xs);
  flex: 0 0 auto;
}
.ths__topic-title {
  font-size: var(--ff-fs-body);
  font-weight: var(--ff-fw-semibold);
  color: var(--ff-text-primary);
}
.ths__topic-desc {
  margin: var(--ff-space-1) 0 0;
  padding-left: 28px;
  font-size: var(--ff-fs-body-sm);
  color: var(--ff-text-secondary);
  line-height: 1.6;
}

/* 东方财富替代源（美股 / 保险）：隐藏热度列，改展示成交额 / 主力净流入 */
.ths__list--em .ths__col-heat {
  display: none;
}
.ths__list--em .ths__list-head,
.ths__list--em .ths__row {
  grid-template-columns: 60px 1fr 88px;
}
.ths__tag--amt {
  background: color-mix(in srgb, #2f7df6 12%, transparent);
  color: #1f5fcf;
}
.ths__tag--inflow.is-up {
  background: color-mix(in srgb, var(--ff-text-up) 14%, transparent);
  color: var(--ff-text-up);
}
.ths__tag--inflow.is-down {
  background: color-mix(in srgb, var(--ff-down-text) 14%, transparent);
  color: var(--ff-down-text);
}
.ths__banner--em {
  background: color-mix(in srgb, #2f7df6 8%, transparent);
  color: #1f5fcf;
}
.ths__banner--em :deep(.ff-icon) {
  color: #2f7df6;
}

.ths__col-heat {
  display: flex;
  flex-direction: column;
  gap: 4px;
  min-width: 0;
}
.ths__heat-bar {
  height: 6px;
  border-radius: 3px;
  background: var(--ff-bg-hover);
  overflow: hidden;
}
.ths__heat-fill {
  height: 100%;
  border-radius: 3px;
  background: linear-gradient(90deg, #ffb454, #ff5a4d);
  transition: width var(--ff-dur-slow) var(--ff-ease-standard);
}
.ths__heat-val {
  font-size: var(--ff-fs-caption);
  color: var(--ff-text-secondary);
}

.ths__chg {
  font-size: var(--ff-fs-body);
  font-weight: var(--ff-fw-semibold);
}
.is-up {
  color: var(--ff-text-up);
}
.is-down {
  color: var(--ff-down-text);
}
.is-flat {
  color: var(--ff-text-tertiary);
}

.ths__updated {
  padding: var(--ff-space-3) var(--ff-space-5);
  font-size: var(--ff-fs-caption);
  color: var(--ff-text-tertiary);
  text-align: right;
  border-top: 1px solid var(--ff-border-subtle);
}

/* ---------- 响应式 ---------- */
@media (max-width: 560px) {
  .ths__list-head,
  .ths__row {
    grid-template-columns: 48px 1fr 120px 72px;
    gap: var(--ff-space-2);
    padding: var(--ff-space-2-5) var(--ff-space-3);
  }
  .ths__list--em .ths__list-head,
  .ths__list--em .ths__row {
    grid-template-columns: 44px 1fr 72px;
  }
  .ths__controls {
    padding: var(--ff-space-3);
  }
}
</style>
