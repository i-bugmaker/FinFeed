<script setup>
/**
 * UnusualAlertCard — 异动监控（通达信行情）
 *
 * 数据来源：GET /api/easytdx/dashboard/unusual?count=20
 * 展示：时间 / 名称·代码 / 异动描述 / 异动数值。
 */
import { ref, watch, onMounted, computed } from 'vue'
import easytdxApi from '../../features/easytdx/api/easytdxApi'
import AppEmpty from '../../ui/AppEmpty.vue'
import AppSkeleton from '../../ui/AppSkeleton.vue'
import AppIcon from '../../ui/AppIcon.vue'

const props = defineProps({
  refreshKey: { type: Number, default: 0 },
})

const loading = ref(false)
const err = ref('')
const rows = ref([])

async function load() {
  loading.value = true
  err.value = ''
  try {
    const res = await easytdxApi.dashboard.unusual(20)
    rows.value = res.ok ? res.data : []
    if (!res.ok) err.value = res.error || '获取失败'
  } catch (e) {
    err.value = e.message || String(e)
  } finally {
    loading.value = false
  }
}

function refresh() {
  load()
}

watch(() => props.refreshKey, refresh)
onMounted(load)
</script>

<template>
  <div class="ua">
    <div v-if="loading && !rows.length" class="ua__load">
      <AppSkeleton variant="text" :lines="5" />
    </div>
    <div v-else-if="err && !rows.length" class="ua__err">
      <AppEmpty icon="zap" title="暂无异动" :description="err" />
    </div>
    <AppEmpty v-else-if="!rows.length" icon="zap" title="暂无异动" description="盘口暂无触发异动监控的标的" />

    <div v-else class="ua__list">
      <div v-for="(row, i) in rows" :key="(row.code || '') + '-' + i" class="ua__row">
        <span class="ua__time ff-num">{{ row.time || '—' }}</span>
        <div class="ua__stock">
          <span class="ua__name">{{ row.name }}</span>
          <span class="ua__code ff-num">{{ row.board }}{{ row.code }}</span>
        </div>
        <span class="ua__desc" :title="row.desc">{{ row.desc || '—' }}</span>
        <span class="ua__value ff-num">{{ row.value || '' }}</span>
      </div>
    </div>
  </div>
</template>

<style scoped>
.ua {
  display: flex;
  flex-direction: column;
  gap: var(--ff-space-3);
}
.ua__load {
  min-height: 120px;
}

.ua__list {
  display: flex;
  flex-direction: column;
}
.ua__row {
  display: grid;
  grid-template-columns: 52px minmax(120px, 1.2fr) minmax(0, 2.4fr) auto;
  align-items: center;
  gap: var(--ff-space-3);
  padding: var(--ff-space-1-5) 0;
  border-bottom: 1px solid var(--ff-border-subtle);
  transition: background-color var(--ff-dur-fast) var(--ff-ease-standard);
}
.ua__row:hover {
  background: var(--ff-bg-hover);
}
.ua__time {
  color: var(--ff-text-tertiary);
  font-size: var(--ff-fs-body-sm);
  font-variant-numeric: tabular-nums;
}
.ua__stock {
  display: flex;
  align-items: baseline;
  gap: 6px;
  min-width: 0;
}
.ua__name {
  font-weight: var(--ff-fw-medium);
  color: var(--ff-text-primary);
  white-space: nowrap;
}
.ua__code {
  flex: 0 0 auto;
  font-size: var(--ff-fs-caption);
  color: var(--ff-text-tertiary);
}
.ua__desc {
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  font-size: var(--ff-fs-body-sm);
  color: var(--ff-text-secondary);
}
.ua__value {
  color: var(--ff-text-up);
  font-weight: var(--ff-fw-semibold);
  font-size: var(--ff-fs-body-sm);
  white-space: nowrap;
  font-variant-numeric: tabular-nums;
}

@media (max-width: 560px) {
  .ua__row {
    grid-template-columns: 48px minmax(0, 1fr) auto;
  }
  .ua__desc {
    display: none;
  }
}
</style>
