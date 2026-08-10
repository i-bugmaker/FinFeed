<script setup>
import { ref, onMounted, computed } from 'vue'
import { api } from '../api/client'
import EmptyState from '../components/EmptyState.vue'
import AppCard from '../ui/AppCard.vue'
import AppDatePicker from '../ui/AppDatePicker.vue'
import AppSelect from '../ui/AppSelect.vue'
import AppSkeleton from '../ui/AppSkeleton.vue'
import AppBadge from '../ui/AppBadge.vue'
import AppIcon from '../ui/AppIcon.vue'

const CAL_TYPE_LABEL = { finance: '财经', stock: '股市', ipo: '新股', global: '全球' }
const CAL_TYPE_VARIANT = { finance: 'brand', stock: 'up', ipo: 'warn', global: 'info' }

// 默认日期：本地当日（YYYY-MM-DD），避免接口未回包时日期为空
function todayStr() {
  const d = new Date()
  const y = d.getFullYear()
  const m = String(d.getMonth() + 1).padStart(2, '0')
  const day = String(d.getDate()).padStart(2, '0')
  return `${y}-${m}-${day}`
}

const type = ref('all')
const date = ref(todayStr())
const events = ref([])
const filters = ref({ types: [], today: todayStr() })
const loading = ref(false)

const typeOptions = computed(() => [
  { label: '全部', value: 'all' },
  ...(filters.value.types || []).map(t => ({ label: t.label, value: t.key })),
])

async function loadInit() {
  try {
    const init = await api.calendar('/init')
    filters.value = { types: init.types || [], today: init.today || todayStr() }
    // 服务端明确返回 today 时使用之；否则保持客户端当日
    if (init.today) date.value = init.today
  } catch (e) {}
}

async function loadList() {
  loading.value = true
  try {
    const res = await api.calendar('/list', {
      type: type.value,  // 'all' 也要传,否则后端 _cal_type 默认退化为 finance
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
        <AppDatePicker v-model="date" class="ff-calendar-view__field" label="日期" @change="loadList" />
        <AppSelect
          v-model="type"
          class="ff-calendar-view__field"
          label="类型"
          :options="typeOptions"
          @update:model-value="loadList"
        />
        <span class="ff-calendar-view__count">
          共 <strong>{{ events.length }}</strong> 个事件
        </span>
      </div>
    </AppCard>

    <AppCard title="事件列表" :subtitle="`共 ${events.length} 条`" :no-padding="true">
      <div v-if="events.length" class="ff-calendar-view__events">
        <div class="ff-calendar-view__head">
          <span class="ff-calendar-view__head-date">日期</span>
          <span class="ff-calendar-view__head-type">类型</span>
          <span class="ff-calendar-view__head-cat">分类</span>
          <span class="ff-calendar-view__head-title">事件</span>
        </div>
        <div class="ff-calendar-view__body">
          <div v-for="(e, i) in events" :key="i" class="ff-calendar-view__event">
            <span class="ff-calendar-view__date ff-num">{{ e.event_date }}</span>
            <AppBadge :text="CAL_TYPE_LABEL[e.cal_type] || e.cal_type" :variant="CAL_TYPE_VARIANT[e.cal_type] || 'default'" />
            <span class="ff-calendar-view__cat">{{ e.category }}</span>
            <span class="ff-calendar-view__title">{{ e.title }}</span>
          </div>
        </div>
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

.ff-calendar-view__events {
  display: flex;
  flex-direction: column;
}

/* 表头：sticky 吸顶 */
.ff-calendar-view__head {
  display: grid;
  grid-template-columns: 100px 84px 120px minmax(0, 1fr);
  gap: var(--ff-space-3);
  align-items: center;
  padding: var(--ff-space-2-5) var(--ff-space-4);
  border-bottom: 1px solid var(--ff-border);
  background: var(--ff-bg-surface);
  position: sticky;
  top: 0;
  z-index: 2;
  flex-shrink: 0;
  font-size: var(--ff-fs-caption);
  font-weight: var(--ff-fw-semibold);
  color: var(--ff-text-tertiary);
  letter-spacing: 0.03em;
}

/* 主体：直接展示全部事件，不内置滚动 */
.ff-calendar-view__body {
  flex: 0 0 auto;
}

/* 事件行：与表头同列宽对齐 */
.ff-calendar-view__event {
  display: grid;
  grid-template-columns: 100px 84px 120px minmax(0, 1fr);
  gap: var(--ff-space-3);
  align-items: center;
  padding: var(--ff-space-2-5) var(--ff-space-4);
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
