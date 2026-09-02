<script setup>
/**
 * ReportReaderView — 报告阅读器（全屏沉浸）
 * 左：目录锚点｜中：摘要卡 + Markdown 正文｜右：操作与元信息
 * 支持底部内联追问此报告（就地完成，不跳转聊天页）。
 */
import { ref, computed, nextTick, onMounted, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { api } from '../../api/client'
import { useAiStore } from '../../store/ai'
import AppButton from '../../ui/AppButton.vue'
import AppIcon from '../../ui/AppIcon.vue'
import MarkdownView from '../../components/ai/MarkdownView.vue'
import ReportSummaryCard from '../../components/ai/ReportSummaryCard.vue'
import ChartPanel from '../../components/ChartPanel.vue'

const route = useRoute()
const router = useRouter()
const store = useAiStore()

const report = ref(null)
const loading = ref(true)
const loadErr = ref('')
const activeSection = ref('')
const bodyEl = ref(null)

async function load(id) {
  loading.value = true
  loadErr.value = ''
  report.value = null
  try {
    const r = await api.llm('/report', { id })
    if (!r.report) throw new Error('报告不存在')
    report.value = r.report
  } catch (e) {
    loadErr.value = e.message || String(e)
  } finally {
    loading.value = false
  }
}

// 目录：从正文提取 ## 标题
const toc = computed(() => {
  const c = report.value?.content || ''
  const items = []
  const re = /^##\s+(.+)$/gm
  let m
  while ((m = re.exec(c))) items.push({ title: m[1].trim(), anchor: encodeURIComponent(m[1].trim()) })
  return items
})

function scrollToSection(title) {
  activeSection.value = title
  const el = bodyEl.value?.querySelector(`[data-anchor="${encodeURIComponent(title)}"]`)
  if (el) el.scrollIntoView({ behavior: 'smooth', block: 'start' })
}
function onBodyScroll() {
  // 简单高亮：滚动时更新当前章节
  const nodes = bodyEl.value?.querySelectorAll('[data-anchor]') || []
  let cur = ''
  for (const n of nodes) {
    if (n.getBoundingClientRect().top <= 140) cur = n.getAttribute('data-anchor') || ''
  }
  if (cur) activeSection.value = decodeURIComponent(cur)
}

// ---------- 引用溯源：[编号] -> 参考资讯对照 ----------
const sources = computed(() => {
  const s = report.value?.sources
  return Array.isArray(s) ? s : []
})

// 把正文里的 [n] 引用编号替换为可点击的页内锚点链接（仅替换存在于对照表的编号）
const citedContent = computed(() => {
  const c = report.value?.content || ''
  if (!sources.value.length) return c
  const idxSet = new Set(sources.value.map((s) => s.idx))
  return c.replace(/\[(\d{1,3})\]/g, (m, n) => {
    const idx = Number(n)
    return idxSet.has(idx) ? `[[${idx}]](#ff-src-${idx})` : m
  })
})

const typeLabel = computed(() => {
  const t = report.value?.report_type
  return { review: '复盘简报', stock: '个股深度', sentiment: '舆情研判' }[t] || ''
})

// 快讯/财经 AI 分析：聚焦单条快讯，收敛附加信息（目录/图表/引用对照）
const isFlash = computed(() => {
  const t = report.value?.title || ''
  return t.startsWith('快讯分析')
})

// 报告内联追问（不再跳转聊天页，就地完成「追问此报告」）
const followUpOpen = ref(false)
const followUp = ref('')
const followUpLog = ref([]) // [{ role: 'user'|'ai', text }]
const followUpBusy = ref(false)
const qEl = ref(null)

function toggleFollowUp() {
  followUpOpen.value = !followUpOpen.value
  if (followUpOpen.value) nextTick(() => qEl.value?.focus())
}

async function sendFollowUp() {
  const q = followUp.value.trim()
  if (!q || followUpBusy.value || !report.value) return
  followUpLog.value.push({ role: 'user', text: q })
  followUp.value = ''
  followUpBusy.value = true
  try {
    const text = await store.postReportFollowUp(q, report.value.id)
    followUpLog.value.push({ role: 'ai', text: text || '（空回复）' })
  } catch (e) {
    followUpLog.value.push({ role: 'ai', text: '出错了：' + (e.message || String(e)) })
  } finally {
    followUpBusy.value = false
    nextTick(() => {
      const el = qEl.value
      if (el) el.focus()
      const body = bodyEl.value
      if (body) body.scrollTop = body.scrollHeight
    })
  }
}

function downloadMarkdown() {
  const c = report.value?.content || ''
  const blob = new Blob([c], { type: 'text/markdown;charset=utf-8' })
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = `${(report.value?.title || 'report').replace(/[\\/:*?"<>|]/g, '_')}.md`
  a.click()
  URL.revokeObjectURL(url)
}

function fmtFull(ts) {
  if (!ts) return ''
  const d = new Date(ts * 1000)
  const p = (n) => String(n).padStart(2, '0')
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())} ${p(d.getHours())}:${p(d.getMinutes())}:${p(d.getSeconds())}`
}

// ---------- 数据可视化（基于报告 stats） ----------
const hasStats = computed(() => {
  const s = report.value?.stats
  return s && (s.sentiment || (s.top_stocks && s.top_stocks.length))
})

const sentimentOption = computed(() => {
  const sent = report.value?.stats?.sentiment || {}
  const positive = Number(sent.positive || 0)
  const neutral = Number(sent.neutral || 0)
  const negative = Number(sent.negative || 0)
  if (!positive && !neutral && !negative) return null
  // 红=正面情绪（利好语义）、绿=负面（利空语义）、灰=中性，与市场语义一致
  return {
    tooltip: { trigger: 'item', formatter: '{b}: {c} 条 ({d}%)' },
    legend: { bottom: 0, itemWidth: 10, itemHeight: 10, textStyle: { fontSize: chartFont(11) } },
    series: [{
      type: 'pie',
      radius: ['46%', '68%'],
      center: ['50%', '44%'],
      avoidLabelOverlap: false,
      itemStyle: { borderRadius: 5, borderColor: 'var(--ff-bg-surface)', borderWidth: 2 },
      label: { show: false },
      emphasis: { label: { show: true, fontSize: 13, fontWeight: 700 } },
      data: [
        { name: '正面', value: positive, itemStyle: { color: 'var(--ff-up)' } },
        { name: '中性', value: neutral, itemStyle: { color: 'var(--ff-text-tertiary)' } },
        { name: '负面', value: negative, itemStyle: { color: 'var(--ff-down)' } },
      ],
    }],
  }
})

const topStocksOption = computed(() => {
  const stocks = report.value?.stats?.top_stocks || []
  if (!stocks.length) return null
  const top = stocks.slice(0, 8).reverse()
  return {
    tooltip: { trigger: 'axis', axisPointer: { type: 'shadow' } },
    grid: { left: 8, right: 16, top: 6, bottom: 4, containLabel: true },
    xAxis: { type: 'value', axisLabel: { fontSize: chartFont(10) }, splitLine: { lineStyle: { color: '#eef1f0' } } },
    yAxis: {
      type: 'category', data: top.map((s) => s.name || s.code),
      axisLabel: { fontSize: chartFont(10.5) }, axisLine: { show: false }, axisTick: { show: false },
    },
    series: [{
      type: 'bar', barWidth: 10, data: top.map((s) => s.count || 0),
      itemStyle: { color: 'var(--ff-brand)', borderRadius: [0, 5, 5, 0] },
      label: { show: true, position: 'right', fontSize: chartFont(10) },
    }],
  }
})

onMounted(() => {
  load(Number(route.params.id))
  store.startPolling()
  store.loadInit()
})
watch(() => route.params.id, (id) => id && load(Number(id)))
</script>

<template>
  <div class="rr">
    <!-- 阅读页的工具栏已展示报告标题，这里用视觉隐藏 h1 保文档语义 -->
    <h1 class="ff-sr-only">{{ report?.title || '报告阅读' }}</h1>

    <!-- 工具栏 -->
    <div class="rr__toolbar">
      <button class="rr__back" @click="router.push('/ai/reports')"><AppIcon name="arrow-left" size="sm" /> 返回列表</button>
      <span class="rr__title">{{ report?.title || '报告' }}</span>
      <span class="rr__sp"></span>
      <span v-if="report" class="rr__meta">{{ fmtFull(report.created_ts) }} · {{ report.model || '—' }}</span>
      <button class="rr__btn" @click="downloadMarkdown"><AppIcon name="download" size="sm" /> 导出</button>
      <button class="rr__btn rr__btn--primary" @click="toggleFollowUp"><AppIcon name="chatter" size="sm" /> 追问此报告</button>
    </div>

    <div v-if="loading" class="rr__loading">
      <span class="rr__spinner"></span> 正在加载报告…
    </div>
    <div v-else-if="loadErr" class="rr__error">
      <AppIcon name="alert-circle" size="xl" />
      <p>{{ loadErr }}</p>
      <button class="rr__btn rr__btn--primary" @click="load(Number(route.params.id))">重试</button>
    </div>

    <div v-else-if="report" class="rr__body" :class="{ 'rr__body--flash': isFlash }">
      <!-- 左目录（快讯分析不展示） -->
      <aside v-if="!isFlash" class="rr__toc">
        <div class="rr__toc-title">目录</div>
        <button
          v-for="t in toc"
          :key="t.anchor"
          class="rr__toc-item"
          :class="{ on: activeSection === t.title }"
          @click="scrollToSection(t.title)"
        >{{ t.title }}</button>
        <div v-if="!toc.length" class="rr__toc-empty">（无章节标题）</div>
      </aside>

      <!-- 中正文 -->
      <article ref="bodyEl" class="rr__content" @scroll.passive="onBodyScroll">
        <h1 class="rr__h1">{{ report.title || '报告 #' + report.id }}</h1>
        <ReportSummaryCard :report="report" />
        <MarkdownView :content="citedContent" />
        <!-- 引用溯源对照表（快讯分析不展示） -->
        <div v-if="!isFlash && sources.length" class="rr__sources">
          <div class="rr__sources-title">📎 引用资讯对照（正文 [编号] 可点击回链）</div>
          <div v-for="s in sources" :key="s.idx" :id="'ff-src-' + s.idx" class="rr__src">
            <span class="rr__src-idx">[{{ s.idx }}]</span>
            <span class="rr__src-main">
              <template v-if="s.url && s.url !== '#'">
                <a :href="s.url" target="_blank" rel="noopener" class="rr__src-link">{{ s.title }}</a>
              </template>
              <template v-else>{{ s.title }}</template>
              <span class="rr__src-meta">{{ s.source }} · {{ s.time }} · 重要性 {{ s.importance }}</span>
            </span>
          </div>
        </div>
      </article>

      <!-- 右操作 -->
      <aside class="rr__side">
        <div class="rr__card">
          <div class="rr__card-label">数据速览</div>
          <template v-if="!isFlash && hasStats">
            <div v-if="sentimentOption" class="rr__chart">
              <div class="rr__chart-title">情绪分布</div>
              <ChartPanel :option="sentimentOption" height="150px" />
            </div>
            <div v-if="topStocksOption" class="rr__chart">
              <div class="rr__chart-title">提及 Top 个股</div>
              <ChartPanel :option="topStocksOption" height="170px" />
            </div>
            <div class="rr__chart-note">来源：报告程序统计，仅反映资讯提及频次</div>
          </template>
          <div v-else-if="!isFlash" class="rr__chart-empty">（该报告无统计数据）</div>
        </div>
        <div class="rr__card">
          <div class="rr__card-label">元信息</div>
          <div v-if="typeLabel" class="rr__kv"><span>类型</span><b>{{ typeLabel }}</b></div>
          <div class="rr__kv"><span>范围</span><b>{{ store.scopeLabel(report.scope) }}</b></div>
          <div class="rr__kv"><span>窗口</span><b>{{ report.window_hours || 24 }} 小时</b></div>
          <div class="rr__kv"><span>资讯</span><b>{{ report.news_count || 0 }} 条</b></div>
          <div class="rr__kv"><span>耗时</span><b>{{ report.elapsed ? report.elapsed.toFixed(1) + 's' : '—' }}</b></div>
        </div>
        <div class="rr__card">
          <div class="rr__card-label">操作</div>
          <button class="rr__side-btn" @click="store.pinReport(report.id, !report.pinned)">
            <AppIcon :name="report.pinned ? 'bookmark' : 'bookmark'" size="sm" /> {{ report.pinned ? '取消置顶' : '置顶' }}
          </button>
          <button class="rr__side-btn" @click="downloadMarkdown"><AppIcon name="download" size="sm" /> 导出 Markdown</button>
          <button class="rr__side-btn" @click="toggleFollowUp"><AppIcon name="chatter" size="sm" /> 基于此报告追问</button>
        </div>
        <div class="rr__card rr__card--warn">
          <AppIcon name="info" size="sm" />
          <span style="font-size: var(--ff-fs-xs);line-height:1.6">本报告由 AI 自动生成，仅供参考，不构成投资建议。</span>
        </div>
      </aside>

      <!-- 底部内联追问区 -->
      <div v-if="followUpOpen" class="rr__follow">
        <div v-if="followUpLog.length" class="rr__follow-log">
          <div v-for="(m, i) in followUpLog" :key="i" class="rr__follow-msg" :class="m.role === 'ai' ? 'ai' : 'user'">
            <template v-if="m.role === 'ai'">
              <div class="rr__follow-tag">AI</div>
              <div class="rr__follow-mark"><MarkdownView :content="m.text || '…'" compact /></div>
            </template>
            <template v-else>
              <div class="rr__follow-q">{{ m.text }}</div>
            </template>
          </div>
        </div>
        <div class="rr__follow-input">
          <textarea
            ref="qEl"
            v-model="followUp"
            rows="1"
            class="rr__follow-field"
            placeholder="就此报告追问…"
            :disabled="followUpBusy"
            @keydown.enter.exact.prevent="sendFollowUp"
          ></textarea>
          <AppButton
            variant="primary"
            size="sm"
            :loading="followUpBusy"
            :disabled="followUpBusy || !followUp.trim()"
            @click="sendFollowUp"
          >发送</AppButton>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.rr { display: flex; flex-direction: column; gap: 14px; }
.rr__toolbar { display: flex; align-items: center; gap: 10px; flex-wrap: wrap; }
.rr__back { display: inline-flex; align-items: center; gap: 5px; border: 1px solid var(--ff-border); background: var(--ff-bg-surface); border-radius: 9px; padding: 7px 12px; font-size: var(--ff-fs-caption); font-weight: 600; color: var(--ff-text-2); cursor: pointer; }
.rr__back:hover { color: var(--ff-brand); border-color: var(--ff-border-brand); }
.rr__title { font-size: var(--ff-fs-body); font-weight: 700; color: var(--ff-text-primary); }
.rr__sp { flex: 1; }
.rr__meta { font-size: var(--ff-fs-xs); color: var(--ff-text-3); }
.rr__btn { display: inline-flex; align-items: center; gap: 5px; border: 1px solid var(--ff-border); background: var(--ff-bg-surface); border-radius: 9px; padding: 7px 13px; font-size: var(--ff-fs-caption); font-weight: 600; color: var(--ff-text-2); cursor: pointer; }
.rr__btn:hover { border-color: var(--ff-border-brand); color: var(--ff-brand); }
.rr__btn--primary { background: var(--ff-brand); color: var(--ff-bg-surface); border-color: var(--ff-brand); }
.rr__btn--primary:hover { background: var(--ff-brand-dark); color: var(--ff-bg-surface); }
.rr__loading, .rr__error { text-align: center; padding: 70px 20px; color: var(--ff-text-3); background: var(--ff-bg-surface); border: 1px solid var(--ff-border); border-radius: 13px; }
.rr__spinner { display: inline-block; width: 16px; height: 16px; border: 2px solid var(--ff-border); border-top-color: var(--ff-brand); border-radius: 50%; animation: rr-rot 0.8s linear infinite; vertical-align: middle; margin-right: 8px; }
@keyframes rr-rot { to { transform: rotate(360deg); } }
.rr__error p { font-size: var(--ff-fs-caption); margin: 10px 0 16px; color: var(--ff-up); }
.rr__body { display: grid; grid-template-columns: 200px minmax(0, 1fr) 210px; gap: 14px; align-items: start; }
.rr__body--flash { grid-template-columns: minmax(0, 1fr) 210px; }
.rr__toc { position: sticky; top: 14px; background: var(--ff-bg-surface); border: 1px solid var(--ff-border); border-radius: 13px; padding: 13px; max-height: calc(100vh - 260px); overflow-y: auto; }
.rr__toc-title { font-size: var(--ff-fs-xs); font-weight: 600; color: var(--ff-text-3); letter-spacing: .06em; margin-bottom: 8px; }
.rr__toc-item { display: block; width: 100%; text-align: left; border: none; background: none; padding: 6px 9px; border-radius: 7px; font-size: var(--ff-fs-caption); color: var(--ff-text-2); cursor: pointer; line-height: 1.4; }
.rr__toc-item:hover { background: var(--ff-bg-hover); }
.rr__toc-item.on { background: var(--ff-bg-brand-subtle); color: var(--ff-brand-dark); font-weight: 600; }
.rr__toc-empty { font-size: var(--ff-fs-xs); color: var(--ff-text-3); padding: 8px; }
.rr__content { background: var(--ff-bg-surface); border: 1px solid var(--ff-border); border-radius: 13px; padding: 26px 30px; max-height: calc(100vh - 260px); overflow-y: auto; }
.rr__h1 { font-size: var(--ff-fs-h2); font-weight: 700; letter-spacing: -0.01em; margin-bottom: 16px; color: var(--ff-text-primary); }
.rr__sources { margin-top: 30px; padding-top: 16px; border-top: 1px dashed var(--ff-border); }
.rr__sources-title { font-size: var(--ff-fs-caption); font-weight: 600; color: var(--ff-text-secondary); margin-bottom: 10px; }
.rr__src { display: flex; gap: 8px; padding: 6px 8px; border-radius: 8px; font-size: var(--ff-fs-caption); line-height: 1.55; scroll-margin-top: 20px; }
.rr__src:hover { background: var(--ff-bg-hover); }
.rr__src-idx { font-family: var(--ff-font-mono, ui-monospace, monospace); color: var(--ff-brand); font-weight: 700; flex-shrink: 0; }
.rr__src-main { min-width: 0; color: var(--ff-text-2); }
.rr__src-link { color: var(--ff-text-primary); text-decoration: none; }
.rr__src-link:hover { color: var(--ff-brand); text-decoration: underline; }
.rr__src-meta { display: block; font-size: var(--ff-fs-xs); color: var(--ff-text-3); margin-top: 1px; }
.rr__side { display: flex; flex-direction: column; gap: 12px; position: sticky; top: 14px; }
.rr__card { background: var(--ff-bg-surface); border: 1px solid var(--ff-border); border-radius: 12px; padding: 13px 14px; }
.rr__card--warn { background: #fef9ee; border-color: #f0dfb8; color: #92400e; display: flex; gap: 8px; align-items: flex-start; }
.rr__card-label { font-size: var(--ff-fs-xs); font-weight: 600; color: var(--ff-text-3); letter-spacing: .06em; margin-bottom: 8px; }
.rr__chart { margin-bottom: 8px; }
.rr__chart-title { font-size: var(--ff-fs-xs); font-weight: 600; color: var(--ff-text-2); margin-bottom: 2px; }
.rr__chart-note { font-size: var(--ff-fs-xs); color: var(--ff-text-3); margin-top: 2px; line-height: 1.5; }
.rr__chart-empty { font-size: var(--ff-fs-xs); color: var(--ff-text-3); padding: 8px 0; }
.rr__kv { display: flex; justify-content: space-between; font-size: var(--ff-fs-caption); padding: 3px 0; color: var(--ff-text-2); }
.rr__kv b { color: var(--ff-text-primary); font-family: var(--ff-font-mono, ui-monospace, monospace); }
.rr__side-btn { display: flex; align-items: center; gap: 7px; width: 100%; border: 1px solid var(--ff-border); background: var(--ff-bg-surface); border-radius: 8px; padding: 7px 11px; font-size: var(--ff-fs-caption); font-weight: 600; color: var(--ff-text-2); cursor: pointer; margin-bottom: 6px; }
.rr__side-btn:hover { border-color: var(--ff-border-brand); color: var(--ff-brand); }

/* 底部内联追问区 */
.rr__follow { grid-column: 2 / -1; display: flex; flex-direction: column; gap: 10px; background: var(--ff-bg-surface); border: 1px solid var(--ff-border); border-radius: 12px; padding: 13px 15px; }
.rr__follow-log { display: flex; flex-direction: column; gap: 10px; max-height: 300px; overflow-y: auto; }
.rr__follow-msg { display: flex; flex-direction: column; gap: 5px; }
.rr__follow-tag { font-size: var(--ff-fs-xs); font-weight: 600; color: var(--ff-brand); }
.rr__follow-mark { font-size: var(--ff-fs-caption); line-height: 1.65; color: var(--ff-text-primary); background: var(--ff-bg-subtle); border: 1px solid var(--ff-border); border-radius: 8px; padding: 9px 12px; }
.rr__follow-q { align-self: flex-end; max-width: 88%; font-size: var(--ff-fs-caption); color: var(--ff-bg-surface); background: var(--ff-brand); border-radius: 10px 10px 4px 10px; padding: 7px 12px; word-break: break-word; }
.rr__follow-input { display: flex; gap: 8px; align-items: flex-end; }
.rr__follow-field { flex: 1; min-height: 38px; max-height: 120px; border: 1px solid var(--ff-border); border-radius: 9px; padding: 8px 12px; font-size: var(--ff-fs-caption); line-height: 1.5; outline: none; background: var(--ff-bg-surface); color: var(--ff-text-primary); resize: none; font-family: inherit; }
.rr__follow-field:focus { border-color: var(--ff-border-focus); box-shadow: 0 0 0 3px var(--ff-focus-ring); }
.rr__follow-field:disabled { opacity: 0.6; }

@media (max-width: 1100px) {
  .rr__body { grid-template-columns: 1fr; }
  .rr__toc { position: static; max-height: none; display: flex; flex-wrap: wrap; gap: 4px; }
  .rr__toc-title { width: 100%; }
  .rr__side { position: static; flex-direction: row; flex-wrap: wrap; }
  .rr__follow { grid-column: 1 / -1; }
}
</style>
