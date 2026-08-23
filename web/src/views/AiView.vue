<script setup>
import { ref, onMounted, onBeforeUnmount, computed, nextTick } from 'vue'
import { api } from '../api/client'
import EmptyState from '../components/EmptyState.vue'
import AppCard from '../ui/AppCard.vue'
import AppButton from '../ui/AppButton.vue'
import AppInput from '../ui/AppInput.vue'
import AppSelect from '../ui/AppSelect.vue'
import AppBadge from '../ui/AppBadge.vue'
import AppIcon from '../ui/AppIcon.vue'
import AppStatus from '../ui/AppStatus.vue'
import AppCheckbox from '../ui/AppCheckbox.vue'
import AppModal from '../ui/AppModal.vue'

const status = ref(null)
const reports = ref([])
const analyzing = ref(false)
const analyzeMsg = ref('')
const chatInput = ref('')
const chatLog = ref([])
const sending = ref(false)
const activeReport = ref(null)
const showReportModal = ref(false)
// 中断控制器：sending 中可由用户中止当前 LLM 请求
let chatAbortController = null
// 聊天容器 DOM ref，用于自动滚到底部
const chatScrollEl = ref(null)

const modelAvailable = computed(() => {
  const s = status.value
  if (!s) return false
  if (typeof s.available === 'boolean') return s.available
  const dp = s.default_provider
  return !!(dp && dp.enabled && (dp.has_api_key || dp.test_status === 1))
})

const LS_KEY = 'finfeed_ai_config'
const providers = ref([])
const defaultProvider = ref(null)
const scopeOptions = ref([])
const windowOptions = ref([24, 48, 72])
const saveMsg = ref('')
const config = ref({
  provider_id: '',
  scope: 'all',
  window: 24,
  focus: '',
  prompts: {
    map_system: '',
    map_user: '',
    reduce_system: '',
    reduce_user: '',
    single_user: '',
  },
})
const promptLabels = {
  map_system: '分析映射 · 系统提示',
  map_user: '分析映射 · 用户模板',
  reduce_system: '汇总成文 · 系统提示',
  reduce_user: '汇总成文 · 用户模板',
  single_user: '单轮分析 · 用户模板',
}

function restoreLocal() {
  try {
    const raw = localStorage.getItem(LS_KEY)
    if (!raw) return
    const c = JSON.parse(raw)
    if (c.provider_id !== undefined) config.value.provider_id = c.provider_id
    if (c.scope) config.value.scope = c.scope
    if (c.window) config.value.window = c.window
    if (c.focus !== undefined) config.value.focus = c.focus
  } catch (e) {}
}
function persistLocal() {
  try {
    localStorage.setItem(
      LS_KEY,
      JSON.stringify({
        provider_id: config.value.provider_id,
        scope: config.value.scope,
        window: config.value.window,
        focus: config.value.focus,
      }),
    )
  } catch (e) {}
}

async function loadStatus() {
  try {
    status.value = await api.llm('/status')
  } catch (e) {
    status.value = { error: e.message }
  }
}
async function loadReports() {
  try {
    const r = await api.llm('/reports', { limit: 20 })
    reports.value = r.reports || r.list || []
  } catch (e) {
    reports.value = []
  }
}
async function loadInit() {
  try {
    const init = await api.llm('/init')
    providers.value = init.providers || []
    defaultProvider.value = init.status?.default_provider || null
    scopeOptions.value = init.scopes || []
    if (init.windows && init.windows.length) windowOptions.value = init.windows
    if (!config.value.provider_id && defaultProvider.value) {
      config.value.provider_id = String(defaultProvider.value.id)
    }
  } catch (e) {}
}
async function loadPrompts() {
  try {
    const p = await api.llm('/prompts')
    const defaults = p.defaults || {}
    const custom = p.custom || {}
    for (const k of Object.keys(config.value.prompts)) {
      const saved = custom[k]
      config.value.prompts[k] = saved != null && saved !== '' ? saved : defaults[k] || ''
    }
  } catch (e) {}
}
async function saveConfig() {
  saveMsg.value = ''
  try {
    const payload = {}
    for (const k of Object.keys(config.value.prompts)) {
      payload['prompt_' + k] = config.value.prompts[k]
    }
    const r = await api.llmPost('/prompts', payload)
    persistLocal()
    saveMsg.value = r && r.success ? '配置已保存' : '保存失败'
    setTimeout(() => (saveMsg.value = ''), 3000)
  } catch (e) {
    saveMsg.value = '保存失败：' + e.message
  }
}
async function generate() {
  analyzing.value = true
  analyzeMsg.value = ''
  try {
    const r = await api.llmPost('/analyze', {
      provider_id: config.value.provider_id ? Number(config.value.provider_id) : undefined,
      scope: config.value.scope,
      hours: Number(config.value.window),
      focus: config.value.focus || undefined,
      min_importance: 0,
    })
    analyzeMsg.value = r.ok
      ? `已提交分析任务（${r.task_id || ''}），稍后在报告列表中查看。`
      : r.error || '提交失败'
    await loadReports()
  } catch (e) {
    analyzeMsg.value = '失败：' + e.message
  } finally {
    analyzing.value = false
  }
}
async function openReport(id) {
  try {
    const r = await api.llm('/report', { id })
    activeReport.value = r.report || null
    showReportModal.value = true
  } catch (e) {
    activeReport.value = { error: e.message }
    showReportModal.value = true
  }
}
async function sendChat() {
  const q = chatInput.value.trim()
  if (!q || sending.value) return
  // 乐观渲染：先入栈用户消息 + AI 占位，立刻滚动到底部
  chatLog.value.push({ role: 'user', text: q })
  chatInput.value = ''
  const aiIndex = chatLog.value.length
  chatLog.value.push({ role: 'ai', text: '', pending: true })
  scrollChatToBottom()
  // 构造请求
  const history = chatLog.value
    .slice(0, aiIndex) // 仅截止到用户消息
    .filter((m) => !m.pending && m.text)
    .slice(-16)
    .map((m) => ({ role: m.role === 'ai' ? 'assistant' : 'user', content: m.text }))
  const payload = { question: q, history }
  if (activeReport.value && activeReport.value.id) {
    payload.report_id = activeReport.value.id
  }
  chatAbortController = new AbortController()
  sending.value = true
  try {
    const r = await api.llmPost('/chat', payload, {
      signal: chatAbortController.signal,
    })
    const text = r.reply || r.answer || r.text || JSON.stringify(r)
    chatLog.value[aiIndex] = { role: 'ai', text, pending: false }
  } catch (e) {
    // 用户主动中止：保留已渲染的 AI 占位，但标 stopped，不当错误
    const stopped =
      e?.name === 'CanceledError' ||
      e?.code === 'ERR_CANCELED' ||
      e?.message?.includes('canceled')
    if (stopped) {
      chatLog.value[aiIndex] = {
        role: 'ai',
        text: chatLog.value[aiIndex].text
          ? chatLog.value[aiIndex].text + '\n[已停止生成]'
          : '[已停止生成]',
        pending: false,
        stopped: true,
      }
    } else {
      chatLog.value[aiIndex] = {
        role: 'ai',
        text: '出错了：' + (e.message || String(e)),
        pending: false,
        error: true,
      }
    }
  } finally {
    sending.value = false
    chatAbortController = null
    scrollChatToBottom()
  }
}

function stopChat() {
  // 立刻把按钮反馈从「停止」切走，并通知 axios 取消当前请求
  if (chatAbortController) {
    chatAbortController.abort()
    chatAbortController = null
  }
}

function scrollChatToBottom() {
  nextTick(() => {
    const el = chatScrollEl.value
    if (el) el.scrollTop = el.scrollHeight
  })
}

function onChatEnter() {
  // 回车发送：sending 中等价于停止（与按钮行为一致）
  if (sending.value) {
    stopChat()
  } else {
    sendChat()
  }
}

// ============================================================
// 模型管理
// ============================================================
const PRESETS = [
  { key: 'openai', label: 'OpenAI', base_url: 'https://api.openai.com/v1', model: 'gpt-4o-mini' },
  { key: 'deepseek', label: 'DeepSeek', base_url: 'https://api.deepseek.com/v1', model: 'deepseek-chat' },
  { key: 'dashscope', label: '阿里通义千问', base_url: 'https://dashscope.aliyuncs.com/compatible-mode/v1', model: 'qwen-plus' },
  { key: 'moonshot', label: '月之暗面 Kimi', base_url: 'https://api.moonshot.cn/v1', model: 'moonshot-v1-32k' },
  { key: 'zhipu', label: '智谱 GLM', base_url: 'https://open.bigmodel.cn/api/paas/v4', model: 'glm-4-plus' },
  { key: 'siliconflow', label: '硅基流动', base_url: 'https://api.siliconflow.cn/v1', model: 'Qwen/Qwen2.5-32B-Instruct' },
  { key: 'volcengine', label: '火山方舟豆包', base_url: 'https://ark.cn-beijing.volces.com/api/v3', model: 'doubao-pro-32k' },
  { key: 'ollama', label: '本地 Ollama', base_url: 'http://127.0.0.1:11434/v1', model: 'qwen2.5:14b' },
  { key: 'lmstudio', label: '本地 LM Studio', base_url: 'http://127.0.0.1:1234/v1', model: 'local-model' },
  { key: 'custom', label: '自定义', base_url: '', model: '' },
]

const providerList = ref([])
const showProviderForm = ref(false)
const editingId = ref(null)
const busyProvider = ref(false)
const providerMsg = ref('')
const testResult = ref('')
const providerForm = ref(blankProvider())

function blankProvider() {
  return {
    id: null,
    name: '',
    base_url: '',
    model: '',
    api_key: '',
    preset: 'custom',
    temperature: 0.3,
    max_tokens: 4096,
    timeout: 120,
    is_default: false,
    enabled: true,
  }
}

async function loadProviders() {
  try {
    const r = await api.llm('/providers')
    providerList.value = r.providers || []
  } catch (e) {
    providerList.value = []
  }
}
function openAddProvider() {
  editingId.value = null
  providerForm.value = blankProvider()
  testResult.value = ''
  providerMsg.value = ''
  showProviderForm.value = true
}
function openEditProvider(p) {
  editingId.value = p.id
  providerForm.value = {
    id: p.id,
    name: p.name || '',
    base_url: p.base_url || '',
    model: p.model || '',
    api_key: '',
    preset: p.preset || 'custom',
    temperature: p.temperature ?? 0.3,
    max_tokens: p.max_tokens ?? 4096,
    timeout: p.timeout ?? 120,
    is_default: !!p.is_default,
    enabled: p.enabled !== false,
  }
  testResult.value = ''
  providerMsg.value = ''
  showProviderForm.value = true
}
function applyPreset() {
  const pre = PRESETS.find((x) => x.key === providerForm.value.preset)
  if (pre && pre.key !== 'custom') {
    providerForm.value.base_url = pre.base_url
    providerForm.value.model = pre.model
  }
}
function closeProviderForm() {
  showProviderForm.value = false
  editingId.value = null
}
async function saveProvider() {
  busyProvider.value = true
  providerMsg.value = ''
  try {
    const f = { ...providerForm.value }
    if (!f.api_key) delete f.api_key
    const r = await api.llmPost('/provider/save', f)
    if (r && r.success) {
      providerMsg.value = '模型已保存'
      showProviderForm.value = false
      await loadProviders()
      await loadStatus()
      await loadInit()
    } else {
      providerMsg.value = '保存失败：' + (r.error || '未知错误')
    }
  } catch (e) {
    providerMsg.value = '保存失败：' + e.message
  } finally {
    busyProvider.value = false
    setTimeout(() => (providerMsg.value = ''), 3000)
  }
}
async function testProvider() {
  busyProvider.value = true
  testResult.value = '测试中…'
  try {
    const f = { ...providerForm.value }
    const payload = editingId.value && !f.api_key
      ? { id: editingId.value, use_saved: true }
      : f
    const r = await api.llmPost('/provider/test', payload)
    testResult.value = r && r.ok
      ? `连通正常（${r.model || ''}）${r.latency_ms ? ' · ' + Math.round(r.latency_ms) + 'ms' : ''}`
      : (r.message || '连通失败')
  } catch (e) {
    testResult.value = '测试失败：' + e.message
  } finally {
    busyProvider.value = false
  }
}
async function setDefault(id) {
  try {
    await api.llmPost('/provider/default', { id })
    await loadProviders()
    await loadStatus()
    await loadInit()
  } catch (e) {}
}
async function deleteProvider(id) {
  if (!confirm('确认删除该模型配置？')) return
  try {
    await api.llmPost('/provider/delete', { id })
    await loadProviders()
    await loadStatus()
    await loadInit()
  } catch (e) {}
}

const providerOptions = computed(() => [
  { label: '自动（默认模型）', value: '' },
  ...providers.value.map((p) => ({ label: p.name, value: String(p.id) })),
])
const scopeSelectOptions = computed(() => scopeOptions.value.map((s) => ({ label: s.label, value: s.key })))
const windowSelectOptions = computed(() => windowOptions.value.map((w) => ({ label: `${w} 小时`, value: w })))
const presetOptions = computed(() => PRESETS.map((p) => ({ label: p.label, value: p.key })))
const testOk = computed(() => testResult.value && !testResult.value.includes('失败') && testResult.value !== '测试中…')
const testBad = computed(() => testResult.value && (testResult.value.includes('失败') || testResult.value.includes('连通失败')))

onMounted(() => {
  restoreLocal()
  loadStatus()
  loadReports()
  loadInit()
  loadPrompts()
  loadProviders()
})
</script>

<template>
  <div class="ff-page ff-ai-view">
    <!-- 头部状态卡 -->
    <AppCard class="ff-ai-view__status">
      <div class="ff-ai-view__status-main">
        <div class="ff-ai-view__brand">
          <div class="ff-ai-view__brand-icon">
            <AppIcon name="cpu" size="xl" />
          </div>
          <div>
            <h3 class="ff-h3">AI 服务状态</h3>
            <div class="ff-ai-view__status-line">
              <template v-if="status && !status.error">
                <AppBadge
                  :text="modelAvailable ? '模型可用' : '模型不可用'"
                  :variant="modelAvailable ? 'success' : 'danger'"
                />
                <span class="ff-text-secondary">
                  {{ status.default_provider?.name || '未配置' }}
                  <template v-if="status.default_provider?.model">· {{ status.default_provider.model }}</template>
                </span>
              </template>
              <span v-else-if="status && status.error" class="ff-text-secondary">状态获取失败：{{ status.error }}</span>
            </div>
            <div v-if="status && status.default_provider" class="ff-ai-view__status-sub">
              {{ status.default_provider.base_url }}
              <span v-if="status.default_provider.test_status === 1" class="ff-t-down">· 已连通</span>
              <span v-else-if="status.default_provider.test_status === 0" class="ff-t-up">· 连通失败</span>
              <span v-else class="ff-text-muted">· 未测试</span>
            </div>
          </div>
        </div>
      </div>
    </AppCard>

    <Transition name="ff-fade">
      <div v-if="analyzeMsg" class="ff-alert" :class="analyzeMsg.includes('已提交') ? 'ff-alert--success' : 'ff-alert--danger'">
        <AppIcon :name="analyzeMsg.includes('已提交') ? 'check-circle' : 'alert-circle'" size="md" />
        {{ analyzeMsg }}
      </div>
    </Transition>

    <!-- 配置面板 -->
    <AppCard title="分析配置">
      <template #actions>
        <AppButton variant="primary" icon="save" size="sm" @click="saveConfig">保存配置</AppButton>
      </template>

      <div class="ff-ai-view__cfg-grid">
        <AppSelect v-model="config.provider_id" label="模型" :options="providerOptions" />
        <AppSelect v-model="config.scope" label="分析范围" :options="scopeSelectOptions" />
        <AppSelect v-model="config.window" label="时间窗口" :options="windowSelectOptions" />
        <AppInput v-model="config.focus" class="ff-ai-view__grow" label="自定义焦点（可选）" placeholder="如：重点关注半导体与新能源" />
      </div>

      <div class="ff-ai-view__prompts">
        <label v-for="(lbl, key) in promptLabels" :key="key" class="ff-ai-view__pfld">
          <span>{{ lbl }}</span>
          <textarea v-model="config.prompts[key]" rows="6" :placeholder="lbl"></textarea>
        </label>
      </div>

      <div class="ff-ai-view__cfg-foot">
        <AppStatus v-if="saveMsg" :text="saveMsg" :tone="saveMsg.includes('已保存') ? 'success' : 'danger'" />
      </div>
    </AppCard>

    <!-- 模型管理 -->
    <AppCard title="模型管理">
      <template #actions>
        <AppButton variant="primary" icon="plus" size="sm" @click="openAddProvider">添加模型</AppButton>
      </template>

      <div v-if="providerList.length" class="ff-ai-view__providers">
        <div
          v-for="p in providerList"
          :key="p.id"
          class="ff-ai-view__provider"
          :class="p.is_default && 'ff-ai-view__provider--default'"
        >
          <div class="ff-ai-view__p-main">
            <div class="ff-ai-view__p-name">
              {{ p.name }}
              <AppBadge v-if="p.is_default" text="默认" variant="brand" />
              <AppBadge v-if="p.enabled" text="已启用" variant="success" />
              <AppBadge v-else text="已停用" variant="muted" />
            </div>
            <div class="ff-ai-view__p-meta">{{ p.model }} · {{ p.base_url }}</div>
          </div>
          <div class="ff-ai-view__p-actions">
            <AppButton v-if="!p.is_default" variant="tonal" size="xs" @click="setDefault(p.id)">设为默认</AppButton>
            <AppButton variant="secondary" size="xs" icon="edit" @click="openEditProvider(p)">编辑</AppButton>
            <AppButton variant="danger" size="xs" icon="trash" @click="deleteProvider(p.id)">删除</AppButton>
          </div>
        </div>
      </div>
      <EmptyState v-else text="还没有配置任何模型" icon="database" />

      <Transition name="ff-fade">
        <div v-if="showProviderForm" class="ff-ai-view__pform">
          <div class="ff-ai-view__pform-grid">
            <AppInput v-model="providerForm.name" label="名称" placeholder="如：我的 DeepSeek" />
            <AppSelect v-model="providerForm.preset" label="预设" :options="presetOptions" @change="applyPreset" />
            <AppInput v-model="providerForm.base_url" class="ff-ai-view__span2" label="接口地址 (Base URL)" placeholder="https://..." />
            <AppInput v-model="providerForm.model" label="模型名称" placeholder="如：deepseek-chat" />
            <AppInput
              v-model="providerForm.api_key"
              type="password"
              label="API Key"
              :placeholder="editingId ? '留空则保留原密钥' : 'sk-...'"
            />
            <AppInput v-model.number="providerForm.temperature" type="number" label="温度 (0–2)" />
            <AppInput v-model.number="providerForm.max_tokens" type="number" label="最大 Token" />
            <AppInput v-model.number="providerForm.timeout" type="number" label="超时 (秒)" />
            <AppCheckbox v-model="providerForm.is_default" label="设为默认模型" />
          </div>
          <div class="ff-ai-view__pform-foot">
            <AppButton variant="primary" :loading="busyProvider" icon="save" @click="saveProvider">保存</AppButton>
            <AppButton variant="secondary" :loading="busyProvider" icon="activity" @click="testProvider">测试连接</AppButton>
            <AppButton variant="ghost" @click="closeProviderForm">取消</AppButton>
            <AppStatus v-if="providerMsg" :text="providerMsg" :tone="providerMsg.includes('已保存') ? 'success' : 'danger'" />
            <AppStatus v-if="testResult" :text="testResult" :tone="testOk ? 'success' : testBad ? 'danger' : 'neutral'" />
          </div>
        </div>
      </Transition>
    </AppCard>

    <!-- 对话 + 报告 -->
    <div class="ff-grid">
      <div class="ff-col-12 ff-col-lg-6">
        <AppCard title="对话" class="ff-ai-view__panel">
          <div ref="chatScrollEl" class="ff-ai-view__chat">
            <div
              v-for="(m, i) in chatLog"
              :key="i"
              class="ff-ai-view__msg"
              :class="`ff-ai-view__msg--${m.role}`"
            >
              <div class="ff-ai-view__avatar" :class="`ff-ai-view__avatar--${m.role}`">
                <AppIcon v-if="m.role === 'ai'" name="sparkles" size="sm" />
                <span v-else class="ff-ai-view__avatar-me">我</span>
              </div>
              <div
                class="ff-ai-view__bubble"
                :class="[
                  `ff-ai-view__bubble--${m.role}`,
                  m.pending && 'ff-ai-view__bubble--pending',
                  m.error && 'ff-ai-view__bubble--error',
                  m.stopped && 'ff-ai-view__bubble--stopped',
                ]"
              >
                <AppIcon
                  v-if="m.pending"
                  name="sparkles"
                  size="sm"
                  class="ff-ai-view__bubble-spin"
                />
                <span v-if="m.pending" class="ff-ai-view__typing-label">AI 正在思考…</span>
                <span v-else class="ff-ai-view__bubble-text">{{ m.text }}</span>
                <span v-if="m.pending" class="ff-ai-view__typing-dots">
                  <span /><span /><span />
                </span>
              </div>
            </div>
            <div v-if="!chatLog.length && !sending" class="ff-ai-view__empty-chat">
              向 FinFeed 的 AI 提问市场 / 新闻相关问题
            </div>
          </div>
          <div class="ff-ai-view__chat-input">
            <AppInput
              v-model="chatInput"
              class="ff-ai-view__chat-field"
              placeholder="输入问题…"
              :disabled="sending"
              @enter="onChatEnter"
            />
            <AppButton
              v-if="!sending"
              variant="primary"
              icon="send"
              :disabled="!chatInput.trim()"
              @click="sendChat"
            >发送</AppButton>
            <AppButton
              v-else
              variant="danger"
              icon="x-circle"
              @click="stopChat"
            >停止</AppButton>
          </div>
        </AppCard>
      </div>

      <div class="ff-col-12 ff-col-lg-6">
        <AppCard title="历史报告" class="ff-ai-view__panel">
          <template #actions>
            <AppButton
              variant="primary"
              size="sm"
              icon="zap"
              :loading="analyzing"
              :disabled="analyzing"
              @click="generate"
            >
              生成每日复盘
            </AppButton>
          </template>
          <div class="ff-ai-view__reports">
            <div v-for="rp in reports" :key="rp.id" class="ff-ai-view__report" @click="openReport(rp.id)">
              <span class="ff-ai-view__report-title">{{ rp.title || ('报告 #' + rp.id) }}</span>
              <span class="ff-text-muted">{{ rp.created_at || '' }}</span>
            </div>
            <EmptyState v-if="!reports.length" text="暂无报告，点击上方「生成每日复盘」" icon="file-text" />
          </div>
        </AppCard>
      </div>
    </div>

    <!-- 报告详情弹窗 -->
    <AppModal
      v-model="showReportModal"
      :title="activeReport?.title || ('报告 #' + activeReport?.id)"
      size="lg"
    >
      <pre v-if="activeReport" class="ff-ai-view__report-pre">{{ activeReport.content || activeReport.error || '（无内容）' }}</pre>
    </AppModal>
  </div>
</template>

<style scoped>
.ff-ai-view {
  max-width: var(--ff-container-max);
  margin: 0 auto;
  display: flex;
  flex-direction: column;
  gap: var(--ff-space-5);
}

.ff-ai-view__status {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--ff-space-4);
}

.ff-ai-view__brand {
  display: flex;
  align-items: center;
  gap: var(--ff-space-4);
}

.ff-ai-view__brand-icon {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 52px;
  height: 52px;
  border-radius: var(--ff-radius-lg);
  background: var(--ff-bg-brand-subtle);
  color: var(--ff-icon-brand);
}

.ff-ai-view__status-line {
  display: flex;
  align-items: center;
  gap: var(--ff-space-3);
  margin-top: var(--ff-space-1);
  font-size: var(--ff-fs-sm);
}

.ff-ai-view__status-sub {
  margin-top: var(--ff-space-1);
  font-size: var(--ff-fs-xs);
  color: var(--ff-text-tertiary);
  word-break: break-all;
}

.ff-ai-view__cfg-grid {
  display: flex;
  gap: var(--ff-space-4);
  flex-wrap: wrap;
  margin-bottom: var(--ff-space-5);
}

.ff-ai-view__cfg-grid > * {
  width: 220px;
}

.ff-ai-view__grow {
  flex: 1 1 280px;
  min-width: 240px;
}

.ff-ai-view__prompts {
  display: grid;
  grid-template-columns: 1fr;
  gap: var(--ff-space-4);
  margin-bottom: var(--ff-space-5);
  padding-top: var(--ff-space-4);
  border-top: 1px dashed var(--ff-border);
}

@media (min-width: 1024px) {
  .ff-ai-view__prompts {
    grid-template-columns: 1fr 1fr;
  }
}

.ff-ai-view__pfld {
  display: flex;
  flex-direction: column;
  gap: var(--ff-space-2);
  font-size: var(--ff-fs-xs);
  font-weight: 500;
  color: var(--ff-text-secondary);
}

.ff-ai-view__pfld textarea {
  width: 100%;
  border: 1px solid var(--ff-border);
  border-left: 3px solid var(--ff-border-brand);
  border-radius: var(--ff-radius-md);
  padding: var(--ff-space-3);
  font-size: var(--ff-fs-sm);
  line-height: var(--ff-lh-normal);
  background: var(--ff-bg-subtle);
  color: var(--ff-text-primary);
  resize: vertical;
  font-family: var(--ff-font-mono);
  outline: none;
  transition: border-color var(--ff-dur-fast), box-shadow var(--ff-dur-fast);
}

.ff-ai-view__pfld textarea:focus {
  border-color: var(--ff-border-focus);
  box-shadow: var(--ff-focus-ring);
}

.ff-ai-view__cfg-foot {
  display: flex;
  align-items: center;
  gap: var(--ff-space-3);
}

.ff-ai-view__providers {
  display: flex;
  flex-direction: column;
  gap: var(--ff-space-3);
}

.ff-ai-view__provider {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--ff-space-4);
  padding: var(--ff-space-3) var(--ff-space-4);
  border: 1px solid var(--ff-border);
  border-radius: var(--ff-radius-md);
  background: var(--ff-bg-surface);
  transition: border-color var(--ff-dur-fast);
}

.ff-ai-view__provider:hover {
  border-color: var(--ff-border-hover);
}

.ff-ai-view__provider--default {
  border-color: var(--ff-border-brand);
  background: var(--ff-bg-brand-subtle);
}

.ff-ai-view__p-name {
  display: flex;
  align-items: center;
  gap: var(--ff-space-2);
  flex-wrap: wrap;
  font-weight: 600;
}

.ff-ai-view__p-meta {
  margin-top: 2px;
  font-size: var(--ff-fs-xs);
  color: var(--ff-text-tertiary);
  word-break: break-all;
}

.ff-ai-view__p-actions {
  display: flex;
  gap: var(--ff-space-2);
  flex-shrink: 0;
}

.ff-ai-view__pform {
  margin-top: var(--ff-space-4);
  padding: var(--ff-space-4);
  border: 1px dashed var(--ff-border);
  border-radius: var(--ff-radius-md);
  background: var(--ff-bg-subtle);
}

.ff-ai-view__pform-grid {
  display: grid;
  grid-template-columns: 1fr;
  gap: var(--ff-space-3);
}

@media (min-width: 768px) {
  .ff-ai-view__pform-grid {
    grid-template-columns: 1fr 1fr;
  }
}

.ff-ai-view__span2 {
  grid-column: 1 / -1;
}

.ff-ai-view__pform-foot {
  display: flex;
  align-items: center;
  gap: var(--ff-space-3);
  margin-top: var(--ff-space-4);
  flex-wrap: wrap;
}

.ff-ai-view__panel {
  display: flex;
  flex-direction: column;
  min-height: 540px;
}

.ff-ai-view__chat {
  flex: 1;
  min-height: 380px;
  overflow-y: auto;
  display: flex;
  flex-direction: column;
  gap: var(--ff-space-3);
  padding: var(--ff-space-3);
}

.ff-ai-view__empty-chat {
  margin: auto;
  font-size: var(--ff-fs-sm);
  color: var(--ff-text-tertiary);
}

/* 消息行：头像 + 气泡，左右分列（IM 风格） */
.ff-ai-view__msg {
  display: flex;
  align-items: flex-start;
  gap: var(--ff-space-2);
  max-width: 100%;
}
.ff-ai-view__msg--ai {
  justify-content: flex-start;
}
.ff-ai-view__msg--user {
  justify-content: flex-end;
  flex-direction: row-reverse;
}

.ff-ai-view__avatar {
  flex-shrink: 0;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 30px;
  height: 30px;
  border-radius: 50%;
  font-size: var(--ff-fs-xs);
  font-weight: 600;
}
.ff-ai-view__avatar--ai {
  background: var(--ff-bg-brand-subtle);
  color: var(--ff-icon-brand);
}
.ff-ai-view__avatar--user {
  background: var(--ff-brand);
  color: var(--ff-brand-fg, #fff);
}
.ff-ai-view__avatar-me {
  font-size: 12px;
}

.ff-ai-view__bubble {
  max-width: 78%;
  padding: var(--ff-space-3) var(--ff-space-4);
  border-radius: var(--ff-radius-xl);
  font-size: var(--ff-fs-sm);
  white-space: pre-wrap;
  line-height: var(--ff-lh-normal);
  word-break: break-word;
}

.ff-ai-view__bubble--user {
  background: var(--ff-bg-brand);
  color: var(--ff-text-inverse);
  border-bottom-right-radius: var(--ff-radius-xs);
}

.ff-ai-view__bubble--ai {
  background: var(--ff-bg-subtle);
  color: var(--ff-text-primary);
  border-bottom-left-radius: var(--ff-radius-xs);
}

.ff-ai-view__bubble--pending {
  background: var(--ff-bg-brand-subtle);
  border: 1px dashed var(--ff-border-brand);
  display: inline-flex;
  align-items: center;
  gap: var(--ff-space-2);
  flex-wrap: wrap;
}
.ff-ai-view__bubble-spin {
  color: var(--ff-icon-brand);
}
.ff-ai-view__typing-label {
  color: var(--ff-text-brand);
  font-weight: 500;
}
.ff-ai-view__typing-dots {
  display: inline-flex;
  gap: 3px;
  margin-left: 2px;
}
.ff-ai-view__typing-dots span {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: var(--ff-icon-brand);
  animation: ff-bounce-dot 1.2s infinite ease-in-out;
  opacity: 0.7;
}
.ff-ai-view__typing-dots span:nth-child(2) { animation-delay: 0.2s; }
.ff-ai-view__typing-dots span:nth-child(3) { animation-delay: 0.4s; }

.ff-ai-view__bubble--error {
  background: var(--ff-down-subtle);
  color: var(--ff-down-text);
  border-left: 3px solid var(--ff-down);
}
.ff-ai-view__bubble--stopped {
  font-style: italic;
  color: var(--ff-text-secondary);
  background: var(--ff-bg-subtle);
}

.ff-ai-view__chat-input {
  display: flex;
  gap: var(--ff-space-3);
  margin-top: var(--ff-space-3);
}

.ff-ai-view__chat-field {
  flex: 1 1 auto;
}

.ff-ai-view__reports {
  flex: 1;
  overflow-y: auto;
  display: flex;
  flex-direction: column;
  gap: var(--ff-space-2);
  min-height: 380px;
}

.ff-ai-view__report {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: var(--ff-space-3);
  padding: var(--ff-space-3) var(--ff-space-4);
  border: 1px solid var(--ff-border);
  border-radius: var(--ff-radius-md);
  cursor: pointer;
  font-size: var(--ff-fs-sm);
  transition: background var(--ff-dur-fast), border-color var(--ff-dur-fast);
}

.ff-ai-view__report:hover {
  background: var(--ff-bg-hover);
  border-color: var(--ff-border-hover);
}

.ff-ai-view__report-title {
  font-weight: 500;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.ff-ai-view__report-pre {
  white-space: pre-wrap;
  font-size: var(--ff-fs-sm);
  line-height: var(--ff-lh-normal);
  max-height: 60vh;
  overflow-y: auto;
  margin: 0;
  font-family: var(--ff-font-mono);
}

.ff-fade-enter-active,
.ff-fade-leave-active {
  transition: opacity var(--ff-dur-fast);
}

.ff-fade-enter-from,
.ff-fade-leave-to {
  opacity: 0;
}

@keyframes ff-bounce-dot {
  0%, 60%, 100% { transform: translateY(0); opacity: 0.4; }
  30% { transform: translateY(-5px); opacity: 1; }
}
</style>
