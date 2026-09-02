<script setup>
/**
 * WorkbenchView — AI 报告中心（报告优先首页）
 * 最近报告为视觉主体 → 顶部「新建报告」入口（内含运行中任务）；支持来自快讯的 flash 快速分析。
 */
import { ref, computed, watch, onMounted, onBeforeUnmount } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useAiStore } from '../../store/ai'
import { toastSuccess, toastError } from '../../composables/useToast'
import AppIcon from '../../ui/AppIcon.vue'
import AppButton from '../../ui/AppButton.vue'
import AppSkeleton from '../../ui/AppSkeleton.vue'
import TaskProgress from '../../components/ai/TaskProgress.vue'
import OnboardWizard from '../../components/ai/OnboardWizard.vue'

const route = useRoute()
const router = useRouter()
const store = useAiStore()

const showWizard = ref(false)
const activeTask = computed(() => store.activeTask)

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

// 来自快讯的快速分析：跨模块携带 q 参数跳转至此，自动提交 flash 任务并留在本页看进度
let flashHandled = false
watch(
  () => route.query.q,
  async (v) => {
    if (!v || flashHandled) return
    flashHandled = true
    const newsId = Number(route.query.news_id) || null
    const r = await store.submitAnalysis({
      provider_id: store.status?.default_provider?.id,
      scope: store.config.scope,
      window: Number(store.config.window) || 24,
      focus: v,
      news_id: newsId,
      report_type: 'flash',
    })
    if (r.ok) {
      toastSuccess(r.queued ? '快讯分析已排队' : '快讯分析已提交')
    } else {
      toastError(r.error || '快讯分析提交失败')
    }
    // 不跳转、不清 query：进度由本页运行中任务卡 + startPolling 呈现，flashHandled 兜住重复触发
  },
  { immediate: true }
)
onBeforeUnmount(() => store.stopPolling())
</script>

<template>
  <div class="wb">
    <!-- 模块页头按产品要求移除，h1 保留 sr-only 保文档语义 -->
    <h1 class="ff-sr-only">报告中心</h1>

    <!-- 未配置模型横幅 -->
    <div v-if="!store.modelAvailable" class="wb__banner">
      <AppIcon name="alert-circle" size="md" />
      <div class="wb__banner-text">
        <b>尚未配置可用的大语言模型</b>
        <span>配置后即可生成每日复盘报告与 AI 分析</span>
      </div>
      <AppButton variant="secondary" size="sm" icon="settings" @click="showWizard = true">立即配置</AppButton>
    </div>

    <!-- 页头：新建报告主入口 -->
    <div class="wb__head">
      <h2 class="wb__head-title">最近报告</h2>
      <div class="wb__head-actions">
        <button class="wb__link" @click="router.push('/ai/reports')">全部报告 →</button>
        <AppButton variant="primary" icon="plus" @click="store.genOpen = true">新建报告</AppButton>
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

    <!-- 最近报告（视觉主体） -->
    <div v-if="store.reportsLoading" class="wb__empty">
      <AppSkeleton variant="text" :lines="4" />
    </div>
    <div v-else-if="store.reports.length" class="wb__grid">
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
        <span v-if="r.pinned" class="wb__report-status pin">置顶</span>
        <AppIcon name="chevron-right" size="sm" class="wb__report-arrow" />
      </div>
    </div>
    <div v-else class="wb__empty">
      <AppIcon name="file-text" size="xl" />
      <p>还没有研究报告</p>
      <AppButton variant="primary" icon="plus" @click="store.genOpen = true">新建第一份报告</AppButton>
    </div>

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
.wb__head { display: flex; align-items: center; justify-content: space-between; gap: 10px; flex-wrap: wrap; }
.wb__head-title { font-size: 17px; font-weight: 700; color: var(--ff-text-primary); margin: 0; }
.wb__head-actions { display: flex; align-items: center; gap: 10px; }
.wb__link { border: none; background: none; color: var(--ff-brand); font-size: 13px; font-weight: 600; cursor: pointer; }
.wb__banner { display: flex; align-items: center; gap: 12px; background: #fef7e6; border: 1px solid #f5d9a0; border-radius: 12px; padding: 13px 16px; color: #b45309; }
.wb__banner-text { display: flex; flex-direction: column; gap: 1px; font-size: 13px; flex: 1; }
.wb__banner-text b { font-size: 14px; }
.wb__banner-text span { color: #92400e; opacity: 0.85; }
.wb__task { background: var(--ff-bg-surface); border: 1px solid var(--ff-border-brand); border-radius: 13px; padding: 13px 16px; }
.wb__task-head { display: flex; align-items: center; gap: 10px; margin-bottom: 8px; }
.wb__task-badge { display: inline-flex; align-items: center; gap: 5px; font-size: 11.5px; font-weight: 700; color: var(--ff-brand-dark); background: var(--ff-bg-brand-subtle); padding: 3px 10px; border-radius: 10px; }
.wb__task-title { flex: 1; font-size: 13px; color: var(--ff-text-secondary); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.wb__task-link { border: none; background: none; color: var(--ff-brand); font-size: 12.5px; font-weight: 600; cursor: pointer; }
.wb__grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(300px, 1fr)); gap: 10px; }
.wb__report { display: flex; align-items: center; gap: 10px; padding: 11px 12px; border: 1px solid var(--ff-border); border-radius: 11px; cursor: pointer; transition: background-color var(--ff-dur-fast) var(--ff-ease-standard), border-color var(--ff-dur-fast) var(--ff-ease-standard); }
.wb__report:hover { border-color: var(--ff-border-brand); background: var(--ff-bg-brand-subtle); }
.wb__report-ic { color: var(--ff-brand); flex-shrink: 0; }
.wb__report-main { flex: 1; min-width: 0; }
.wb__report-title { font-size: 13px; font-weight: 600; color: var(--ff-text-primary); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.wb__report-meta { font-size: 11px; color: var(--ff-text-3); margin-top: 1px; }
.wb__report-status { font-size: 10.5px; color: var(--ff-brand); font-weight: 600; }
.wb__report-status.pin { color: var(--ff-brand); }
.wb__report-arrow { color: var(--ff-text-3); }
.wb__empty { text-align: center; padding: 30px 10px; color: var(--ff-text-3); }
.wb__empty p { font-size: 13px; margin: 8px 0 12px; }
</style>
