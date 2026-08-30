<script setup>
/**
 * LimitUpLadderView — 连板天地（行情与量化 · 独立模块）
 *
 * 由仪表盘「涨跌全景」中的连板天梯整体提取而来，承载全量视图：
 *   · 连板天梯：晋级股（红涨实色）+ 断板股（灰度虚化，按「昨日高度 + 1」归位）
 *   · 连跌天梯：通达信跌停池，按连续跌停天数分层
 *
 * 仪表盘侧仅在「涨跌全景」顶部保留 4 格涨跌停概览（涨停/跌停/炸板/最高连板），
 * 连板梯队全量渲染只在本模块做一次，规避重复请求与视觉冗余。
 *
 * 自动刷新沿用「行情与量化」分组惯例（与全景行情一致）：
 * 固定 30 秒后台静默轮询，无开关/档位/刷新按钮，仅保留最后更新时间提示。
 */
import { ref, onMounted, onUnmounted } from 'vue'
import AppCard from '../ui/AppCard.vue'
import LimitUpSummaryCard from '../components/review/LimitUpSummaryCard.vue'

// 固定 30 秒，后台静默执行，无任何交互控件
const AUTO_REFRESH_MS = 30 * 1000

// 递增 refreshKey 驱动卡片重新取数（与仪表盘一致的刷新协议）
const refreshKey = ref(0)
const refreshing = ref(false)
const lastUpdated = ref('')
// 数据日期 / 晋级数量（由卡片取数结果带出，展示在卡片头部）
const dataDate = ref('')
const totalUp = ref(0)

let refreshTimer = null

function fmtClock(d = new Date()) {
  const p = (n) => String(n).padStart(2, '0')
  return `${p(d.getHours())}:${p(d.getMinutes())}:${p(d.getSeconds())}`
}

function startAutoRefresh() {
  stopAutoRefresh()
  refreshTimer = setInterval(() => {
    if (document.hidden || refreshing.value) return
    refresh()
  }, AUTO_REFRESH_MS)
}

function stopAutoRefresh() {
  if (refreshTimer) {
    clearInterval(refreshTimer)
    refreshTimer = null
  }
}

function refresh() {
  refreshing.value = true
  refreshKey.value += 1
}

// 卡片取数结束（成功或失败）都落地时间戳，失败时时间不前进，避免「看似刷新成功」
function onLoaded({ ok, date, total }) {
  refreshing.value = false
  if (ok) {
    lastUpdated.value = fmtClock()
    if (date) dataDate.value = date
    if (typeof total === 'number') totalUp.value = total
  }
}

function onVisibilityChange() {
  // 切回页面时立即刷新一次，避免看到陈旧盘面
  if (!document.hidden && !refreshing.value) refresh()
}

onMounted(() => {
  startAutoRefresh()
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

    <!-- 头部直接挂在 AppCard 上：header 展示数据日期，actions 展示最后更新时间 -->
    <AppCard>
      <template #header>
        <span class="ff-limitup-view__head">
          <span class="ff-limitup-view__date">
            数据日期 <b class="ff-num">{{ dataDate || '—' }}</b>
          </span>
          <span class="ff-limitup-view__date">
            晋级 <b class="ff-num">{{ totalUp }}</b> 只
          </span>
        </span>
      </template>
      <template #actions>
        <span class="ff-limitup-view__updated ff-num">
          最后更新 {{ lastUpdated || '--:--:--' }}
        </span>
      </template>
      <LimitUpSummaryCard :refresh-key="refreshKey" @loaded="onLoaded" />
    </AppCard>
  </div>
</template>

<style scoped>
.ff-limitup-view {
  max-width: var(--ff-container-max);
  margin: 0 auto;
}

/* AppCard header slot：数据日期 · 晋级数量 */
.ff-limitup-view__head {
  display: inline-flex;
  align-items: center;
  gap: var(--ff-space-3);
}
.ff-limitup-view__date {
  font-size: var(--ff-fs-caption);
  color: var(--ff-text-tertiary);
  white-space: nowrap;
}
.ff-limitup-view__date b {
  font-weight: var(--ff-fw-semibold);
  color: var(--ff-text-secondary);
  font-variant-numeric: tabular-nums;
}

/* AppCard 右上角 actions slot：最后更新时间提示 */
.ff-limitup-view__updated {
  font-size: var(--ff-fs-caption);
  color: var(--ff-text-tertiary);
  white-space: nowrap;
  font-variant-numeric: tabular-nums;
}
</style>
