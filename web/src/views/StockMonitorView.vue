<script setup>
/**
 * 股票监控 — 导入管理 / 舆情聚合 / AI 智能分析
 *
 * 数据流：
 *  - 监控列表与分组舆情来自 /api/stock-monitor/feed（系统内 news 匹配 + 系统外东财缓存）
 *  - 实时增量走 SSE /api/stock-monitor/feed/stream（事件 feed），60s 轮询兜底
 *  - 离线补全：localStorage 记忆 last_seen_ts，重开页面时全量拉取并按 last_seen 本地高亮遗漏消息
 *  - AI 分析提交后台任务后轮询 /analyze/task/{id}，结果持久化并按股票关联
 */
import { ref, reactive, computed, onMounted, onUnmounted, nextTick } from 'vue'
import { stockMonitorApi, subscribeStockFeed } from '../api/stockMonitor'
import AppIcon from '../ui/AppIcon.vue'
import AppButton from '../ui/AppButton.vue'
import AppInput from '../ui/AppInput.vue'
import AppModal from '../ui/AppModal.vue'
import AppTabs from '../ui/AppTabs.vue'
import AppSkeleton from '../ui/AppSkeleton.vue'
import EmptyState from '../components/EmptyState.vue'
import MarkdownView from '../components/ai/MarkdownView.vue'

// ---------------------------------------------------------------------------
// 常量
// ---------------------------------------------------------------------------
const LAST_SEEN_KEY = 'finfeed_stock_monitor_last_seen'

const CHANNEL_META = {
  flash: { label: '快讯', icon: 'zap' },
  article: { label: '财经', icon: 'newspaper' },
  forum: { label: '舆情', icon: 'chatter' },
  announcement: { label: '公告', icon: 'bookmark' },
  report: { label: '研报', icon: 'doc' },
  news: { label: '资讯', icon: 'list' },
}

// 重大公告置顶、其余按时间倒序（与后端 _feed_sort_key 保持一致）
function feedSortKey(it) {
  return (it.importance || 0) >= 0.7 ? 0 : 1
}

const IMPORT_TABS = [
  { value: 'manual', label: '手动输入' },
  { value: 'text', label: '文本批量' },
  { value: 'image', label: '截图导入' },
]

// ---------------------------------------------------------------------------
// 监控列表
// ---------------------------------------------------------------------------
const stocks = ref([])
const stocksLoading = ref(false)
const selectedCode = ref('')
const selectedStock = computed(() => stocks.value.find((s) => s.code === selectedCode.value) || null)

async function loadStocks(selectFirst = false) {
  stocksLoading.value = true
  try {
    const data = await stockMonitorApi.listStocks()
    stocks.value = data.stocks || []
    if (selectFirst && !selectedCode.value && stocks.value.length) {
      selectStock(stocks.value[0].code)
    }
  } finally {
    stocksLoading.value = false
  }
}

function selectStock(code) {
  selectedCode.value = code
  loadLatestAnalysis(code)
}

// ---------------------------------------------------------------------------
// 舆情聚合
// ---------------------------------------------------------------------------
const groups = ref({}) // code -> { items: [], counts: {} }
const feedLoading = ref(false)
const catchUpCount = ref(0) // 离线期间补全的消息数
const live = ref(false)
const liveFlash = ref(0) // 本页打开期间实时新消息数
let lastSeenTs = 0
const seenKeys = new Set()

function itemKey(it, code) {
  return `${code}|${it.source_type}|${it.ref_id ?? ''}|${it.dedup_key ?? ''}|${it.title}`
}

function ingestItems(items, { prepend = false, catchUp = false } = {}) {
  let added = 0
  for (const raw of items) {
    const codes = raw.code ? [raw.code] : raw.codes || []
    for (const code of codes) {
      const g = groups.value[code]
      if (!g) continue
      const item = { ...raw, _catchup: catchUp }
      const key = itemKey(item, code)
      if (seenKeys.has(key)) continue
      seenKeys.add(key)
      if (prepend) g.items.unshift(item)
      else g.items.push(item)
      g.items.sort((a, b) => {
        const ga = feedSortKey(a)
        const gb = feedSortKey(b)
        if (ga !== gb) return ga - gb
        return (b.publish_ts || 0) - (a.publish_ts || 0)
      })
      g.counts = {
        ...g.counts,
        total: g.counts.total + 1,
        internal: g.counts.internal + (item.source_type === 'internal' ? 1 : 0),
        external: g.counts.external + (item.source_type === 'external' ? 1 : 0),
        announcement: g.counts.announcement + (item.channel === 'announcement' ? 1 : 0),
        report: g.counts.report + (item.channel === 'report' ? 1 : 0),
        major: g.counts.major + (item.major ? 1 : 0),
      }
      added += 1
    }
  }
  return added
}

async function loadFeed({ withCatchUp = false } = {}) {
  feedLoading.value = true
  try {
    const since = withCatchUp ? Number(localStorage.getItem(LAST_SEEN_KEY) || 0) : 0
    // 始终全量拉取：since_ts 传给后端会被过滤成增量，导致进入页面只剩遗漏消息（常为空），
    // 需手动刷新才显示全量。last_seen 只用于本地标记「离线补全」高亮。
    const data = await stockMonitorApi.feed({ since_ts: 0, limit: 80 })
    const nextGroups = {}
    let catchUp = 0
    for (const [code, g] of Object.entries(data.groups || {})) {
      const items = (g.items || []).map((it) => ({
        ...it,
        _catchup: withCatchUp && (it.publish_ts || 0) > since,
      }))
      if (withCatchUp) catchUp += items.filter((i) => i._catchup).length
      nextGroups[code] = { stock: g.stock, items, counts: g.counts }
      for (const it of items) seenKeys.add(itemKey(it, code))
    }
    groups.value = nextGroups
    if (withCatchUp && since > 0) catchUpCount.value = catchUp
    lastSeenTs = data.server_ts || Math.floor(Date.now() / 1000)
    localStorage.setItem(LAST_SEEN_KEY, String(lastSeenTs))
    ensureSelected()
  } finally {
    feedLoading.value = false
  }
}

function ensureSelected() {
  const codes = Object.keys(groups.value)
  if (codes.length && (!selectedCode.value || !groups.value[selectedCode.value])) {
    // 默认选中消息最多的股票
    const best = codes.sort((a, b) => (groups.value[b].counts?.total || 0) - (groups.value[a].counts?.total || 0))[0]
    selectStock(best)
  }
}

const activeGroup = computed(() => groups.value[selectedCode.value] || null)
const activeItems = computed(() => activeGroup.value?.items || [])

// ---------------------------------------------------------------------------
// SSE 实时推送 + 轮询兜底
// ---------------------------------------------------------------------------
let unsubFeed = null
let pollTimer = null

function connectFeed() {
  const codes = stocks.value.map((s) => s.code)
  unsubFeed = subscribeStockFeed(codes, {
    onConnected: () => {
      live.value = true
    },
    onItems: (items) => {
      const marked = items.map((it) => ({ ...it, _realtime: true }))
      const added = ingestItems(marked, { prepend: true })
      if (added > 0) {
        liveFlash.value += added
        ensureSelected()
      }
    },
    onError: () => {
      live.value = false
    },
  })
}

// ---------------------------------------------------------------------------
// 导入（手动 / 文本批量 / 截图）
// ---------------------------------------------------------------------------
const importModal = reactive({
  open: false,
  tab: 'manual',
  text: '',
  file: null,
  filePreview: '',
  importing: false,
  result: null,
  error: '',
})

function openImport(tab = 'manual') {
  importModal.open = true
  importModal.tab = tab
  importModal.text = ''
  importModal.file = null
  importModal.filePreview = ''
  importModal.importing = false
  importModal.result = null
  importModal.error = ''
  suggestState.open = false
  suggestState.items = []
}

// 手动输入智能联想（参照多标的分时对比搜索栏：即时匹配 + 下拉候选）
const suggestState = reactive({
  items: [],
  open: false,
  active: -1,
  timer: null,
  seq: 0,
})

function onManualInput() {
  clearTimeout(suggestState.timer)
  const q = importModal.text.trim()
  if (!q) {
    suggestState.items = []
    suggestState.open = false
    suggestState.active = -1
    return
  }
  suggestState.timer = setTimeout(async () => {
    const seq = ++suggestState.seq
    try {
      const items = await stockMonitorApi.suggest(q, 8)
      if (seq !== suggestState.seq) return // 丢弃过期响应
      suggestState.items = items
      suggestState.open = items.length > 0
      suggestState.active = -1
    } catch { /* 忽略联想失败 */ }
  }, 160)
}

function pickSuggestion(item) {
  suggestState.open = false
  importModal.text = item.code
  submitImport()
}

function closeSuggest() {
  setTimeout(() => {
    suggestState.open = false
  }, 150)
}

function onPickFile(e) {
  const file = e.target.files?.[0]
  if (file) setImportImage(file)
}

function setImportImage(file) {
  if (!file || !/^image\//.test(file.type)) return
  if (importModal.filePreview) URL.revokeObjectURL(importModal.filePreview)
  importModal.file = file
  importModal.filePreview = URL.createObjectURL(file)
}

function onDropFile(e) {
  e.preventDefault()
  const file = e.dataTransfer?.files?.[0]
  if (file) setImportImage(file)
}

async function submitImport() {
  importModal.importing = true
  importModal.error = ''
  importModal.result = null
  try {
    let res
    if (importModal.tab === 'image') {
      if (!importModal.file) {
        importModal.error = '请先选择截图文件'
        return
      }
      res = await stockMonitorApi.importImage(importModal.file)
    } else {
      if (!importModal.text.trim()) {
        importModal.error = '请输入股票代码'
        return
      }
      res = await stockMonitorApi.importText(importModal.text)
    }
    importModal.result = res
    await loadStocks()
    await loadFeed()
    connectFeedResubscribe()
  } catch (e) {
    importModal.error = e?.message || '导入失败，请稍后重试'
  } finally {
    importModal.importing = false
  }
}

// ---------------------------------------------------------------------------
// 编辑 / 删除
// ---------------------------------------------------------------------------
const editModal = reactive({ open: false, code: '', name: '', note: '', saving: false })

function openEdit(stock) {
  editModal.code = stock.code
  editModal.name = stock.name || stock.code
  editModal.note = stock.note || ''
  editModal.open = true
}

async function saveNote() {
  editModal.saving = true
  try {
    await stockMonitorApi.updateNote(editModal.code, editModal.note)
    const s = stocks.value.find((x) => x.code === editModal.code)
    if (s) s.note = editModal.note
    editModal.open = false
  } finally {
    editModal.saving = false
  }
}

async function removeStock(code) {
  // 删除不可恢复（监控及其聚合舆情一并消失），必须二次确认
  const name = stocks.value.find((s) => s.code === code)?.name || code
  if (!window.confirm(`确认删除对「${name}（${code}）」的监控吗？该操作不可恢复。`)) return
  try {
    await stockMonitorApi.deleteStock(code)
    delete groups.value[code]
    stocks.value = stocks.value.filter((s) => s.code !== code)
    if (selectedCode.value === code) {
      selectedCode.value = ''
      ensureSelected()
    }
    connectFeedResubscribe()
  } catch (e) {
    console.error(e)
    window.alert('删除失败：' + (e.message || e))
  }
}

// ---------------------------------------------------------------------------
// AI 智能分析
// ---------------------------------------------------------------------------
const analysis = reactive({
  running: false,
  row: null, // 当前展示的分析结果
  history: [],
  showHistory: false,
  error: '',
  pollTimer: null,
})

async function loadLatestAnalysis(code) {
  analysis.row = null
  analysis.error = ''
  analysis.history = []
  analysis.showHistory = false
  try {
    const data = await stockMonitorApi.analysisLatest(code)
    if (data.analysis) analysis.row = data.analysis
  } catch { /* ignore */ }
}

async function runAnalysis() {
  if (!selectedCode.value || analysis.running) return
  analysis.running = true
  analysis.error = ''
  try {
    const res = await stockMonitorApi.analyze(selectedCode.value)
    pollAnalysis(res.analysis_id)
  } catch (e) {
    analysis.error = e?.message || '提交分析失败'
    analysis.running = false
  }
}

function pollAnalysis(id) {
  clearInterval(analysis.pollTimer)
  analysis.pollTimer = setInterval(async () => {
    try {
      const row = await stockMonitorApi.analysisTask(id)
      if (row.status === 'done') {
        clearInterval(analysis.pollTimer)
        analysis.running = false
        analysis.row = row
      } else if (row.status === 'failed') {
        clearInterval(analysis.pollTimer)
        analysis.running = false
        analysis.error = row.error || '分析失败'
      }
    } catch {
      clearInterval(analysis.pollTimer)
      analysis.running = false
      analysis.error = '查询分析任务失败'
    }
  }, 2500)
}

async function toggleHistory() {
  analysis.showHistory = !analysis.showHistory
  if (analysis.showHistory && selectedCode.value) {
    const data = await stockMonitorApi.analysisHistory(selectedCode.value, 10)
    analysis.history = data.analyses || []
  }
}

function viewHistoryRow(row) {
  analysis.row = row
  analysis.showHistory = false
}

// ---------------------------------------------------------------------------
// 手动刷新外部消息
// ---------------------------------------------------------------------------
const refreshing = ref(false)
async function manualRefresh() {
  refreshing.value = true
  try {
    await stockMonitorApi.refresh()
    await loadFeed()
  } finally {
    refreshing.value = false
  }
}

// ---------------------------------------------------------------------------
// 工具
// ---------------------------------------------------------------------------
function channelLabel(ch) {
  return CHANNEL_META[ch] || { label: ch || '消息', icon: 'list' }
}

function sentimentClass(s) {
  if (s === 'positive' || s === '利好') return 'up'
  if (s === 'negative' || s === '利空') return 'down'
  return 'neu'
}

function sentimentText(s) {
  if (s === 'positive') return '利多'
  if (s === 'negative') return '利空'
  return s === '利好' || s === '利空' ? s : '中性'
}

function fmtCount(n) {
  return n > 99 ? '99+' : String(n || 0)
}

function connectFeedResubscribe() {
  if (unsubFeed) unsubFeed()
  connectFeed()
}

// ---------------------------------------------------------------------------
// 生命周期
// ---------------------------------------------------------------------------
onMounted(async () => {
  await loadStocks(true)
  await loadFeed({ withCatchUp: true })
  await nextTick()
  connectFeed()
  pollTimer = setInterval(() => loadFeed(), 60000) // 轮询兜底（外部公告等非 SSE 覆盖路径）
})

onUnmounted(() => {
  if (unsubFeed) unsubFeed()
  if (pollTimer) clearInterval(pollTimer)
  clearInterval(analysis.pollTimer)
})
</script>

<template>
  <div class="ff-page ff-sm-view">
    <!-- 双栏 grid 布局，标题用视觉隐藏 h1 保文档语义 -->
    <h1 class="ff-sr-only">股票监控</h1>

    <!-- ============ 左列：监控列表 ============ -->
    <aside class="ff-sm-view__side">
      <div class="ff-sm-side">
        <header class="ff-sm-side__head">
          <h2 class="ff-sm-side__title">
            <AppIcon name="monitor" size="sm" />
            监控列表
            <span class="ff-sm-side__count">{{ stocks.length }}</span>
          </h2>
          <div class="ff-sm-side__actions">
            <AppButton size="sm" variant="ghost" icon="plus" @click="openImport('manual')">导入</AppButton>
          </div>
        </header>

        <div v-if="stocksLoading" class="ff-sm-side__list">
          <AppSkeleton variant="text" :lines="6" />
        </div>

        <div v-else-if="stocks.length === 0" class="ff-sm-side__empty">
          <EmptyState icon="monitor" text="暂无监控股票">
            <template #description>
              <span class="ff-sm-muted">支持手动输入、文本批量粘贴与截图识别三种导入方式</span>
            </template>
            <template #action>
              <AppButton size="sm" icon="plus" @click="openImport('manual')">导入股票</AppButton>
            </template>
          </EmptyState>
        </div>

        <div v-else class="ff-sm-side__list">
          <div
            v-for="s in stocks"
            :key="s.code"
            class="ff-sm-stock"
            :class="{ 'is-active': s.code === selectedCode }"
            @click="selectStock(s.code)"
          >
            <div class="ff-sm-stock__main">
              <div class="ff-sm-stock__name">
                <span class="ff-sm-stock__title">{{ s.name || s.code }}</span>
                <span class="ff-sm-stock__board">{{ s.board || '—' }}</span>
              </div>
              <div class="ff-sm-stock__meta">
                <span class="ff-sm-stock__code">{{ s.code }}</span>
                <span
                  v-if="groups[s.code]"
                  class="ff-sm-stock__badge"
                  title="系统内/系统外消息数"
                >
                  {{ fmtCount(groups[s.code].counts?.internal) }}/{{ fmtCount(groups[s.code].counts?.external) }}
                </span>
                <span v-if="s.note" class="ff-sm-stock__note-icon" title="有备注">
                  <AppIcon name="bookmark" size="xs" />
                </span>
              </div>
            </div>
            <div class="ff-sm-stock__ops" @click.stop>
              <button class="ff-sm-iconbtn" title="编辑备注" @click="openEdit(s)">
                <AppIcon name="edit" size="xs" />
              </button>
              <button class="ff-sm-iconbtn ff-sm-iconbtn--danger" title="删除监控" @click="removeStock(s.code)">
                <AppIcon name="trash" size="xs" />
              </button>
            </div>
          </div>
        </div>
      </div>
    </aside>

    <!-- ============ 右列：舆情聚合 + AI 分析 ============ -->
    <section class="ff-sm-view__main">
      <template v-if="!activeGroup">
        <EmptyState
          :icon="stocks.length ? 'chatter' : 'monitor'"
          :text="stocks.length ? '正在加载舆情数据…' : '导入监控股票后，这里将按股票聚合展示舆情与 AI 分析'"
        />
      </template>

      <template v-else>
        <!-- 详情头部 -->
        <header class="ff-sm-detail__head">
          <div class="ff-sm-detail__id">
            <h2 class="ff-sm-detail__name">{{ activeGroup.stock.name || selectedCode }}</h2>
            <span class="ff-sm-detail__code">{{ selectedCode }}</span>
            <span v-if="activeGroup.stock.board" class="ff-sm-stock__board">{{ activeGroup.stock.board }}</span>
          </div>
          <div class="ff-sm-detail__tools">
            <span class="ff-sm-live" :class="{ 'is-live': live }">
              <AppIcon name="dot" size="xs" />
              {{ live ? '实时推送中' : '实时连接断开' }}
            </span>
            <span v-if="liveFlash > 0" class="ff-sm-flash" title="本页打开期间实时新增">
              +{{ liveFlash }} 新消息
            </span>
            <AppButton size="sm" variant="ghost" icon="refresh" :loading="refreshing" @click="manualRefresh">
              刷新
            </AppButton>
            <AppButton size="sm" icon="sparkles" :loading="analysis.running" @click="runAnalysis">
              {{ analysis.running ? '分析中…' : 'AI 分析' }}
            </AppButton>
          </div>
        </header>

        <div v-if="catchUpCount > 0" class="ff-sm-catchup">
          <AppIcon name="clock" size="xs" />
          已补全离线期间遗漏的 {{ catchUpCount }} 条消息（高亮显示）
        </div>

        <div v-if="activeGroup.stock.note" class="ff-sm-note">
          <AppIcon name="bookmark" size="xs" />
          {{ activeGroup.stock.note }}
        </div>

        <!-- 统计条 -->
        <div class="ff-sm-stats">
          <span class="ff-sm-stat"><b>{{ fmtCount(activeGroup.counts?.total) }}</b> 舆情总数</span>
          <span class="ff-sm-stat"><b class="c-internal">{{ fmtCount(activeGroup.counts?.internal) }}</b> 系统内</span>
          <span class="ff-sm-stat"><b class="c-external">{{ fmtCount(activeGroup.counts?.external) }}</b> 系统外</span>
          <span class="ff-sm-stat"><b class="c-ann">{{ fmtCount(activeGroup.counts?.announcement) }}</b> 公告</span>
          <span class="ff-sm-stat"><b>{{ fmtCount(activeGroup.counts?.report) }}</b> 研报</span>
          <span v-if="activeGroup.counts?.major" class="ff-sm-stat"><b class="c-major">{{ fmtCount(activeGroup.counts?.major) }}</b> 重大</span>
        </div>

        <!-- AI 分析面板 -->
        <div class="ff-sm-ai" :class="{ 'is-open': analysis.row || analysis.running || analysis.error }">
          <header class="ff-sm-ai__head">
            <h3 class="ff-sm-ai__title">
              <AppIcon name="sparkles" size="sm" />
              AI 智能分析
            </h3>
            <div class="ff-sm-ai__ops">
              <AppButton v-if="analysis.row" size="xs" variant="ghost" @click.stop="toggleHistory">
                {{ analysis.showHistory ? '收起历史' : '历史分析' }}
              </AppButton>
            </div>
          </header>

          <div v-if="analysis.running" class="ff-sm-ai__running">
            <AppSkeleton variant="text" :lines="4" />
            <span class="ff-sm-muted">正在基于该股票聚合舆情进行消息解读、情绪倾向与影响评估…</span>
          </div>

          <div v-else-if="analysis.error" class="ff-sm-ai__error">
            <AppIcon name="info" size="xs" />
            {{ analysis.error }}
          </div>

          <div v-else-if="analysis.row" class="ff-sm-ai__body">
            <div class="ff-sm-ai__chips">
              <span class="ff-sm-chip" :class="`is-${sentimentClass(analysis.row.sentiment)}`">
                情绪：{{ sentimentText(analysis.row.sentiment) }}
              </span>
              <span v-if="analysis.row.impact" class="ff-sm-chip is-impact">
                影响评估：{{ analysis.row.impact }}
              </span>
              <span v-if="analysis.row.model" class="ff-sm-chip is-model">{{ analysis.row.model }}</span>
              <span class="ff-sm-chip is-time">{{ (analysis.row.created_at || '').replace('T', ' ') }}</span>
            </div>
            <MarkdownView :content="analysis.row.content" />
          </div>

          <div v-else class="ff-sm-ai__hint">
            <AppIcon name="info" size="xs" />
            点击右上角「AI 分析」，对当前股票的聚合舆情生成消息解读 / 情绪倾向 / 影响评估。
          </div>

          <div v-if="analysis.showHistory" class="ff-sm-ai__history">
            <button
              v-for="h in analysis.history"
              :key="h.id"
              class="ff-sm-ai__hrow"
              :class="{ 'is-current': h.id === analysis.row?.id }"
              @click="viewHistoryRow(h)"
            >
              <span class="ff-sm-chip" :class="`is-${sentimentClass(h.sentiment)}`">{{ sentimentText(h.sentiment) || '—' }}</span>
              <span class="ff-sm-ai__htime">{{ (h.created_at || '').replace('T', ' ') }}</span>
              <span class="ff-sm-ai__hmsgs">{{ h.msg_count }} 条消息</span>
              <span v-if="h.status === 'failed'" class="ff-sm-ai__hfail">失败</span>
            </button>
          </div>
        </div>

        <!-- 舆情消息流 -->
        <div class="ff-sm-feed">
          <h3 class="ff-sm-feed__title">
            <AppIcon name="chatter" size="sm" />
            舆情聚合
            <span class="ff-sm-muted">（系统内 + 系统外，按时间倒序）</span>
          </h3>

          <div v-if="feedLoading && activeItems.length === 0" class="ff-sm-feed__list">
            <AppSkeleton variant="text" :lines="8" />
          </div>

          <div v-else-if="activeItems.length === 0" class="ff-sm-feed__list">
            <EmptyState icon="inbox" text="暂无舆情消息" />
          </div>

          <div v-else class="ff-sm-feed__list">
            <article
              v-for="(it, idx) in activeItems"
              :key="itemKey(it, selectedCode) + idx"
              class="ff-sm-item"
              :class="{ 'is-catchup': it._catchup, 'is-new': it._realtime, 'is-major': it.major }"
            >
              <div class="ff-sm-item__badges">
                <span
                  class="ff-sm-item__src"
                  :class="it.source_type === 'internal' ? 'is-internal' : 'is-external'"
                >
                  {{ it.source_type === 'internal' ? '系统内' : '系统外' }}
                </span>
                <span class="ff-sm-item__ch">
                  <AppIcon :name="channelLabel(it.channel).icon" size="xs" />
                  {{ channelLabel(it.channel).label }}
                </span>
                <span v-if="it.channel === 'announcement' && it.major" class="ff-sm-chip is-major-tag">重大</span>
                <span v-if="it.ann_type" class="ff-sm-chip is-ann-type">{{ it.ann_type }}</span>
                <span v-if="it.sentiment && it.sentiment !== 'neutral'" class="ff-sm-chip" :class="`is-${sentimentClass(it.sentiment)}`">
                  {{ sentimentText(it.sentiment) }}
                </span>
              </div>
              <div class="ff-sm-item__body">
                <a v-if="it.url" class="ff-sm-item__title" :href="it.url" target="_blank" rel="noopener noreferrer">{{ it.title }}</a>
                <span v-else class="ff-sm-item__title">{{ it.title }}</span>
                <p v-if="it.summary" class="ff-sm-item__summary">{{ it.summary }}</p>
                <div class="ff-sm-item__meta">
                  <span>{{ it.source || '未知来源' }}</span>
                  <span>{{ it.publish_time || '' }}</span>
                  <span v-if="it.importance >= 0.7" class="ff-sm-item__imp">高重要性</span>
                  <span v-if="it._catchup" class="ff-sm-item__catchup-tag">离线补全</span>
                </div>
              </div>
            </article>
          </div>
        </div>
      </template>
    </section>

    <!-- ============ 导入弹窗 ============ -->
    <AppModal
      v-model="importModal.open"
      title="导入监控股票"
      size="md"
      :ok-text="importModal.tab === 'image' ? '识别并导入' : '校验并导入'"
      :loading="importModal.importing"
      @ok="submitImport"
    >
      <AppTabs v-model="importModal.tab" :items="IMPORT_TABS" />

      <div v-if="importModal.tab === 'manual'" class="ff-sm-import__pane">
        <div class="ff-sm-suggest">
          <AppInput
            v-model="importModal.text"
            placeholder="输入代码 / 名称 / 拼音，如 600519、茅台、gzmt"
            clearable
            @input="onManualInput"
            @blur="closeSuggest"
          />
          <div v-if="suggestState.open" class="ff-sm-suggest__drop">
            <button
              v-for="(it, i) in suggestState.items"
              :key="it.code"
              class="ff-sm-suggest__item"
              :class="{ 'is-active': i === suggestState.active }"
              @mousedown.prevent="pickSuggestion(it)"
            >
              <b>{{ it.name || it.code }}</b>
              <span class="ff-sm-suggest__code">{{ it.code }}</span>
              <span v-if="it.board" class="ff-sm-stock__board">{{ it.board }}</span>
              <span class="ff-sm-suggest__match">{{ it.market }}</span>
            </button>
            <div v-if="suggestState.items.length === 0" class="ff-sm-suggest__empty">无匹配结果</div>
          </div>
        </div>
        <p class="ff-sm-import__hint">
          输入单个股票：6 位代码（含 sh/sz 前缀）、股票名称或拼音简称均可，下拉即时联想，点击候选即可导入。
        </p>
      </div>

      <div v-else-if="importModal.tab === 'text'" class="ff-sm-import__pane">
        <textarea
          v-model="importModal.text"
          class="ff-sm-import__textarea"
          rows="7"
          placeholder="每行一个或用空格/逗号分隔，例如：&#10;600519&#10;000001.SZ&#10;贵州茅台&#10;宁德时代 ndsd"
        />
        <p class="ff-sm-import__hint">
          支持代码（600519 / 000001.SZ / sh300750）、股票名称（如 茅台）、拼音简称（如 gzmt，含前缀模糊）混合粘贴，自动去重并逐个校验；名称/拼音命中多只股票时会列出候选。
        </p>
      </div>

      <div v-else class="ff-sm-import__pane">
        <label class="ff-sm-import__drop" @dragover.prevent @drop.prevent="onDropFile">
          <input type="file" accept="image/*" hidden @change="onPickFile" />
          <img v-if="importModal.filePreview" :src="importModal.filePreview" class="ff-sm-import__preview" alt="截图预览" />
          <span v-else class="ff-sm-import__drop-hint">
            <AppIcon name="upload" size="md" />
            点击选择 / 拖拽图片到此处
          </span>
        </label>
        <p class="ff-sm-import__hint">
          支持截图软件保存后在此上传识别；服务端需安装 OCR 引擎（推荐 <code>pip install rapidocr-onnxruntime</code>），未安装时会给出明确提示。
        </p>
      </div>

      <!-- 导入结果 -->
      <div v-if="importModal.result" class="ff-sm-import__result">
        <div class="ff-sm-import__summary">
          <span class="ff-sm-chip is-ok">新增 {{ importModal.result.added }}</span>
          <span class="ff-sm-chip is-neu">重复 {{ importModal.result.duplicates }}</span>
          <span v-if="importModal.result.results" class="ff-sm-chip is-bad">
            无效 {{ importModal.result.results.filter((r) => !r.valid).length }}
          </span>
        </div>
          <div v-if="importModal.result.results" class="ff-sm-import__rows">
            <div v-for="(r, i) in importModal.result.results" :key="i" class="ff-sm-import__row">
              <AppIcon :name="r.valid ? 'check' : 'x'" size="xs" :class="r.valid ? 'c-ok' : 'c-bad'" />
              <b>{{ r.code || r.raw }}</b>
              <span v-if="r.name">{{ r.name }}</span>
              <span v-if="r.board" class="ff-sm-muted">{{ r.board }}</span>
              <span v-if="r.matched_by" class="ff-sm-muted">[{{ r.matched_by === 'pinyin' ? '拼音' : r.matched_by === 'name' ? '名称' : '代码' }}]</span>
              <span v-if="r.duplicate" class="ff-sm-muted">已在监控中</span>
              <span v-if="r.reason" class="c-bad">{{ r.reason }}</span>
            </div>
          </div>
      </div>
      <div v-if="importModal.error" class="ff-sm-ai__error">
        <AppIcon name="info" size="xs" />
        {{ importModal.error }}
      </div>
    </AppModal>

    <!-- ============ 编辑备注弹窗 ============ -->
    <AppModal
      v-model="editModal.open"
      :title="`编辑备注 · ${editModal.name}`"
      ok-text="保存"
      :loading="editModal.saving"
      @ok="saveNote"
    >
      <textarea v-model="editModal.note" class="ff-sm-import__textarea" rows="4" placeholder="关注逻辑、目标价、风险提示…" />
    </AppModal>
  </div>
</template>

<style scoped>
.ff-sm-view {
  max-width: var(--ff-container-max);
  margin: 0 auto;
  display: grid;
  grid-template-columns: 320px minmax(0, 1fr);
  gap: var(--ff-space-5);
  align-items: start;
}

@media (max-width: 1024px) {
  .ff-sm-view {
    grid-template-columns: 1fr;
  }
}

.ff-sm-muted {
  color: var(--ff-text-tertiary);
  font-weight: 400;
  font-size: var(--ff-fs-sm);
}
.c-internal { color: var(--ff-brand, var(--p-brand-600)); }
.c-external { color: var(--p-violet-600); }
.c-ann { color: var(--p-warn-600); }
.c-major { color: var(--ff-up); }
.c-ok { color: var(--p-brand-500); }
.c-bad { color: var(--ff-up); }

/* ---------------- 左列 ---------------- */
.ff-sm-side {
  background: var(--ff-bg-surface);
  border: 1px solid var(--ff-border);
  border-radius: var(--ff-radius-lg);
  overflow: hidden;
}
.ff-sm-side__head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: var(--ff-space-3) var(--ff-space-4);
  border-bottom: 1px solid var(--ff-border);
}
.ff-sm-side__title {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  font-size: var(--ff-fs-h4);
  font-weight: 700;
  margin: 0;
}
.ff-sm-side__count {
  font-size: var(--ff-fs-xs);
  font-weight: 700;
  color: var(--ff-text-secondary);
  background: var(--ff-bg-muted);
  border-radius: var(--ff-radius-pill);
  padding: 1px 8px;
}
.ff-sm-side__list {
  max-height: calc(100vh - 220px);
  overflow-y: auto;
  padding: var(--ff-space-2);
  display: flex;
  flex-direction: column;
  gap: 2px;
}
.ff-sm-stock {
  display: flex;
  align-items: center;
  gap: var(--ff-space-2);
  padding: 10px var(--ff-space-3);
  border-radius: var(--ff-radius-md);
  cursor: pointer;
  transition: background var(--ff-dur-fast);
}
.ff-sm-stock:hover { background: var(--ff-bg-subtle); }
.ff-sm-stock.is-active {
  background: var(--ff-brand-subtle, var(--p-brand-50));
  box-shadow: inset 2px 0 0 var(--p-brand-600);
}
.ff-sm-stock__main { flex: 1 1 auto; min-width: 0; }
.ff-sm-stock__name {
  display: flex;
  align-items: baseline;
  gap: 6px;
  min-width: 0;
}
.ff-sm-stock__title {
  font-weight: 600;
  font-size: var(--ff-fs-body);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
.ff-sm-stock__board {
  flex: none;
  font-size: var(--ff-fs-xs);
  font-weight: 600;
  color: var(--ff-text-secondary);
  background: var(--ff-bg-muted);
  border-radius: var(--ff-radius-xs);
  padding: 1px 6px;
}
.ff-sm-stock__meta {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-top: 2px;
}
.ff-sm-stock__code {
  font-family: var(--ff-font-mono);
  font-size: var(--ff-fs-xs);
  color: var(--ff-text-tertiary);
}
.ff-sm-stock__badge {
  font-family: var(--ff-font-mono);
  font-size: var(--ff-fs-xs);
  color: var(--ff-text-secondary);
  background: var(--ff-bg-subtle);
  border: 1px solid var(--ff-border);
  border-radius: var(--ff-radius-pill);
  padding: 0 6px;
}
.ff-sm-stock__note-icon { color: var(--p-warn-500); display: inline-flex; }
.ff-sm-stock__ops { display: flex; gap: 2px; opacity: 0; transition: opacity var(--ff-dur-fast); }
.ff-sm-stock:hover .ff-sm-stock__ops { opacity: 1; }
.ff-sm-iconbtn {
  border: none;
  background: transparent;
  color: var(--ff-text-tertiary);
  border-radius: var(--ff-radius-xs);
  padding: 5px;
  cursor: pointer;
  display: inline-flex;
}
.ff-sm-iconbtn:hover { background: var(--ff-bg-muted); color: var(--ff-text-primary); }
.ff-sm-iconbtn--danger:hover { color: var(--ff-up); }

/* ---------------- 右列 ---------------- */
.ff-sm-detail__head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  flex-wrap: wrap;
  gap: var(--ff-space-3);
  margin-bottom: var(--ff-space-3);
}
.ff-sm-detail__id { display: flex; align-items: baseline; gap: 10px; flex-wrap: wrap; }
.ff-sm-detail__name { font-size: var(--ff-fs-h2); font-weight: var(--ff-fw-bold); margin: 0; }
.ff-sm-detail__code {
  font-family: var(--ff-font-mono);
  font-size: var(--ff-fs-body-sm);
  color: var(--ff-text-tertiary);
}
.ff-sm-detail__tools { display: flex; align-items: center; gap: var(--ff-space-2); flex-wrap: wrap; }
.ff-sm-live {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  font-size: var(--ff-fs-xs);
  color: var(--ff-text-tertiary);
}
.ff-sm-live.is-live { color: var(--p-brand-600); }
.ff-sm-flash {
  font-size: var(--ff-fs-xs);
  font-weight: 700;
  color: var(--ff-up);
  background: var(--ff-up-subtle);
  border: 1px solid var(--ff-up-border);
  border-radius: var(--ff-radius-pill);
  padding: 1px 8px;
}

.ff-sm-catchup {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: var(--ff-fs-sm);
  color: var(--p-warn-700);
  background: var(--p-warn-50);
  border: 1px solid var(--p-warn-200);
  border-radius: var(--ff-radius-md);
  padding: 8px 12px;
  margin-bottom: var(--ff-space-3);
}
.ff-sm-note {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: var(--ff-fs-sm);
  color: var(--ff-text-secondary);
  background: var(--ff-bg-subtle);
  border-radius: var(--ff-radius-md);
  padding: 8px 12px;
  margin-bottom: var(--ff-space-3);
}

.ff-sm-stats {
  display: flex;
  gap: var(--ff-space-4);
  font-size: var(--ff-fs-caption);
  color: var(--ff-text-secondary);
  margin-bottom: var(--ff-space-3);
}
.ff-sm-stat b {
  font-family: var(--ff-font-mono);
  font-size: var(--ff-fs-body);
  margin-right: 4px;
  color: var(--ff-text-primary);
}

/* ---------------- AI 分析 ---------------- */
.ff-sm-ai {
  background: var(--ff-bg-surface);
  border: 1px solid var(--ff-border);
  border-radius: var(--ff-radius-lg);
  margin-bottom: var(--ff-space-4);
  overflow: hidden;
}
.ff-sm-ai.is-open { border-color: var(--p-brand-200); }
.ff-sm-ai__head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: var(--ff-space-3) var(--ff-space-4);
  border-bottom: 1px solid var(--ff-border);
  background: var(--p-brand-50);
}
.ff-sm-ai__title {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  margin: 0;
  font-size: var(--ff-fs-h4);
  font-weight: 700;
}
.ff-sm-ai__body { padding: var(--ff-space-4); }
.ff-sm-ai__chips {
  display: flex;
  align-items: center;
  gap: var(--ff-space-2);
  flex-wrap: wrap;
  margin-bottom: var(--ff-space-3);
}
.ff-sm-ai__running { padding: var(--ff-space-4); display: flex; flex-direction: column; gap: var(--ff-space-3); }
.ff-sm-ai__error {
  display: flex;
  align-items: center;
  gap: 6px;
  margin: var(--ff-space-3) var(--ff-space-4);
  color: var(--ff-up);
  font-size: var(--ff-fs-sm);
}
.ff-sm-ai__hint {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: var(--ff-space-3) var(--ff-space-4);
  color: var(--ff-text-tertiary);
  font-size: var(--ff-fs-sm);
}
.ff-sm-ai__history {
  border-top: 1px solid var(--ff-border);
  padding: var(--ff-space-2) var(--ff-space-3);
  display: flex;
  flex-direction: column;
  gap: 2px;
  max-height: 260px;
  overflow-y: auto;
}
.ff-sm-ai__hrow {
  display: flex;
  align-items: center;
  gap: var(--ff-space-2);
  border: none;
  background: transparent;
  text-align: left;
  padding: 6px 8px;
  border-radius: var(--ff-radius-xs);
  cursor: pointer;
  font-size: var(--ff-fs-caption);
}
.ff-sm-ai__hrow:hover { background: var(--ff-bg-subtle); }
.ff-sm-ai__hrow.is-current { background: var(--ff-bg-muted); }
.ff-sm-ai__htime { font-family: var(--ff-font-mono); color: var(--ff-text-secondary); }
.ff-sm-ai__hmsgs, .ff-sm-ai__hfail { color: var(--ff-text-tertiary); }
.ff-sm-ai__hfail { color: var(--ff-up); }

.ff-sm-chip {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  font-size: var(--ff-fs-xs);
  font-weight: 600;
  padding: 2px 8px;
  border-radius: var(--ff-radius-xs);
  background: var(--ff-bg-subtle);
  color: var(--ff-text-secondary);
  border: 1px solid var(--ff-border);
}
.ff-sm-chip.is-up { background: var(--ff-up-subtle); color: var(--ff-up-text, var(--ff-up)); border-color: var(--ff-up-border); }
.ff-sm-chip.is-down { background: var(--ff-down-subtle); color: var(--ff-down-text, var(--ff-down)); border-color: var(--ff-down-border); }
.ff-sm-chip.is-impact { background: var(--p-violet-100); color: var(--p-violet-600); border-color: transparent; }
.ff-sm-chip.is-major-tag { background: var(--ff-up-subtle); color: var(--ff-up); border-color: var(--ff-up-border); font-weight: 700; }
.ff-sm-chip.is-ann-type { background: var(--p-brand-50); color: var(--p-brand-700); border-color: var(--p-brand-200); }
.ff-sm-chip.is-model { font-family: var(--ff-font-mono); font-weight: 500; }
.ff-sm-chip.is-time { font-family: var(--ff-font-mono); font-weight: 400; }
.ff-sm-chip.is-ok { background: var(--p-brand-50); color: var(--p-brand-700); border-color: var(--p-brand-200); }
.ff-sm-chip.is-bad { background: var(--ff-up-subtle); color: var(--ff-up); border-color: var(--ff-up-border); }

/* ---------------- 舆情流 ---------------- */
.ff-sm-feed__title {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  font-size: var(--ff-fs-h4);
  font-weight: 700;
  margin: 0 0 var(--ff-space-3);
}
.ff-sm-feed__list {
  display: flex;
  flex-direction: column;
  gap: var(--ff-space-2);
  padding-bottom: var(--ff-space-8);
}
.ff-sm-item {
  display: flex;
  gap: var(--ff-space-3);
  background: var(--ff-bg-surface);
  border: 1px solid var(--ff-border);
  border-radius: var(--ff-radius-md);
  padding: var(--ff-space-3) var(--ff-space-4);
  transition: border-color var(--ff-dur-fast);
}
.ff-sm-item.is-catchup { border-color: var(--p-warn-400); background: var(--p-warn-50); }
.ff-sm-item.is-new { border-color: var(--p-brand-300); }
.ff-sm-item.is-major {
  border-color: var(--ff-up-border);
  box-shadow: inset 3px 0 0 var(--ff-up);
  background: var(--ff-up-subtle, transparent);
}
.ff-sm-item__badges {
  flex: none;
  display: flex;
  flex-direction: column;
  align-items: flex-start;
  gap: 4px;
  min-width: 64px;
}
.ff-sm-item__src {
  font-size: var(--ff-fs-xs);
  font-weight: 700;
  border-radius: var(--ff-radius-xs);
  padding: 1px 6px;
}
.ff-sm-item__src.is-internal { background: var(--p-brand-50); color: var(--p-brand-700); }
.ff-sm-item__src.is-external { background: var(--p-violet-100); color: var(--p-violet-600); }
.ff-sm-item__ch {
  display: inline-flex;
  align-items: center;
  gap: 3px;
  font-size: var(--ff-fs-xs);
  color: var(--ff-text-tertiary);
}
.ff-sm-item__body { flex: 1 1 auto; min-width: 0; }
.ff-sm-item__title {
  display: block;
  font-weight: 600;
  font-size: var(--ff-fs-body);
  color: var(--ff-text-primary);
  text-decoration: none;
  line-height: 1.5;
}
a.ff-sm-item__title:hover { color: var(--p-brand-600); }
.ff-sm-item__summary {
  margin: 4px 0 0;
  font-size: var(--ff-fs-body-sm);
  color: var(--ff-text-secondary);
  line-height: 1.55;
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
}
.ff-sm-item__meta {
  display: flex;
  align-items: center;
  gap: var(--ff-space-3);
  margin-top: 6px;
  font-size: var(--ff-fs-xs);
  color: var(--ff-text-tertiary);
  flex-wrap: wrap;
}
.ff-sm-item__imp { color: var(--ff-up); font-weight: 600; }
.ff-sm-item__catchup-tag { color: var(--p-warn-700); font-weight: 600; }

/* ---------------- 导入弹窗 ---------------- */
.ff-sm-import__pane { margin-top: var(--ff-space-4); display: flex; flex-direction: column; gap: var(--ff-space-2); }
.ff-sm-import__hint { margin: 0; font-size: var(--ff-fs-caption); color: var(--ff-text-tertiary); }

/* 手动输入联想下拉 */
.ff-sm-suggest { position: relative; }
.ff-sm-suggest__drop {
  position: absolute;
  top: calc(100% + 4px);
  left: 0;
  right: 0;
  z-index: 30;
  background: var(--ff-bg-surface);
  border: 1px solid var(--ff-border);
  border-radius: var(--ff-radius-md);
  box-shadow: var(--ff-shadow-lg, 0 12px 32px rgba(18, 25, 38, 0.14));
  overflow: hidden;
  max-height: 300px;
  overflow-y: auto;
}
.ff-sm-suggest__item {
  display: flex;
  align-items: baseline;
  gap: 8px;
  width: 100%;
  border: none;
  background: transparent;
  text-align: left;
  padding: 8px 12px;
  cursor: pointer;
  font-size: var(--ff-fs-caption);
  color: var(--ff-text-primary);
}
.ff-sm-suggest__item:hover, .ff-sm-suggest__item.is-active {
  background: var(--ff-brand-subtle, var(--p-brand-50));
}
.ff-sm-suggest__code {
  font-family: var(--ff-font-mono);
  font-size: var(--ff-fs-xs);
  color: var(--ff-text-tertiary);
}
.ff-sm-suggest__match {
  margin-left: auto;
  font-size: var(--ff-fs-xs);
  color: var(--ff-text-tertiary);
}
.ff-sm-suggest__empty {
  padding: 10px 12px;
  font-size: var(--ff-fs-caption);
  color: var(--ff-text-tertiary);
}
.ff-sm-import__hint code {
  font-family: var(--ff-font-mono);
  background: var(--ff-bg-muted);
  border-radius: var(--ff-radius-xs);
  padding: 1px 5px;
}
.ff-sm-import__textarea {
  width: 100%;
  box-sizing: border-box;
  font: var(--ff-fs-body-sm) / 1.6 var(--ff-font-sans);
  color: var(--ff-text-primary);
  background: var(--ff-bg-subtle);
  border: 1px solid var(--ff-border);
  border-radius: var(--ff-radius-md);
  padding: 10px 12px;
  resize: vertical;
}
.ff-sm-import__textarea:focus { outline: 2px solid var(--p-brand-300); outline-offset: -1px; }
.ff-sm-import__drop {
  display: flex;
  align-items: center;
  justify-content: center;
  min-height: 160px;
  border: 1.5px dashed var(--ff-border);
  border-radius: var(--ff-radius-md);
  cursor: pointer;
  transition: border-color var(--ff-dur-fast);
}
.ff-sm-import__drop:hover { border-color: var(--p-brand-400); }
.ff-sm-import__drop-hint {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: var(--ff-space-2);
  color: var(--ff-text-tertiary);
  font-size: var(--ff-fs-sm);
}
.ff-sm-import__preview { max-width: 100%; max-height: 240px; border-radius: var(--ff-radius-sm); }
.ff-sm-import__result { margin-top: var(--ff-space-4); border-top: 1px solid var(--ff-border); padding-top: var(--ff-space-3); }
.ff-sm-import__summary { display: flex; gap: var(--ff-space-2); flex-wrap: wrap; }
.ff-sm-import__rows {
  margin-top: var(--ff-space-2);
  display: flex;
  flex-direction: column;
  gap: 4px;
  max-height: 200px;
  overflow-y: auto;
}
.ff-sm-import__row {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: var(--ff-fs-caption);
  padding: 3px 0;
}
</style>
