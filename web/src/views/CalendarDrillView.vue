<script setup>
import { ref, computed, watch, onMounted } from 'vue'
import { api } from '../api/client'
import { useAutoToday, todayStr } from '../composables/useAutoToday'
import EmptyState from '../components/EmptyState.vue'
import AppCard from '../ui/AppCard.vue'
import AppIcon from '../ui/AppIcon.vue'
import AppSelect from '../ui/AppSelect.vue'
import AppSegmented from '../ui/AppSegmented.vue'
import AppButton from '../ui/AppButton.vue'
import AppSkeleton from '../ui/AppSkeleton.vue'
import AppBadge from '../ui/AppBadge.vue'

const CAL_TYPE_LABEL = { finance: '财经', stock: '股市', ipo: '新股', global: '全球' }
const CAL_TYPE_VARIANT = { finance: 'brand', stock: 'up', ipo: 'warn', global: 'info' }
const CAL_TYPE_ORDER = ['finance', 'stock', 'ipo', 'global']
const WD = ['一', '二', '三', '四', '五', '六', '日']

// 默认选中当日；用户未手动改时随时间自动滚动到当前日期
const { date, markTouched } = useAutoToday({ interval: 60000 })
const level = ref('month') // month | week | day
const type = ref('all')
const typeOptions = computed(() => [
  { label: '全部', value: 'all' },
  ...CAL_TYPE_ORDER.map((k) => ({ label: CAL_TYPE_LABEL[k], value: k })),
])
const countsMap = ref({}) // 月视图：{date: {total,high,...}}
const items = ref([]) // 周/日视图：事件列表
const loading = ref(false)
const filters = ref({ types: [] })

// ---------------- 日期工具 ----------------
function pad(n) {
  return String(n).padStart(2, '0')
}
function toDate(s) {
  const [y, m, d] = s.split('-').map(Number)
  return new Date(y, m - 1, d)
}
function fmt(d) {
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`
}
function addDays(d, n) {
  const r = new Date(d)
  r.setDate(r.getDate() + n)
  return r
}
function addMonths(d, n) {
  const r = new Date(d)
  r.setMonth(r.getMonth() + n)
  return r
}
function startOfWeek(d) {
  return addDays(d, -((d.getDay() + 6) % 7)) // 周一为一周起点
}
const anchorDate = computed(() => toDate(date.value))

// ---------------- 视图计算 ----------------
const monthKey = computed(() => {
  const d = anchorDate.value
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}`
})
const monthCells = computed(() => {
  const base = anchorDate.value
  const y = base.getFullYear()
  const m = base.getMonth()
  const first = new Date(y, m, 1)
  const startWd = (first.getDay() + 6) % 7
  const start = addDays(first, -startWd)
  const cells = []
  for (let i = 0; i < 42; i++) {
    const c = addDays(start, i)
    const key = fmt(c)
    const cnt = countsMap.value[key]
    cells.push({
      key,
      day: c.getDate(),
      inMonth: c.getMonth() === m,
      isToday: key === todayStr(),
      total: cnt ? cnt.total || 0 : 0,
      high: cnt ? cnt.high || 0 : 0,
    })
  }
  return cells
})

const weekDays = computed(() => {
  const ws = startOfWeek(anchorDate.value)
  const arr = []
  for (let i = 0; i < 7; i++) {
    const d = addDays(ws, i)
    const key = fmt(d)
    arr.push({
      key,
      date: d,
      label: `${d.getMonth() + 1}/${d.getDate()}`,
      weekday: WD[(d.getDay() + 6) % 7],
      items: itemsByDate.value[key] || [],
    })
  }
  return arr
})

const itemsByDate = computed(() => {
  const m = {}
  for (const e of items.value) {
    if (!m[e.event_date]) m[e.event_date] = []
    m[e.event_date].push(e)
  }
  return m
})

const dayGroups = computed(() => {
  const list = items.value
  const map = {}
  for (const e of list) {
    if (!map[e.cal_type]) map[e.cal_type] = []
    map[e.cal_type].push(e)
  }
  return CAL_TYPE_ORDER.filter((k) => map[k] && map[k].length).map((k) => ({
    key: k,
    label: CAL_TYPE_LABEL[k] || k,
    variant: CAL_TYPE_VARIANT[k] || 'default',
    events: map[k],
  }))
})

const rangeLabel = computed(() => {
  const d = anchorDate.value
  if (level.value === 'month') return `${d.getFullYear()}年${d.getMonth() + 1}月`
  if (level.value === 'week') {
    const a = weekDays.value[0].date
    const b = weekDays.value[6].date
    return `${a.getMonth() + 1}月${a.getDate()}日 - ${b.getMonth() + 1}月${b.getDate()}日`
  }
  return `${d.getFullYear()}年${d.getMonth() + 1}月${d.getDate()}日 周${WD[(d.getDay() + 6) % 7]}`
})

// ---------------- 数据加载 ----------------
function rangeFor() {
  if (level.value === 'week') {
    const ws = startOfWeek(anchorDate.value)
    return { start: fmt(ws), end: fmt(addDays(ws, 6)) }
  }
  return { start: date.value, end: date.value }
}

async function load() {
  loading.value = true
  try {
    if (level.value === 'month') {
      const res = await api.calendar('/month', { month: monthKey.value, type: type.value })
      countsMap.value = (res && res.counts) || {}
      items.value = []
    } else {
      const { start, end } = rangeFor()
      const res = await api.calendar('/list', { type: type.value, start, end, limit: 2000 })
      items.value = (res && (res.items || res.events || res.list)) || []
      countsMap.value = {}
    }
  } catch (e) {
    items.value = []
    countsMap.value = {}
  } finally {
    loading.value = false
  }
}

watch([level, date, type], load, { immediate: false })

onMounted(async () => {
  try {
    const init = await api.calendar('/init')
    filters.value = { types: init.types || [] }
  } catch (e) {}
  await load()
})

// ---------------- 交互 ----------------
function navigate(dir) {
  markTouched()
  if (level.value === 'month') date.value = fmt(addMonths(anchorDate.value, dir))
  else if (level.value === 'week') date.value = fmt(addDays(anchorDate.value, dir * 7))
  else date.value = fmt(addDays(anchorDate.value, dir))
}
function goToday() {
  date.value = todayStr()
}
function drillDay(cell) {
  markTouched()
  date.value = cell.key
  level.value = 'day'
}
function drillWeek(i) {
  markTouched()
  date.value = weekDays.value[i].key
  level.value = 'week'
}
function upLevel() {
  if (level.value === 'day') level.value = 'week'
  else if (level.value === 'week') level.value = 'month'
}
function setLevel(l) {
  if (l === level.value) return
  if (l !== 'day') markTouched()
  level.value = l
}

function onTypeChange() {
  markTouched()
  load()
}
</script>

<template>
  <div class="ff-page ff-cal-drill">
    <div class="ff-page__header">
      <div>
        <h1 class="ff-page__title">
          <AppIcon name="calendar-days" size="lg" /> 财经日历 · 下钻
        </h1>
        <p class="ff-page__subtitle">按 月 / 周 / 日 层级查看财经事件，点击日期向下钻取</p>
      </div>
    </div>

    <AppCard class="ff-cal-drill__toolbar">
      <div class="ff-cal-drill__row">
        <AppSegmented
          :model-value="level"
          :options="[
            { label: '月', value: 'month' },
            { label: '周', value: 'week' },
            { label: '日', value: 'day' },
          ]"
          @update:model-value="setLevel"
        />
        <AppSelect v-model="type" class="ff-cal-drill__type" :options="typeOptions" @update:model-value="onTypeChange" />
        <div class="ff-cal-drill__nav">
          <AppButton variant="tonal" size="sm" icon="chevron-left" @click="navigate(-1)" />
          <span class="ff-cal-drill__range">{{ rangeLabel }}</span>
          <AppButton variant="tonal" size="sm" icon="chevron-right" @click="navigate(1)" />
          <AppButton variant="secondary" size="sm" @click="goToday">今天</AppButton>
        </div>
      </div>
    </AppCard>

    <!-- 面包屑下钻路径 -->
    <div class="ff-cal-drill__crumbs">
      <button class="ff-cal-drill__crumb" :class="level === 'month' && 'is-active'" @click="setLevel('month')">月</button>
      <span class="ff-cal-drill__sep">/</span>
      <button class="ff-cal-drill__crumb" :class="level === 'week' && 'is-active'" :disabled="level === 'month'" @click="setLevel('week')">周</button>
      <span class="ff-cal-drill__sep">/</span>
      <button class="ff-cal-drill__crumb" :class="level === 'day' && 'is-active'" :disabled="level !== 'day'" @click="setLevel('day')">日</button>
    </div>

    <!-- 月视图 -->
    <AppCard v-if="level === 'month'" :no-padding="true">
      <div class="ff-cal-drill__grid">
        <div class="ff-cal-drill__wd" v-for="w in WD" :key="'h' + w">{{ w }}</div>
        <template v-for="(cell, i) in monthCells" :key="cell.key">
          <button
            class="ff-cal-drill__cell"
            :class="{
              'is-out': !cell.inMonth,
              'is-today': cell.isToday,
            }"
            @click="drillDay(cell)"
          >
            <span class="ff-cal-drill__day ff-num">{{ cell.day }}</span>
            <span v-if="cell.total" class="ff-cal-drill__badge">
              <span class="ff-cal-drill__total ff-num">{{ cell.total }}</span>
              <span v-if="cell.high" class="ff-cal-drill__high" title="高重要性事件">★{{ cell.high }}</span>
            </span>
            <span v-else class="ff-cal-drill__badge ff-cal-drill__badge--empty">·</span>
          </button>
        </template>
      </div>
      <AppSkeleton v-if="loading" variant="text" :lines="6" />
    </AppCard>

    <!-- 周视图 -->
    <div v-else-if="level === 'week'" class="ff-cal-drill__weeks">
      <div v-for="(d, i) in weekDays" :key="d.key" class="ff-cal-drill__weekday" :class="d.key === todayStr() && 'is-today'">
        <button class="ff-cal-drill__weekhead" @click="drillDay({ key: d.key })">
          <span class="ff-cal-drill__weekwd">周{{ d.weekday }}</span>
          <span class="ff-cal-drill__weekdate ff-num">{{ d.label }}</span>
          <span class="ff-cal-drill__weekcnt ff-num">{{ d.items.length }}</span>
        </button>
        <div class="ff-cal-drill__weeklist">
          <div v-for="(e, j) in d.items" :key="j" class="ff-cal-drill__wevent" :class="`ff-cal-drill__wevent--${e.cal_type}`">
            <span class="ff-cal-drill__wevent-time ff-num">{{ e.event_time || '' }}</span>
            <span class="ff-cal-drill__wevent-title">{{ e.title }}</span>
          </div>
          <div v-if="!d.items.length" class="ff-cal-drill__noon">无事件</div>
        </div>
      </div>
    </div>

    <!-- 日视图 -->
    <AppCard v-else :no-padding="true">
      <div v-if="dayGroups.length" class="ff-cal-drill__daygroups">
        <section v-for="g in dayGroups" :key="g.key" class="ff-cal-drill__daygroup">
          <header class="ff-cal-drill__dayhead">
            <AppBadge :text="g.label" :variant="g.variant" />
            <span class="ff-cal-drill__daycount">{{ g.events.length }} 条</span>
          </header>
          <div
            v-for="(e, i) in g.events"
            :key="g.key + '-' + i"
            class="ff-cal-drill__dayevent"
          >
            <span class="ff-cal-drill__e-cat">{{ e.category }}</span>
            <span class="ff-cal-drill__e-title">{{ e.title }}</span>
            <span v-if="e.importance >= 3" class="ff-cal-drill__e-imp" title="高重要性">★</span>
          </div>
        </section>
      </div>
      <AppSkeleton v-else-if="loading" variant="text" :lines="6" />
      <EmptyState v-else text="当日无财经事件" icon="calendar-days" />
    </AppCard>
  </div>
</template>

<style scoped>
.ff-cal-drill {
  max-width: var(--ff-container-max);
  margin: 0 auto;
}
.ff-cal-drill__toolbar {
  margin-bottom: var(--ff-space-3);
}
.ff-cal-drill__row {
  display: flex;
  align-items: center;
  gap: var(--ff-space-4);
  flex-wrap: wrap;
}
.ff-cal-drill__type {
  width: 160px;
}
.ff-cal-drill__nav {
  margin-left: auto;
  display: flex;
  align-items: center;
  gap: var(--ff-space-2);
}
.ff-cal-drill__range {
  min-width: 180px;
  text-align: center;
  font-weight: 600;
  color: var(--ff-text-primary);
  font-variant-numeric: tabular-nums;
}
.ff-cal-drill__crumbs {
  display: flex;
  align-items: center;
  gap: var(--ff-space-2);
  margin-bottom: var(--ff-space-3);
  font-size: var(--ff-fs-sm);
}
.ff-cal-drill__crumb {
  border: none;
  background: transparent;
  color: var(--ff-text-secondary);
  font-weight: 600;
  cursor: pointer;
  padding: 2px 10px;
  border-radius: var(--ff-radius-pill);
  transition: background var(--ff-dur-fast), color var(--ff-dur-fast);
}
.ff-cal-drill__crumb:hover:not(:disabled) {
  background: var(--ff-bg-hover);
  color: var(--ff-text-primary);
}
.ff-cal-drill__crumb.is-active {
  background: var(--ff-bg-brand-subtle);
  color: var(--ff-text-brand);
}
.ff-cal-drill__crumb:disabled {
  opacity: 0.45;
  cursor: default;
}
.ff-cal-drill__sep {
  color: var(--ff-text-tertiary);
}

/* 月历网格 */
.ff-cal-drill__grid {
  display: grid;
  grid-template-columns: repeat(7, 1fr);
  gap: 1px;
  background: var(--ff-border);
  border: 1px solid var(--ff-border);
}
.ff-cal-drill__wd {
  background: var(--ff-bg-subtle);
  text-align: center;
  padding: var(--ff-space-2);
  font-size: var(--ff-fs-caption);
  font-weight: var(--ff-fw-semibold);
  color: var(--ff-text-tertiary);
}
.ff-cal-drill__cell {
  background: var(--ff-bg-surface);
  border: none;
  min-height: 84px;
  padding: var(--ff-space-2);
  display: flex;
  flex-direction: column;
  align-items: flex-start;
  gap: 4px;
  cursor: pointer;
  text-align: left;
  transition: background var(--ff-dur-fast);
}
.ff-cal-drill__cell:hover {
  background: var(--ff-bg-hover);
}
.ff-cal-drill__cell.is-out {
  background: var(--ff-bg-canvas);
  color: var(--ff-text-disabled);
}
.ff-cal-drill__cell.is-today {
  box-shadow: inset 0 0 0 2px var(--ff-brand-border);
}
.ff-cal-drill__day {
  font-weight: var(--ff-fw-semibold);
  color: var(--ff-text-primary);
  font-size: var(--ff-fs-sm);
}
.ff-cal-drill__cell.is-out .ff-cal-drill__day {
  color: var(--ff-text-disabled);
}
.ff-cal-drill__badge {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  font-size: var(--ff-fs-xs);
}
.ff-cal-drill__total {
  background: var(--ff-brand-subtle);
  color: var(--ff-brand-text);
  border-radius: var(--ff-radius-pill);
  padding: 0 8px;
  font-weight: 600;
  line-height: 18px;
}
.ff-cal-drill__high {
  color: var(--ff-up-text);
  font-weight: 600;
}
.ff-cal-drill__badge--empty {
  color: var(--ff-text-disabled);
}

/* 周视图 */
.ff-cal-drill__weeks {
  display: grid;
  grid-template-columns: repeat(7, 1fr);
  gap: var(--ff-space-2);
}
@media (max-width: 980px) {
  .ff-cal-drill__weeks {
    grid-template-columns: repeat(2, 1fr);
  }
}
.ff-cal-drill__weekday {
  background: var(--ff-bg-surface);
  border: 1px solid var(--ff-border);
  border-radius: var(--ff-radius-md);
  overflow: hidden;
  display: flex;
  flex-direction: column;
}
.ff-cal-drill__weekday.is-today {
  border-color: var(--ff-brand-border);
  box-shadow: 0 0 0 1px var(--ff-brand-border);
}
.ff-cal-drill__weekhead {
  display: flex;
  align-items: center;
  gap: var(--ff-space-2);
  width: 100%;
  border: none;
  background: var(--ff-bg-subtle);
  padding: var(--ff-space-2) var(--ff-space-3);
  cursor: pointer;
  color: var(--ff-text-secondary);
  transition: background var(--ff-dur-fast);
}
.ff-cal-drill__weekhead:hover {
  background: var(--ff-bg-hover);
}
.ff-cal-drill__weekwd {
  font-weight: 600;
}
.ff-cal-drill__weekdate {
  font-size: var(--ff-fs-sm);
  color: var(--ff-text-primary);
}
.ff-cal-drill__weekcnt {
  margin-left: auto;
  font-size: var(--ff-fs-xs);
  color: var(--ff-text-tertiary);
  background: var(--ff-bg-canvas);
  border-radius: var(--ff-radius-pill);
  padding: 0 8px;
}
.ff-cal-drill__weeklist {
  padding: var(--ff-space-2);
  display: flex;
  flex-direction: column;
  gap: 4px;
  max-height: 320px;
  overflow-y: auto;
}
.ff-cal-drill__wevent {
  display: flex;
  gap: var(--ff-space-2);
  font-size: var(--ff-fs-xs);
  padding: 4px 6px;
  border-radius: var(--ff-radius-sm);
  border-left: 3px solid var(--ff-border);
  background: var(--ff-bg-canvas);
}
.ff-cal-drill__wevent--finance { border-left-color: var(--ff-brand); }
.ff-cal-drill__wevent--stock { border-left-color: var(--ff-up); }
.ff-cal-drill__wevent--ipo { border-left-color: var(--ff-warn); }
.ff-cal-drill__wevent--global { border-left-color: var(--ff-info, var(--ff-text-tertiary)); }
.ff-cal-drill__wevent-time {
  color: var(--ff-text-tertiary);
  flex-shrink: 0;
}
.ff-cal-drill__wevent-title {
  color: var(--ff-text-secondary);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.ff-cal-drill__noon {
  font-size: var(--ff-fs-xs);
  color: var(--ff-text-disabled);
  text-align: center;
  padding: var(--ff-space-3) 0;
}

/* 日视图 */
.ff-cal-drill__daygroups {
  display: flex;
  flex-direction: column;
  gap: var(--ff-space-4);
  padding: var(--ff-space-3) 0;
}
.ff-cal-drill__daygroup {
  border-bottom: 1px solid var(--ff-border);
  padding-bottom: var(--ff-space-3);
}
.ff-cal-drill__daygroup:last-child {
  border-bottom: none;
  padding-bottom: 0;
}
.ff-cal-drill__dayhead {
  display: flex;
  align-items: center;
  gap: var(--ff-space-2-5);
  padding: var(--ff-space-2-5) var(--ff-space-4);
  position: sticky;
  top: 0;
  background: var(--ff-bg-surface);
  z-index: 2;
}
.ff-cal-drill__daycount {
  font-size: var(--ff-fs-caption);
  font-weight: 600;
  color: var(--ff-text-tertiary);
}
.ff-cal-drill__dayevent {
  display: grid;
  grid-template-columns: 120px minmax(0, 1fr) 16px;
  gap: var(--ff-space-3);
  align-items: center;
  padding: var(--ff-space-2-5) var(--ff-space-4);
  border-top: 1px solid var(--ff-border);
  font-size: var(--ff-fs-base);
  transition: background var(--ff-dur-fast);
}
.ff-cal-drill__dayevent:hover {
  background: var(--ff-bg-hover);
}
.ff-cal-drill__dayevent:hover .ff-cal-drill__e-title {
  color: var(--ff-text-brand);
}
.ff-cal-drill__e-cat {
  flex-shrink: 0;
  color: var(--ff-text-secondary);
  width: 110px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  font-size: var(--ff-fs-sm);
}
.ff-cal-drill__e-title {
  flex: 1 1 auto;
  min-width: 0;
  line-height: var(--ff-lh-normal);
}
.ff-cal-drill__e-imp {
  color: var(--ff-up-text);
}
</style>
