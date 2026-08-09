<script setup>
import { ref, onMounted, computed } from 'vue'
import { api } from '../api/client'
import EmptyState from '../components/EmptyState.vue'

const status = ref(null)
const reports = ref([])
const analyzing = ref(false)
const analyzeMsg = ref('')
const chatInput = ref('')
const chatLog = ref([])
const sending = ref(false)
const activeReport = ref(null)

// ---- 模型可用性（优先用后端 available，缺省时按 default_provider 推导）----
const modelAvailable = computed(() => {
  const s = status.value
  if (!s) return false
  if (typeof s.available === 'boolean') return s.available
  const dp = s.default_provider
  return !!(dp && dp.enabled && (dp.has_api_key || dp.test_status === 1))
})

// ---- 配置：恢复用户之前已保存的配置项 ----
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
  } catch (e) {
    activeReport.value = { error: e.message }
  }
}
async function sendChat() {
  const q = chatInput.value.trim()
  if (!q || sending.value) return
  chatLog.value.push({ role: 'user', text: q })
  chatInput.value = ''
  sending.value = true
  try {
    // 构建历史（最近 8 轮）
    const history = chatLog.value.slice(-16).map((m) => ({
      role: m.role === 'ai' ? 'assistant' : 'user',
      content: m.text,
    }))
    const payload = { question: q, history }
    // 如果用户选中了某份报告，自动切换为报告追问模式
    if (activeReport.value && activeReport.value.id) {
      payload.report_id = activeReport.value.id
    }
    const r = await api.llmPost('/chat', payload)
    const text = r.reply || r.answer || r.text || JSON.stringify(r)
    chatLog.value.push({ role: 'ai', text })
  } catch (e) {
    chatLog.value.push({ role: 'ai', text: '出错了：' + e.message })
  } finally {
    sending.value = false
  }
}

// ============================================================
// 模型管理（新增）
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
      ? `✅ 连通正常（${r.model || ''}）${r.latency_ms ? ' · ' + Math.round(r.latency_ms) + 'ms' : ''}`
      : '❌ ' + (r.message || '连通失败')
  } catch (e) {
    testResult.value = '❌ 测试失败：' + e.message
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
  <div class="ai">
    <!-- 头部 -->
    <div class="top card">
      <div class="top-l">
        <div class="brand">
          <span class="brand-ico">🤖</span>
          <div>
            <h3>AI 分析</h3>
            <div class="status-line">
              <template v-if="status && !status.error">
                <span class="chip" :class="modelAvailable ? 'ok' : 'bad'">
                  {{ modelAvailable ? '模型可用' : '模型不可用' }}
                </span>
                <span class="text-3">
                  {{ status.default_provider?.name || '未配置' }}
                  <template v-if="status.default_provider?.model">· {{ status.default_provider.model }}</template>
                </span>
              </template>
              <span v-else-if="status && status.error" class="text-3">状态获取失败：{{ status.error }}</span>
            </div>
            <div v-if="status && status.default_provider" class="status-sub text-3">
              {{ status.default_provider.base_url }}
              <span v-if="status.default_provider.test_status === 1" class="t-ok">· 已连通</span>
              <span v-else-if="status.default_provider.test_status === 0" class="t-bad">· 连通失败</span>
              <span v-else class="t-idle">· 未测试</span>
            </div>
          </div>
        </div>
      </div>
      <button class="btn btn-primary lg" :disabled="analyzing" @click="generate">
        {{ analyzing ? '生成中…' : '⚡ 生成每日复盘' }}
      </button>
    </div>
    <transition name="fade">
      <div v-if="analyzeMsg" class="banner" :class="analyzeMsg.includes('已提交') ? 'ok' : 'err'">
        {{ analyzeMsg }}
      </div>
    </transition>

    <!-- 配置面板 -->
    <div class="card cfg">
      <div class="sec-head">
        <span class="sec-bar"></span>
        <h4>分析配置</h4>
        <span class="sec-hint">已自动恢复本地保存的模型 / 范围 / 窗口与提示词</span>
      </div>

      <div class="cfg-grid">
        <label class="fld">
          <span>模型</span>
          <div class="ctrl">
            <select v-model="config.provider_id">
              <option value="">自动（默认模型）</option>
              <option v-for="p in providers" :key="p.id" :value="String(p.id)">{{ p.name }}</option>
            </select>
          </div>
        </label>
        <label class="fld">
          <span>分析范围</span>
          <div class="ctrl">
            <select v-model="config.scope">
              <option v-for="s in scopeOptions" :key="s.key" :value="s.key">{{ s.label }}</option>
            </select>
          </div>
        </label>
        <label class="fld">
          <span>时间窗口</span>
          <div class="ctrl">
            <select v-model="config.window">
              <option v-for="w in windowOptions" :key="w" :value="w">{{ w }} 小时</option>
            </select>
          </div>
        </label>
        <label class="fld grow">
          <span>自定义焦点（可选）</span>
          <div class="ctrl">
            <input v-model="config.focus" placeholder="如：重点关注半导体与新能源" />
          </div>
        </label>
      </div>

      <div class="prompts">
        <label v-for="(lbl, key) in promptLabels" :key="key" class="pfld">
          <span>{{ lbl }}</span>
          <textarea v-model="config.prompts[key]" rows="6" :placeholder="lbl"></textarea>
        </label>
      </div>

      <div class="cfg-foot">
        <button class="btn btn-primary" @click="saveConfig">保存配置</button>
        <transition name="fade">
          <span v-if="saveMsg" class="save-msg" :class="{ ok: saveMsg.includes('已保存') }">{{ saveMsg }}</span>
        </transition>
      </div>
    </div>

    <!-- 模型管理（新增） -->
    <div class="card cfg">
      <div class="sec-head">
        <span class="sec-bar"></span>
        <h4>模型管理</h4>
        <span class="sec-hint">新增 / 编辑 OpenAI 兼容模型，可测试连通性并设为默认</span>
        <button class="btn btn-primary sm" @click="openAddProvider">+ 添加模型</button>
      </div>

      <div v-if="providerList.length" class="providers">
        <div v-for="p in providerList" :key="p.id" class="provider" :class="{ default: p.is_default }">
          <div class="p-main">
            <div class="p-name">
              {{ p.name }}
              <span v-if="p.is_default" class="tag tag-default">默认</span>
              <span v-if="p.enabled" class="tag tag-on">已启用</span>
              <span v-else class="tag tag-off">已停用</span>
            </div>
            <div class="p-meta text-3">{{ p.model }} · {{ p.base_url }}</div>
          </div>
          <div class="p-actions">
            <button v-if="!p.is_default" class="btn xs" @click="setDefault(p.id)">设为默认</button>
            <button class="btn xs" @click="openEditProvider(p)">编辑</button>
            <button class="btn xs danger" @click="deleteProvider(p.id)">删除</button>
          </div>
        </div>
      </div>
      <EmptyState v-else text="还没有配置任何模型" />

      <transition name="fade">
        <div v-if="showProviderForm" class="pform">
          <div class="pform-grid">
            <label class="pf">
              <span>名称</span>
              <input v-model="providerForm.name" placeholder="如：我的 DeepSeek" />
            </label>
            <label class="pf">
              <span>预设</span>
              <select v-model="providerForm.preset" @change="applyPreset">
                <option v-for="pre in PRESETS" :key="pre.key" :value="pre.key">{{ pre.label }}</option>
              </select>
            </label>
            <label class="pf span2">
              <span>接口地址 (Base URL)</span>
              <input v-model="providerForm.base_url" placeholder="https://..." />
            </label>
            <label class="pf">
              <span>模型名称</span>
              <input v-model="providerForm.model" placeholder="如：deepseek-chat" />
            </label>
            <label class="pf">
              <span>API Key</span>
              <input v-model="providerForm.api_key" type="password" :placeholder="editingId ? '留空则保留原密钥' : 'sk-...'" />
            </label>
            <label class="pf">
              <span>温度 (0–2)</span>
              <input v-model.number="providerForm.temperature" type="number" min="0" max="2" step="0.1" />
            </label>
            <label class="pf">
              <span>最大 Token</span>
              <input v-model.number="providerForm.max_tokens" type="number" min="256" max="131072" step="256" />
            </label>
            <label class="pf">
              <span>超时 (秒)</span>
              <input v-model.number="providerForm.timeout" type="number" min="5" max="900" step="5" />
            </label>
            <label class="pf check">
              <input v-model="providerForm.is_default" type="checkbox" />
              <span>设为默认模型</span>
            </label>
          </div>
          <div class="pform-foot">
            <button class="btn btn-primary" :disabled="busyProvider" @click="saveProvider">保存</button>
            <button class="btn" :disabled="busyProvider" @click="testProvider">测试连接</button>
            <button class="btn" @click="closeProviderForm">取消</button>
            <transition name="fade">
              <span v-if="providerMsg" class="save-msg" :class="{ ok: providerMsg.includes('已保存') }">{{ providerMsg }}</span>
            </transition>
            <span v-if="testResult" class="test-result" :class="{ ok: testResult.startsWith('✅'), bad: testResult.startsWith('❌') }">{{ testResult }}</span>
          </div>
        </div>
      </transition>
    </div>

    <!-- 对话 + 报告 -->
    <div class="grid">
      <div class="card panel chat-panel">
        <div class="sec-head">
          <span class="sec-bar"></span>
          <h4>对话</h4>
        </div>
        <div class="chat">
          <div v-for="(m, i) in chatLog" :key="i" class="bubble" :class="m.role">
            {{ m.text }}
          </div>
          <div v-if="sending" class="bubble ai typing">
            <span class="dot"></span><span class="dot"></span><span class="dot"></span>
          </div>
          <div v-if="!chatLog.length && !sending" class="text-3 empty-chat">向 FinFeed 的 AI 提问市场 / 新闻相关问题</div>
        </div>
        <div class="chat-input">
          <input v-model="chatInput" @keyup.enter="sendChat" placeholder="输入问题…" :disabled="sending" />
          <button class="btn btn-primary" @click="sendChat" :disabled="sending">发送</button>
        </div>
      </div>

      <div class="card panel report-panel">
        <div class="sec-head">
          <span class="sec-bar"></span>
          <h4>历史报告</h4>
        </div>
        <div class="reports">
          <div v-for="rp in reports" :key="rp.id" class="report" @click="openReport(rp.id)">
            <span class="rt">{{ rp.title || ('报告 #' + rp.id) }}</span>
            <span class="text-3">{{ rp.created_at || '' }}</span>
          </div>
          <EmptyState v-if="!reports.length" text="暂无报告，点击上方「生成每日复盘」" />
        </div>
        <transition name="fade">
          <div v-if="activeReport" class="report-detail">
            <button class="close" @click="activeReport = null">✕</button>
            <h4>{{ activeReport.title || ('报告 #' + activeReport.id) }}</h4>
            <pre>{{ activeReport.content || activeReport.error || '（无内容）' }}</pre>
          </div>
        </transition>
      </div>
    </div>
  </div>
</template>

<style scoped>
.ai {
  width: 100%;
  display: flex;
  flex-direction: column;
  gap: var(--sp-4);
}

/* ── 通用卡片 ── */
.card {
  background: var(--bg-surface);
  border: 1px solid var(--border);
  border-radius: var(--r-lg);
  box-shadow: var(--shadow-sm);
}

/* ── 分区标题 ── */
.sec-head {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-bottom: var(--sp-4);
}
.sec-bar {
  width: 4px;
  height: 18px;
  border-radius: var(--r-pill);
  background: var(--primary);
}
.sec-head h4 {
  font-size: var(--fs-md);
  font-weight: 700;
  color: var(--text-1);
}
.sec-hint {
  font-size: var(--fs-xs);
  color: var(--text-3);
  margin-left: auto;
}

/* ── 头部 ── */
.top {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  padding: var(--sp-4) var(--sp-5);
}
.brand {
  display: flex;
  align-items: center;
  gap: 14px;
}
.brand-ico {
  font-size: 32px;
  line-height: 1;
}
.top-l h3 {
  font-size: var(--fs-lg);
  font-weight: 700;
}
.status-line {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-top: 6px;
  font-size: var(--fs-sm);
}
.status-sub {
  margin-top: 4px;
  font-size: var(--fs-xs);
  word-break: break-all;
}
.t-ok { color: var(--down); }
.t-bad { color: var(--up); }
.t-idle { color: var(--text-3); }
.chip {
  padding: 3px 11px;
  border-radius: var(--r-pill);
  font-size: var(--fs-xs);
  font-weight: 600;
}
.chip.ok { background: var(--down-subtle); color: var(--down); }
.chip.bad { background: var(--up-subtle); color: var(--up); }

/* ── 结果横幅 ── */
.banner {
  padding: 11px 16px;
  border-radius: var(--r-md);
  font-size: var(--fs-sm);
  font-weight: 500;
}
.banner.ok { background: var(--down-subtle); color: var(--down); }
.banner.err { background: var(--up-subtle); color: var(--up); }

/* ── 配置面板 ── */
.cfg { padding: var(--sp-5); }
.cfg-grid {
  display: flex;
  gap: 16px;
  flex-wrap: wrap;
  margin-bottom: var(--sp-5);
}
.fld {
  display: flex;
  flex-direction: column;
  gap: 6px;
  font-size: var(--fs-xs);
  font-weight: 500;
  color: var(--text-2);
  min-width: 170px;
}
.fld.grow { flex: 1; min-width: 240px; }
.ctrl {
  position: relative;
}
.ctrl select,
.ctrl input {
  width: 100%;
  border: 1px solid var(--border);
  border-radius: var(--r-md);
  padding: 11px 13px;
  font-size: var(--fs-base);
  background: var(--bg-surface);
  color: var(--text-1);
  outline: none;
  transition: border-color 0.15s, box-shadow 0.15s;
  appearance: none;
}
.ctrl select {
  background-image: url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='12' height='12' fill='%239ca3af' viewBox='0 0 16 16'%3E%3Cpath d='M4 6l4 4 4-4'/%3E%3C/svg%3E");
  background-repeat: no-repeat;
  background-position: right 13px center;
  padding-right: 34px;
}
.ctrl select:focus,
.ctrl input:focus {
  border-color: var(--primary);
  box-shadow: 0 0 0 3px var(--primary-subtle);
}

/* ── 提示词 ── */
.prompts {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 16px;
  margin-bottom: var(--sp-5);
  padding-top: var(--sp-4);
  border-top: 1px dashed var(--border);
}
.pfld {
  display: flex;
  flex-direction: column;
  gap: 6px;
  font-size: var(--fs-xs);
  font-weight: 500;
  color: var(--text-2);
}
.pfld textarea {
  width: 100%;
  border: 1px solid var(--border);
  border-left: 3px solid var(--primary);
  border-radius: var(--r-md);
  padding: 11px 13px;
  font-size: var(--fs-sm);
  line-height: 1.6;
  background: var(--bg-surface-2);
  color: var(--text-1);
  resize: vertical;
  font-family: var(--font-num);
  outline: none;
  transition: border-color 0.15s, box-shadow 0.15s;
}
.pfld textarea:focus {
  border-color: var(--primary);
  border-left-color: var(--primary);
  box-shadow: 0 0 0 3px var(--primary-subtle);
}

.cfg-foot {
  display: flex;
  align-items: center;
  gap: 14px;
}
.save-msg { font-size: var(--fs-sm); color: var(--up); }
.save-msg.ok { color: var(--down); }

/* ── 模型管理 ── */
.providers {
  display: flex;
  flex-direction: column;
  gap: 10px;
}
.provider {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 14px;
  padding: 13px 16px;
  border: 1px solid var(--border);
  border-radius: var(--r-md);
  background: var(--bg-surface);
  transition: all 0.15s;
}
.provider.default {
  border-color: var(--primary);
  background: var(--primary-subtle);
}
.provider:hover { border-color: var(--border-strong); }
.p-name {
  font-size: var(--fs-base);
  font-weight: 600;
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}
.p-meta {
  margin-top: 4px;
  font-size: var(--fs-xs);
  word-break: break-all;
}
.tag {
  font-size: 10px;
  font-weight: 700;
  padding: 1px 8px;
  border-radius: var(--r-pill);
}
.tag-default { background: var(--primary); color: #fff; }
.tag-on { background: var(--down-subtle); color: var(--down); }
.tag-off { background: var(--bg-surface-2); color: var(--text-3); }
.p-actions {
  display: flex;
  gap: 8px;
  flex-shrink: 0;
}

/* 模型表单 */
.pform {
  margin-top: var(--sp-4);
  padding: var(--sp-4);
  border: 1px dashed var(--border);
  border-radius: var(--r-md);
  background: var(--bg-surface-2);
}
.pform-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 14px;
}
.pf {
  display: flex;
  flex-direction: column;
  gap: 6px;
  font-size: var(--fs-xs);
  font-weight: 500;
  color: var(--text-2);
}
.pf.span2 { grid-column: 1 / -1; }
.pf input,
.pf select {
  width: 100%;
  border: 1px solid var(--border);
  border-radius: var(--r-md);
  padding: 10px 12px;
  font-size: var(--fs-sm);
  background: var(--bg-surface);
  color: var(--text-1);
  outline: none;
  transition: border-color 0.15s, box-shadow 0.15s;
}
.pf input:focus,
.pf select:focus {
  border-color: var(--primary);
  box-shadow: 0 0 0 3px var(--primary-subtle);
}
.pf.check {
  flex-direction: row;
  align-items: center;
  gap: 8px;
}
.pf.check input { width: auto; }
.pform-foot {
  display: flex;
  align-items: center;
  gap: 12px;
  margin-top: var(--sp-4);
  flex-wrap: wrap;
}
.test-result { font-size: var(--fs-sm); }
.test-result.ok { color: var(--down); }
.test-result.bad { color: var(--up); }

/* ── 按钮 ── */
.btn {
  border: 1px solid var(--border);
  background: var(--bg-surface);
  color: var(--text-1);
  border-radius: var(--r-md);
  padding: 9px 18px;
  font-size: var(--fs-sm);
  cursor: pointer;
  transition: all 0.15s;
}
.btn:hover { background: var(--bg-hover); }
.btn-primary {
  background: var(--primary);
  color: #fff;
  border-color: var(--primary);
}
.btn-primary:hover { background: var(--primary-hover); }
.btn-primary:disabled { opacity: 0.6; cursor: not-allowed; }
.btn.sm { padding: 7px 14px; font-size: var(--fs-xs); margin-left: auto; }
.btn.xs { padding: 6px 12px; font-size: var(--fs-xs); }
.btn.danger { color: var(--up); border-color: var(--up-subtle); }
.btn.danger:hover { background: var(--up-subtle); }
.btn.lg { padding: 12px 26px; font-size: var(--fs-base); font-weight: 600; }

/* ── 对话 + 报告 ── */
.grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: var(--sp-4);
  align-items: stretch;
}
.panel {
  padding: var(--sp-5);
  display: flex;
  flex-direction: column;
  min-height: 540px;
}
.chat {
  flex: 1;
  min-height: 380px;
  overflow-y: auto;
  display: flex;
  flex-direction: column;
  gap: 12px;
  padding: var(--sp-2) var(--sp-1);
}
.empty-chat {
  margin: auto;
  font-size: var(--fs-sm);
}
.bubble {
  max-width: 86%;
  padding: 11px 15px;
  border-radius: 14px;
  font-size: var(--fs-sm);
  white-space: pre-wrap;
  line-height: 1.55;
}
.bubble.user {
  align-self: flex-end;
  background: var(--primary);
  color: #fff;
  border-bottom-right-radius: 4px;
}
.bubble.ai {
  align-self: flex-start;
  background: var(--bg-surface-2);
  color: var(--text-1);
  border-bottom-left-radius: 4px;
}
.bubble.typing {
  display: flex;
  gap: 4px;
  padding: 14px 16px;
}
.bubble.typing .dot {
  width: 7px;
  height: 7px;
  border-radius: 50%;
  background: var(--text-3);
  animation: dot-bounce 1.2s infinite ease-in-out;
}
.bubble.typing .dot:nth-child(2) { animation-delay: 0.2s; }
.bubble.typing .dot:nth-child(3) { animation-delay: 0.4s; }
@keyframes dot-bounce {
  0%, 60%, 100% { transform: translateY(0); opacity: 0.4; }
  30% { transform: translateY(-5px); opacity: 1; }
}
.chat-input {
  display: flex;
  gap: 10px;
  margin-top: var(--sp-3);
}
.chat-input input {
  flex: 1;
  border: 1px solid var(--border);
  border-radius: var(--r-md);
  padding: 11px 14px;
  font-size: var(--fs-sm);
  outline: none;
  background: var(--bg-surface);
  color: var(--text-1);
  transition: border-color 0.15s, box-shadow 0.15s;
}
.chat-input input:focus {
  border-color: var(--primary);
  box-shadow: 0 0 0 3px var(--primary-subtle);
}
.chat-input input:disabled {
  opacity: 0.6;
  cursor: not-allowed;
}

.reports {
  flex: 1;
  overflow-y: auto;
  display: flex;
  flex-direction: column;
  gap: 8px;
}
.report {
  display: flex;
  justify-content: space-between;
  gap: 10px;
  padding: 12px 14px;
  border: 1px solid var(--border);
  border-radius: var(--r-md);
  cursor: pointer;
  font-size: var(--fs-sm);
  transition: all 0.15s;
}
.report:hover {
  background: var(--bg-hover);
  border-color: var(--border-strong);
}
.rt { font-weight: 500; }

.report-detail {
  margin-top: var(--sp-3);
  padding: var(--sp-4);
  background: var(--bg-surface-2);
  border: 1px solid var(--border);
  border-radius: var(--r-md);
  position: relative;
}
.report-detail pre {
  white-space: pre-wrap;
  font-size: var(--fs-sm);
  line-height: 1.6;
  max-height: 280px;
  overflow-y: auto;
  margin: 0;
}
.close {
  position: absolute;
  top: 10px;
  right: 10px;
  border: none;
  background: none;
  color: var(--text-3);
  font-size: 16px;
  cursor: pointer;
}

/* ── 过渡 ── */
.fade-enter-active,
.fade-leave-active { transition: opacity 0.2s; }
.fade-enter-from,
.fade-leave-to { opacity: 0; }

@media (max-width: 880px) {
  .grid { grid-template-columns: 1fr; }
  .prompts { grid-template-columns: 1fr; }
  .pform-grid { grid-template-columns: 1fr; }
  .panel { min-height: 440px; }
}
</style>
