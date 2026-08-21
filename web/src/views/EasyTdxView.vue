<script setup>
import { ref, reactive, computed, onMounted, onBeforeUnmount } from 'vue'
import AppCard from '../ui/AppCard.vue'
import AppButton from '../ui/AppButton.vue'
import AppIcon from '../ui/AppIcon.vue'
import AppBadge from '../ui/AppBadge.vue'
import AppTabs from '../ui/AppTabs.vue'
import EasyTdxNav from '../components/easytdx/EasyTdxNav.vue'
import EasyTdxParamForm from '../components/easytdx/EasyTdxParamForm.vue'
import EasyTdxResultPanel from '../components/easytdx/EasyTdxResultPanel.vue'
import EasyTdxTaskStatus from '../components/easytdx/EasyTdxTaskStatus.vue'
import EasyTdxStockPicker from '../components/easytdx/EasyTdxStockPicker.vue'
import EasyTdxQuickTasks from '../components/easytdx/EasyTdxQuickTasks.vue'
import easytdxApi from '../api/easytdx'
import { loadStockNames } from '../components/easytdx/stockNames'

const loading = ref(false)
const meta = ref(null)
const strategies = ref([])
const navGroups = ref([])
const selectedFuncId = ref('')
const params = reactive({})
const task = ref(null)
const running = ref(false)
const recent = ref([])
const query = ref('')
const errMsg = ref('')
const pickerRef = ref(null)

const mode = ref('workbench') // workbench | functions
const modes = [
  { value: 'workbench', label: '工作台' },
  { value: 'functions', label: '全部功能' },
]

// ---------------- 股票标的 ----------------
const stock = ref(null) // { market, code, name }
const stockNames = ref({})

async function loadNames() {
  stockNames.value = await loadStockNames()
}

function selectStock(s) {
  stock.value = s
  errMsg.value = ''
  // 已选功能若接受个股参数，立即带入
  injectStockToFunc()
}

function clearStock() {
  stock.value = null
}

function changeStock() {
  stock.value = null
  pickerRef.value?.focus()
}

// 把当前标的注入到功能参数（market/code 或 stocklist）
function injectStockToFunc() {
  if (!stock.value || !selectedFunc.value) return
  const func = selectedFunc.value
  const hasCode = func.params?.some((p) => p.key === 'code')
  const hasStocks = func.params?.some((p) => p.key === 'stocks')
  if (hasCode) {
    params.code = stock.value.code
    if (func.params.some((p) => p.key === 'market')) params.market = stock.value.market
  } else if (hasStocks) {
    params.stocks = `${stock.value.market} ${stock.value.code}`
  }
}

// ---------------- 场景化分组 ----------------
const SCENES = [
  { id: 'quote', label: '行情数据', icon: 'trending-up', groups: ['kline', 'minute', 'transaction', 'macquote', 'mackline', 'mactick', 'ex'] },
  { id: 'stock', label: '个股资料', icon: 'file-text', groups: ['finance', 'cninfo', 'block'] },
  { id: 'market', label: '市场扫描', icon: 'activity', groups: ['market', 'fundflow', 'macboard', 'maccapital', 'macmonitor'] },
  { id: 'tools', label: '高级工具', icon: 'candles', groups: ['chanlun', 'backtest', 'file'] },
  { id: 'conn', label: '系统连接', icon: 'database', groups: ['conn'] },
]
const GROUP_LABELS = {}

function buildNav(groups, functions) {
  for (const g of groups) GROUP_LABELS[g.id] = g.label
  return SCENES.map((scene) => {
    const items = functions
      .filter((f) => scene.groups.includes(f.group))
      .map((f) => ({ id: f.id, label: f.label, tag: GROUP_LABELS[f.group] }))
    return { id: scene.id, label: scene.label, icon: scene.icon, items }
  }).filter((s) => s.items.length)
}

// ---------------- 功能选择 / 参数 ----------------
const selectedFunc = computed(
  () => meta.value?.functions.find((f) => f.id === selectedFuncId.value) || null,
)

function resetParams(func) {
  for (const k of Object.keys(params)) delete params[k]
  for (const p of func.params || []) {
    params[p.key] = p.default ?? (p.type === 'bool' ? false : '')
  }
}

function selectFunc(id, { autoInject = true } = {}) {
  errMsg.value = ''
  selectedFuncId.value = id
  const func = meta.value.functions.find((f) => f.id === id)
  if (func) {
    resetParams(func)
    if (autoInject) injectStockToFunc()
  }
  task.value = null
}

// ---------------- 快捷任务 ----------------
async function runTask(t) {
  if (t.needsStock && !stock.value) {
    errMsg.value = '请先选择股票标的（输入名称或代码），再执行「' + t.label + '」'
    pickerRef.value?.focus()
    return
  }
  selectFunc(t.func, { autoInject: false })
  const func = selectedFunc.value
  if (func) {
    resetParams(func)
    Object.assign(params, t.params || {})
    // 注入股票：个股类任务自动带入当前标的
    if (t.needsStock && stock.value) {
      const hasCode = func.params?.some((p) => p.key === 'code')
      const hasStocks = func.params?.some((p) => p.key === 'stocks')
      if (hasCode) {
        params.code = stock.value.code
        if (func.params.some((p) => p.key === 'market')) params.market = stock.value.market
      } else if (hasStocks) {
        params.stocks = `${stock.value.market} ${stock.value.code}`
      }
    }
  }
  run()
}

// ---------------- 执行 / 轮询 ----------------
let pollTimer = null

async function run() {
  if (!selectedFunc.value) return
  errMsg.value = ''
  task.value = null
  running.value = true
  try {
    const r = await easytdxApi.run(selectedFuncId.value, { ...params })
    startPolling(r.task_id)
  } catch (e) {
    running.value = false
    errMsg.value = '提交失败：' + (e.message || e)
  }
}

function startPolling(taskId) {
  if (pollTimer) clearInterval(pollTimer)
  pollTimer = setInterval(() => pollTask(taskId), 800)
  pollTask(taskId)
}

async function pollTask(taskId) {
  try {
    const t = await easytdxApi.task(taskId)
    task.value = t
    if (t.status === 'success' || t.status === 'error') {
      stopPolling()
      running.value = false
      loadRecent()
    }
  } catch (e) {
    /* 单次轮询失败不打断 */
  }
}

function stopPolling() {
  if (pollTimer) {
    clearInterval(pollTimer)
    pollTimer = null
  }
}

async function loadMeta() {
  loading.value = true
  try {
    const [m, s] = await Promise.all([easytdxApi.meta(), easytdxApi.strategies()])
    meta.value = m
    strategies.value = s.strategies || []
    navGroups.value = buildNav(m.group_meta, m.functions)
    if (m.functions.length) selectFunc(m.functions[0].id, { autoInject: false })
  } catch (e) {
    errMsg.value = '加载功能清单失败：' + (e.message || e)
  } finally {
    loading.value = false
  }
}

async function loadRecent() {
  try {
    const r = await easytdxApi.tasks(8)
    recent.value = r.tasks || []
  } catch (e) {
    /* 静默降级 */
  }
}

onMounted(async () => {
  await Promise.all([loadMeta(), loadNames()])
  await loadRecent()
})
onBeforeUnmount(stopPolling)
</script>

<template>
  <div class="ff-page etdx-view">
    <header class="etdx-view__header">
      <div class="etdx-view__title">
        <h1 class="ff-page__title">
          <AppIcon name="cpu" size="lg" /> easy-tdx 数据源
        </h1>
        <p class="ff-page__subtitle">
          通达信 / Mac / 扩展行情 / 巨潮 / 缠论 / 回测 —— 输入股票名称即可快速查询
        </p>
      </div>

      <!-- 视图切换 -->
      <AppTabs v-model="mode" type="line" :items="modes" class="etdx-view__tabs" />
    </header>

    <div v-if="errMsg" class="ff-alert ff-alert--danger etdx-view__err">
      <AppIcon name="alert-circle" size="md" /> {{ errMsg }}
    </div>

    <!-- 标的选择条：输入名称/代码，个股类功能自动带入 -->
    <AppCard class="etdx-view__banner" :no-padding="true">
      <div class="etdx-view__banner-body">
        <EasyTdxStockPicker
          ref="pickerRef"
          :stock="stock"
          class="etdx-view__picker"
          @select="selectStock"
          @clear="clearStock"
        />
        <div class="etdx-view__banner-text">
          <strong v-if="stock">{{ stock.name }} ({{ stock.code }}.{{ stock.market }})</strong>
          <strong v-else>输入股票名称 / 代码开始查询</strong>
          <span v-if="stock">个股类任务（K线 / 报价 / 公告 / 缠论 / 回测…）将自动作用于该标的</span>
          <span v-else>支持名称或代码模糊搜索，如「茅台」「600519」「平安」</span>
        </div>
        <span v-if="meta" class="etdx-view__banner-count">
          {{ navGroups.reduce((n, g) => n + g.items.length, 0) }} 项功能可用
        </span>
      </div>
    </AppCard>

    <div class="etdx-view__body">
      <!-- 全部功能：左侧场景化导航 -->
      <AppCard v-if="mode === 'functions'" class="etdx-view__nav" :no-padding="true">
        <EasyTdxNav
          :groups="navGroups"
          :active-id="selectedFuncId"
          v-model:query="query"
          @select="(id) => selectFunc(id)"
        />
      </AppCard>

      <div class="etdx-view__main">
        <!-- 工作台：快捷任务 -->
        <template v-if="mode === 'workbench'">
          <AppCard class="etdx-view__tasks" :no-padding="true">
            <div class="etdx-view__tasks-head">
              <AppIcon name="zap" size="sm" />
              <span>快捷任务</span>
              <span class="etdx-view__tasks-hint">点击即执行，参数可在下方调整后重跑</span>
            </div>
            <div class="etdx-view__tasks-body">
              <EasyTdxQuickTasks :has-stock="!!stock" @run="runTask" />
            </div>
          </AppCard>
        </template>

        <!-- 执行区：参数 + 结果 -->
        <AppCard v-if="selectedFunc" class="etdx-view__panel">
          <div class="etdx-view__func-head">
            <div>
              <div class="etdx-view__func-title">
                {{ selectedFunc.label }}
                <AppBadge variant="muted">{{ selectedFunc.group }}</AppBadge>
                <AppBadge variant="brand">{{ selectedFunc.client }}</AppBadge>
              </div>
              <p v-if="selectedFunc.help" class="etdx-view__func-help">{{ selectedFunc.help }}</p>
            </div>
            <AppButton
              variant="primary"
              icon="play"
              :loading="running"
              :disabled="running"
              @click="run"
            >
              {{ running ? '执行中…' : '执行' }}
            </AppButton>
          </div>

          <div class="etdx-view__content">
            <!-- 参数表单 -->
            <div class="etdx-view__form">
              <h3 class="ff-h3">参数</h3>
              <EasyTdxParamForm
                :func="selectedFunc"
                :model="params"
                :strategies="strategies"
                :stock="stock"
                @change-stock="changeStock"
              />
            </div>

            <!-- 结果 -->
            <div class="etdx-view__result">
              <h3 class="ff-h3">结果</h3>
              <EasyTdxResultPanel
                :result="task && task.status !== 'running' ? task.result : null"
                :func="selectedFunc"
                :loading="running"
                :stock-names="stockNames"
              />
            </div>
          </div>
        </AppCard>

        <!-- 执行状态 / 日志 -->
        <AppCard class="etdx-view__status" :no-padding="true">
          <div class="etdx-view__status-head">
            <AppIcon name="list" size="sm" />
            <span>执行状态与日志</span>
            <button v-if="recent.length" type="button" class="etdx-view__recent" title="最近任务">
              最近 {{ recent.length }} 条
            </button>
          </div>
          <div class="etdx-view__status-body">
            <EasyTdxTaskStatus :task="task" />
          </div>
        </AppCard>
      </div>
    </div>
  </div>
</template>

<style scoped>
.etdx-view {
  max-width: var(--ff-container-max);
  margin: 0 auto;
}
.etdx-view__header {
  display: flex;
  align-items: flex-end;
  justify-content: space-between;
  gap: var(--ff-space-4);
  flex-wrap: wrap;
  margin-bottom: var(--ff-space-4);
}
.etdx-view__title {
  min-width: 260px;
}
.etdx-view__tabs {
  margin: 0;
}
.etdx-view__err {
  margin-bottom: var(--ff-space-4);
}
.etdx-view__body {
  display: grid;
  grid-template-columns: 260px 1fr;
  gap: var(--ff-space-4);
  align-items: start;
}
.etdx-view__body:has(> :first-child:only-child) {
  grid-template-columns: 1fr;
}
.etdx-view__nav {
  position: sticky;
  top: var(--ff-space-4);
  max-height: calc(100vh - 140px);
}
.etdx-view__main {
  display: flex;
  flex-direction: column;
  gap: var(--ff-space-4);
  min-width: 0;
}
/* 标的选择条 */
.etdx-view__banner {
  margin-bottom: var(--ff-space-4);
}
.etdx-view__banner-body {
  display: flex;
  align-items: center;
  gap: var(--ff-space-4);
  padding: var(--ff-space-3) var(--ff-space-4);
  flex-wrap: wrap;
}
.etdx-view__picker {
  flex-shrink: 0;
  width: 300px;
}
.etdx-view__banner-text {
  display: flex;
  flex-direction: column;
  gap: 2px;
  flex: 1;
  min-width: 220px;
}
.etdx-view__banner-text strong {
  font-size: var(--ff-fs-body);
  color: var(--ff-text-primary);
}
.etdx-view__banner-text span {
  font-size: var(--ff-fs-caption);
  color: var(--ff-text-tertiary);
}
.etdx-view__banner-count {
  font-size: var(--ff-fs-caption);
  color: var(--ff-text-tertiary);
  background: var(--ff-bg-subtle);
  border-radius: var(--ff-radius-pill);
  padding: 2px 10px;
}
/* 工作台：快捷任务 */
.etdx-view__tasks-head {
  display: flex;
  align-items: center;
  gap: var(--ff-space-2);
  padding: var(--ff-space-3) var(--ff-space-4);
  border-bottom: 1px solid var(--ff-border-subtle);
  font-size: var(--ff-fs-body-sm);
  font-weight: 600;
  color: var(--ff-text-secondary);
}
.etdx-view__tasks-hint {
  font-weight: 400;
  color: var(--ff-text-tertiary);
  font-size: var(--ff-fs-caption);
}
.etdx-view__tasks-body {
  padding: var(--ff-space-4);
}
/* 执行区 */
.etdx-view__func-head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: var(--ff-space-4);
  margin-bottom: var(--ff-space-4);
}
.etdx-view__func-title {
  display: flex;
  align-items: center;
  gap: var(--ff-space-2);
  font-size: var(--ff-fs-title-sm);
  font-weight: 700;
  color: var(--ff-text-primary);
}
.etdx-view__func-help {
  margin: 6px 0 0;
  font-size: var(--ff-fs-body-sm);
  color: var(--ff-text-tertiary);
}
.etdx-view__content {
  display: grid;
  grid-template-columns: 320px 1fr;
  gap: var(--ff-space-5);
  align-items: start;
}
.etdx-view__form,
.etdx-view__result {
  min-width: 0;
}
.etdx-view__status-head {
  display: flex;
  align-items: center;
  gap: var(--ff-space-2);
  padding: var(--ff-space-3) var(--ff-space-4);
  border-bottom: 1px solid var(--ff-border-subtle);
  font-size: var(--ff-fs-body-sm);
  font-weight: 600;
  color: var(--ff-text-secondary);
}
.etdx-view__recent {
  margin-left: auto;
  border: none;
  background: transparent;
  color: var(--ff-text-tertiary);
  font-size: var(--ff-fs-caption);
  cursor: default;
}
.etdx-view__status-body {
  height: 240px;
}
.etdx-view__nav :deep(.etdx-nav) {
  height: calc(100vh - 140px);
}

@media (max-width: 1100px) {
  .etdx-view__body {
    grid-template-columns: 1fr;
  }
  .etdx-view__nav {
    position: static;
    max-height: 320px;
  }
  .etdx-view__content {
    grid-template-columns: 1fr;
  }
}
</style>
