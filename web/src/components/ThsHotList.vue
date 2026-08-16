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

const subTabs = computed(() =>
  Object.entries(SUB_LISTS).map(([value, m]) => ({ value, label: m.title })),
)
const periodOptions = computed(() =>
  (SUB_LISTS[subList.value]?.periods || ['day']).map((p) => ({
    value: p,
    label: p === 'hour' ? '1小时' : '24小时',
  })),
)
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
  if (category.value !== 'stock') return
  loading.value = true
  err.value = ''
  unsupported.value = false
  noDataForDate.value = ''
  data.value = null
  try {
    const params = { list: subList.value, period: period.value }
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
  const periods = SUB_LISTS[v]?.periods || ['day']
  if (!periods.includes(period.value)) period.value = periods[0]
  load()
})
watch(period, load)
watch(category, (v) => {
  if (v === 'stock') load()
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
      <p class="ths__hero-sub">同花顺用户都关注的股票 · 数据来源：同花顺</p>
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

    <template v-if="category === 'stock'">
      <div class="ths__controls">
        <AppTabs :items="subTabs" v-model="subList" type="pill" class="ths__subtabs" />
        <div class="ths__controls-right">
          <AppDatePicker
            v-model="selectedDate"
            clearable
            size="sm"
            class="ths__datepicker"
            placeholder="实时（留空）"
            :min="dateMin"
            :max="dateMax"
            hint=""
          />
          <AppSegmented :options="periodOptions" v-model="period" size="sm" />
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

      <div v-if="loading" class="ths__loading">
        <AppSkeleton variant="text" :lines="10" />
      </div>

      <div v-else-if="unsupported" class="ths__notice">
        <AppIcon name="info" size="md" />
        <span>新股热度榜数据源需同花顺鉴权，暂未接入；其余榜单正常可用。</span>
      </div>

      <div v-else-if="err" class="ff-alert ff-alert--danger">
        <AppIcon name="alert-circle" size="md" /> {{ err }}
      </div>

      <div v-else-if="noDataForDate" class="ths__notice">
        <AppIcon name="calendar" size="md" />
        <span>{{ noDataForDate }}。请选择其它日期，或清除日期查看实时热榜。</span>
      </div>

      <div v-else-if="data && data.rows.length" class="ths__list">
        <div class="ths__list-head">
          <span class="ths__col-rank">排名</span>
          <span class="ths__col-stock">股票</span>
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
            <div v-if="row.popularity_tag || (row.concept_tags && row.concept_tags.length)" class="ths__tags">
              <span v-if="row.popularity_tag" class="ths__tag ths__tag--pop">{{ row.popularity_tag }}</span>
              <span v-for="t in row.concept_tags" :key="t" class="ths__tag">{{ t }}</span>
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

      <AppEmpty v-else icon="flame" title="暂无热榜数据" />
    </template>

    <AppEmpty
      v-else
      icon="layers"
      :title="`「${catTitle(category)}」榜单接入中`"
      description="当前已开放「热股」热榜，其余类目数据源正在接入。"
    />
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
  color: #ff6a3d;
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
  background: color-mix(in srgb, #ff9f2e 12%, transparent);
  color: #b9701a;
}
.ths__banner--warn :deep(.ff-icon) {
  color: #d98324;
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
  background: linear-gradient(135deg, #ff7a45, #ff4d4f);
  color: #fff;
}
.ths__rank.is-2 {
  background: linear-gradient(135deg, #ffa940, #ff7a45);
  color: #fff;
}
.ths__rank.is-3 {
  background: linear-gradient(135deg, #ffc53d, #ffa940);
  color: #fff;
}
.ths__rank-chg {
  font-size: 10px;
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
  font-size: 11px;
  line-height: 1.6;
  padding: 0 6px;
  border-radius: var(--ff-radius-sm);
  background: var(--ff-bg-hover);
  color: var(--ff-text-secondary);
  white-space: nowrap;
}
.ths__tag--pop {
  background: color-mix(in srgb, #ff6a3d 16%, transparent);
  color: #d9431f;
  font-weight: var(--ff-fw-medium);
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
  .ths__controls {
    padding: var(--ff-space-3);
  }
}
</style>
