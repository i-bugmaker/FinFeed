<script setup>
/**
 * SettingsView — AI 设置中心
 * 左导航（模型管理 / Prompt 模板 / 分析默认值）＋ 右表单
 * 模型 CRUD 保留原有交互，升级为卡片列表 + 抽屉表单；Prompt 默认折叠为高级区。
 */
import { ref, computed, onMounted } from 'vue'
import { useAiStore } from '../../store/ai'
import { api } from '../../api/client'
import AppIcon from '../../ui/AppIcon.vue'
import AppInput from '../../ui/AppInput.vue'
import AppSelect from '../../ui/AppSelect.vue'
import AppCheckbox from '../../ui/AppCheckbox.vue'

const store = useAiStore()

const section = ref('models')
const sections = [
  { key: 'models', label: '模型管理', icon: 'cpu' },
  { key: 'prompts', label: 'Prompt 模板', icon: 'sliders' },
  { key: 'defaults', label: '分析默认值', icon: 'settings' },
]

// ---------- 模型 ----------
const showForm = ref(false)
const editingId = ref(null)
const busy = ref(false)
const msg = ref('')
const testResult = ref('')
const testingIds = ref(new Set()) // 自动连通性测试中的模型 id
const autoTesting = ref(false)
const form = ref(blankProvider())
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
const presetOptions = computed(() => PRESETS.map((p) => ({ label: p.label, value: p.key })))
const testOk = computed(() => testResult.value && testResult.value.includes('连通正常'))
const testBad = computed(() => testResult.value && (testResult.value.includes('失败') || testResult.value.includes('连通失败')))

function blankProvider() {
  return { id: null, name: '', base_url: '', model: '', api_key: '', preset: 'custom', temperature: 0.3, max_tokens: 4096, timeout: 120, is_default: false, enabled: true }
}
function openAdd() {
  editingId.value = null
  form.value = blankProvider()
  testResult.value = ''
  showForm.value = true
}
function openEdit(p) {
  editingId.value = p.id
  form.value = { ...blankProvider(), ...p, api_key: '' }
  testResult.value = ''
  showForm.value = true
}
function applyPreset() {
  const pre = PRESETS.find((x) => x.key === form.value.preset)
  if (pre && pre.key !== 'custom') {
    form.value.base_url = pre.base_url
    form.value.model = pre.model
  }
}
async function saveProvider() {
  busy.value = true
  msg.value = ''
  try {
    const f = { ...form.value }
    if (!f.api_key) delete f.api_key
    const r = await api.llmPost('/provider/save', f)
    if (r && r.success) {
      msg.value = '模型已保存'
      showForm.value = false
      await store.loadProviders()
      await store.loadStatus()
    } else {
      msg.value = '保存失败：' + (r.error || '未知错误')
    }
  } catch (e) {
    msg.value = '保存失败：' + e.message
  } finally {
    busy.value = false
    setTimeout(() => (msg.value = ''), 3000)
  }
}
async function testProvider() {
  busy.value = true
  testResult.value = '测试中…'
  try {
    const f = { ...form.value }
    const payload = editingId.value && !f.api_key ? { id: editingId.value, use_saved: true } : f
    const r = await api.llmPost('/provider/test', payload)
    testResult.value = r && r.ok
      ? `连通正常（${r.model || ''}）${r.latency_ms ? ' · ' + Math.round(r.latency_ms) + 'ms' : ''}`
      : (r.message || '连通失败')
  } catch (e) {
    testResult.value = '测试失败：' + e.message
  } finally {
    busy.value = false
  }
}
async function setDefault(id) {
  await api.llmPost('/provider/default', { id })
  await store.loadProviders()
  await store.loadStatus()
}

// 进入页面时自动逐个测试所有已保存模型的连通性（串行，避免并发风暴）
async function autoTestAll() {
  const providers = [...store.providers]
  if (!providers.length || autoTesting.value) return
  autoTesting.value = true
  const ids = new Set()
  for (const p of providers) {
    ids.add(p.id)
    testingIds.value = new Set(ids)
    try {
      await api.llmPost('/provider/test', { id: p.id, use_saved: true })
    } catch (e) {
      // 单个失败不中断整体流程
    }
  }
  testingIds.value = new Set()
  autoTesting.value = false
  await store.loadProviders()
  await store.loadStatus()
}
async function deleteProvider(id) {
  if (!window.confirm('确认删除该模型配置？')) return
  await api.llmPost('/provider/delete', { id })
  await store.loadProviders()
  await store.loadStatus()
}

// ---------- Prompt ----------
const showPrompts = ref(true) // 默认展开，便于直接查看与编辑模板
const prompts = ref({ map_system: '', map_user: '', reduce_system: '', reduce_user: '', single_user: '' })
const promptLabels = {
  map_system: '分析映射 · 系统提示',
  map_user: '分析映射 · 用户模板',
  reduce_system: '汇总成文 · 系统提示',
  reduce_user: '汇总成文 · 用户模板',
  single_user: '单轮分析 · 用户模板',
}
const saveMsg = ref('')
async function loadPrompts() {
  try {
    const p = await api.llm('/prompts')
    const defaults = p.defaults || {}
    const custom = p.custom || {}
    for (const k of Object.keys(prompts.value)) {
      const saved = custom[k]
      prompts.value[k] = saved != null && saved !== '' ? saved : defaults[k] || ''
    }
  } catch (e) {}
}
async function savePrompts() {
  saveMsg.value = ''
  try {
    const payload = {}
    for (const k of Object.keys(prompts.value)) payload['prompt_' + k] = prompts.value[k]
    const r = await api.llmPost('/prompts', payload)
    saveMsg.value = r && r.success ? 'Prompt 已保存' : '保存失败'
    setTimeout(() => (saveMsg.value = ''), 3000)
  } catch (e) {
    saveMsg.value = '保存失败：' + e.message
  }
}

// ---------- 默认值 ----------
const defaults = ref({ scope: 'all', window: 24, focus: '' })
const scopeOptions = computed(() => store.scopeOptions.map((s) => ({ label: s.label, value: s.key })))
const windowOptions = computed(() => store.windowOptions.map((w) => ({ label: `${w} 小时`, value: w })))
function saveDefaults() {
  try {
    localStorage.setItem('finfeed_ai_config', JSON.stringify(defaults.value))
    window.alert('默认值已保存到本地')
  } catch (e) {}
}

onMounted(() => {
  store.loadProviders()
  store.loadStatus()
  store.loadInit()
  loadPrompts()
  // 恢复本地默认值
  try {
    const raw = localStorage.getItem('finfeed_ai_config')
    if (raw) {
      const c = JSON.parse(raw)
      if (c.scope) defaults.value.scope = c.scope
      if (c.window) defaults.value.window = c.window
      if (c.focus !== undefined) defaults.value.focus = c.focus
    }
  } catch (e) {}
  // 等待 providers 加载完成后自动测试连通性
  setTimeout(() => {
    if (store.providers.length) autoTestAll()
  }, 300)
})
</script>

<template>
  <div class="sv">
    <div class="sv__layout">
      <!-- 左导航 -->
      <aside class="sv__nav">
        <button v-for="s in sections" :key="s.key" class="sv__nav-item" :class="{ on: section === s.key }" @click="section = s.key">
          <AppIcon :name="s.icon" size="sm" /> {{ s.label }}
        </button>
      </aside>

      <!-- 右内容 -->
      <div class="sv__content">
        <!-- 模型管理 -->
        <div v-if="section === 'models'" class="sv__panel">
          <div class="sv__head">
            <h3 class="sv__h3">模型管理</h3>
            <button class="sv__add" @click="openAdd"><AppIcon name="plus" size="sm" /> 添加模型</button>
          </div>
          <div v-if="autoTesting" class="sv__autotest">
            <span class="sv__autotest-spin"></span>
            正在自动测试模型连通性（{{ store.providers.length - testingIds.size }}/{{ store.providers.length }}）…
          </div>
          <div v-if="store.providers.length" class="sv__providers">
            <div v-for="p in store.providers" :key="p.id" class="sv__provider" :class="{ def: p.is_default }">
              <div class="sv__p-main">
                <div class="sv__p-name">
                  {{ p.name }}
                  <span v-if="p.is_default" class="sv__badge sv__badge--brand">默认</span>
                  <span :class="p.enabled ? 'sv__badge sv__badge--ok' : 'sv__badge sv__badge--muted'">{{ p.enabled ? '已启用' : '已停用' }}</span>
                  <span v-if="testingIds.has(p.id)" class="sv__badge sv__badge--run">测试中…</span>
                  <span v-else-if="p.test_status === 1" class="sv__badge sv__badge--ok">已连通 {{ p.test_latency ? Math.round(p.test_latency) + 'ms' : '' }}</span>
                  <span v-else-if="p.test_status === 0" class="sv__badge sv__badge--bad">连通失败</span>
                  <span v-else class="sv__badge sv__badge--muted">未测试</span>
                </div>
                <div class="sv__p-meta">{{ p.model }} · {{ p.base_url }}</div>
              </div>
              <div class="sv__p-ops">
                <button v-if="!p.is_default" class="sv__op" @click="setDefault(p.id)">设为默认</button>
                <button class="sv__op" @click="openEdit(p)"><AppIcon name="edit" size="sm" /> 编辑</button>
                <button class="sv__op sv__op--danger" @click="deleteProvider(p.id)"><AppIcon name="trash" size="sm" /></button>
              </div>
            </div>
          </div>
          <div v-else class="sv__empty">
            <AppIcon name="cpu" size="xl" />
            <p>还没有配置任何模型</p>
            <button class="sv__add" @click="openAdd">添加第一个模型</button>
          </div>

          <!-- 表单抽屉 -->
          <Teleport to="body">
            <Transition name="sv-fade">
              <div v-if="showForm" class="sv__mask" @click.self="showForm = false">
                <div class="sv__drawer">
                  <div class="sv__drawer-head">
                    <span>{{ editingId ? '编辑模型' : '添加模型' }}</span>
                    <button class="sv__drawer-x" @click="showForm = false"><AppIcon name="x" size="sm" /></button>
                  </div>
                  <div class="sv__drawer-body">
                    <AppInput v-model="form.name" label="名称" placeholder="如：我的 DeepSeek" />
                    <AppSelect v-model="form.preset" label="预设" :options="presetOptions" @change="applyPreset" />
                    <AppInput v-model="form.base_url" label="接口地址 (Base URL)" placeholder="https://..." />
                    <AppInput v-model="form.model" label="模型名称" placeholder="如：deepseek-chat" />
                    <AppInput v-model="form.api_key" type="password" label="API Key" :placeholder="editingId ? '留空则保留原密钥' : 'sk-...'" />
                    <div class="sv__grid2">
                      <AppInput v-model.number="form.temperature" type="number" label="温度 (0–2)" />
                      <AppInput v-model.number="form.max_tokens" type="number" label="最大 Token" />
                    </div>
                    <AppInput v-model.number="form.timeout" type="number" label="超时 (秒)" />
                    <AppCheckbox v-model="form.is_default" label="设为默认模型" />
                    <AppCheckbox v-model="form.enabled" label="启用该模型" />
                    <p v-if="testResult" class="sv__test" :class="{ err: testBad, ok: testOk }">{{ testResult }}</p>
                  </div>
                  <div class="sv__drawer-foot">
                    <button class="sv__btn sv__btn--ghost" @click="showForm = false">取消</button>
                    <button class="sv__btn" :disabled="busy" @click="testProvider">{{ busy ? '测试中…' : '测试连接' }}</button>
                    <button class="sv__btn sv__btn--primary" :disabled="busy" @click="saveProvider">保存</button>
                  </div>
                  <p v-if="msg" class="sv__msg">{{ msg }}</p>
                </div>
              </div>
            </Transition>
          </Teleport>
        </div>

        <!-- Prompt -->
        <div v-else-if="section === 'prompts'" class="sv__panel">
          <div class="sv__head">
            <h3 class="sv__h3">Prompt 模板</h3>
            <button class="sv__add" @click="savePrompts"><AppIcon name="save" size="sm" /> 保存模板</button>
          </div>
          <div class="sv__adv">
            <button class="sv__adv-toggle" @click="showPrompts = !showPrompts">
              <AppIcon :name="showPrompts ? 'chevron-down' : 'chevron-right'" size="sm" />
              {{ showPrompts ? '收起高级配置' : '展开高级配置（面向高级用户）' }}
            </button>
            <Transition name="sv-fade">
              <div v-if="showPrompts" class="sv__prompts">
                <p class="sv__hint">这些模板决定了 AI 分析报告的质量。修改后需保存，修改前请先阅读默认模板理解各环节作用。</p>
                <label v-for="(lbl, key) in promptLabels" :key="key" class="sv__pfld">
                  <span>{{ lbl }}</span>
                  <textarea v-model="prompts[key]" rows="5" :placeholder="lbl"></textarea>
                </label>
                <p v-if="saveMsg" class="sv__msg" style="color:var(--ff-brand, #2f7d5b)">{{ saveMsg }}</p>
              </div>
            </Transition>
          </div>
        </div>

        <!-- 默认值 -->
        <div v-else class="sv__panel">
          <div class="sv__head"><h3 class="sv__h3">分析默认值</h3></div>
          <div class="sv__defaults">
            <AppSelect v-model="defaults.scope" label="默认分析范围" :options="scopeOptions" />
            <AppSelect v-model="defaults.window" label="默认时间窗口" :options="windowOptions" />
            <AppInput v-model="defaults.focus" label="自定义焦点（可选）" placeholder="如：重点关注半导体与新能源" />
            <button class="sv__btn sv__btn--primary" style="align-self:flex-start" @click="saveDefaults">保存默认值</button>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.sv__layout { display: grid; grid-template-columns: 200px 1fr; gap: 16px; align-items: start; }
.sv__nav { background: var(--ff-bg-surface, #fff); border: 1px solid var(--ff-border, #e5e7eb); border-radius: 13px; padding: 8px; display: flex; flex-direction: column; gap: 2px; }
.sv__nav-item { display: flex; align-items: center; gap: 8px; border: none; background: none; border-radius: 9px; padding: 10px 13px; font-size: 13.5px; font-weight: 600; color: var(--ff-text-2, #6b7280); cursor: pointer; text-align: left; }
.sv__nav-item:hover { background: var(--ff-bg-hover, #f3f6f4); }
.sv__nav-item.on { background: var(--ff-bg-brand-subtle, #eaf4ef); color: var(--ff-brand-dark, #1d4e39); }
.sv__content { min-width: 0; }
.sv__panel { background: var(--ff-bg-surface, #fff); border: 1px solid var(--ff-border, #e5e7eb); border-radius: 13px; padding: 18px; }
.sv__head { display: flex; align-items: center; justify-content: space-between; margin-bottom: 14px; }
.sv__h3 { font-size: 16px; font-weight: 700; }
.sv__add { display: inline-flex; align-items: center; gap: 6px; border: none; background: var(--ff-brand, #2f7d5b); color: #fff; border-radius: 9px; padding: 8px 15px; font-size: 12.5px; font-weight: 600; cursor: pointer; }
.sv__add:hover { background: var(--ff-brand-dark, #1d4e39); }
.sv__providers { display: flex; flex-direction: column; gap: 9px; }
.sv__provider { display: flex; align-items: center; justify-content: space-between; gap: 12px; padding: 12px 14px; border: 1px solid var(--ff-border, #e5e7eb); border-radius: 11px; }
.sv__provider.def { border-color: var(--ff-border-brand, #9fc3b1); background: var(--ff-bg-brand-subtle, #f4faf7); }
.sv__p-main { min-width: 0; }
.sv__p-name { display: flex; align-items: center; gap: 7px; flex-wrap: wrap; font-weight: 700; font-size: 14px; }
.sv__p-meta { font-size: 11.5px; color: var(--ff-text-3, #9ca3af); margin-top: 3px; word-break: break-all; }
.sv__badge { font-size: 10.5px; font-weight: 700; padding: 2px 8px; border-radius: 8px; }
.sv__badge--brand { background: var(--ff-bg-brand-subtle, #eaf4ef); color: var(--ff-brand-dark, #1d4e39); }
.sv__badge--ok { background: var(--ff-down-subtle, #e8f7ee); color: var(--ff-up, #12a150); }
.sv__badge--bad { background: var(--ff-up-subtle, #fdecec); color: var(--ff-down, #e5484d); }
.sv__badge--muted { background: var(--ff-bg-subtle, #f1f4f2); color: var(--ff-text-3, #9ca3af); }
.sv__badge--run { background: var(--ff-bg-brand-subtle, #eaf4ef); color: var(--ff-brand-dark, #1d4e39); animation: sv-pulse 1.2s infinite; }
@keyframes sv-pulse { 0%,100% { opacity: 1; } 50% { opacity: 0.55; } }
.sv__autotest { display: flex; align-items: center; gap: 8px; font-size: 12.5px; color: var(--ff-brand-dark, #1d4e39); background: var(--ff-bg-brand-subtle, #eaf4ef); border: 1px solid var(--ff-border-brand, #bfd9cc); border-radius: 10px; padding: 9px 13px; margin-bottom: 12px; }
.sv__autotest-spin { width: 13px; height: 13px; border: 2px solid var(--ff-border-brand, #bfd9cc); border-top-color: var(--ff-brand, #2f7d5b); border-radius: 50%; animation: sv-rot 0.8s linear infinite; flex-shrink: 0; }
@keyframes sv-rot { to { transform: rotate(360deg); } }
.sv__p-ops { display: flex; gap: 6px; flex-shrink: 0; }
.sv__op { display: inline-flex; align-items: center; gap: 4px; border: 1px solid var(--ff-border, #e5e7eb); background: var(--ff-bg-surface, #fff); border-radius: 8px; padding: 6px 11px; font-size: 12px; font-weight: 600; color: var(--ff-text-2, #6b7280); cursor: pointer; }
.sv__op:hover { border-color: var(--ff-border-brand, #9fc3b1); color: var(--ff-brand, #2f7d5b); }
.sv__op--danger:hover { color: var(--ff-down, #e5484d); border-color: #f5c6c8; }
.sv__empty { text-align: center; padding: 40px 10px; color: var(--ff-text-3, #9ca3af); }
.sv__empty p { margin: 10px 0 14px; font-size: 13.5px; }
.sv__mask { position: fixed; inset: 0; z-index: 950; background: rgba(15, 25, 20, 0.35); display: flex; justify-content: flex-end; }
.sv__drawer { width: 440px; max-width: 92vw; height: 100%; background: var(--ff-bg-surface, #fff); display: flex; flex-direction: column; box-shadow: -8px 0 24px rgba(10, 30, 22, 0.15); }
.sv__drawer-head { display: flex; align-items: center; justify-content: space-between; padding: 16px 20px; border-bottom: 1px solid var(--ff-border, #e5e7eb); font-size: 15px; font-weight: 700; }
.sv__drawer-x { border: none; background: var(--ff-bg-subtle, #f3f6f4); border-radius: 8px; width: 30px; height: 30px; cursor: pointer; color: var(--ff-text-2, #6b7280); }
.sv__drawer-body { flex: 1; overflow-y: auto; padding: 18px 20px; display: flex; flex-direction: column; gap: 13px; }
.sv__grid2 { display: grid; grid-template-columns: 1fr 1fr; gap: 10px; }
.sv__drawer-foot { display: flex; justify-content: flex-end; gap: 8px; padding: 14px 20px; border-top: 1px solid var(--ff-border, #e5e7eb); }
.sv__btn { border: 1px solid var(--ff-border, #e5e7eb); background: var(--ff-bg-surface, #fff); border-radius: 9px; padding: 8px 16px; font-size: 12.5px; font-weight: 600; color: var(--ff-text-2, #6b7280); cursor: pointer; }
.sv__btn--primary { background: var(--ff-brand, #2f7d5b); color: #fff; border-color: var(--ff-brand, #2f7d5b); }
.sv__btn--ghost { border-color: transparent; background: none; }
.sv__btn:disabled { opacity: 0.5; }
.sv__test { font-size: 12px; margin: 0; }
.sv__test.ok { color: var(--ff-brand, #2f7d5b); }
.sv__test.err { color: var(--ff-down, #e5484d); }
.sv__msg { font-size: 12.5px; color: var(--ff-down, #e5484d); padding: 0 20px 12px; margin: 0; }
.sv__adv-toggle { display: inline-flex; align-items: center; gap: 6px; border: 1px solid var(--ff-border, #e5e7eb); background: var(--ff-bg-subtle, #f9fafb); border-radius: 9px; padding: 8px 14px; font-size: 12.5px; font-weight: 600; color: var(--ff-text-2, #6b7280); cursor: pointer; }
.sv__prompts { margin-top: 14px; display: grid; grid-template-columns: 1fr 1fr; gap: 13px; }
.sv__hint { grid-column: 1 / -1; font-size: 12px; color: var(--ff-text-3, #9ca3af); }
.sv__pfld { display: flex; flex-direction: column; gap: 6px; font-size: 12.5px; font-weight: 600; color: var(--ff-text-secondary, #4b5563); }
.sv__pfld textarea { border: 1px solid var(--ff-border, #d1d5db); border-left: 3px solid var(--ff-brand, #2f7d5b); border-radius: 9px; padding: 10px 12px; font-size: 13.5px; line-height: 1.7; background: var(--ff-bg-surface, #fff); color: var(--ff-text-primary, #1f2937); resize: vertical; font-family: var(--ff-sans, -apple-system, 'PingFang SC', 'Microsoft YaHei', sans-serif); -webkit-font-smoothing: antialiased; outline: none; }
.sv__pfld textarea::placeholder { color: var(--ff-text-3, #9ca3af); }
.sv__pfld textarea:focus { border-color: var(--ff-border-focus, #4f9e76); box-shadow: 0 0 0 3px rgba(47, 125, 91, 0.12); }
.sv__defaults { display: flex; flex-direction: column; gap: 13px; max-width: 420px; }
.sv-fade-enter-active, .sv-fade-leave-active { transition: opacity 160ms; }
.sv-fade-enter-from, .sv-fade-leave-to { opacity: 0; }

@media (max-width: 768px) {
  .sv__layout { grid-template-columns: 1fr; }
  .sv__nav { flex-direction: row; overflow-x: auto; }
  .sv__prompts { grid-template-columns: 1fr; }
}
</style>
