<script setup>
import { ref, onMounted, computed, watch } from 'vue'
import { api } from '../api/client'
import { useAutoToday, todayStr } from '../composables/useAutoToday'
import EmptyState from '../components/EmptyState.vue'
import AppCard from '../ui/AppCard.vue'
import AppDatePicker from '../ui/AppDatePicker.vue'
import AppSkeleton from '../ui/AppSkeleton.vue'
import AppBadge from '../ui/AppBadge.vue'
import AppIcon from '../ui/AppIcon.vue'
import AppButton from '../ui/AppButton.vue'

const CAL_TYPE_LABEL = { finance: '财经大事', stock: 'A股要闻', ipo: '新股申购', global: '全球宏观' }
const CAL_TYPE_VARIANT = { finance: 'brand', stock: 'up', ipo: 'warn', global: 'info' }
const CAL_TYPE_ORDER = ['finance', 'stock', 'ipo', 'global']

const { date, markTouched } = useAutoToday()

const type = ref('all')
const events = ref([])
const filters = ref({ types: [], today: todayStr() })
const loading = ref(false)
const err = ref('')
let loadSeq = 0 // 请求序号守卫：防止快速切换日期/分类时旧响应覆盖新数据

const typeOptions = [
  { label: '全部事件', value: 'all', icon: 'calendar' },
  { label: '财经大事', value: 'finance', icon: 'newspaper' },
  { label: 'A股要闻', value: 'stock', icon: 'trending-up' },
  { label: '新股申购', value: 'ipo', icon: 'zap' },
  { label: '全球宏观', value: 'global', icon: 'globe' },
]

function shiftDate(days) {
  const d = new Date(date.value || todayStr())
  d.setDate(d.getDate() + days)
  const pad = (n) => String(n).padStart(2, '0')
  date.value = `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`
  markTouched()
}

function setToday() {
  date.value = todayStr()
  markTouched()
}

const groups = computed(() => {
  const list =
    type.value === 'all'
      ? events.value
      : events.value.filter((e) => e.cal_type === type.value)
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

const totalEvents = computed(() => events.value.length)

async function loadInit() {
  try {
    const init = await api.calendar('/init')
    filters.value = { types: init.types || [], today: init.today || todayStr() }
  } catch (e) {}
}

async function loadList() {
  const mySeq = ++loadSeq
  loading.value = true
  err.value = ''
  try {
    const res = await api.calendar('/list', {
      type: type.value,
      start: date.value || undefined,
      end: date.value || undefined,
      limit: 500,
    })
    if (mySeq !== loadSeq) return // 已有更新的请求，丢弃过期响应
    events.value = res.items || res.events || res.list || []
  } catch (e) {
    if (mySeq !== loadSeq) return
    // 失败时保留旧数据，仅在无数据时展示错误态——绝不把失败伪装成「当日暂无」
    err.value = e?.message || String(e)
    if (!events.value.length) events.value = []
  } finally {
    if (mySeq === loadSeq) loading.value = false
  }
}

watch(date, loadList)

onMounted(async () => {
  await loadInit()
  await loadList()
})
</script>

<template>
  <div class="ff-page ff-calendar-view">
    <!-- 页面标题按产品要求移除，h1 保留 sr-only 保文档语义 -->
    <h1 class="ff-sr-only">财经日历</h1>

    <!-- 日期导航与分类选择 Ribbon -->
    <div class="ff-calendar-view__ribbon ff-glass">
      <div class="ff-calendar-view__date-nav">
        <AppButton variant="secondary" size="sm" icon="arrow-left" @click="shiftDate(-1)" title="前一天" />
        <AppButton variant="secondary" size="sm" @click="setToday" :class="{ 'is-today': date === todayStr() }">今天</AppButton>
        <AppButton variant="secondary" size="sm" icon="arrow-right" @click="shiftDate(1)" title="后一天" />
        <AppDatePicker v-model="date" class="ff-calendar-view__datepicker" @change="markTouched" />
      </div>

      <div class="ff-calendar-view__type-chips">
        <button
          v-for="opt in typeOptions"
          :key="opt.value"
          class="ff-calendar-view__type-chip"
          :class="{ 'is-active': type === opt.value }"
          @click="type = opt.value; loadList()"
        >
          <AppIcon :name="opt.icon" size="xs" />
          <span>{{ opt.label }}</span>
        </button>
      </div>

      <div class="ff-calendar-view__count-badge">
        <span>共 <strong class="ff-num">{{ totalEvents }}</strong> 项日历事件</span>
      </div>
    </div>

    <!-- 事件列表 -->
    <AppCard :no-padding="true" class="ff-calendar-view__card">
      <div v-if="totalEvents" class="ff-calendar-view__groups">
        <section
          v-for="g in groups"
          :key="g.key"
          class="ff-calendar-view__group"
        >
          <header class="ff-calendar-view__group-head">
            <AppBadge :text="g.label" :variant="g.variant" />
            <span class="ff-calendar-view__group-count ff-num">{{ g.events.length }} 项</span>
          </header>
          
          <div class="ff-calendar-view__body">
            <div
              v-for="(e, i) in g.events"
              :key="g.key + '-' + i"
              class="ff-calendar-view__event"
            >
              <span class="ff-calendar-view__date ff-num">{{ e.event_date }}</span>
              <span class="ff-calendar-view__cat-badge">{{ e.category }}</span>
              <span class="ff-calendar-view__title">{{ e.title }}</span>
            </div>
          </div>
        </section>
      </div>
      <div v-else-if="loading" class="ff-calendar-view__loading">
        <AppSkeleton variant="text" :lines="6" />
      </div>
      <EmptyState v-else-if="err" text="日历事件加载失败" icon="alert-triangle">
        <template #description>网络或服务异常（{{ err }}），请重试。</template>
        <template #action>
          <AppButton variant="primary" size="sm" icon="refresh" @click="loadList">重试</AppButton>
        </template>
      </EmptyState>
      <EmptyState v-else text="当日暂无财经事件数据" icon="calendar" />
    </AppCard>
  </div>
</template>

<style scoped>
.ff-calendar-view {
  max-width: var(--ff-container-max);
  margin: 0 auto;
}

.ff-calendar-view__ribbon {
  display: flex;
  align-items: center;
  gap: var(--ff-space-4);
  padding: 12px 18px;
  border-radius: var(--ff-radius-lg);
  border: 1px solid var(--ff-border);
  margin-bottom: var(--ff-space-4);
  flex-wrap: wrap;
}

.ff-calendar-view__date-nav {
  display: flex;
  align-items: center;
  gap: 6px;
}

.ff-calendar-view__datepicker {
  width: 190px;
}

/* 「今天」按钮选中态：当前日期为今天时高亮，切换日期后高亮消失 */
.ff-calendar-view__date-nav :deep(.ff-btn.is-today) {
  background: var(--ff-brand);
  border-color: var(--ff-brand);
  color: var(--ff-brand-fg);
  font-weight: var(--ff-fw-semibold);
}

.ff-calendar-view__type-chips {
  display: flex;
  align-items: center;
  gap: 6px;
  background: var(--ff-bg-subtle);
  padding: 3px;
  border-radius: var(--ff-radius-md);
  border: 1px solid var(--ff-border-subtle);
}

.ff-calendar-view__type-chip {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  padding: 4px 10px;
  border-radius: var(--ff-radius-sm);
  font-size: 12px;
  font-weight: 500;
  color: var(--ff-text-secondary);
  background: none;
  border: none;
  cursor: pointer;
  transition: background-color var(--ff-dur-fast) var(--ff-ease-standard), border-color var(--ff-dur-fast) var(--ff-ease-standard), color var(--ff-dur-fast) var(--ff-ease-standard), box-shadow var(--ff-dur-fast) var(--ff-ease-standard), transform var(--ff-dur-fast) var(--ff-ease-standard);
}

.ff-calendar-view__type-chip:hover {
  color: var(--ff-text-primary);
}

.ff-calendar-view__type-chip.is-active {
  background: var(--ff-bg-surface);
  color: var(--ff-brand-text);
  font-weight: 600;
  box-shadow: var(--ff-shadow-xs);
}

.ff-calendar-view__count-badge {
  margin-left: auto;
  font-size: 12px;
  color: var(--ff-text-secondary);
  font-family: var(--ff-font-mono);
}

.ff-calendar-view__card {
  overflow: hidden;
}

.ff-calendar-view__groups {
  display: grid;
  grid-template-columns: repeat(2, 1fr);
  gap: var(--ff-space-3);
  padding: var(--ff-space-3);
  align-items: start;
}

@media (max-width: 767px) {
  .ff-calendar-view__groups {
    grid-template-columns: 1fr;
  }
}

.ff-calendar-view__group {
  border: 1px solid var(--ff-border-subtle);
  border-radius: var(--ff-radius-md);
  overflow: hidden;
  background: var(--ff-bg-surface);
}

.ff-calendar-view__group-head {
  display: flex;
  align-items: center;
  gap: var(--ff-space-3);
  padding: 10px 14px;
  background: var(--ff-bg-subtle);
  border-bottom: 1px solid var(--ff-border-subtle);
}

.ff-calendar-view__group-count {
  font-size: 11.5px;
  font-weight: 600;
  color: var(--ff-text-tertiary);
}

.ff-calendar-view__event {
  display: grid;
  grid-template-columns: 90px 130px minmax(0, 1fr);
  gap: var(--ff-space-3);
  align-items: center;
  padding: 12px 18px;
  border-bottom: 1px solid var(--ff-border-subtle);
  font-size: 13.5px;
  transition: background var(--ff-dur-fast);
}

.ff-calendar-view__event:last-child {
  border-bottom: none;
}

.ff-calendar-view__event:hover {
  background: var(--ff-bg-hover);
}

.ff-calendar-view__date {
  color: var(--ff-text-tertiary);
  font-size: 12px;
}

.ff-calendar-view__cat-badge {
  display: inline-block;
  color: var(--ff-text-secondary);
  background: var(--ff-bg-subtle);
  padding: 2px 8px;
  border-radius: var(--ff-radius-xs);
  border: 1px solid var(--ff-border-subtle);
  font-size: 11.5px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.ff-calendar-view__title {
  color: var(--ff-text-primary);
  font-weight: 500;
  line-height: 1.5;
}

.ff-calendar-view__loading {
  padding: var(--ff-space-5);
}
</style>
