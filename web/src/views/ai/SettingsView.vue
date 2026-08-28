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
import OnboardWizard from '../../components/ai/OnboardWizard.vue'

const store = useAiStore()

const section = ref('models')
const sections = [
  { key: 'models', label: '模型管理', icon: 'cpu' },
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
const prompts = ref({ map_system: '', map_user: '', reduce_system: '', reduce_user: '', single_user: '' })
const promptDefaults = ref({ map_system: '', map_user: '', reduce_system: '', reduce_user: '', single_user: '' })

// 按流水线阶段分组：同屏只展示当前阶段的模板，降低视觉密度。
// MAP=分批压缩要点；REDUCE=汇总成分章报告；SINGLE=一次性生成报告。
const PROMPT_STAGES = [
  { key: 'map', label: '① 分析映射', desc: '对每批新闻做要点压缩：抽事件、去噪、保留主体与量化信息', keys: ['map_system', 'map_user'] },
  { key: 'reduce', label: '② 汇总成文', desc: '汇总全部分块要点，产出结构化复盘报告', keys: ['reduce_system', 'reduce_user'] },
  { key: 'single', label: '③ 单轮分析', desc: '跳过分批压缩，一次性基于原始资讯生成报告', keys: ['single_user'] },
]
const activeStage = ref('map')
const currentStage = computed(() => PROMPT_STAGES.find((s) => s.key === activeStage.value) || PROMPT_STAGES[0])

// 每个模板的名称与一句话用途说明；compact=true 表示较短的系统提示，用更小的编辑区
const promptMeta = {
  map_system: { name: '系统提示', desc: '设定分析师角色与事实边界，约束模型不引入材料之外的信息、不编造数据', compact: true },
  map_user: { name: '用户模板', desc: '每批资讯的压缩指令与输出格式，含 {payload} 运行时占位符' },
  reduce_system: { name: '系统提示', desc: '设定首席策略分析师角色与排版规范（emoji 图标、加粗、要点化）', compact: true },
  reduce_user: { name: '用户模板', desc: '九章节复盘简报的结构指令，含 {stats_block} / {digests} 运行时占位符' },
  single_user: { name: '用户模板', desc: '单次调用直接生成完整报告的指令，含 {stats_block} / {payload} 运行时占位符' },
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
  store.saveConfig({
    scope: defaults.value.scope,
    window: Number(defaults.value.window) || 24,
    focus: defaults.value.focus || '',
  })
  window.alert('默认值已保存，生成报告时将使用该范围与窗口')
}

onMounted(() => {
  store.loadProviders()
  store.loadStatus()
  store.loadInit()
  loadPrompts()
  // 恢复本地默认值（与 store 单一数据源同步）
  store.loadConfig()
  defaults.value.scope = store.config.scope
  defaults.value.window = store.config.window
  defaults.value.focus = store.config.focus
  // 等待 providers 加载完成后自动测试连通性
  setTimeout(() => {
    if (store.providers.length) autoTestAll()
  }, 300)
})
</script>

<template>
  <div class="sv">
    <header class="ff-page__header">
      <div class="ff-page__heading">
        <h1 class="ff-page__title">AI 设置</h1>
        <p class="ff-page__desc">
          模型供应商、Prompt 模板与分析默认值
        </p>
      </div>
    </header>

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
                  <span>模板决定 AI 分析报告的质量与结构。花括号占位符（如 {payload}）由程序在运行时注入，请勿删除；修改后需点击下方「保存模板」。</span>
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

                <p v-if="saveMsg" class="sv__msg" style="color:var(--ff-brand, #2f7d5b)">{{ saveMsg }}</p>

                <!-- 底部操作条：未保存状态 + 全局操作 -->
                <div class="sv__pbar">
                  <span v-if="dirtyCount" class="sv__pbar-state warn">有 {{ dirtyCount }} 个模板已修改，尚未保存</span>
                  <span v-else class="sv__pbar-state">所有模板均为默认内容</span>
                  <div class="sv__pbar-actions">
                    <button class="sv__btn" @click="resetAllPrompts">全部恢复默认</button>
                    <button class="sv__add" @click="savePrompts"><AppIcon name="save" size="sm" /> 保存模板</button>
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
.sv__btn { border: 1px solid var(--ff-border, #e5e7eb); background: var(--ff-bg-surface, #fff); border-radius: 9px; padding: 8px 16px; font-size: 12.5px; font-weight: 600; color: var(--ff-text-2, #6b7280); cursor: pointer; }
.sv__btn--primary { background: var(--ff-brand, #2f7d5b); color: #fff; border-color: var(--ff-brand, #2f7d5b); }
.sv__msg { font-size: 12.5px; color: var(--ff-down, #e5484d); padding: 0 20px 12px; margin: 0; }
.sv__disclose { display: flex; align-items: center; gap: 7px; width: 100%; border: 1px solid var(--ff-border, #e5e7eb); background: var(--ff-bg-subtle, #f9fafb); border-radius: 9px; padding: 9px 14px; font-size: 12.5px; font-weight: 600; color: var(--ff-text-2, #6b7280); cursor: pointer; text-align: left; }
.sv__disclose:hover { border-color: var(--ff-border-brand, #9fc3b1); color: var(--ff-brand-dark, #1d4e39); }
.sv__disclose-badge { margin-left: auto; font-size: 10.5px; font-weight: 700; padding: 2px 8px; border-radius: 8px; background: var(--ff-bg-brand-subtle, #eaf4ef); color: var(--ff-brand-dark, #1d4e39); }
/* 阶段分组：分段式 Tab */
.sv__stages { display: flex; gap: 4px; background: var(--ff-bg-subtle, #f1f4f2); border-radius: 10px; padding: 4px; }
.sv__stage-tab { flex: 1; display: inline-flex; align-items: center; justify-content: center; gap: 6px; border: none; background: none; border-radius: 8px; padding: 8px 12px; font-size: 13px; font-weight: 600; color: var(--ff-text-2, #6b7280); cursor: pointer; white-space: nowrap; }
.sv__stage-tab:hover { color: var(--ff-brand-dark, #1d4e39); }
.sv__stage-tab.on { background: var(--ff-bg-surface, #fff); color: var(--ff-brand-dark, #1d4e39); box-shadow: 0 1px 3px rgba(0, 0, 0, 0.08); }
.sv__stage-n { font-size: 10.5px; font-weight: 700; min-width: 17px; height: 17px; line-height: 17px; text-align: center; border-radius: 8px; background: rgba(47, 125, 91, 0.12); color: inherit; }
.sv__stage-desc { margin: -4px 2px 0; font-size: 12px; color: var(--ff-text-3, #9ca3af); }
.sv__prompts { margin-top: 14px; display: flex; flex-direction: column; gap: 13px; }
.sv__hint { display: flex; align-items: flex-start; gap: 6px; font-size: 12px; line-height: 1.6; color: var(--ff-text-3, #9ca3af); margin: 0; }
/* 模板卡片 */
.sv__pcard { display: flex; flex-direction: column; gap: 8px; border: 1px solid var(--ff-border, #e5e7eb); border-radius: 11px; padding: 13px 15px; background: var(--ff-bg-surface, #fff); }
.sv__pcard.custom { border-color: var(--ff-border-brand, #9fc3b1); box-shadow: inset 3px 0 0 0 var(--ff-brand, #2f7d5b); }
.sv__pcard-head { display: flex; align-items: center; justify-content: space-between; gap: 10px; flex-wrap: wrap; }
.sv__pcard-title { display: flex; align-items: center; gap: 7px; font-size: 13.5px; font-weight: 700; color: var(--ff-text-primary, #1f2937); }
.sv__pcard-tools { display: flex; align-items: center; gap: 10px; }
.sv__pcard-count { font-size: 11.5px; color: var(--ff-text-3, #9ca3af); font-variant-numeric: tabular-nums; }
.sv__pcard-desc { margin: 0; font-size: 12px; line-height: 1.55; color: var(--ff-text-3, #9ca3af); }
.sv__ptext { border: 1px solid var(--ff-border, #d1d5db); border-radius: 9px; padding: 11px 13px; min-height: 230px; font-size: 13px; line-height: 1.65; background: var(--ff-bg-surface, #fff); color: var(--ff-text-primary, #1f2937); resize: vertical; outline: none; font-family: ui-monospace, 'Cascadia Code', Consolas, 'PingFang SC', 'Microsoft YaHei', monospace; -webkit-font-smoothing: antialiased; }
.sv__ptext.compact { min-height: 150px; }
.sv__ptext:focus { border-color: var(--ff-border-focus, #4f9e76); box-shadow: 0 0 0 3px rgba(47, 125, 91, 0.12); }
/* 底部操作条：随滚动吸底，状态与操作同屏可见 */
.sv__pbar { position: sticky; bottom: 0; z-index: 2; display: flex; align-items: center; justify-content: space-between; gap: 10px; flex-wrap: wrap; margin: 6px -18px -18px; padding: 11px 18px; border-top: 1px solid var(--ff-border, #e5e7eb); background: var(--ff-bg-subtle, #f9fafb); border-radius: 0 0 13px 13px; }
.sv__pbar-state { font-size: 12.5px; color: var(--ff-text-3, #9ca3af); }
.sv__pbar-state.warn { color: var(--ff-warn, #b45309); font-weight: 600; }
.sv__pbar-actions { display: flex; align-items: center; gap: 8px; }
.sv__defaults { display: flex; flex-direction: column; gap: 13px; max-width: 420px; }
.sv-fade-enter-active, .sv-fade-leave-active { transition: opacity 160ms; }
.sv-fade-enter-from, .sv-fade-leave-to { opacity: 0; }

@media (max-width: 768px) {
  .sv__layout { grid-template-columns: 1fr; }
  .sv__nav { flex-direction: row; overflow-x: auto; }
  .sv__stages { overflow-x: auto; }
  .sv__stage-tab { flex: none; }
}
</style>
