<script setup>
/**
 * SettingsView — AI 设置中心
 * 左导航（模型管理 / Prompt 模板 / 分析默认值）＋ 右表单
 * 模型添加/编辑统一使用 ModelConfigDialog（与工作台一致的居中弹窗交互）。
 */
import { ref, computed, onMounted } from 'vue'
import { useAiStore } from '../../store/ai'
import { api } from '../../api/client'
import AppIcon from '../../ui/AppIcon.vue'
import AppInput from '../../ui/AppInput.vue'
import AppSelect from '../../ui/AppSelect.vue'
import AppButton from '../../ui/AppButton.vue'
import OnboardWizard from '../../components/ai/OnboardWizard.vue'
import { toastSuccess, toastError } from '../../composables/useToast'

const store = useAiStore()

const section = ref('models')
const sections = [
  { key: 'models', label: '模型管理', icon: 'cpu' },
  { key: 'agents', label: '智能体 / 角色', icon: 'sparkles' },
  { key: 'prompts', label: 'Prompt 模板', icon: 'sliders' },
  { key: 'defaults', label: '分析默认值', icon: 'settings' },
]

// ---------- 模型 ----------
const modelDialogOpen = ref(false)
const editingProvider = ref(null) // null=新增，对象=编辑
const testingIds = ref(new Set()) // 自动连通性测试中的模型 id
const autoTesting = ref(false)

function openAdd() {
  editingProvider.value = null
  modelDialogOpen.value = true
}
function openEdit(p) {
  editingProvider.value = p
  modelDialogOpen.value = true
}
async function onModelSaved() {
  modelDialogOpen.value = false
  await store.loadProviders()
  await store.loadStatus()
  // 新添加的模型无测试记录 → 立即自动测试并开始计时；已有模型仍遵守各自冷却
  autoTestAll()
}
async function setDefault(id) {
  await api.llmPost('/provider/default', { id })
  await store.loadProviders()
  await store.loadStatus()
}

const AUTO_TEST_COOLDOWN = 60 * 60 * 1000 // 单个模型自动测试冷却 1 小时
const TEST_MAP_KEY = 'finfeed_ai_auto_test_map' // {providerId: 上次自动测试时间戳}

// 进入页面时自动测试到期模型：按单个模型各自冷却（无记录=新模型 立即测试），
// 1 小时内已测过的模型跳过；手动测试（弹窗内）不受任何冷却限制
async function autoTestAll() {
  const providers = [...store.providers]
  if (!providers.length || autoTesting.value) return
  let map = {}
  try { map = JSON.parse(localStorage.getItem(TEST_MAP_KEY) || '{}') } catch (e) {}
  const now = Date.now()
  // 过滤出需要测试的模型：从未测过（新添加）或距上次超过 1 小时
  const due = providers.filter((p) => {
    const last = Number(map[p.id] || 0)
    return now - last >= AUTO_TEST_COOLDOWN
  })
  if (!due.length) return
  autoTesting.value = true
  const ids = new Set()
  for (const p of due) {
    ids.add(p.id)
    testingIds.value = new Set(ids)
    try {
      await api.llmPost('/provider/test', { id: p.id, use_saved: true })
      map[p.id] = Date.now()
      localStorage.setItem(TEST_MAP_KEY, JSON.stringify(map))
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
const PROMPT_KEYS = [
  'map_system', 'map_user', 'reduce_system', 'reduce_user', 'single_user',
  'stock_system', 'stock_user', 'sentiment_system', 'sentiment_user',
]
const prompts = ref(Object.fromEntries(PROMPT_KEYS.map((k) => [k, ''])))
const promptDefaults = ref(Object.fromEntries(PROMPT_KEYS.map((k) => [k, ''])))

// 按流水线阶段分组：同屏只展示当前阶段的模板，降低视觉密度。
// MAP=分批要点提炼；REDUCE=汇总成章报告；SINGLE=一次性生成报告；
// STOCK/SENTIMENT=个股深度与舆情研判的独立模板。
const PROMPT_STAGES = [
  { key: 'map', label: '① 要点提炼', desc: '把这段时间的新闻分批读懂，抽取每件大事的要点、去掉噪音，供下一步汇总成报告。', keys: ['map_system', 'map_user'] },
  { key: 'reduce', label: '② 汇总成文', desc: '把提炼好的全部要点整理成一份结构完整、章节清晰的报告。', keys: ['reduce_system', 'reduce_user'] },
  { key: 'single', label: '③ 单轮分析', desc: '资讯不多时，直接一次性写出完整报告，跳过「先提炼再汇总」的中间步骤，更快也更省调用。', keys: ['single_user'] },
  { key: 'stock', label: '④ 个股深度', desc: '针对某只个股：结合行情与相关资讯，输出个股分析与判断。', keys: ['stock_system', 'stock_user'] },
  { key: 'sentiment', label: '⑤ 舆情研判', desc: '围绕某个热点或专题，结合市场信息与资讯，输出舆情走势研判。', keys: ['sentiment_system', 'sentiment_user'] },
]
const activeStage = ref('map')
const currentStage = computed(() => PROMPT_STAGES.find((s) => s.key === activeStage.value) || PROMPT_STAGES[0])

// 每个模板的名称与一句话用途说明；compact=true 表示较短的系统提示，用更小的编辑区
const promptMeta = {
  map_system: { name: '系统提示（角色）', desc: '设定分析角色的专业度与事实底线：只用提供的材料，不编造、不推断材料之外的内容。', compact: true },
  map_user: { name: '用户模板（提炼指令）', desc: '告诉模型怎么分批提炼要点、输出成什么格式。{payload} 是程序自动代入的本批新闻，请保留；保留 [编号] 便于在正文标注引用来源。' },
  reduce_system: { name: '系统提示（角色）', desc: '设定汇总成文的角色与排版要求（图标、加粗、要点化、引用标注），让报告结构清晰、易读。', compact: true },
  reduce_user: { name: '用户模板（结构指令）', desc: '规定复盘报告的章节与排版。{facts_block}、{stats_block}、{digests} 由程序自动代入数据，请保留不要删除。' },
  single_user: { name: '用户模板（成文指令）', desc: '规定「一次性成文」时的报告结构与排版。{facts_block}、{stats_block}、{payload} 由程序自动代入，请保留不要删除。' },
  stock_system: { name: '系统提示（角色）', desc: '设定个股分析的研究员角色与数据边界：只基于提供的数据研判，不臆造。', compact: true },
  stock_user: { name: '用户模板（个股结构）', desc: '规定个股报告的结构。{stock_name} 是个股代码/名称，{facts_block}、{payload} 由程序代入，请保留。' },
  sentiment_system: { name: '系统提示（角色）', desc: '设定舆情研判的分析师角色与数据边界：只基于提供的数据，不编造。', compact: true },
  sentiment_user: { name: '用户模板（舆情结构）', desc: '规定舆情报告的结构。{facts_block}、{facts_market_block}、{payload} 由程序代入，请保留不要删除。' },
}

const isCustom = (key) => prompts.value[key] !== promptDefaults.value[key]
const dirtyCount = computed(() => Object.keys(prompts.value).filter(isCustom).length)
const fmtCount = (key) => (prompts.value[key] || '').length.toLocaleString()

function resetPrompt(key) {
  if (!window.confirm('确认恢复该模板为默认内容？')) return
  prompts.value[key] = promptDefaults.value[key] || ''
}
function resetAllPrompts() {
  if (!window.confirm('确认将全部模板恢复为默认内容？（仍需点击「保存模板」才会生效）')) return
  for (const k of Object.keys(prompts.value)) prompts.value[k] = promptDefaults.value[k] || ''
}

const saveMsg = ref('')
let promptsLoadFailed = false
async function loadPrompts() {
  try {
    const p = await api.llm('/prompts')
    const defaults = p.defaults || {}
    const custom = p.custom || {}
    for (const k of Object.keys(prompts.value)) {
      promptDefaults.value[k] = defaults[k] || ''
      const saved = custom[k]
      prompts.value[k] = saved != null && saved !== '' ? saved : defaults[k] || ''
    }
    promptsLoadFailed = false
  } catch (e) {
    // 加载失败必须阻断保存：空表单全量提交会把服务端自定义模板覆盖为空
    promptsLoadFailed = true
    toastError('Prompt 模板加载失败，为避免覆盖已有配置已禁止保存，请刷新重试')
  }
}
async function savePrompts() {
  if (promptsLoadFailed) {
    toastError('模板未加载完成，已阻止保存以保护服务端配置，请刷新页面后重试')
    return
  }
  saveMsg.value = ''
  try {
    const payload = {}
    for (const k of Object.keys(prompts.value)) payload['prompt_' + k] = prompts.value[k]
    const r = await api.llmPost('/prompts', payload)
    if (r && r.success) {
      saveMsg.value = 'Prompt 已保存'
      toastSuccess('Prompt 模板已保存')
    } else {
      saveMsg.value = '保存失败'
      toastError('Prompt 保存失败')
    }
    setTimeout(() => (saveMsg.value = ''), 3000)
  } catch (e) {
    saveMsg.value = '保存失败：' + e.message
    toastError('Prompt 保存失败：' + e.message)
  }
}

// ---------- 智能体 / 角色画像 ----------
const AGENT_FIELDS = [
  { key: 'name', label: '角色名', ph: '如：快讯分析师' },
  { key: 'personality', label: '性格', ph: '如：理性审慎、消息驱动' },
  { key: 'stance', label: '立场', ph: '如：平衡（利好利空同等对待）' },
  { key: 'style', label: '文风', ph: '如：精准聚焦、结论先行' },
  { key: 'tone', label: '语气', ph: '如：专业' },
]
const agents = ref({})      // agent_key -> {name, personality, stance, style, tone, system_prompt}
const agentDefaults = ref({})
const agentMeta = ref({})
const agentKeys = computed(() => Object.keys(agentMeta.value || {}))

function isAgentCustom(key) {
  const cur = agents.value[key] || {}
  const def = agentDefaults.value[key] || {}
  return ['name', 'personality', 'stance', 'style', 'tone'].some((f) => (cur[f] || '') !== (def[f] || '')) || !!cur.system_prompt
}
function agentDirtyCount() {
  let n = 0
  for (const k of agentKeys.value) if (isAgentCustom(k)) n++
  return n
}
async function loadAgents() {
  try {
    const r = await api.llm('/agents')
    agents.value = r.agents || {}
    agentDefaults.value = r.defaults || {}
    agentMeta.value = r.meta || {}
  } catch (e) {
    toastError('智能体画像加载失败：' + e.message)
  }
}
async function saveAgents() {
  try {
    const r = await api.llmPost('/agents', { agents: agents.value })
    if (r && r.success) {
      toastSuccess('智能体画像已保存')
    } else {
      toastError('智能体保存失败')
    }
  } catch (e) {
    toastError('智能体保存失败：' + e.message)
  }
}
async function resetAgent(key) {
  if (!window.confirm(`确认将「${agentMeta.value[key]?.label || key}」恢复为默认画像？（保存后生效）`)) return
  const def = agentDefaults.value[key]
  agents.value[key] = {
    name: def?.name || '',
    personality: def?.personality || '',
    stance: def?.stance || '',
    style: def?.style || '',
    tone: def?.tone || '',
    system_prompt: '',
  }
}

// ---------- 默认值 ----------
const defaults = ref({ scope: 'all', window: 24, focus: '', report_type: 'review' })
const scopeOptions = computed(() => store.scopeOptions.map((s) => ({ label: s.label, value: s.key })))
const windowOptions = computed(() => store.windowOptions.map((w) => ({ label: `${w} 小时`, value: w })))
const typeOptions = computed(() =>
  (store.reportTypes?.length
    ? store.reportTypes
    : [
        { key: 'review', label: '复盘简报' },
        { key: 'stock', label: '个股深度' },
        { key: 'sentiment', label: '舆情研判' },
      ]
  ).map((t) => ({ label: t.label, value: t.key }))
)
function saveDefaults() {
  store.saveConfig({
    scope: defaults.value.scope,
    window: Number(defaults.value.window) || 24,
    focus: defaults.value.focus || '',
    report_type: defaults.value.report_type || 'review',
  })
  toastSuccess('默认值已保存（服务端持久化），生成报告时将使用该范围与窗口')
}

onMounted(async () => {
  store.loadProviders()
  store.loadStatus()
  store.loadInit()
  loadPrompts()
  loadAgents()
  // 恢复默认值：先等服务端配置回填完成再读，避免拿到 localStorage 旧值
  await store.loadConfig()
  defaults.value.scope = store.config.scope
  defaults.value.window = store.config.window
  defaults.value.focus = store.config.focus
  defaults.value.report_type = store.config.report_type || 'review'
  // 等待 providers 加载完成后自动测试连通性
  setTimeout(() => {
    if (store.providers.length) autoTestAll()
  }, 300)
})
</script>

<template>
  <div class="sv">
    <!-- 模块页头按产品要求移除，h1 保留 sr-only 保文档语义 -->
    <h1 class="ff-sr-only">AI 设置</h1>

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
            <AppButton variant="primary" size="sm" icon="plus" @click="openAdd">添加模型</AppButton>
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
            <AppButton variant="primary" size="sm" icon="plus" @click="openAdd">添加第一个模型</AppButton>
          </div>

          <!-- 模型配置弹窗（与工作台一致的交互） -->
          <OnboardWizard
            :open="modelDialogOpen"
            :presets="store.presets"
            :provider="editingProvider"
            mode="form"
            @close="modelDialogOpen = false"
            @done="onModelSaved"
          />
        </div>

        <!-- 智能体 / 角色画像 -->
        <div v-else-if="section === 'agents'" class="sv__panel">
          <div class="sv__head">
            <h3 class="sv__h3">智能体 / 角色画像</h3>
            <AppButton variant="primary" size="sm" icon="save" @click="saveAgents">保存智能体</AppButton>
          </div>
          <p class="sv__hint" style="margin:0 0 14px">
            <AppIcon name="info" size="xs" tone="muted" />
            <span>每个报告类型对应一个智能体，可自定义角色名、性格、立场、文风、语气与系统提示词。性格字段直接拼入 system 提示词；「系统提示词」留空则用右侧 Prompt 模板里的默认提示词，填入则优先覆盖。</span>
          </p>

          <div v-if="agentKeys.length" class="sv__agents">
            <div v-for="key in agentKeys" :key="key" class="sv__acard" :class="{ custom: isAgentCustom(key) }">
              <div class="sv__acard-head">
                <div class="sv__acard-title">
                  {{ agentMeta[key]?.label || key }}
                  <span v-if="isAgentCustom(key)" class="sv__badge sv__badge--brand">已自定义</span>
                  <span v-else class="sv__badge sv__badge--muted">默认</span>
                  <span class="sv__acard-key">{{ key }}</span>
                </div>
                <div class="sv__acard-tools">
                  <button v-if="isAgentCustom(key)" class="sv__op" @click="resetAgent(key)">
                    <AppIcon name="refresh" size="sm" /> 恢复默认
                  </button>
                </div>
              </div>
              <div class="sv__afields">
                <AppInput
                  v-for="f in AGENT_FIELDS"
                  :key="f.key"
                  :model-value="(agents[key] || {})[f.key]"
                  @update:model-value="agents[key] = { ...(agents[key] || {}), [f.key]: $event }"
                  :label="f.label"
                  :placeholder="f.ph"
                />
              </div>
              <div class="sv__asys">
                <span class="sv__asys-label">系统提示词（留空 = 用右侧 Prompt 模板默认）</span>
                <textarea
                  :value="(agents[key] || {}).system_prompt"
                  @input="agents[key] = { ...(agents[key] || {}), system_prompt: $event.target.value }"
                  class="sv__asys-text"
                  spellcheck="false"
                  :aria-label="(agentMeta[key]?.label || key) + ' 系统提示词'"
                  placeholder="（留空使用默认提示词；填入则优先用于该类型分析）"
                ></textarea>
              </div>
            </div>
          </div>
          <div v-else class="sv__empty">
            <AppIcon name="sparkles" size="xl" />
            <p>智能体画像加载中…</p>
          </div>
        </div>

        <!-- Prompt -->
        <div v-else-if="section === 'prompts'" class="sv__panel">
          <div class="sv__head">
            <h3 class="sv__h3">Prompt 模板</h3>
          </div>
          <div class="sv__adv">
            <button class="sv__disclose" @click="showPrompts = !showPrompts">
              <AppIcon :name="showPrompts ? 'chevron-down' : 'chevron-right'" size="sm" />
              <span>{{ showPrompts ? '收起高级配置' : '展开高级配置（面向高级用户）' }}</span>
              <span v-if="!showPrompts && dirtyCount" class="sv__disclose-badge">{{ dirtyCount }} 个已修改</span>
            </button>
            <Transition name="sv-fade">
              <div v-if="showPrompts" class="sv__prompts">
                <p class="sv__hint">
                  <AppIcon name="info" size="xs" tone="muted" />
                  <span>这些模板决定了 AI 报告的侧重点与结构。`花括号` 里的内容（如 {payload}）是程序自动代入的实时数据，请保留不要删除；若想调整 AI 的身份、口吻或报告格式，可在此修改对应模板，改完点击下方「保存模板」。</span>
                </p>

                <!-- 阶段分组 Tab：一次只编辑一个环节 -->
                <div class="sv__stages">
                  <button
                    v-for="st in PROMPT_STAGES"
                    :key="st.key"
                    class="sv__stage-tab"
                    :class="{ on: activeStage === st.key }"
                    @click="activeStage = st.key"
                  >
                    {{ st.label }}
                    <span class="sv__stage-n">{{ st.keys.length }}</span>
                  </button>
                </div>
                <p class="sv__stage-desc">{{ currentStage.desc }}</p>

                <!-- 当前阶段的模板卡片 -->
                <div v-for="key in currentStage.keys" :key="key" class="sv__pcard" :class="{ custom: isCustom(key) }">
                  <div class="sv__pcard-head">
                    <div class="sv__pcard-title">
                      {{ promptMeta[key].name }}
                      <span v-if="isCustom(key)" class="sv__badge sv__badge--brand">已自定义</span>
                      <span v-else class="sv__badge sv__badge--muted">默认</span>
                    </div>
                    <div class="sv__pcard-tools">
                      <span class="sv__pcard-count">{{ fmtCount(key) }} 字</span>
                      <button v-if="isCustom(key)" class="sv__op" @click="resetPrompt(key)">
                        <AppIcon name="refresh" size="sm" /> 恢复默认
                      </button>
                    </div>
                  </div>
                  <p class="sv__pcard-desc">{{ promptMeta[key].desc }}</p>
                  <textarea
                    v-model="prompts[key]"
                    class="sv__ptext"
                    :class="{ compact: promptMeta[key].compact }"
                    :aria-label="currentStage.label + ' · ' + promptMeta[key].name"
                    spellcheck="false"
                  ></textarea>
                </div>

                <p v-if="saveMsg" class="sv__msg" style="color:var(--ff-brand)">{{ saveMsg }}</p>

                <!-- 底部操作条：未保存状态 + 全局操作 -->
                <div class="sv__pbar">
                  <span v-if="dirtyCount" class="sv__pbar-state warn">有 {{ dirtyCount }} 个模板已修改，尚未保存</span>
                  <span v-else class="sv__pbar-state">所有模板均为默认内容</span>
                  <div class="sv__pbar-actions">
                    <AppButton variant="ghost" size="sm" @click="resetAllPrompts">全部恢复默认</AppButton>
                    <AppButton variant="primary" size="sm" icon="save" @click="savePrompts">保存模板</AppButton>
                  </div>
                </div>
              </div>
            </Transition>
          </div>
        </div>

        <!-- 默认值 -->
        <div v-else class="sv__panel">
          <div class="sv__head"><h3 class="sv__h3">分析默认值</h3></div>
          <div class="sv__defaults">
            <AppSelect v-model="defaults.report_type" label="默认报告类型" :options="typeOptions" />
            <AppSelect v-model="defaults.scope" label="默认分析范围" :options="scopeOptions" />
            <AppSelect v-model="defaults.window" label="默认时间窗口" :options="windowOptions" />
            <AppInput v-model="defaults.focus" label="自定义焦点（可选）" placeholder="如：重点关注半导体与新能源" />
            <AppButton variant="primary" style="align-self:flex-start" icon="save" @click="saveDefaults">保存默认值</AppButton>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.sv__layout { display: grid; grid-template-columns: 200px 1fr; gap: 16px; align-items: start; }
.sv__nav { background: var(--ff-bg-surface); border: 1px solid var(--ff-border); border-radius: 13px; padding: 8px; display: flex; flex-direction: column; gap: 2px; }
.sv__nav-item { display: flex; align-items: center; gap: 8px; border: none; background: none; border-radius: 9px; padding: 10px 13px; font-size: var(--ff-fs-caption); font-weight: 600; color: var(--ff-text-2); cursor: pointer; text-align: left; }
.sv__nav-item:hover { background: var(--ff-bg-hover); }
.sv__nav-item.on { background: var(--ff-bg-brand-subtle); color: var(--ff-brand-dark); }
.sv__content { min-width: 0; }
.sv__panel { background: var(--ff-bg-surface); border: 1px solid var(--ff-border); border-radius: 13px; padding: 18px; }
.sv__head { display: flex; align-items: center; justify-content: space-between; margin-bottom: 14px; }
.sv__h3 { font-size: var(--ff-fs-h4); font-weight: 700; }
.sv__add { display: inline-flex; align-items: center; gap: 6px; border: none; background: var(--ff-brand); color: var(--ff-bg-surface); border-radius: 9px; padding: 8px 15px; font-size: var(--ff-fs-caption); font-weight: 600; cursor: pointer; }
.sv__add:hover { background: var(--ff-brand-dark); }
.sv__providers { display: flex; flex-direction: column; gap: 9px; }
.sv__provider { display: flex; align-items: center; justify-content: space-between; gap: 12px; padding: 12px 14px; border: 1px solid var(--ff-border); border-radius: 11px; }
.sv__provider.def { border-color: var(--ff-border-brand); background: var(--ff-bg-brand-subtle); }
.sv__p-main { min-width: 0; }
.sv__p-name { display: flex; align-items: center; gap: 7px; flex-wrap: wrap; font-weight: 700; font-size: var(--ff-fs-body-sm); }
.sv__p-meta { font-size: var(--ff-fs-xs); color: var(--ff-text-3); margin-top: 3px; word-break: break-all; }
.sv__badge { font-size: var(--ff-fs-xs); font-weight: 600; padding: 2px 8px; border-radius: 8px; }
.sv__badge--brand { background: var(--ff-bg-brand-subtle); color: var(--ff-brand-dark); }
.sv__badge--ok { background: var(--ff-down-subtle); color: var(--ff-down); }
.sv__badge--bad { background: var(--ff-up-subtle); color: var(--ff-up); }
.sv__badge--muted { background: var(--ff-bg-subtle); color: var(--ff-text-3); }
.sv__badge--run { background: var(--ff-bg-brand-subtle); color: var(--ff-brand-dark); animation: sv-pulse 1.2s infinite; }
@keyframes sv-pulse { 0%,100% { opacity: 1; } 50% { opacity: 0.55; } }
.sv__autotest { display: flex; align-items: center; gap: 8px; font-size: var(--ff-fs-caption); color: var(--ff-brand-dark); background: var(--ff-bg-brand-subtle); border: 1px solid var(--ff-border-brand); border-radius: 10px; padding: 9px 13px; margin-bottom: 12px; }
.sv__autotest-spin { width: 13px; height: 13px; border: 2px solid var(--ff-border-brand); border-top-color: var(--ff-brand); border-radius: 50%; animation: sv-rot 0.8s linear infinite; flex-shrink: 0; }
@keyframes sv-rot { to { transform: rotate(360deg); } }
.sv__p-ops { display: flex; gap: 6px; flex-shrink: 0; }
.sv__op { display: inline-flex; align-items: center; gap: 4px; border: 1px solid var(--ff-border); background: var(--ff-bg-surface); border-radius: 8px; padding: 6px 11px; font-size: var(--ff-fs-xs); font-weight: 600; color: var(--ff-text-2); cursor: pointer; }
.sv__op:hover { border-color: var(--ff-border-brand); color: var(--ff-brand); }
.sv__op--danger:hover { color: var(--ff-up); border-color: var(--ff-up-border); }
.sv__empty { text-align: center; padding: 40px 10px; color: var(--ff-text-3); }
.sv__empty p { margin: 10px 0 14px; font-size: var(--ff-fs-caption); }
.sv__btn { border: 1px solid var(--ff-border); background: var(--ff-bg-surface); border-radius: 9px; padding: 8px 16px; font-size: var(--ff-fs-caption); font-weight: 600; color: var(--ff-text-2); cursor: pointer; }
.sv__btn--primary { background: var(--ff-brand); color: var(--ff-bg-surface); border-color: var(--ff-brand); }
.sv__msg { font-size: var(--ff-fs-caption); color: var(--ff-up); padding: 0 20px 12px; margin: 0; }
.sv__disclose { display: flex; align-items: center; gap: 7px; width: 100%; border: 1px solid var(--ff-border); background: var(--ff-bg-subtle); border-radius: 9px; padding: 9px 14px; font-size: var(--ff-fs-caption); font-weight: 600; color: var(--ff-text-2); cursor: pointer; text-align: left; }
.sv__disclose:hover { border-color: var(--ff-border-brand); color: var(--ff-brand-dark); }
.sv__disclose-badge { margin-left: auto; font-size: var(--ff-fs-xs); font-weight: 600; padding: 2px 8px; border-radius: 8px; background: var(--ff-bg-brand-subtle); color: var(--ff-brand-dark); }
/* 阶段分组：分段式 Tab */
.sv__stages { display: flex; gap: 4px; background: var(--ff-bg-subtle); border-radius: 10px; padding: 4px; }
.sv__stage-tab { flex: 1; display: inline-flex; align-items: center; justify-content: center; gap: 6px; border: none; background: none; border-radius: 8px; padding: 8px 12px; font-size: var(--ff-fs-caption); font-weight: 600; color: var(--ff-text-2); cursor: pointer; white-space: nowrap; }
.sv__stage-tab:hover { color: var(--ff-brand-dark); }
.sv__stage-tab.on { background: var(--ff-bg-surface); color: var(--ff-brand-dark); box-shadow: 0 1px 3px rgba(0, 0, 0, 0.08); }
.sv__stage-n { font-size: var(--ff-fs-micro); font-weight: 700; min-width: 17px; height: 17px; line-height: 17px; text-align: center; border-radius: 8px; background: rgba(37, 99, 235, 0.12); color: inherit; }
.sv__stage-desc { margin: -4px 2px 0; font-size: var(--ff-fs-xs); color: var(--ff-text-3); }
.sv__prompts { margin-top: 14px; display: flex; flex-direction: column; gap: 13px; }
.sv__hint { display: flex; align-items: flex-start; gap: 6px; font-size: var(--ff-fs-xs); line-height: 1.6; color: var(--ff-text-3); margin: 0; }
/* 模板卡片 */
.sv__pcard { display: flex; flex-direction: column; gap: 8px; border: 1px solid var(--ff-border); border-radius: 11px; padding: 13px 15px; background: var(--ff-bg-surface); }
.sv__pcard.custom { border-color: var(--ff-border-brand); box-shadow: inset 3px 0 0 0 var(--ff-brand); }
.sv__pcard-head { display: flex; align-items: center; justify-content: space-between; gap: 10px; flex-wrap: wrap; }
.sv__pcard-title { display: flex; align-items: center; gap: 7px; font-size: var(--ff-fs-caption); font-weight: 700; color: var(--ff-text-primary); }
.sv__pcard-tools { display: flex; align-items: center; gap: 10px; }
.sv__pcard-count { font-size: var(--ff-fs-xs); color: var(--ff-text-3); font-variant-numeric: tabular-nums; }
.sv__pcard-desc { margin: 0; font-size: var(--ff-fs-xs); line-height: 1.55; color: var(--ff-text-3); }
.sv__ptext { border: 1px solid var(--ff-border); border-radius: 9px; padding: 11px 13px; min-height: 230px; font-size: var(--ff-fs-caption); line-height: 1.65; background: var(--ff-bg-surface); color: var(--ff-text-primary); resize: vertical; outline: none; font-family: var(--ff-font-mono); -webkit-font-smoothing: antialiased; }
.sv__ptext.compact { min-height: 150px; }
.sv__ptext:focus { border-color: var(--ff-border-focus); box-shadow: 0 0 0 3px rgba(37, 99, 235, 0.12); }
/* 底部操作条：随滚动吸底，状态与操作同屏可见 */
.sv__pbar { position: sticky; bottom: 0; z-index: 2; display: flex; align-items: center; justify-content: space-between; gap: 10px; flex-wrap: wrap; margin: 6px -18px -18px; padding: 11px 18px; border-top: 1px solid var(--ff-border); background: var(--ff-bg-subtle); border-radius: 0 0 13px 13px; }
.sv__pbar-state { font-size: var(--ff-fs-caption); color: var(--ff-text-3); }
.sv__pbar-state.warn { color: var(--ff-warn); font-weight: 600; }
.sv__pbar-actions { display: flex; align-items: center; gap: 8px; }
.sv__defaults { display: flex; flex-direction: column; gap: 13px; max-width: 420px; }
/* 智能体卡片 */
.sv__agents { display: flex; flex-direction: column; gap: 11px; }
.sv__acard { display: flex; flex-direction: column; gap: 11px; border: 1px solid var(--ff-border); border-radius: 11px; padding: 13px 15px; background: var(--ff-bg-surface); }
.sv__acard.custom { border-color: var(--ff-border-brand); box-shadow: inset 3px 0 0 0 var(--ff-brand); }
.sv__acard-head { display: flex; align-items: center; justify-content: space-between; gap: 10px; flex-wrap: wrap; }
.sv__acard-title { display: flex; align-items: center; gap: 7px; font-size: var(--ff-fs-caption); font-weight: 700; color: var(--ff-text-primary); }
.sv__acard-key { font-size: var(--ff-fs-micro); font-weight: 600; color: var(--ff-text-3); background: var(--ff-bg-subtle); border-radius: 6px; padding: 1px 7px; font-family: var(--ff-font-mono); }
.sv__acard-tools { display: flex; align-items: center; gap: 6px; }
.sv__afields { display: grid; grid-template-columns: repeat(auto-fill, minmax(230px, 1fr)); gap: 10px; }
.sv__asys { display: flex; flex-direction: column; gap: 6px; }
.sv__asys-label { font-size: var(--ff-fs-xs); color: var(--ff-text-3); }
.sv__asys-text { border: 1px solid var(--ff-border); border-radius: 9px; padding: 10px 12px; min-height: 96px; font-size: var(--ff-fs-caption); line-height: 1.6; background: var(--ff-bg-surface); color: var(--ff-text-primary); resize: vertical; outline: none; font-family: var(--ff-font-mono); -webkit-font-smoothing: antialiased; }
.sv__asys-text:focus { border-color: var(--ff-border-focus); box-shadow: 0 0 0 3px rgba(37, 99, 235, 0.12); }
.sv-fade-enter-active, .sv-fade-leave-active { transition: opacity 160ms; }
.sv-fade-enter-from, .sv-fade-leave-to { opacity: 0; }

@media (max-width: 768px) {
  .sv__layout { grid-template-columns: 1fr; }
  .sv__nav { flex-direction: row; overflow-x: auto; }
  .sv__stages { overflow-x: auto; }
  .sv__stage-tab { flex: none; }
}
</style>
