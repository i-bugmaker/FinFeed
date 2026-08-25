<script setup>
/**
 * ReportReaderView — 报告阅读器（全屏沉浸）
 * 左：目录锚点｜中：摘要卡 + Markdown 正文｜右：操作与元信息
 * 支持追问此报告（携带 report_id 跳转分析师）。
 */
import { ref, computed, onMounted, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { api } from '../../api/client'
import { useAiStore } from '../../store/ai'
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

function askReport() {
  store.setContextReport({ id: report.value.id, title: report.value.title, created_at: report.value.created_at })
  router.push({ path: '/ai/analyst', query: { report_id: report.value.id } })
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
    legend: { bottom: 0, itemWidth: 10, itemHeight: 10, textStyle: { fontSize: 11 } },
    series: [{
      type: 'pie',
      radius: ['46%', '68%'],
      center: ['50%', '44%'],
      avoidLabelOverlap: false,
      itemStyle: { borderRadius: 5, borderColor: '#fff', borderWidth: 2 },
      label: { show: false },
      emphasis: { label: { show: true, fontSize: 13, fontWeight: 700 } },
      data: [
        { name: '正面', value: positive, itemStyle: { color: '#e5484d' } },
        { name: '中性', value: neutral, itemStyle: { color: '#9ca3af' } },
        { name: '负面', value: negative, itemStyle: { color: '#12a150' } },
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
    xAxis: { type: 'value', axisLabel: { fontSize: 10 }, splitLine: { lineStyle: { color: '#eef1f0' } } },
    yAxis: {
      type: 'category', data: top.map((s) => s.name || s.code),
      axisLabel: { fontSize: 10.5 }, axisLine: { show: false }, axisTick: { show: false },
    },
    series: [{
      type: 'bar', barWidth: 10, data: top.map((s) => s.count || 0),
      itemStyle: { color: '#2f7d5b', borderRadius: [0, 5, 5, 0] },
      label: { show: true, position: 'right', fontSize: 10 },
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
    <!-- 工具栏 -->
    <div class="rr__toolbar">
      <button class="rr__back" @click="router.push('/ai/reports')"><AppIcon name="arrow-left" size="sm" /> 返回列表</button>
      <span class="rr__title">{{ report?.title || '报告' }}</span>
      <span class="rr__sp"></span>
      <span v-if="report" class="rr__meta">{{ fmtFull(report.created_ts) }} · {{ report.model || '—' }}</span>
      <button class="rr__btn" @click="downloadMarkdown"><AppIcon name="download" size="sm" /> 导出</button>
      <button class="rr__btn rr__btn--primary" @click="askReport"><AppIcon name="chatter" size="sm" /> 追问此报告</button>
    </div>

    <div v-if="loading" class="rr__loading">
      <span class="rr__spinner"></span> 正在加载报告…
    </div>
    <div v-else-if="loadErr" class="rr__error">
      <AppIcon name="alert-circle" size="xl" />
      <p>{{ loadErr }}</p>
      <button class="rr__btn rr__btn--primary" @click="load(Number(route.params.id))">重试</button>
    </div>

    <div v-else-if="report" class="rr__body">
      <!-- 左目录 -->
      <aside class="rr__toc">
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
        <MarkdownView :content="report.content" />
      </article>

      <!-- 右操作 -->
      <aside class="rr__side">
        <div class="rr__card">
          <div class="rr__card-label">数据速览</div>
          <template v-if="hasStats">
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
          <div v-else class="rr__chart-empty">（该报告无统计数据）</div>
        </div>
        <div class="rr__card">
          <div class="rr__card-label">元信息</div>
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
          <button class="rr__side-btn" @click="askReport"><AppIcon name="chatter" size="sm" /> 基于此报告追问</button>
        </div>
        <div class="rr__card rr__card--warn">
          <AppIcon name="info" size="sm" />
          <span style="font-size:11.5px;line-height:1.6">本报告由 AI 自动生成，仅供参考，不构成投资建议。</span>
        </div>
      </aside>
    </div>
  </div>
</template>

<style scoped>
.rr { display: flex; flex-direction: column; gap: 14px; }
.rr__toolbar { display: flex; align-items: center; gap: 10px; flex-wrap: wrap; }
.rr__back { display: inline-flex; align-items: center; gap: 5px; border: 1px solid var(--ff-border, #e5e7eb); background: var(--ff-bg-surface, #fff); border-radius: 9px; padding: 7px 12px; font-size: 12.5px; font-weight: 600; color: var(--ff-text-2, #6b7280); cursor: pointer; }
.rr__back:hover { color: var(--ff-brand, #2f7d5b); border-color: var(--ff-border-brand, #9fc3b1); }
.rr__title { font-size: 15px; font-weight: 700; color: var(--ff-text-primary, #1f2937); }
.rr__sp { flex: 1; }
.rr__meta { font-size: 12px; color: var(--ff-text-3, #9ca3af); }
.rr__btn { display: inline-flex; align-items: center; gap: 5px; border: 1px solid var(--ff-border, #e5e7eb); background: var(--ff-bg-surface, #fff); border-radius: 9px; padding: 7px 13px; font-size: 12.5px; font-weight: 600; color: var(--ff-text-2, #6b7280); cursor: pointer; }
.rr__btn:hover { border-color: var(--ff-border-brand, #9fc3b1); color: var(--ff-brand, #2f7d5b); }
.rr__btn--primary { background: var(--ff-brand, #2f7d5b); color: #fff; border-color: var(--ff-brand, #2f7d5b); }
.rr__btn--primary:hover { background: var(--ff-brand-dark, #1d4e39); color: #fff; }
.rr__loading, .rr__error { text-align: center; padding: 70px 20px; color: var(--ff-text-3, #9ca3af); background: var(--ff-bg-surface, #fff); border: 1px solid var(--ff-border, #e5e7eb); border-radius: 13px; }
.rr__spinner { display: inline-block; width: 16px; height: 16px; border: 2px solid var(--ff-border, #e5e7eb); border-top-color: var(--ff-brand, #2f7d5b); border-radius: 50%; animation: rr-rot 0.8s linear infinite; vertical-align: middle; margin-right: 8px; }
@keyframes rr-rot { to { transform: rotate(360deg); } }
.rr__error p { font-size: 13.5px; margin: 10px 0 16px; color: var(--ff-down, #e5484d); }
.rr__body { display: grid; grid-template-columns: 200px minmax(0, 1fr) 210px; gap: 14px; align-items: start; }
.rr__toc { position: sticky; top: 14px; background: var(--ff-bg-surface, #fff); border: 1px solid var(--ff-border, #e5e7eb); border-radius: 13px; padding: 13px; max-height: calc(100vh - 260px); overflow-y: auto; }
.rr__toc-title { font-size: 11px; font-weight: 700; color: var(--ff-text-3, #8aa096); letter-spacing: .06em; margin-bottom: 8px; }
.rr__toc-item { display: block; width: 100%; text-align: left; border: none; background: none; padding: 6px 9px; border-radius: 7px; font-size: 12.5px; color: var(--ff-text-2, #6b7280); cursor: pointer; line-height: 1.4; }
.rr__toc-item:hover { background: var(--ff-bg-hover, #f3f6f4); }
.rr__toc-item.on { background: var(--ff-bg-brand-subtle, #eaf4ef); color: var(--ff-brand-dark, #1d4e39); font-weight: 600; }
.rr__toc-empty { font-size: 12px; color: var(--ff-text-3, #9ca3af); padding: 8px; }
.rr__content { background: var(--ff-bg-surface, #fff); border: 1px solid var(--ff-border, #e5e7eb); border-radius: 13px; padding: 26px 30px; max-height: calc(100vh - 260px); overflow-y: auto; }
.rr__h1 { font-size: 21px; font-weight: 700; letter-spacing: -0.01em; margin-bottom: 16px; color: var(--ff-text-primary, #1f2937); }
.rr__side { display: flex; flex-direction: column; gap: 12px; position: sticky; top: 14px; }
.rr__card { background: var(--ff-bg-surface, #fff); border: 1px solid var(--ff-border, #e5e7eb); border-radius: 12px; padding: 13px 14px; }
.rr__card--warn { background: #fef9ee; border-color: #f0dfb8; color: #92400e; display: flex; gap: 8px; align-items: flex-start; }
.rr__card-label { font-size: 11px; font-weight: 700; color: var(--ff-text-3, #8aa096); letter-spacing: .06em; margin-bottom: 8px; }
.rr__chart { margin-bottom: 8px; }
.rr__chart-title { font-size: 11.5px; font-weight: 600; color: var(--ff-text-2, #6b7280); margin-bottom: 2px; }
.rr__chart-note { font-size: 10.5px; color: var(--ff-text-3, #9ca3af); margin-top: 2px; line-height: 1.5; }
.rr__chart-empty { font-size: 12px; color: var(--ff-text-3, #9ca3af); padding: 8px 0; }
.rr__kv { display: flex; justify-content: space-between; font-size: 12.5px; padding: 3px 0; color: var(--ff-text-2, #6b7280); }
.rr__kv b { color: var(--ff-text-primary, #1f2937); font-family: var(--ff-font-mono, ui-monospace, monospace); }
.rr__side-btn { display: flex; align-items: center; gap: 7px; width: 100%; border: 1px solid var(--ff-border, #e5e7eb); background: var(--ff-bg-surface, #fff); border-radius: 8px; padding: 7px 11px; font-size: 12.5px; font-weight: 600; color: var(--ff-text-2, #6b7280); cursor: pointer; margin-bottom: 6px; }
.rr__side-btn:hover { border-color: var(--ff-border-brand, #9fc3b1); color: var(--ff-brand, #2f7d5b); }

@media (max-width: 1100px) {
  .rr__body { grid-template-columns: 1fr; }
  .rr__toc { position: static; max-height: none; display: flex; flex-wrap: wrap; gap: 4px; }
  .rr__toc-title { width: 100%; }
  .rr__side { position: static; flex-direction: row; flex-wrap: wrap; }
}
</style>
