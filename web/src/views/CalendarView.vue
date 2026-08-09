<script setup>
import { ref, onMounted, computed } from 'vue'
import { api } from '../api/client'
import ChartPanel from '../components/ChartPanel.vue'
import EmptyState from '../components/EmptyState.vue'

const CAL_TYPE_LABEL = { finance: '财经', stock: '股市', ipo: '新股', global: '全球' }

const filters = ref({ types: [], today: '' })
const type = ref('all')
const date = ref('')
const events = ref([])
const stats = ref(null)
const loading = ref(false)

const statsOption = ref({})

// 按类型聚合的概览（前端二次统计，保证与列表一致）
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
  <div class="cal">
    <div class="toolbar card">
      <div class="row">
        <span class="lbl">日期</span>
        <input class="date" type="date" v-model="date" @change="reload" />
        <span class="lbl">类型</span>
        <select v-model="type" @change="reload" class="sel">
          <option value="all">全部</option>
          <option v-for="t in filters.types" :key="t.key" :value="t.key">{{ t.label }}</option>
        </select>
        <span class="cnt">共 {{ events.length }} 个事件</span>
      </div>
    </div>

    <!-- 类型概览条 -->
    <div v-if="typeSummary.length" class="overview">
      <div
        v-for="s in typeSummary"
        :key="s.key"
        class="ov"
        :class="'ov-' + s.key"
        @click="type = s.key; reload()"
      >
        <span class="ov-num num">{{ s.count }}</span>
        <span class="ov-lbl">{{ s.label }}</span>
      </div>
    </div>

    <div class="grid">
      <div class="card list-card">
        <h3>事件列表（{{ events.length }}）</h3>
        <div v-if="events.length" class="events">
          <div v-for="(e, i) in events" :key="i" class="event">
            <span class="ed num">{{ e.event_date }}</span>
            <span class="et" :class="'t-' + (e.cal_type || 'finance')">{{ CAL_TYPE_LABEL[e.cal_type] || e.cal_type }}</span>
            <span class="ecat">{{ e.category }}</span>
            <span class="etitle">{{ e.title }}</span>
          </div>
        </div>
        <div v-else-if="loading" class="loading"><span class="spinner"></span></div>
        <EmptyState v-else text="当日无财经事件" />
      </div>
      <div class="card chart-card">
        <h3>类型分布</h3>
        <ChartPanel :option="statsOption" height="320px" v-if="stats" />
        <EmptyState v-else text="无统计" />
      </div>
    </div>
  </div>
</template>

<style scoped>
.cal {
  max-width: var(--content-max);
  margin: 0 auto;
}
.toolbar {
  padding: var(--sp-4) var(--sp-5);
  margin-bottom: var(--sp-4);
}
.row {
  display: flex;
  align-items: center;
  gap: 14px;
  flex-wrap: wrap;
}
.lbl {
  font-size: var(--fs-sm);
  font-weight: 600;
  color: var(--text-2);
}
.date,
.sel {
  border: 1px solid var(--border);
  border-radius: var(--r-sm);
  padding: 9px 12px;
  font-size: var(--fs-base);
  background: var(--bg-surface);
  color: var(--text-1);
}
.cnt {
  margin-left: auto;
  font-size: var(--fs-sm);
  color: var(--text-3);
}

/* 类型概览条 */
.overview {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: var(--sp-3);
  margin-bottom: var(--sp-4);
}
.ov {
  background: var(--bg-surface);
  border: 1px solid var(--border);
  border-left: 4px solid var(--text-3);
  border-radius: var(--r-md);
  padding: 14px 18px;
  cursor: pointer;
  display: flex;
  flex-direction: column;
  gap: 2px;
  transition: all 0.15s;
}
.ov:hover {
  box-shadow: var(--shadow-sm);
  transform: translateY(-1px);
}
.ov-num {
  font-size: var(--fs-xl);
  font-weight: 700;
  line-height: 1.1;
}
.ov-lbl {
  font-size: var(--fs-sm);
  color: var(--text-2);
}
.ov-finance { border-left-color: var(--primary); }
.ov-stock { border-left-color: var(--up); }
.ov-ipo { border-left-color: var(--warn); }
.ov-global { border-left-color: var(--info); }

.grid {
  display: grid;
  grid-template-columns: 1.5fr 1fr;
  gap: var(--sp-4);
}
.list-card,
.chart-card {
  padding: var(--sp-5);
}
.list-card h3,
.chart-card h3 {
  font-size: var(--fs-md);
  margin-bottom: var(--sp-4);
}
.events {
  display: flex;
  flex-direction: column;
  gap: 0;
  max-height: 600px;
  overflow-y: auto;
}
.event {
  display: flex;
  align-items: center;
  gap: 16px;
  padding: 15px 10px;
  border-bottom: 1px solid var(--border);
  font-size: var(--fs-base);
}
.event:hover {
  background: var(--bg-hover);
}
.ed {
  color: var(--text-3);
  width: 96px;
  flex-shrink: 0;
  font-size: var(--fs-sm);
}
.et {
  flex-shrink: 0;
  padding: 4px 12px;
  border-radius: var(--r-pill);
  font-size: var(--fs-xs);
  font-weight: 600;
  color: #fff;
  background: var(--text-3);
  white-space: nowrap;
}
.et.t-finance {
  background: var(--primary);
}
.et.t-stock {
  background: var(--up);
}
.et.t-ipo {
  background: var(--warn);
}
.et.t-global {
  background: var(--info);
}
.ecat {
  flex-shrink: 0;
  color: var(--text-2);
  width: 110px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  font-size: var(--fs-sm);
}
.etitle {
  flex: 1;
  min-width: 0;
  line-height: 1.5;
}
.loading {
  text-align: center;
  padding: var(--sp-6);
}
@media (max-width: 880px) {
  .grid {
    grid-template-columns: 1fr;
  }
  .overview {
    grid-template-columns: repeat(2, 1fr);
  }
}
</style>
