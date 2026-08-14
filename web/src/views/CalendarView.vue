<script setup>
import { ref, onMounted, computed, watch } from 'vue'
import { api } from '../api/client'
import { useAutoToday, todayStr } from '../composables/useAutoToday'
import EmptyState from '../components/EmptyState.vue'
import AppCard from '../ui/AppCard.vue'
import AppDatePicker from '../ui/AppDatePicker.vue'
import AppSelect from '../ui/AppSelect.vue'
import AppSkeleton from '../ui/AppSkeleton.vue'
import AppBadge from '../ui/AppBadge.vue'
import AppIcon from '../ui/AppIcon.vue'

const CAL_TYPE_LABEL = { finance: '财经', stock: '股市', ipo: '新股', global: '全球' }
const CAL_TYPE_VARIANT = { finance: 'brand', stock: 'up', ipo: 'warn', global: 'info' }
const CAL_TYPE_ORDER = ['finance', 'stock', 'ipo', 'global']

// 默认选中当日；用户未手动改日期时随时间自动滚动到当前日期
const { date, markTouched } = useAutoToday()

const type = ref('all')
const events = ref([])
const filters = ref({ types: [], today: todayStr() })
const loading = ref(false)

const typeOptions = computed(() => [
  { label: '全部', value: 'all' },
  ...(filters.value.types || []).map((t) => ({ label: t.label, value: t.key })),
])

// 按分类类型分组（与「类型」列的四大类一一对应，组头展示当日该类型事件数）
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
  loading.value = true
  try {
    const res = await api.calendar('/list', {
      type: type.value, // 'all' 也要传,否则后端 _cal_type 默认退化为 finance
      start: date.value || undefined,
      end: date.value || undefined,
      limit: 500,
    })
    events.value = res.items || res.events || res.list || []
  } catch (e) {
    events.value = []
  } finally {
    loading.value = false
  }
}

// 日期自动滚动到当日、或用户手动切换时都重新拉取
watch(date, loadList)

onMounted(async () => {
  await loadInit()
  await loadList()
})
</script>

<template>
  <div class="ff-page ff-calendar-view">
    <div class="ff-page__header">
      <div>
        <h1 class="ff-page__title">
          <AppIcon name="calendar" size="lg" /> 财经日历
        </h1>
        <p class="ff-page__subtitle">宏观数据、股市事件、新股申购与全球市场前瞻</p>
      </div>
    </div>

    <AppCard class="ff-calendar-view__toolbar">
      <div class="ff-calendar-view__row">
        <AppDatePicker v-model="date" class="ff-calendar-view__field" label="日期" @change="markTouched" />
        <AppSelect
          v-model="type"
          class="ff-calendar-view__field"
          label="类型"
          :options="typeOptions"
          @update:model-value="loadList"
        />
        <span class="ff-calendar-view__count">
          共 <strong>{{ totalEvents }}</strong> 个事件
        </span>
      </div>
    </AppCard>

    <AppCard title="事件列表" :subtitle="`共 ${totalEvents} 条`" :no-padding="true">
      <div v-if="totalEvents" class="ff-calendar-view__groups">
        <section
          v-for="g in groups"
          :key="g.key"
          class="ff-calendar-view__group"
        >
          <header class="ff-calendar-view__group-head">
            <AppBadge :text="g.label" :variant="g.variant" />
            <span class="ff-calendar-view__group-count">{{ g.events.length }} 条</span>
          </header>
          <div class="ff-calendar-view__body">
            <div class="ff-calendar-view__head">
              <span class="ff-calendar-view__head-date">日期</span>
              <span class="ff-calendar-view__head-cat">分类</span>
              <span class="ff-calendar-view__head-title">事件</span>
            </div>
            <div
              v-for="(e, i) in g.events"
              :key="g.key + '-' + i"
              class="ff-calendar-view__event"
            >
              <span class="ff-calendar-view__date ff-num">{{ e.event_date }}</span>
              <span class="ff-calendar-view__cat">{{ e.category }}</span>
              <span class="ff-calendar-view__title">{{ e.title }}</span>
            </div>
          </div>
        </section>
      </div>
      <AppSkeleton v-else-if="loading" variant="text" :lines="6" />
      <EmptyState v-else text="当日无财经事件" icon="calendar" />
    </AppCard>
  </div>
</template>

<style scoped>
.ff-calendar-view {
  max-width: var(--ff-container-max);
  margin: 0 auto;
}

.ff-calendar-view__toolbar {
  margin-bottom: var(--ff-space-4);
}

.ff-calendar-view__row {
  display: flex;
  align-items: flex-end;
  gap: var(--ff-space-4);
  flex-wrap: wrap;
}

.ff-calendar-view__field {
  width: 200px;
}

.ff-calendar-view__count {
  margin-left: auto;
  font-size: var(--ff-fs-sm);
  color: var(--ff-text-secondary);
}

.ff-calendar-view__groups {
  display: flex;
  flex-direction: column;
  gap: var(--ff-space-4);
  padding: var(--ff-space-3) 0;
}

/* 分类分组：每组独立卡片感 */
.ff-calendar-view__group {
  border-bottom: 1px solid var(--ff-border);
  padding-bottom: var(--ff-space-3);
}
.ff-calendar-view__group:last-child {
  border-bottom: none;
  padding-bottom: 0;
}

.ff-calendar-view__group-head {
  display: flex;
  align-items: center;
  gap: var(--ff-space-2-5);
  padding: var(--ff-space-2-5) var(--ff-space-4);
  position: sticky;
  top: 0;
  background: var(--ff-bg-surface);
  z-index: 2;
}
.ff-calendar-view__group-count {
  font-size: var(--ff-fs-caption);
  font-weight: 600;
  color: var(--ff-text-tertiary);
  font-variant-numeric: tabular-nums;
}

.ff-calendar-view__body {
  flex: 0 0 auto;
}

/* 表头：sticky 吸顶 */
.ff-calendar-view__head {
  display: grid;
  grid-template-columns: 100px 120px minmax(0, 1fr);
  gap: var(--ff-space-3);
  align-items: center;
  padding: var(--ff-space-2) var(--ff-space-4);
  background: var(--ff-bg-subtle);
  font-size: var(--ff-fs-caption);
  font-weight: var(--ff-fw-semibold);
  color: var(--ff-text-tertiary);
  letter-spacing: 0.03em;
}

/* 事件行：与表头同列宽对齐 */
.ff-calendar-view__event {
  display: grid;
  grid-template-columns: 100px 120px minmax(0, 1fr);
  gap: var(--ff-space-3);
  align-items: center;
  padding: var(--ff-space-2-5) var(--ff-space-4);
  border-top: 1px solid var(--ff-border);
  font-size: var(--ff-fs-base);
  transition: background var(--ff-dur-fast);
}
.ff-calendar-view__event:last-child {
  border-bottom: none;
}
.ff-calendar-view__event:hover {
  background: var(--ff-bg-hover);
}
.ff-calendar-view__event:hover .ff-calendar-view__title {
  color: var(--ff-text-brand);
}

.ff-calendar-view__date {
  color: var(--ff-text-tertiary);
  width: 96px;
  flex-shrink: 0;
  font-size: var(--ff-fs-sm);
}

.ff-calendar-view__cat {
  flex-shrink: 0;
  color: var(--ff-text-secondary);
  width: 110px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  font-size: var(--ff-fs-sm);
}

.ff-calendar-view__title {
  flex: 1 1 auto;
  min-width: 0;
  line-height: var(--ff-lh-normal);
}
</style>
