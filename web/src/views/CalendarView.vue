<script setup>
import { ref, onMounted, computed } from 'vue'
import { api } from '../api/client'
import ChartPanel from '../components/ChartPanel.vue'
import EmptyState from '../components/EmptyState.vue'
import AppCard from '../ui/AppCard.vue'
import AppDatePicker from '../ui/AppDatePicker.vue'
import AppSelect from '../ui/AppSelect.vue'
import AppSkeleton from '../ui/AppSkeleton.vue'
import AppBadge from '../ui/AppBadge.vue'
import AppIcon from '../ui/AppIcon.vue'

const CAL_TYPE_LABEL = { finance: '财经', stock: '股市', ipo: '新股', global: '全球' }
const CAL_TYPE_VARIANT = { finance: 'brand', stock: 'up', ipo: 'warn', global: 'info' }

const filters = ref({ types: [], today: '' })
const type = ref('all')
const date = ref('')
const events = ref([])
const stats = ref(null)
const loading = ref(false)
const statsOption = ref({})

const typeOptions = computed(() => [
  { label: '全部', value: 'all' },
  ...(filters.value.types || []).map(t => ({ label: t.label, value: t.key })),
])

const typeSummary = computed(() => {
  const map = {}
  for (const e of events.value) {
    const k = e.cal_type || 'finance'
    map[k] = (map[k] || 0) + 1
  }
  return Object.entries(map).map(([k, v]) => ({ key: k, label: CAL_TYPE_LABEL[k] || k, count: v }))
})

async function loadInit() {
  try {
    const init = await api.calendar('/init')
    filters.value = { types: init.types || [], today: init.today || '' }
    if (init.today) date.value = init.today
  } catch (e) {}
}

async function loadList() {
  loading.value = true
  try {
    const res = await api.calendar('/list', {
      type: type.value !== 'all' ? type.value : undefined,
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

async function loadStats() {
  try {
    const s = await api.calendar('/stats', { date: date.value || undefined })
    stats.value = s
    const dist = s.by_type || {}
    statsOption.value = {
      tooltip: { trigger: 'item' },
      series: [
        {
          type: 'pie',
          radius: ['45%', '70%'],
          data: Object.entries(dist).map(([k, v]) => ({
            name: CAL_TYPE_LABEL[k] || k,
            value: v,
          })),
          label: { formatter: '{b}\n{d}%' },
        },
      ],
    }
  } catch (e) {}
}

function reload() {
  loadList()
  loadStats()
}

onMounted(async () => {
  await loadInit()
  reload()
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
        <AppDatePicker v-model="date" class="ff-calendar-view__field" label="日期" @change="reload" />
        <AppSelect
          v-model="type"
          class="ff-calendar-view__field"
          label="类型"
          :options="typeOptions"
          @update:model-value="reload"
        />
        <span class="ff-calendar-view__count">
          共 <strong>{{ events.length }}</strong> 个事件
        </span>
      </div>
    </AppCard>

    <div v-if="typeSummary.length" class="ff-calendar-view__overview">
      <AppCard
        v-for="s in typeSummary"
        :key="s.key"
        interactive
        class="ff-calendar-view__ov"
        :class="`ff-calendar-view__ov--${s.key}`"
        @click="type = s.key; reload()"
      >
        <div class="ff-metric">
          <span class="ff-metric__value">{{ s.count }}</span>
          <span class="ff-metric__label">{{ s.label }}</span>
        </div>
      </AppCard>
    </div>

    <div class="ff-grid">
      <div class="ff-col-12 ff-col-lg-8">
        <AppCard title="事件列表" :subtitle="`共 ${events.length} 条`" :no-padding="true">
          <div v-if="events.length" class="ff-calendar-view__events">
            <div v-for="(e, i) in events" :key="i" class="ff-calendar-view__event">
              <span class="ff-calendar-view__date ff-num">{{ e.event_date }}</span>
              <AppBadge :text="CAL_TYPE_LABEL[e.cal_type] || e.cal_type" :variant="CAL_TYPE_VARIANT[e.cal_type] || 'default'" />
              <span class="ff-calendar-view__cat">{{ e.category }}</span>
              <span class="ff-calendar-view__title">{{ e.title }}</span>
            </div>
          </div>
          <AppSkeleton v-else-if="loading" variant="text" :lines="6" />
          <EmptyState v-else text="当日无财经事件" icon="calendar" />
        </AppCard>
      </div>
      <div class="ff-col-12 ff-col-lg-4">
        <AppCard title="类型分布" :no-padding="true">
          <div class="ff-calendar-view__chart">
            <ChartPanel :option="statsOption" height="320px" v-if="stats" />
            <EmptyState v-else text="无统计" icon="pie-chart" />
          </div>
        </AppCard>
      </div>
    </div>
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

.ff-calendar-view__overview {
  display: grid;
  grid-template-columns: repeat(2, 1fr);
  gap: var(--ff-space-3);
  margin-bottom: var(--ff-space-4);
}

.ff-calendar-view__ov {
  border-left: 4px solid var(--ff-border);
}

.ff-calendar-view__ov--finance { border-left-color: var(--ff-border-brand); }
.ff-calendar-view__ov--stock { border-left-color: var(--ff-border-up); }
.ff-calendar-view__ov--ipo { border-left-color: var(--ff-border-warn); }
.ff-calendar-view__ov--global { border-left-color: var(--ff-border-info); }

.ff-calendar-view__events {
  display: flex;
  flex-direction: column;
  max-height: 600px;
  overflow-y: auto;
}

.ff-calendar-view__event {
  display: flex;
  align-items: center;
  gap: var(--ff-space-4);
  padding: var(--ff-space-3) var(--ff-space-4);
  border-bottom: 1px solid var(--ff-border);
  font-size: var(--ff-fs-base);
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

.ff-calendar-view__chart {
  padding: var(--ff-space-4);
}

@media (min-width: 1024px) {
  .ff-calendar-view__overview {
    grid-template-columns: repeat(4, 1fr);
  }
}
</style>
