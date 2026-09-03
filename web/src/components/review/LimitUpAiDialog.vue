<script setup>
/**
 * LimitUpAiDialog — 连板天梯「AI 分析」结果弹窗
 *
 * 调用系统已配置的大模型（默认取默认配置，可临时切换其他已配置模型），
 * 对当日涨跌停盘面做一次性结构化分析：情绪周期定位 / 涨停概念分类 /
 * 真跌停专项 / 潜在行情发掘 / 风险提示。
 *
 * 传输协议：POST /api/llm/insight/limitup 提交任务 → SSE 增量渲染 →
 * 任务查询取回权威全文。同一交易日结果服务端有缓存，重复打开秒开，
 * 需重新解读时点「重新分析」绕过缓存。
 */
import { ref, computed, watch, onUnmounted } from 'vue'
import AppModal from '../../ui/AppModal.vue'
import AppButton from '../../ui/AppButton.vue'
import AppSelect from '../../ui/AppSelect.vue'
import AppIcon from '../../ui/AppIcon.vue'
import MarkdownView from '../ai/MarkdownView.vue'
import { api } from '../../api/client'

const props = defineProps({
  modelValue: { type: Boolean, default: false },
  // 数据日期（YYYY-MM-DD）；为空由后端取当日
  date: { type: String, default: '' },
  // 历史归档报告（{ id, content, stats, model, elapsed, title }）：非空时只读展示，不触发新任务
  archived: { type: Object, default: null },
})

const emit = defineEmits(['update:modelValue'])

// 任务状态：idle 未开始 / running 进行中 / done 完成 / error 失败
const status = ref('idle')
const content = ref('')
const errorMsg = ref('')
const stageText = ref('')
const meta = ref(null)
const modelName = ref('')
const elapsed = ref(0)
const taskId = ref('')
const copied = ref(false)
// 历史归档只读模式标识（用于展示「查看历史」提示条与切回实时分析）
const archivedMode = ref(false)

const providers = ref([])
const providersLoaded = ref(false)
const providerId = ref('') // '' = 系统默认配置

let unsubscribe = null

const providerOptions = computed(() => [
  { label: '系统默认模型', value: '' },
  ...providers.value
    .filter((p) => p.enabled !== false)
    .map((p) => ({ label: `${p.name} · ${p.model}`, value: p.id })),
])

const running = computed(() => status.value === 'running')

// 元信息摘要（数据口径提示条）
const metaChips = computed(() => {
  const m = meta.value
  if (!m) return []
  const out = []
  if (m.date) out.push({ label: '数据日期', value: m.date })
  if (typeof m.limit_up_total === 'number') out.push({ label: '涨停', value: m.limit_up_total, tone: 'up' })
  if (typeof m.real_down_total === 'number') out.push({ label: '真跌停', value: m.real_down_total, tone: 'down' })
  if (typeof m.down_total === 'number') out.push({ label: '跌停池', value: m.down_total, tone: 'down' })
  if (typeof m.broken_total === 'number') out.push({ label: '炸板', value: m.broken_total })
  if (typeof m.max_height === 'number') out.push({ label: '最高连板', value: `${m.max_height}板` })
  return out
})

async function loadProviders() {
  if (providersLoaded.value) return
  try {
    const res = await api.providers()
    providers.value = (res && res.providers) || []
    providersLoaded.value = true
  } catch {
    providers.value = []
  }
}

function closeStream() {
  if (unsubscribe) {
    unsubscribe()
    unsubscribe = null
  }
}

async function start(refresh = false) {
  closeStream()
  archivedMode.value = false
  status.value = 'running'
  content.value = ''
  errorMsg.value = ''
  stageText.value = '正在装配盘面数据…'
  meta.value = null
  modelName.value = ''
  elapsed.value = 0
  copied.value = false

  try {
    const payload = { refresh }
    if (props.date) payload.date = props.date
    if (providerId.value !== '' && providerId.value != null) payload.provider_id = providerId.value

    const res = await api.insightLimitUp(payload)
    if (!res || !res.ok) {
      status.value = 'error'
      errorMsg.value = (res && res.error) || '分析任务提交失败'
      return
    }

    const task = res.task || {}
    taskId.value = res.task_id || ''
    if (task.meta) meta.value = task.meta
    if (task.model) modelName.value = task.model

    // 命中服务端缓存：直接落地结果，无需订阅流
    if (res.cached || task.status === 'success') {
      content.value = task.content || ''
      elapsed.value = task.elapsed || 0
      status.value = 'done'
      return
    }

    unsubscribe = api.insightStream(taskId.value, {
      onStage: (d) => {
        stageText.value = d.stage_label || d.message || '分析中…'
      },
      onDelta: (text) => {
        content.value += text
        stageText.value = '正在生成分析结论…'
      },
      onReset: () => {
        content.value = ''
      },
      onDone: (d) => finalize(d),
      onError: () => {
        /* EventSource 自动重连，忽略瞬时错误 */
      },
    })
  } catch (e) {
    status.value = 'error'
    errorMsg.value = e?.message || '分析任务提交失败'
  }
}

async function finalize(done) {
  closeStream()
  if (done && (done.status === 'failed' || done.status === 'cancelled')) {
    status.value = done.status === 'cancelled' ? 'idle' : 'error'
    errorMsg.value = done.error || '分析失败'
    content.value = ''
    return
  }
  // 以服务端任务状态为准取回全文，避免增量丢帧导致内容残缺
  try {
    const res = await api.insightTask(taskId.value)
    const task = (res && res.task) || {}
    content.value = task.content || content.value
    if (task.meta) meta.value = task.meta
    if (task.model) modelName.value = task.model
    elapsed.value = task.elapsed || 0
    status.value = task.status === 'success' ? 'done' : 'error'
    if (task.status !== 'success') errorMsg.value = task.error || '分析未完成'
  } catch (e) {
    status.value = content.value ? 'done' : 'error'
    if (!content.value) errorMsg.value = e?.message || '结果获取失败'
  }
}

async function stop() {
  if (taskId.value) {
    try {
      await api.insightCancel(taskId.value)
    } catch { /* 忽略取消失败 */ }
  }
  closeStream()
  status.value = 'idle'
  content.value = ''
  stageText.value = ''
}

// 只读展示一份历史归档报告（不触发新任务）
function renderArchived(report) {
  closeStream()
  archivedMode.value = true
  status.value = 'done'
  content.value = report.content || ''
  meta.value = report.stats || report.meta || null
  modelName.value = report.model || ''
  elapsed.value = report.elapsed || 0
  copied.value = false
}

// 从历史查看切回实时分析
function enterLive() {
  loadProviders()
  start(true)
}

// 首次打开：有历史归档则只读展示；否则自动发起实时分析（同日命中缓存瞬时返回）
watch(
  () => props.modelValue,
  async (open) => {
    if (!open) return
    await loadProviders()
    if (props.archived && props.archived.content) {
      renderArchived(props.archived)
      return
    }
    start(false)
  },
)

async function copyResult() {
  if (!content.value) return
  try {
    await navigator.clipboard.writeText(content.value)
    copied.value = true
    setTimeout(() => (copied.value = false), 1600)
  } catch {
    copied.value = false
  }
}

// 导出：将结论（Markdown 全文 + 口径元信息头）下载为 .md 文件
function exportResult() {
  if (!content.value) return
  const date = (meta.value && meta.value.date) || props.date || ''
  const stamp = new Date().toLocaleString('zh-CN', { hour12: false })
  const metaLines = [
    '---',
    `数据日期：${date || '--'}`,
    modelName.value ? `模型：${modelName.value}` : null,
    elapsed.value ? `耗时：${elapsed.value}s` : null,
    `导出时间：${stamp}`,
    '---',
  ].filter(Boolean)
  const file = metaLines.join('\n') + '\n\n' + content.value

  const blob = new Blob([file], { type: 'text/markdown;charset=utf-8' })
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = date ? `AI分析_${date}.md` : 'AI分析.md'
  document.body.appendChild(a)
  a.click()
  document.body.removeChild(a)
  URL.revokeObjectURL(url)
}

function onClose() {
  emit('update:modelValue', false)
}

onUnmounted(closeStream)
</script>

<template>
  <AppModal
    :model-value="modelValue"
    title="AI 分析 · 涨跌停结构与潜在行情"
    size="lg"
    max-width="960px"
    :show-ok="false"
    :show-cancel="false"
    @update:model-value="(v) => !v && onClose()"
  >
    <div class="ai-ana">
      <!-- 工具条：模型选择 + 操作 -->
      <div class="ai-ana__bar">
        <div class="ai-ana__pick">
          <span class="ai-ana__pick-label">模型</span>
          <AppSelect
            v-model="providerId"
            :options="providerOptions"
            size="sm"
            :disabled="running"
            placeholder="系统默认模型"
          />
        </div>
        <div class="ai-ana__acts">
          <AppButton
            v-if="running"
            size="sm"
            variant="secondary"
            icon="x"
            @click="stop"
          >
            停止
          </AppButton>
          <AppButton
            v-else-if="archivedMode"
            size="sm"
            variant="secondary"
            icon="sparkles"
            @click="enterLive"
          >
            重新分析
          </AppButton>
          <AppButton
            v-else
            size="sm"
            variant="secondary"
            icon="refresh"
            @click="start(status === 'idle' ? false : true)"
          >
            {{ status === 'idle' ? '开始分析' : '重新分析' }}
          </AppButton>
          <AppButton
            size="sm"
            variant="ghost"
            :icon="copied ? 'check' : 'copy'"
            :disabled="!content"
            @click="copyResult"
          >
            {{ copied ? '已复制' : '复制' }}
          </AppButton>
          <AppButton
            size="sm"
            variant="ghost"
            icon="download"
            :disabled="!content"
            @click="exportResult"
          >
            导出
          </AppButton>
        </div>
      </div>

      <!-- 历史归档提示条 -->
      <div v-if="archivedMode" class="ai-ana__archived">
        <AppIcon name="clock" size="sm" />
        <span>正在查看历史分析结果 · {{ (meta && meta.date) || props.date || '—' }}</span>
        <AppButton size="xs" variant="ghost" @click="enterLive">改为实时分析</AppButton>
      </div>

      <!-- 数据口径提示条 -->
      <div v-if="metaChips.length && status !== 'idle'" class="ai-ana__meta">
        <span v-for="c in metaChips" :key="c.label" class="ai-ana__chip" :class="c.tone && `is-${c.tone}`">
          {{ c.label }} <b class="ff-num">{{ c.value }}</b>
        </span>
        <span v-if="modelName" class="ai-ana__chip is-model">{{ modelName }}</span>
        <span v-if="elapsed && status === 'done'" class="ai-ana__chip">耗时 <b class="ff-num">{{ elapsed }}s</b></span>
      </div>

      <!-- 运行态 -->
      <div v-if="running" class="ai-ana__running">
        <AppIcon name="sparkles" size="sm" spin />
        <span>{{ stageText || '模型分析中…' }}</span>
      </div>

      <!-- 错误态 -->
      <div v-if="status === 'error' && errorMsg" class="ai-ana__error">
        <AppIcon name="info" size="sm" />
        <span>{{ errorMsg }}</span>
        <AppButton size="xs" variant="ghost" @click="start(true)">重试</AppButton>
      </div>

      <!-- 结果区 -->
      <div v-if="content" class="ai-ana__body">
        <MarkdownView :content="content" />
        <span v-if="running" class="ai-ana__caret" aria-hidden="true"></span>
      </div>

      <!-- 空态 -->
      <div v-else-if="status === 'idle' && !errorMsg" class="ai-ana__empty">
        <AppIcon name="sparkles" size="lg" />
        <p>由系统配置的大模型解读当日涨停梯队、真跌停结构与潜在主线，点击「开始分析」运行。</p>
      </div>

      <p class="ai-ana__foot">
        结论由大模型基于当日盘面数据生成，仅供研究参考，不构成投资建议。
      </p>
    </div>
  </AppModal>
</template>

<style scoped>
.ai-ana {
  display: flex;
  flex-direction: column;
  gap: var(--ff-space-3);
}

/* 工具条 */
.ai-ana__bar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--ff-space-3);
  flex-wrap: wrap;
}
.ai-ana__pick {
  display: inline-flex;
  align-items: center;
  gap: var(--ff-space-2);
  min-width: 220px;
}
.ai-ana__pick-label {
  font-size: var(--ff-fs-caption);
  color: var(--ff-text-tertiary);
  white-space: nowrap;
}
.ai-ana__acts {
  display: inline-flex;
  align-items: center;
  gap: var(--ff-space-2);
}

/* 数据口径提示条 */
.ai-ana__meta {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 6px;
  padding: 8px 10px;
  border: 1px solid var(--ff-border-subtle);
  border-radius: var(--ff-radius-md);
  background: var(--ff-bg-subtle);
}
.ai-ana__chip {
  display: inline-flex;
  align-items: baseline;
  gap: 4px;
  padding: 1px 8px;
  border-radius: var(--ff-radius-pill);
  background: var(--ff-bg-surface);
  border: 1px solid var(--ff-border);
  font-size: var(--ff-fs-overline);
  color: var(--ff-text-tertiary);
  white-space: nowrap;
}
.ai-ana__chip b {
  font-weight: var(--ff-fw-semibold);
  color: var(--ff-text-secondary);
  font-variant-numeric: tabular-nums;
}
.ai-ana__chip.is-up b { color: var(--ff-text-up); }
.ai-ana__chip.is-down b { color: var(--ff-down-text); }
.ai-ana__chip.is-model {
  font-family: var(--ff-font-mono, ui-monospace, monospace);
  background: var(--ff-bg-muted);
}

/* 历史归档提示条 */
.ai-ana__archived {
  display: flex;
  align-items: center;
  gap: var(--ff-space-2);
  font-size: var(--ff-fs-caption);
  color: var(--ff-text-tertiary);
}
.ai-ana__archived span {
  flex: 1 1 auto;
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

/* 运行 / 错误 / 空态 */
.ai-ana__running,
.ai-ana__error,
.ai-ana__empty {
  display: flex;
  align-items: center;
  gap: var(--ff-space-2);
  font-size: var(--ff-fs-body-sm);
}
.ai-ana__running { color: var(--ff-brand-text); }
.ai-ana__error { color: var(--ff-text-up); flex-wrap: wrap; }
.ai-ana__empty {
  flex-direction: column;
  gap: var(--ff-space-2);
  padding: var(--ff-space-6) var(--ff-space-4);
  color: var(--ff-text-tertiary);
  text-align: center;
}
.ai-ana__empty p { margin: 0; max-width: 460px; line-height: 1.6; }

/* 结果正文（加高 + 更宽阅读区） */
.ai-ana__body {
  position: relative;
  max-height: 64vh;
  overflow-y: auto;
  padding: var(--ff-space-4) var(--ff-space-5);
  border: 1px solid var(--ff-border-subtle);
  border-radius: var(--ff-radius-md);
  background: var(--ff-bg-surface);
}

/* 弹窗内 Markdown 字体清晰化：放大正文字号 + 开启字体平滑。
   选择器带类型前缀提升特异性，确保覆盖 MarkdownView 的共享默认值，
   仅作用于本弹窗，不影响报告/对话等其他使用处。 */
.ai-ana__body :deep(div.mdv) {
  font-size: var(--ff-fs-body);
  line-height: 1.75;
  color: var(--ff-text-primary);
  -webkit-font-smoothing: antialiased;
  -moz-osx-font-smoothing: grayscale;
  text-rendering: optimizeLegibility;
}
.ai-ana__body :deep(div.mdv) h2 { font-size: var(--ff-fs-data-lg); }
.ai-ana__body :deep(div.mdv) h3 { font-size: var(--ff-fs-h4); }
.ai-ana__body :deep(div.mdv) h4 { font-size: var(--ff-fs-body); }
.ai-ana__body :deep(div.mdv) p { margin: 9px 0; }
.ai-ana__body :deep(div.mdv) ul,
.ai-ana__body :deep(div.mdv) ol { margin: 9px 0; padding-left: 24px; }
.ai-ana__body :deep(div.mdv) li { margin: 5px 0; }
.ai-ana__body :deep(div.mdv) code { font-size: var(--ff-fs-caption); }
.ai-ana__body :deep(div.mdv) pre { font-size: var(--ff-fs-caption); }
.ai-ana__body :deep(div.mdv) pre code { font-size: var(--ff-fs-caption); }
.ai-ana__body :deep(div.mdv) table { font-size: var(--ff-fs-caption); }
.ai-ana__body :deep(div.mdv) th { font-size: var(--ff-fs-caption); padding: 8px 12px; }
.ai-ana__body :deep(div.mdv) td { padding: 8px 12px; }
/* 流式光标 */
.ai-ana__caret {
  display: inline-block;
  width: 6px;
  height: 1em;
  margin-left: 2px;
  vertical-align: text-bottom;
  background: var(--ff-brand);
  animation: ai-caret 1s steps(2, start) infinite;
}
@keyframes ai-caret {
  0%, 100% { opacity: 1; }
  50% { opacity: 0; }
}

.ai-ana__foot {
  margin: 0;
  font-size: var(--ff-fs-overline);
  color: var(--ff-text-tertiary);
  line-height: 1.6;
}

/* ── 窄屏适配（≤768px：模型选择占满一行 / 正文区收窄加高）── */
@media (max-width: 768px) {
  .ai-ana__pick {
    min-width: 0;
    flex: 1 1 100%;
  }
  .ai-ana__acts {
    flex-wrap: wrap;
  }
  .ai-ana__body {
    max-height: 56vh;
    padding: var(--ff-space-3);
  }
}
</style>
