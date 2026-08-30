<script setup>
/**
 * LimitUpLadderView — 连板天地（行情与量化 · 独立模块）
 *
 * 由仪表盘「涨跌全景」中的连板天梯整体提取而来，承载全量视图：
 *   · 连板天梯：晋级股（红涨实色）+ 断板股（灰度虚化，按「昨日高度 + 1」归位）
 *   · 连跌天梯：通达信跌停池，按连续跌停天数分层
 *
 * 仪表盘侧改为 LimitUpMiniCard 概览 + 跳转入口，两处共用同一批接口，
 * 但列表渲染只在模块内做一次，避免重复请求与视觉冗余。
 *
 * 自动刷新沿用「行情与量化」分组惯例（与全景行情一致）：
 * 开关 + 30/60s 档位，状态持久化到 localStorage，默认关闭。
 */
import { ref, watch, onMounted, onUnmounted } from 'vue'
import AppCard from '../ui/AppCard.vue'
import AppButton from '../ui/AppButton.vue'
import AppSwitch from '../ui/AppSwitch.vue'
import AppSegmented from '../ui/AppSegmented.vue'
import LimitUpSummaryCard from '../components/review/LimitUpSummaryCard.vue'

const AUTO_REFRESH_KEY = 'finfeed_limitup_autorefresh'
const AUTO_REFRESH_SEC_KEY = 'finfeed_limitup_autorefresh_sec'

const INTERVALS = [
  { value: 30, label: '30s' },
  { value: 60, label: '60s' },
]

// 递增 refreshKey 驱动卡片重新取数（与仪表盘一致的刷新协议）
const refreshKey = ref(0)
const refreshing = ref(false)
const lastUpdated = ref('')

const autoRefresh = ref(localStorage.getItem(AUTO_REFRESH_KEY) === '1')
const autoRefreshInterval = ref(Number(localStorage.getItem(AUTO_REFRESH_SEC_KEY)) || 60)
let refreshTimer = null

function fmtClock(d = new Date()) {
  const p = (n) => String(n).padStart(2, '0')
  return `${p(d.getHours())}:${p(d.getMinutes())}:${p(d.getSeconds())}`
}

function startAutoRefresh() {
  stopAutoRefresh()
  if (!autoRefresh.value) return
  refreshTimer = setInterval(() => {
    if (document.hidden || refreshing.value) return
    refresh()
  }, autoRefreshInterval.value * 1000)
}

function stopAutoRefresh() {
  if (refreshTimer) {
    clearInterval(refreshTimer)
    refreshTimer = null
  }
}

function toggleAutoRefresh(v) {
  autoRefresh.value = v
  localStorage.setItem(AUTO_REFRESH_KEY, v ? '1' : '0')
  if (v) {
    refresh()
    startAutoRefresh()
  } else {
    stopAutoRefresh()
  }
}

function changeRefreshInterval(v) {
  autoRefreshInterval.value = Number(v) || 60
  localStorage.setItem(AUTO_REFRESH_SEC_KEY, String(autoRefreshInterval.value))
  if (autoRefresh.value) startAutoRefresh()
}

function refresh() {
  refreshing.value = true
  refreshKey.value += 1
}

// 卡片取数结束（成功或失败）都落地时间戳，失败时时间不前进，避免「看似刷新成功」
function onLoaded({ ok }) {
  refreshing.value = false
  if (ok) lastUpdated.value = fmtClock()
}

function onVisibilityChange() {
  // 切回页面且开着自动刷新时立即刷新一次，避免看到陈旧盘面
  if (!document.hidden && autoRefresh.value && !refreshing.value) refresh()
}

onMounted(() => {
  if (autoRefresh.value) startAutoRefresh()
  document.addEventListener('visibilitychange', onVisibilityChange)
})

onUnmounted(() => {
  stopAutoRefresh()
  document.removeEventListener('visibilitychange', onVisibilityChange)
})
</script>

<template>
  <div class="ff-page ff-limitup-view">
    <!-- 页面标题按产品要求移除，h1 保留 sr-only 保文档语义 -->
    <h1 class="ff-sr-only">连板天地</h1>

    <header class="ff-limitup-view__toolbar">
      <span class="ff-limitup-view__legend" aria-hidden="true">
        <span><i class="is-up"></i>晋级实色</span>
        <span><i class="is-broken"></i>断板虚化</span>
      </span>

      <span class="ff-limitup-view__spacer"></span>

      <span class="ff-limitup-view__updated ff-num">
        最后更新 {{ lastUpdated || '--:--:--' }}
      </span>

      <span class="ff-limitup-view__sep" aria-hidden="true"></span>

      <span class="ff-limitup-view__lbl">刷新</span>
      <AppSegmented v-model="autoRefreshInterval" :options="INTERVALS" size="sm" />

      <AppSwitch :model-value="autoRefresh" @change="toggleAutoRefresh" />
      <span class="ff-limitup-view__autorefresh-label">自动刷新</span>

      <AppButton
        variant="tonal"
        size="sm"
        icon="refresh"
        :loading="refreshing"
        @click="refresh"
      >
        刷新
      </AppButton>
    </header>

    <AppCard title="连板天梯" subtitle="晋级 / 断板 · 连跌天梯">
      <LimitUpSummaryCard :refresh-key="refreshKey" @loaded="onLoaded" />
    </AppCard>
  </div>
</template>

<style scoped>
.ff-limitup-view {
  max-width: var(--ff-container-max);
  margin: 0 auto;
}

.ff-limitup-view__toolbar {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: var(--ff-space-3);
  padding: var(--ff-space-3) var(--ff-space-4);
  border: 1px solid var(--ff-border);
  border-radius: var(--ff-radius-lg);
  background: var(--ff-bg-surface);
  margin-bottom: var(--ff-space-4);
}

.ff-limitup-view__legend {
  display: inline-flex;
  align-items: center;
  gap: var(--ff-space-3);
  font-size: var(--ff-fs-caption);
  color: var(--ff-text-secondary);
  white-space: nowrap;
}
.ff-limitup-view__legend > span {
  display: inline-flex;
  align-items: center;
  gap: 5px;
}
.ff-limitup-view__legend i {
  display: inline-block;
  width: 8px;
  height: 8px;
  border-radius: 50%;
}
.ff-limitup-view__legend i.is-up {
  background: var(--ff-up);
  box-shadow: 0 0 0 3px var(--ff-up-subtle);
}
.ff-limitup-view__legend i.is-broken {
  background: var(--ff-text-tertiary);
  box-shadow: 0 0 0 3px var(--ff-bg-muted);
}

.ff-limitup-view__spacer {
  flex: 1 1 auto;
  min-width: var(--ff-space-3);
}

.ff-limitup-view__updated {
  font-size: var(--ff-fs-body-sm);
  color: var(--ff-text-tertiary);
  white-space: nowrap;
  font-variant-numeric: tabular-nums;
}

.ff-limitup-view__sep {
  display: inline-block;
  width: 1px;
  height: 14px;
  background: var(--ff-border);
}

.ff-limitup-view__lbl {
  font-size: var(--ff-fs-body-sm);
  font-weight: 600;
  color: var(--ff-text-secondary);
  white-space: nowrap;
}

.ff-limitup-view__autorefresh-label {
  font-size: var(--ff-fs-body-sm);
  color: var(--ff-text-secondary);
  white-space: nowrap;
  user-select: none;
}
</style>
