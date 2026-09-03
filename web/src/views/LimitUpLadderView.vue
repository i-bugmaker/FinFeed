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
 * 仅交易时段（工作日 9:15-11:30 / 13:00-15:00）固定 30 秒后台静默轮询，
 * 收盘后 / 午休 / 休市日不再发起取数请求，避免无意义的后台刷新与页面重渲染；
 * 无开关/档位/刷新按钮，仅保留最后更新时间提示。
 */
import { ref, onMounted, onUnmounted, nextTick, watch } from 'vue'
import AppCard from '../ui/AppCard.vue'
import AppButton from '../ui/AppButton.vue'
import AppIcon from '../ui/AppIcon.vue'
import LimitUpSummaryCard from '../components/review/LimitUpSummaryCard.vue'
import LimitUpAiDialog from '../components/review/LimitUpAiDialog.vue'
import { useScrollRestore } from '../composables/useScrollRestore'
import { api } from '../api/client'

// 固定 30 秒，后台静默执行，无任何交互控件
const AUTO_REFRESH_MS = 30 * 1000

// 交易时段判断（与后端 finfeed.sector_minute.store.is_trading_time 口径一致）：
// 工作日 9:15-11:30 / 13:00-15:00 视为交易时段，其余（盘前/午休/收盘后/休市）不自动取数
function isTradingTime(d = new Date()) {
  const day = d.getDay()
  if (day === 0 || day === 6) return false
  const sec = d.getHours() * 3600 + d.getMinutes() * 60 + d.getSeconds()
  return (9 * 3600 + 15 * 60 <= sec && sec <= 11 * 3600 + 30 * 60) ||
    (13 * 3600 <= sec && sec <= 15 * 3600)
}

// 递增 refreshKey 驱动卡片重新取数（与仪表盘一致的刷新协议）
const refreshKey = ref(0)
const refreshing = ref(false)
const lastUpdated = ref('')
// 数据日期 / 晋级数量（由卡片取数结果带出，展示在卡片头部）
const dataDate = ref('')
const totalUp = ref(0)

// AI 分析弹窗：调用系统已配置的大模型解读当日涨跌停结构
const showAi = ref(false)
// 选中的历史归档报告（非空时弹窗进入只读展示模式）
const archivedReport = ref(null)
// 历史分析下拉
const historyOpen = ref(false)
const historyItems = ref([])
const historyLoading = ref(false)
const historyError = ref('')
const historyTrigger = ref(null)
const historyMenu = ref(null)

let refreshTimer = null

// 实时 AI 分析：清空历史归档，走 live 流程
function openLive() {
  archivedReport.value = null
  showAi.value = true
}

// 打开历史分析下拉并加载归档列表
async function toggleHistory() {
  if (historyOpen.value) {
    historyOpen.value = false
    return
  }
  historyOpen.value = true
  historyLoading.value = true
  historyError.value = ''
  try {
    const res = await api.insightHistory(20)
    historyItems.value = (res && res.items) || []
    if (!historyItems.value.length) historyError.value = '暂无历史分析记录'
  } catch {
    historyItems.value = []
    historyError.value = '历史记录加载失败'
  } finally {
    historyLoading.value = false
  }
}

// 从历史列表选中一份归档，读取全文并进入只读展示
async function pickHistory(item) {
  historyOpen.value = false
  try {
    const res = await api.insightReport(item.id)
    const rep = (res && res.report) || {}
    archivedReport.value = {
      id: item.id,
      title: rep.title || item.title || '',
      content: rep.content || '',
      model: rep.model || '',
      elapsed: rep.elapsed || 0,
      stats: rep.stats || null,
    }
    showAi.value = true
  } catch {
    archivedReport.value = null
  }
}

function positionHistoryMenu() {
  if (!historyTrigger.value || !historyMenu.value) return
  const rect = historyTrigger.value.getBoundingClientRect()
  const menu = historyMenu.value
  const vw = document.documentElement.clientWidth
  const margin = 8
  const menuW = Math.min(320, vw - margin * 2)
  menu.style.width = `${menuW}px`
  menu.style.top = `${rect.bottom + 6}px`
  menu.style.left = `${Math.min(Math.max(margin, rect.left), vw - margin - menuW)}px`
}

function onClickOutside(e) {
  if (
    historyOpen.value &&
    !historyTrigger.value?.contains(e.target) &&
    !historyMenu.value?.contains(e.target)
  ) {
    historyOpen.value = false
  }
}

// 历史下拉打开/关闭时绑定定位与点击外部收起
watch(historyOpen, (v) => {
  if (v) {
    nextTick(positionHistoryMenu)
    document.addEventListener('click', onClickOutside, true)
    window.addEventListener('resize', positionHistoryMenu)
  } else {
    document.removeEventListener('click', onClickOutside, true)
    window.removeEventListener('resize', positionHistoryMenu)
  }
})

// 滚动位置记忆：本模块为长列表（连板梯队 + 连跌梯队全量渲染），点击个股跳转他页后
// 返回时需回到原浏览位置。默认以路由 path 为 key，离开前留存、挂载后恢复。
useScrollRestore()

function fmtClock(d = new Date()) {
  const p = (n) => String(n).padStart(2, '0')
  return `${p(d.getHours())}:${p(d.getMinutes())}:${p(d.getSeconds())}`
}

function startAutoRefresh() {
  stopAutoRefresh()
  refreshTimer = setInterval(() => {
    // 仅交易时段自动取数；收盘 / 午休 / 休市时静默跳过，避免无意义的后台刷新与重渲染
    if (!isTradingTime()) return
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
  document.removeEventListener('click', onClickOutside, true)
  window.removeEventListener('resize', positionHistoryMenu)
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
        <AppButton
          ref="historyTrigger"
          size="sm"
          variant="ghost"
          icon="clock"
          title="查看历史 AI 分析结果"
          @click="toggleHistory"
        >
          历史
        </AppButton>
        <AppButton
          size="sm"
          variant="tonal"
          icon="sparkles"
          title="用系统配置的大模型分析当日涨跌停结构与潜在行情"
          @click="openLive"
        >
          AI 分析
        </AppButton>
        <span class="ff-limitup-view__updated ff-num">
          最后更新 {{ lastUpdated || '--:--:--' }}
        </span>
      </template>
      <LimitUpSummaryCard :refresh-key="refreshKey" @loaded="onLoaded" />
    </AppCard>

    <!-- 历史 AI 分析下拉：读取服务端归档，点击项进入只读展示 -->
    <Teleport to="body">
      <div
        v-show="historyOpen"
        ref="historyMenu"
        class="ff-history ff-menu"
      >
        <div class="ff-history__head">
          <AppIcon name="clock" size="sm" />
          <span>历史 AI 分析</span>
        </div>
        <ul v-if="historyItems.length" class="ff-menu__items">
          <li
            v-for="item in historyItems"
            :key="item.id"
            class="ff-menu__item"
            @click="pickHistory(item)"
          >
            <span class="ff-menu__item-text ff-history__item">
              <span class="ff-history__title">{{ item.title }}</span>
              <span class="ff-history__meta">
                <span v-if="item.model">{{ item.model }}</span>
                <span class="ff-num">{{ item.created_at }}</span>
              </span>
            </span>
          </li>
        </ul>
        <div v-else class="ff-empty ff-empty--compact">
          {{ historyLoading ? '加载中…' : (historyError || '暂无历史分析记录') }}
        </div>
      </div>
    </Teleport>

    <!-- AI 分析弹窗：常驻挂载，关闭后仍保留任务进度与结果；传入 archived 时只读展示历史 -->
    <LimitUpAiDialog v-model="showAi" :date="dataDate" :archived="archivedReport" />
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

/* 窄屏：卡片头 meta 与 actions 允许换行，避免挤压溢出 */
@media (max-width: 768px) {
  .ff-limitup-view :deep(.ff-card__header) {
    flex-wrap: wrap;
    row-gap: var(--ff-space-1);
    padding: var(--ff-space-3) var(--ff-space-4);
  }
  .ff-limitup-view__head {
    gap: var(--ff-space-2);
  }
}

/* 历史 AI 分析下拉（Teleport 到 body，用 fixed 定位覆盖全局 .ff-menu 的 absolute/min-width） */
.ff-history {
  position: fixed;
  min-width: 320px;
  max-height: 340px;
  overflow-y: auto;
}
.ff-history__head {
  display: flex;
  align-items: center;
  gap: var(--ff-space-2);
  padding: 6px 10px 8px;
  font-size: var(--ff-fs-caption);
  color: var(--ff-text-tertiary);
}
.ff-history__item {
  display: flex;
  flex-direction: column;
  gap: 2px;
  padding: 2px 0;
}
.ff-history__title {
  font-size: var(--ff-fs-body-sm);
  color: var(--ff-text-secondary);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.ff-history__meta {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  font-size: var(--ff-fs-overline);
  color: var(--ff-text-tertiary);
}
</style>
