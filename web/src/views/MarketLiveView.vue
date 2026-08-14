<script setup>
import { ref, computed, onMounted } from 'vue'
import { useMarketSocket } from '../composables/useMarketSocket'
import AppCard from '../ui/AppCard.vue'
import AppIcon from '../ui/AppIcon.vue'
import AppStatus from '../ui/AppStatus.vue'
import AppBadge from '../ui/AppBadge.vue'

const {
  connected,
  connecting,
  data,
  alerts,
  lastUpdate,
  error,
  reconnectAttempts,
} = useMarketSocket({ autoConnect: true })

const sentiment = computed(() => data.value && data.value.sentiment)
const overview = computed(() => data.value && data.value.overview)
const limitUp = computed(() => (data.value ? data.value.limit_up : null))
const tradeDate = computed(() => (data.value ? data.value.trade_date : null))

const lastUpdateText = computed(() => {
  if (!lastUpdate.value) return '—'
  const d = new Date(lastUpdate.value)
  const p = (n) => String(n).padStart(2, '0')
  return `${p(d.getHours())}:${p(d.getMinutes())}:${p(d.getSeconds())}`
})

const connTone = computed(() => (connected.value ? 'success' : connecting.value ? 'warn' : 'danger'))
const connText = computed(() =>
  connected.value ? '已连接' : connecting.value ? '连接中…' : '已断开（自动重连）',
)

const KIND_LABEL = { exception: '异常', timeout: '超时', empty: '空数据', exhausted: '重试耗尽' }
function kindLabel(k) {
  return KIND_LABEL[k] || k
}
function fmtTs(ts) {
  if (!ts) return ''
  const d = new Date(ts * 1000)
  const p = (n) => String(n).padStart(2, '0')
  return `${p(d.getHours())}:${p(d.getMinutes())}:${p(d.getSeconds())}`
}

const metrics = computed(() => {
  const s = sentiment.value
  if (!s) return []
  return [
    { label: '交易日', value: s.trade_date || '—', tone: '' },
    { label: '涨跌家数', value: s.breadth ?? '—', tone: '' },
    { label: '涨停家数', value: s.up_limit ?? '—', tone: 'up' },
    { label: '跌停家数', value: s.down_limit ?? '—', tone: 'down' },
    { label: '情绪指数', value: s.sentiment_index ?? '—', tone: '' },
    { label: '涨停池', value: limitUp.value ?? '—', tone: 'up' },
  ]
})
</script>

<template>
  <div class="ff-page ff-live-view">
    <div class="ff-page__header">
      <div>
        <h1 class="ff-page__title">
          <AppIcon name="activity" size="lg" /> 行情实时推送
        </h1>
        <p class="ff-page__subtitle">通过 WebSocket 接收行情快照与采集告警，断线自动重连</p>
      </div>
      <div class="ff-live-view__conn">
        <AppStatus :text="connText" :tone="connTone" :pulse="connected" />
        <span v-if="reconnectAttempts" class="ff-live-view__retry">第 {{ reconnectAttempts }} 次重连</span>
      </div>
    </div>

    <AppCard class="ff-live-view__status" :no-padding="true">
      <div class="ff-live-view__status-row">
        <span class="ff-live-view__status-item">
          <AppIcon name="clock" size="sm" /> 最近更新 <strong class="ff-num">{{ lastUpdateText }}</strong>
        </span>
        <span class="ff-live-view__status-item">
          交易日 <strong>{{ tradeDate || '—' }}</strong>
        </span>
        <span v-if="error" class="ff-live-view__status-item ff-live-view__status-item--err">
          <AppIcon name="alert-triangle" size="sm" /> {{ error }}
        </span>
      </div>
    </AppCard>

    <div class="ff-live-view__grid">
      <AppCard title="行情快照" subtitle="每 5 秒推送一次">
        <div v-if="metrics.length" class="ff-live-view__metrics">
          <div
            v-for="m in metrics"
            :key="m.label"
            class="ff-live-view__metric"
            :class="m.tone && `ff-t-${m.tone}`"
          >
            <span class="ff-live-view__metric-label">{{ m.label }}</span>
            <span class="ff-live-view__metric-value ff-num">{{ m.value }}</span>
          </div>
        </div>
        <div v-if="overview" class="ff-live-view__ov">
          数据表 <strong>{{ overview.tables }}</strong> · 板块 <strong>{{ overview.boards }}</strong>
        </div>
        <div v-if="!data" class="ff-live-view__empty">
          <AppIcon name="activity" size="lg" />
          <span>等待行情数据推送{{ connected ? '…' : '（未连接）' }}</span>
        </div>
      </AppCard>

      <AppCard title="采集失败告警" subtitle="实时来自后端告警模块">
        <div v-if="alerts.length" class="ff-live-view__alerts">
          <div
            v-for="(a, i) in alerts"
            :key="i"
            class="ff-live-view__alert"
          >
            <AppBadge :text="kindLabel(a.kind)" variant="warn" />
            <span class="ff-live-view__alert-task">{{ a.task }}</span>
            <span class="ff-live-view__alert-time ff-num">{{ fmtTs(a.ts) }}</span>
            <span class="ff-live-view__alert-msg">{{ a.error }}</span>
          </div>
        </div>
        <div v-else class="ff-live-view__empty">
          <AppIcon name="check-circle" size="lg" />
          <span>暂无告警，采集运行正常</span>
        </div>
      </AppCard>
    </div>
  </div>
</template>

<style scoped>
.ff-live-view {
  max-width: var(--ff-container-max);
  margin: 0 auto;
}
.ff-live-view__conn {
  display: flex;
  align-items: center;
  gap: var(--ff-space-3);
}
.ff-live-view__retry {
  font-size: var(--ff-fs-caption);
  color: var(--ff-text-tertiary);
}
.ff-live-view__status {
  margin-bottom: var(--ff-space-4);
}
.ff-live-view__status :deep(.ff-card__body) {
  padding: var(--ff-space-3) var(--ff-space-4);
}
.ff-live-view__status-row {
  display: flex;
  gap: var(--ff-space-5);
  flex-wrap: wrap;
  font-size: var(--ff-fs-sm);
  color: var(--ff-text-secondary);
}
.ff-live-view__status-item strong {
  color: var(--ff-text-primary);
  margin-left: 4px;
}
.ff-live-view__status-item--err {
  color: var(--ff-text-down);
}
.ff-live-view__grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: var(--ff-space-4);
}
@media (max-width: 880px) {
  .ff-live-view__grid {
    grid-template-columns: 1fr;
  }
}
.ff-live-view__metrics {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: var(--ff-space-3);
}
.ff-live-view__metric {
  display: flex;
  flex-direction: column;
  gap: 4px;
  padding: var(--ff-space-3);
  border: 1px solid var(--ff-border);
  border-radius: var(--ff-radius-md);
  background: var(--ff-bg-surface);
}
.ff-live-view__metric-label {
  font-size: var(--ff-fs-caption);
  color: var(--ff-text-tertiary);
}
.ff-live-view__metric-value {
  font-size: var(--ff-fs-lg);
  font-weight: var(--ff-fw-semibold);
  color: var(--ff-text-primary);
}
.ff-live-view__ov {
  margin-top: var(--ff-space-3);
  font-size: var(--ff-fs-sm);
  color: var(--ff-text-secondary);
}
.ff-live-view__ov strong {
  color: var(--ff-text-primary);
}
.ff-live-view__alerts {
  display: flex;
  flex-direction: column;
  gap: var(--ff-space-2);
  max-height: 360px;
  overflow-y: auto;
}
.ff-live-view__alert {
  display: flex;
  align-items: center;
  gap: var(--ff-space-2);
  padding: var(--ff-space-2) var(--ff-space-3);
  border-radius: var(--ff-radius-sm);
  background: var(--ff-bg-subtle);
  font-size: var(--ff-fs-sm);
}
.ff-live-view__alert-task {
  font-weight: var(--ff-fw-medium);
  color: var(--ff-text-primary);
}
.ff-live-view__alert-time {
  color: var(--ff-text-tertiary);
  font-size: var(--ff-fs-xs);
}
.ff-live-view__alert-msg {
  flex: 1;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  color: var(--ff-text-secondary);
}
.ff-live-view__empty {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: var(--ff-space-2);
  padding: var(--ff-space-6) 0;
  color: var(--ff-text-tertiary);
  font-size: var(--ff-fs-sm);
}
</style>
