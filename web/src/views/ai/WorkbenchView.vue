<script setup>
/**
 * WorkbenchView — AI 投研工作台（入口页）
 * 服务状态 → 快捷指令 → KPI → 运行中任务 → 最近报告 → 今日洞察
 */
import { ref, computed, onMounted, onBeforeUnmount } from 'vue'
import { useRouter } from 'vue-router'
import { useAiStore } from '../../store/ai'
import AppIcon from '../../ui/AppIcon.vue'
import TaskProgress from '../../components/ai/TaskProgress.vue'
import OnboardWizard from '../../components/ai/OnboardWizard.vue'

const router = useRouter()
const store = useAiStore()

const showWizard = ref(false)
const generating = ref(false)
const genMsg = ref('')

const quickActions = [
  { icon: 'zap', title: '生成复盘', desc: '一键产出当日复盘报告', to: '/ai/tasks', act: 'generate' },
  { icon: 'target', title: '解读个股', desc: '@ 标的深度分析', to: '/ai/analyst' },
  { icon: 'chatter', title: '追问行情', desc: '基于快讯与报告问答', to: '/ai/analyst' },
  { icon: 'settings', title: 'AI 设置', desc: '模型与 Prompt 配置', to: '/ai/settings' },
]

const todayReports = computed(() => {
  const today = new Date().toDateString()
  return store.reports.filter((r) => new Date((r.created_ts || 0) * 1000).toDateString() === today).length
})

const activeTask = computed(() => store.activeTask)

function summaryOf(content) {
  const c = content || ''
  const m = c.match(/(?:摘要|核心结论|结论)[：:]\s*\n?([^\n]+(?:\n[^\n]+){0,3})/i)
  if (m) return m[1].trim().slice(0, 140)
  return c.split(/\n{2,}/).find((p) => p.trim())?.slice(0, 140) || '（暂无内容）'
}

function go(action, to) {
  if (action === 'generate') {
    generate()
  } else {
    router.push(to)
  }
}

async function generate() {
  if (generating.value) return
  generating.value = true
  genMsg.value = ''
  try {
    // 使用设置页保存的分析默认值
    const r = await store.submitAnalysis({
      provider_id: store.status?.default_provider?.id,
      scope: store.config.scope,
      window: Number(store.config.window) || 24,
      focus: store.config.focus || '',
    })
    if (r.ok) {
      genMsg.value = `已提交分析任务（${r.task_id}），可在任务中心查看进度`
      router.push('/ai/tasks')
    } else {
      genMsg.value = r.error || '提交失败'
      // 未配置模型 → 弹出向导
      if (!store.modelAvailable) showWizard.value = true
    }
  } catch (e) {
    genMsg.value = '失败：' + (e.message || e)
  } finally {
    generating.value = false
  }
}

function fmtTime(ts) {
  if (!ts) return ''
  const d = new Date(ts * 1000)
  return `${String(d.getHours()).padStart(2, '0')}:${String(d.getMinutes()).padStart(2, '0')}`
}
function fmtDate(ts) {
  if (!ts) return ''
  return new Date(ts * 1000).toLocaleDateString('zh-CN', { month: 'numeric', day: 'numeric' })
}

onMounted(() => {
  store.loadConfig()
  store.loadInit()
  store.loadReports({ limit: 6 })
  store.loadTasks()
  store.startPolling()
})
onBeforeUnmount(() => store.stopPolling())
</script>

<template>
  <div class="wb">
    <!-- 未配置模型横幅 -->
    <div v-if="!store.modelAvailable" class="wb__banner">
      <AppIcon name="alert-circle" size="md" />
      <div class="wb__banner-text">
        <b>尚未配置可用的大语言模型</b>
        <span>配置后即可生成每日复盘报告与 AI 分析</span>
      </div>
      <button class="wb__banner-btn" @click="showWizard = true">立即配置</button>
    </div>

    <!-- 快捷指令 -->
    <div class="wb__actions">
      <button v-for="a in quickActions" :key="a.title" class="wb__act" @click="go(a.act, a.to)">
        <span class="wb__act-ic"><AppIcon :name="a.icon" size="md" /></span>
        <span class="wb__act-title">{{ a.title }}</span>
        <span class="wb__act-desc">{{ a.desc }}</span>
      </button>
    </div>

    <!-- KPI 行 -->
    <div class="wb__kpis">
      <div class="wb__kpi">
        <div class="wb__kpi-label">今日报告</div>
        <div class="wb__kpi-num">{{ todayReports }}<small> 篇</small></div>
        <div class="wb__kpi-sub">全部 {{ store.reportsTotal }}</div>
      </div>
      <div class="wb__kpi">
        <div class="wb__kpi-label">运行中任务</div>
        <div class="wb__kpi-num">{{ store.runningTasks.length }}<small> 个</small></div>
        <div class="wb__kpi-sub">{{ activeTask ? '预计 ' + Math.max(10, Math.round((activeTask.progress || 10) / 10) * 10) + 's 完成' : '当前空闲' }}</div>
      </div>
      <div class="wb__kpi">
        <div class="wb__kpi-label">默认模型</div>
        <div class="wb__kpi-num" style="font-size:15px">{{ store.status?.default_provider?.name || '未配置' }}</div>
        <div class="wb__kpi-sub">{{ store.status?.default_provider?.model || '—' }}</div>
      </div>
      <div class="wb__kpi">
        <div class="wb__kpi-label">数据窗口</div>
        <div class="wb__kpi-num" style="font-size:15px">{{ store.config.window || 24 }}<small> 小时</small></div>
        <div class="wb__kpi-sub">{{ store.scopeLabel(store.config.scope) }}</div>
      </div>
    </div>

    <!-- 运行中任务 -->
    <div v-if="activeTask" class="wb__task">
      <div class="wb__task-head">
        <span class="wb__task-badge"><AppIcon name="activity" size="xs" /> 进行中</span>
        <span class="wb__task-title">{{ activeTask.provider_name || '' }} · {{ activeTask.message || '分析中' }}</span>
        <button class="wb__task-link" @click="router.push('/ai/tasks')">查看详情 →</button>
      </div>
      <TaskProgress :task="activeTask" />
    </div>

    <!-- 主区：最近报告 + 今日洞察 -->
    <div class="wb__cols">
      <div class="wb__card wb__reports">
        <div class="wb__card-head">
          <h3 class="wb__card-title">最近报告</h3>
          <button class="wb__card-more" @click="router.push('/ai/reports')">全部 →</button>
        </div>
        <div v-if="store.reports.length" class="wb__list">
          <div
            v-for="r in store.reports"
            :key="r.id"
            class="wb__report"
            @click="router.push('/ai/reports/' + r.id)"
          >
            <span class="wb__report-ic"><AppIcon name="file-text" size="sm" /></span>
            <div class="wb__report-main">
              <div class="wb__report-title">{{ r.title || '报告 #' + r.id }}</div>
              <div class="wb__report-meta">{{ fmtDate(r.created_ts) }} {{ fmtTime(r.created_ts) }} · {{ r.model || '—' }}</div>
            </div>
            <span class="wb__report-status" :class="r.pinned ? 'pin' : ''">{{ r.pinned ? '置顶' : '' }}</span>
            <AppIcon name="chevron-right" size="sm" class="wb__report-arrow" />
          </div>
        </div>
        <div v-else class="wb__empty">
          <AppIcon name="file-text" size="xl" />
          <p>还没有研究报告</p>
          <button class="wb__empty-btn" @click="generate">生成第一份复盘</button>
        </div>
      </div>

      <div class="wb__cols-right">
        <div v-if="store.reports[0]" class="wb__card">
          <div class="wb__card-head"><h3 class="wb__card-title">最新洞察</h3></div>
          <p class="wb__insight">{{ summaryOf(store.reports[0].content) }}</p>
          <button class="wb__insight-link" @click="router.push('/ai/reports/' + store.reports[0].id)">查看完整报告 →</button>
        </div>
        <div class="wb__card">
          <div class="wb__card-head"><h3 class="wb__card-title">快捷帮助</h3></div>
          <ul class="wb__help">
            <li><span class="kbd">Ctrl</span>+<span class="kbd">K</span> 命令面板</li>
            <li><span class="kbd">Ctrl</span>+<span class="kbd">↵</span> 发送消息</li>
            <li>输入 <code>@标的</code> 引用证券</li>
            <li>输入 <code>/复盘</code> 快速生成</li>
          </ul>
        </div>
      </div>
    </div>

    <p v-if="genMsg" class="wb__genmsg" :class="{ err: !genMsg.includes('已提交') }">{{ genMsg }}</p>

    <OnboardWizard
      :open="showWizard"
      :presets="store.presets"
      @close="showWizard = false"
      @done="showWizard = false; store.loadInit(); store.loadProviders()"
    />
  </div>
</template>

<style scoped>
.wb { display: flex; flex-direction: column; gap: 16px; }
.wb__banner { display: flex; align-items: center; gap: 12px; background: #fef7e6; border: 1px solid #f5d9a0; border-radius: 12px; padding: 13px 16px; color: #b45309; }
.wb__banner-text { display: flex; flex-direction: column; gap: 1px; font-size: 13px; flex: 1; }
.wb__banner-text b { font-size: 14px; }
.wb__banner-text span { color: #92400e; opacity: 0.85; }
.wb__banner-btn { height: 30px; padding: 0 14px; border-radius: 8px; border: none; background: #d97706; color: #fff; font-size: 12.5px; font-weight: 600; cursor: pointer; }
.wb__actions { display: grid; grid-template-columns: repeat(4, 1fr); gap: 12px; }
.wb__act { display: flex; flex-direction: column; align-items: flex-start; gap: 4px; background: var(--ff-bg-surface, #fff); border: 1px solid var(--ff-border, #e5e7eb); border-radius: 13px; padding: 14px 16px; cursor: pointer; text-align: left; transition: background-color var(--ff-dur-fast) var(--ff-ease-standard), border-color var(--ff-dur-fast) var(--ff-ease-standard), color var(--ff-dur-fast) var(--ff-ease-standard), box-shadow var(--ff-dur-fast) var(--ff-ease-standard), transform var(--ff-dur-fast) var(--ff-ease-standard); }
.wb__act:hover { border-color: var(--ff-border-brand, #9fc3b1); transform: translateY(-1px); box-shadow: 0 4px 14px rgba(16, 40, 30, 0.08); }
.wb__act-ic { width: 34px; height: 34px; border-radius: 10px; background: var(--ff-bg-brand-subtle, #eaf4ef); color: var(--ff-brand, #2f7d5b); display: flex; align-items: center; justify-content: center; margin-bottom: 4px; }
.wb__act-title { font-size: 14px; font-weight: 700; color: var(--ff-text-primary, #1f2937); }
.wb__act-desc { font-size: 11.5px; color: var(--ff-text-3, #9ca3af); }
.wb__kpis { display: grid; grid-template-columns: repeat(4, 1fr); gap: 12px; }
.wb__kpi { background: var(--ff-bg-surface, #fff); border: 1px solid var(--ff-border, #e5e7eb); border-radius: 13px; padding: 13px 16px; }
.wb__kpi-label { font-size: 11px; font-weight: 700; color: var(--ff-text-3, #8aa096); letter-spacing: .05em; }
.wb__kpi-num { font-family: var(--ff-font-mono, ui-monospace, monospace); font-size: 22px; font-weight: 700; margin: 4px 0 2px; color: var(--ff-text-primary, #1f2937); }
.wb__kpi-num small { font-size: 11px; color: var(--ff-text-3, #9ca3af); font-weight: 500; font-family: var(--ff-sans, sans-serif); }
.wb__kpi-sub { font-size: 11.5px; color: var(--ff-text-3, #9ca3af); }
.wb__task { background: var(--ff-bg-surface, #fff); border: 1px solid var(--ff-border-brand, #bfd9cc); border-radius: 13px; padding: 13px 16px; }
.wb__task-head { display: flex; align-items: center; gap: 10px; margin-bottom: 8px; }
.wb__task-badge { display: inline-flex; align-items: center; gap: 5px; font-size: 11.5px; font-weight: 700; color: var(--ff-brand-dark, #1d4e39); background: var(--ff-bg-brand-subtle, #eaf4ef); padding: 3px 10px; border-radius: 10px; }
.wb__task-title { flex: 1; font-size: 13px; color: var(--ff-text-secondary, #6b7280); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.wb__task-link { border: none; background: none; color: var(--ff-brand, #2f7d5b); font-size: 12.5px; font-weight: 600; cursor: pointer; }
.wb__cols { display: grid; grid-template-columns: 1.6fr 1fr; gap: 16px; align-items: start; }
.wb__cols-right { display: flex; flex-direction: column; gap: 16px; }
.wb__card { background: var(--ff-bg-surface, #fff); border: 1px solid var(--ff-border, #e5e7eb); border-radius: 13px; padding: 15px 16px; }
.wb__card-head { display: flex; align-items: center; justify-content: space-between; margin-bottom: 11px; }
.wb__card-title { font-size: 14.5px; font-weight: 700; color: var(--ff-text-primary, #1f2937); }
.wb__card-more { border: none; background: none; color: var(--ff-brand, #2f7d5b); font-size: 12.5px; font-weight: 600; cursor: pointer; }
.wb__list { display: flex; flex-direction: column; gap: 6px; }
.wb__report { display: flex; align-items: center; gap: 10px; padding: 9px 10px; border: 1px solid var(--ff-border, #e5e7eb); border-radius: 10px; cursor: pointer; transition: background-color var(--ff-dur-fast) var(--ff-ease-standard), border-color var(--ff-dur-fast) var(--ff-ease-standard), color var(--ff-dur-fast) var(--ff-ease-standard), box-shadow var(--ff-dur-fast) var(--ff-ease-standard), transform var(--ff-dur-fast) var(--ff-ease-standard); }
.wb__report:hover { border-color: var(--ff-border-brand, #9fc3b1); background: var(--ff-bg-brand-subtle, #f4faf7); }
.wb__report-ic { color: var(--ff-brand, #2f7d5b); flex-shrink: 0; }
.wb__report-main { flex: 1; min-width: 0; }
.wb__report-title { font-size: 13px; font-weight: 600; color: var(--ff-text-primary, #1f2937); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.wb__report-meta { font-size: 11px; color: var(--ff-text-3, #9ca3af); margin-top: 1px; }
.wb__report-status { font-size: 10.5px; color: var(--ff-brand, #2f7d5b); font-weight: 600; }
.wb__report-arrow { color: var(--ff-text-3, #c3cdc8); }
.wb__empty { text-align: center; padding: 26px 10px; color: var(--ff-text-3, #9ca3af); }
.wb__empty p { font-size: 13px; margin: 8px 0 12px; }
.wb__empty-btn { border: none; background: var(--ff-brand, #2f7d5b); color: #fff; border-radius: 9px; padding: 8px 16px; font-size: 12.5px; font-weight: 600; cursor: pointer; }
.wb__insight { font-size: 13px; line-height: 1.7; color: var(--ff-text-secondary, #6b7280); }
.wb__insight-link { border: none; background: none; color: var(--ff-brand, #2f7d5b); font-size: 12.5px; font-weight: 600; cursor: pointer; margin-top: 6px; }
.wb__help { list-style: none; padding: 0; margin: 0; display: flex; flex-direction: column; gap: 8px; font-size: 12.5px; color: var(--ff-text-secondary, #6b7280); }
.wb__help code { font-family: var(--ff-font-mono, ui-monospace, monospace); font-size: 11.5px; background: var(--ff-bg-subtle, #f3f4f6); padding: 1px 5px; border-radius: 4px; }
.wb__genmsg { font-size: 12.5px; color: var(--ff-brand, #2f7d5b); }
.wb__genmsg.err { color: var(--ff-down, #e5484d); }

@media (max-width: 1024px) {
  .wb__actions { grid-template-columns: repeat(2, 1fr); }
  .wb__kpis { grid-template-columns: repeat(2, 1fr); }
  .wb__cols { grid-template-columns: 1fr; }
}
</style>
