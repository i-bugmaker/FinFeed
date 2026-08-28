<script setup>
/**
 * TasksView — 任务中心
 * 全部/进行中/已完成/失败 筛选；阶段进度；取消/重试/批量重试；日志抽屉。
 */
import { ref, computed, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { useAiStore } from '../../store/ai'
import AppIcon from '../../ui/AppIcon.vue'
import TaskProgress from '../../components/ai/TaskProgress.vue'
import MarkdownView from '../../components/ai/MarkdownView.vue'

const router = useRouter()
const store = useAiStore()

const tab = ref('all')
const logTask = ref(null)
const showLog = ref(false)
const busy = ref(false)

const tabs = [
  { key: 'all', label: '全部' },
  { key: 'running', label: '进行中' },
  { key: 'success', label: '已完成' },
  { key: 'failed', label: '失败' },
]

const filtered = computed(() => {
  if (tab.value === 'all') return store.tasks
  return store.tasks.filter((t) => t.status === tab.value)
})
const failedCount = computed(() => store.tasks.filter((t) => t.status === 'failed').length)

// REDUCE 流式预览：仅当订阅中的任务处于汇总阶段且有增量时展示
// （订阅跨视图保持存活：离开再回来正文不丢，done 事件自动刷新任务与报告）
const streamingTaskId = computed(() => store.streamTaskId)
const streamText = computed(() => store.taskStreamText)
const showStream = computed(() => {
  const t = store.activeTask
  return !!(t && t.task_id === streamingTaskId.value && t.stage === 'reduce' && streamText.value)
})

const STATUS_META = {
  pending: { label: '排队中', cls: 'run' },
  running: { label: '进行中', cls: 'run' },
  success: { label: '完成', cls: 'ok' },
  failed: { label: '失败', cls: 'bad' },
  cancelled: { label: '已取消', cls: 'idle' },
}

function fmtTime(ts) {
  if (!ts) return ''
  return new Date(ts * 1000).toLocaleString('zh-CN', { month: 'numeric', day: 'numeric', hour: '2-digit', minute: '2-digit' })
}

async function onRetry(t) {
  const r = await store.retryTask(t.task_id)
  if (!r.ok) window.alert(r.error || '重试失败')
}
async function retryAllFailed() {
  const fails = store.tasks.filter((t) => t.status === 'failed')
  if (!fails.length) return
  if (!window.confirm(`重新提交 ${fails.length} 个失败任务？`)) return
  busy.value = true
  for (const t of fails) await store.retryTask(t.task_id)
  busy.value = false
}

onMounted(() => {
  store.loadTasks()
  store.startPolling()
})
</script>

<template>
  <div class="tv">
    <header class="ff-page__header">
      <div class="ff-page__heading">
        <h1 class="ff-page__title">任务中心</h1>
        <p class="ff-page__desc">
          AI 分析任务的执行状态与进度{{ failedCount ? ` · ${failedCount} 个失败可重试` : '' }}
        </p>
      </div>
    </header>

    <div class="tv__bar">
      <div class="tv__tabs">
        <button v-for="t in tabs" :key="t.key" class="tv__tab" :class="{ on: tab === t.key }" @click="tab = t.key">
          {{ t.label }}
        </button>
      </div>
      <span class="tv__sp"></span>
      <button v-if="failedCount" class="tv__retry-all" :disabled="busy" @click="retryAllFailed">
        <AppIcon name="refresh" size="sm" /> 批量重试失败（{{ failedCount }}）
      </button>
    </div>

    <div v-if="filtered.length" class="tv__list">
      <div v-for="t in filtered" :key="t.task_id" class="tv__item">
        <div class="tv__row">
          <span class="tv__badge" :class="STATUS_META[t.status]?.cls || 'idle'">
            <span class="tv__dot" :class="STATUS_META[t.status]?.cls || 'idle'"></span>
            {{ STATUS_META[t.status]?.label || t.status }}
          </span>
          <span class="tv__name">{{ t.provider_name || '分析' }} · {{ store.scopeLabel(t.scope) }} / {{ t.hours || 24 }} 小时</span>
          <span v-if="t.model" class="tv__model">{{ t.model }}</span>
          <span class="tv__sp"></span>
          <span class="tv__time">{{ fmtTime(t.created_ts) }}</span>
          <span class="tv__elapsed">{{ t.elapsed ? t.elapsed.toFixed(1) + 's' : '' }}</span>
        </div>

        <!-- 运行中：阶段进度 + REDUCE 流式预览 -->
        <div v-if="t.status === 'running' || t.status === 'pending'" class="tv__progress">
          <TaskProgress :task="t" />
          <div class="tv__ops">
            <button class="tv__op tv__op--danger" @click="store.cancelTask(t.task_id)">取消</button>
          </div>
          <div v-if="t.task_id === streamingTaskId && streamText" class="tv__stream">
            <div class="tv__stream-head">
              <span class="tv__stream-dot"></span>
              实时生成中 · {{ streamText.length }} 字
            </div>
            <MarkdownView :content="streamText" compact class="tv__stream-body" />
          </div>
        </div>

        <!-- 完成：跳转报告 -->
        <div v-else-if="t.status === 'success'" class="tv__done">
          <span class="tv__msg">{{ t.message }}</span>
          <button v-if="t.report_id" class="tv__op tv__op--link" @click="router.push('/ai/reports/' + t.report_id)">查看报告 →</button>
        </div>

        <!-- 失败：错误 + 重试 + 日志 -->
        <div v-else-if="t.status === 'failed'" class="tv__fail">
          <span class="tv__errmsg">错误：{{ t.error || t.message }}</span>
          <div class="tv__ops">
            <button class="tv__op" @click="onRetry(t)"><AppIcon name="refresh" size="sm" /> 重试</button>
            <button class="tv__op" @click="logTask = t; showLog = true"><AppIcon name="rows" size="sm" /> 日志</button>
          </div>
        </div>

        <div v-else class="tv__msg">{{ t.message }}</div>
      </div>
    </div>

    <div v-else class="tv__empty">
      <AppIcon name="activity" size="xl" />
      <p>{{ tab === 'all' ? '暂无分析任务' : '该分类下没有任务' }}</p>
      <p class="tv__empty-sub">在工作台点击「生成每日复盘」创建首个任务</p>
    </div>

    <!-- 日志抽屉 -->
    <Teleport to="body">
      <Transition name="tv-fade">
        <div v-if="showLog" class="tv__mask" @click.self="showLog = false">
          <div class="tv__log">
            <div class="tv__log-head">
              <span>任务日志 · {{ logTask?.task_id }}</span>
              <button class="tv__log-x" @click="showLog = false"><AppIcon name="x" size="sm" /></button>
            </div>
            <div class="tv__log-body">
              <div class="tv__log-kv"><span>状态</span><b>{{ logTask?.status }}</b></div>
              <div class="tv__log-kv"><span>阶段</span><b>{{ logTask?.stage_label || logTask?.stage }}</b></div>
              <div class="tv__log-kv"><span>错误</span><b>{{ logTask?.error || '—' }}</b></div>
              <div class="tv__log-kv"><span>创建</span><b>{{ fmtTime(logTask?.created_ts) }}</b></div>
              <div class="tv__log-kv"><span>耗时</span><b>{{ logTask?.elapsed ? logTask.elapsed.toFixed(1) + 's' : '—' }}</b></div>
            </div>
          </div>
        </div>
      </Transition>
    </Teleport>
  </div>
</template>

<style scoped>
.tv { display: flex; flex-direction: column; gap: 14px; }
.tv__bar { display: flex; align-items: center; gap: 10px; flex-wrap: wrap; }
.tv__tabs { display: flex; gap: 4px; background: var(--ff-bg-subtle); border-radius: 10px; padding: 3px; }
.tv__tab { border: none; background: none; border-radius: 8px; padding: 6px 15px; font-size: 13px; font-weight: 600; color: var(--ff-text-2); cursor: pointer; }
.tv__tab.on { background: var(--ff-bg-surface); color: var(--ff-brand-dark); box-shadow: 0 1px 3px rgba(16, 40, 30, 0.12); }
.tv__sp { flex: 1; }
.tv__retry-all { display: inline-flex; align-items: center; gap: 6px; border: 1px solid var(--ff-up-border); background: var(--ff-up-subtle); color: var(--ff-up); border-radius: 9px; padding: 7px 13px; font-size: 12.5px; font-weight: 600; cursor: pointer; }
.tv__retry-all:disabled { opacity: 0.5; }
.tv__list { display: flex; flex-direction: column; gap: 10px; }
.tv__item { background: var(--ff-bg-surface); border: 1px solid var(--ff-border); border-radius: 12px; padding: 14px 16px; }
.tv__row { display: flex; align-items: center; gap: 10px; flex-wrap: wrap; }
.tv__badge { display: inline-flex; align-items: center; gap: 6px; font-size: 11.5px; font-weight: 700; padding: 3px 10px; border-radius: 10px; }
.tv__badge.ok { background: var(--ff-down-subtle); color: var(--ff-down); }
.tv__badge.bad { background: var(--ff-up-subtle); color: var(--ff-up); }
.tv__badge.run { background: var(--ff-bg-brand-subtle); color: var(--ff-brand-dark); }
.tv__badge.idle { background: var(--ff-bg-subtle); color: var(--ff-text-3); }
.tv__dot { width: 7px; height: 7px; border-radius: 50%; }
.tv__dot.ok { background: var(--ff-down); }
.tv__dot.bad { background: var(--ff-up); }
.tv__dot.run { background: var(--ff-brand); animation: tv-pulse 1.2s infinite; }
.tv__dot.idle { background: var(--ff-text-3); }
@keyframes tv-pulse { 0%,100% { opacity: 1; } 50% { opacity: 0.35; } }
.tv__name { font-size: 13.5px; font-weight: 600; color: var(--ff-text-primary); }
.tv__model { font-size: 11.5px; color: var(--ff-text-3); font-family: var(--ff-font-mono, ui-monospace, monospace); }
.tv__time, .tv__elapsed { font-size: 11.5px; color: var(--ff-text-3); }
.tv__progress { margin-top: 12px; }
.tv__stream { margin-top: 10px; border: 1px dashed var(--ff-border-brand); border-radius: 10px; background: var(--ff-bg-subtle); overflow: hidden; }
.tv__stream-head { display: flex; align-items: center; gap: 7px; font-size: 12px; font-weight: 600; color: var(--ff-brand-dark); padding: 8px 12px; background: var(--ff-bg-brand-subtle); }
.tv__stream-dot { width: 7px; height: 7px; border-radius: 50%; background: var(--ff-brand); animation: tv-pulse 1.2s infinite; }
.tv__stream-body { max-height: 320px; overflow-y: auto; padding: 4px 12px 10px; }
.tv__done { display: flex; align-items: center; justify-content: space-between; gap: 10px; margin-top: 8px; }
.tv__fail { display: flex; align-items: center; justify-content: space-between; gap: 10px; margin-top: 8px; flex-wrap: wrap; }
.tv__msg { font-size: 12.5px; color: var(--ff-text-2); }
.tv__errmsg { font-size: 12.5px; color: var(--ff-up); }
.tv__ops { display: flex; gap: 6px; }
.tv__op { display: inline-flex; align-items: center; gap: 5px; border: 1px solid var(--ff-border); background: var(--ff-bg-surface); border-radius: 8px; padding: 6px 12px; font-size: 12px; font-weight: 600; color: var(--ff-text-2); cursor: pointer; }
.tv__op:hover { border-color: var(--ff-border-brand); color: var(--ff-brand); }
.tv__op--danger { color: var(--ff-up); border-color: var(--ff-up-border); }
.tv__op--link { color: var(--ff-brand); border-color: var(--ff-border-brand); }
.tv__empty { text-align: center; padding: 60px 20px; color: var(--ff-text-3); background: var(--ff-bg-surface); border: 1px dashed var(--ff-border); border-radius: 13px; }
.tv__empty p { font-size: 14px; margin: 10px 0 4px; }
.tv__empty-sub { font-size: 12px !important; margin: 0 !important; }
.tv__mask { position: fixed; inset: 0; z-index: 900; background: rgba(15, 25, 20, 0.35); display: flex; align-items: flex-end; justify-content: flex-end; }
.tv__log { width: 420px; max-width: 90vw; height: 100%; background: var(--ff-bg-surface); padding: 16px; box-shadow: -8px 0 24px rgba(10, 30, 22, 0.15); }
.tv__log-head { display: flex; align-items: center; justify-content: space-between; font-size: 14px; font-weight: 700; margin-bottom: 14px; }
.tv__log-x { border: none; background: var(--ff-bg-subtle); border-radius: 8px; width: 30px; height: 30px; cursor: pointer; color: var(--ff-text-2); }
.tv__log-kv { display: flex; gap: 12px; padding: 8px 0; border-bottom: 1px dashed var(--ff-border); font-size: 13px; }
.tv__log-kv span { color: var(--ff-text-3); width: 48px; flex-shrink: 0; }
.tv__log-kv b { color: var(--ff-text-primary); word-break: break-all; font-weight: 600; }
.tv-fade-enter-active, .tv-fade-leave-active { transition: opacity 180ms; }
.tv-fade-enter-from, .tv-fade-leave-to { opacity: 0; }
</style>
