<script setup>
// easy-tdx 投研工作台（全新 UI）
// 布局：顶部命令条 → 左栏（自选股 + 场景导航）→ 中栏（标的名片 + 快捷任务 + 视图）→ 右栏（参数）→ 底部任务中心
import { ref, computed, watch, onMounted, onBeforeUnmount } from 'vue'
import AppIcon from '../ui/AppIcon.vue'
import AppBadge from '../ui/AppBadge.vue'
import AppButton from '../ui/AppButton.vue'
import EasyTdxWatchlist from '../components/easytdx/EasyTdxWatchlist.vue'
import EasyTdxNav from '../components/easytdx/EasyTdxNav.vue'
import EasyTdxQuickTasks from '../components/easytdx/EasyTdxQuickTasks.vue'
import EasyTdxParamForm from '../components/easytdx/EasyTdxParamForm.vue'
import EasyTdxResultPanel from '../components/easytdx/EasyTdxResultPanel.vue'
import EasyTdxStockPicker from '../components/easytdx/EasyTdxStockPicker.vue'
import { useEasytdxStore } from '../store/easytdx'

const store = useEasytdxStore()

// ---------------- 视图与场景 ----------------
// 视图 Tab（中栏）
const VIEWS = [
  { id: 'overview', label: '总览', icon: 'dashboard' },
  { id: 'kline', label: 'K线', icon: 'candles' },
  { id: 'tick', label: '分时', icon: 'activity' },
  { id: 'fund', label: '资金', icon: 'coins' },
  { id: 'chanlun', label: '缠论', icon: 'activity' },
  { id: 'backtest', label: '回测', icon: 'cpu' },
  { id: 'board', label: '板块榜', icon: 'bar-chart' },
]

// 视图 → 默认执行功能（overview 为面板视图）
const VIEW_FUNC = {
  overview: '',
  kline: 'mac_stock_kline',
  tick: 'mac_tick_chart',
  fund: 'mac_capital_flow',
  chanlun: 'chanlun_analyze',
  backtest: 'backtest_run',
  board: 'mac_board_ranking',
}

// 六大场景（左栏导航），场景 → 视图 + 功能集合
const SCENES = [
  { id: 'overview', label: '总览工作台', icon: 'dashboard', funcIds: ['mac_stock_quotes', 'mac_stock_kline', 'mac_tick_chart', 'mac_capital_flow', 'finance_info', 'xdxr_info', 'cninfo_announcements', 'chanlun_analyze', 'backtest_run', 'mac_board_ranking', 'mac_unusual', 'mac_transactions'] },
  { id: 'kline', label: 'K线 / 行情', icon: 'candles', funcIds: ['mac_stock_kline', 'mac_stock_kline_indicators', 'security_bars', 'index_bars', 'minute_time_data', 'history_minute_time_data', 'security_quotes', 'mac_transactions'] },
  { id: 'fund', label: '资金流向', icon: 'coins', funcIds: ['mac_capital_flow', 'fund_flow', 'history_fund_flow'] },
  { id: 'chanlun', label: '缠论分析', icon: 'activity', funcIds: ['chanlun_analyze'] },
  { id: 'backtest', label: '策略回测', icon: 'cpu', funcIds: ['backtest_run'] },
  { id: 'board', label: '市场扫描', icon: 'bar-chart', funcIds: ['mac_board_ranking', 'mac_board_change_ranking', 'mac_unusual', 'mac_auction', 'market_stat', 'mac_stock_quotes_list', 'price_limits'] },
]

const currentView = ref('overview')
const query = ref('')
const paramsCollapsed = ref(false)

const funcs = computed(() => store.meta?.functions || [])
const selectedFunc = computed(() => store.selectedFunc)
const running = computed(() => store.running)
const errMsg = computed(() => store.errMsg)

// 功能是否需要标的
function funcNeedsStock(func) {
  return !!func?.params?.some((p) => p.key === 'code' || p.key === 'stocks')
}

// 当前视图是否需要标的
const currentNeedsStock = computed(() => {
  const fid = VIEW_FUNC[currentView.value]
  const func = funcs.value.find((f) => f.id === fid)
  return funcNeedsStock(func)
})

// ---------------- 视图切换 ----------------
function activateView(view) {
  currentView.value = view
  const fid = VIEW_FUNC[view]
  if (!fid) return
  const func = funcs.value.find((f) => f.id === fid)
  if (!func) return
  store.selectFunc(fid) // 重置参数并注入标的
  if (funcNeedsStock(func) && !store.stock) {
    // 未选标的：给出明确指引，避免「点了没反应」
    store.errMsg = '请先在顶部搜索框选择股票标的（如「茅台」），再执行「' + func.label + '」'
    return
  }
  run()
}

function onSceneView(view) {
  activateView(view)
}

function onNavSelect(funcId) {
  const func = funcs.value.find((f) => f.id === funcId)
  if (!func) return
  // 定位到功能所属场景（视图）
  const scene = SCENES.find((s) => s.funcIds.includes(funcId))
  if (scene) currentView.value = scene.id
  store.selectFunc(funcId)
  if (funcNeedsStock(func) && !store.stock) {
    store.errMsg = '请先在顶部搜索框选择股票标的，再执行「' + func.label + '」'
    return
  }
  run()
}

// ---------------- 标的 ----------------
function selectStock(s) {
  store.selectStock(s)
  if (currentNeedsStock.value) run()
}

function clearStock() {
  store.clearStock()
}

function changeStock() {
  store.clearStock()
  pickerRef.value?.focus()
}

const pickerRef = ref(null)

// ---------------- 执行 ----------------
async function run() {
  if (!store.selectedFunc) return
  // 结果可见性保证：若当前停留在总览视图（无结果面板），
  // 自动定位到该功能所属的视图，确保执行结果立即可见
  if (currentView.value === 'overview') {
    const view = locateViewForFunc(store.selectedFuncId)
    if (view) currentView.value = view
  }
  try {
    await store.run()
  } catch (e) {
    store.errMsg = '提交失败：' + (e.message || e)
  }
}

// 功能 → 所属场景（视图）
function locateViewForFunc(funcId) {
  return SCENES.find((s) => s.funcIds.includes(funcId))?.id || null
}

// 快捷任务：先定位到功能所属视图（结果面板可见），再执行
async function runTask(t) {
  const view = locateViewForFunc(t.func)
  if (view && view !== currentView.value) currentView.value = view
  await store.runTask(t)
}

// 最近任务：回看结果 —— 定位视图并挂载对应功能（不重置参数）
function loadTask(id) {
  const t = store.recent.find((x) => x.task_id === id)
  if (t) {
    const view = locateViewForFunc(t.func_id)
    if (view) currentView.value = view
    if (t.func_id) store.selectedFuncId = t.func_id
  }
  store.loadTask(id)
}

function taskLabel(t) {
  return t.func_label || t.label || t.function || t.func_id || t.task_id
}

// 任务完成 → 刷新最近
watch(
  () => store.task?.status,
  (s) => {
    if (s === 'success' || s === 'error') store.loadRecent()
  },
)

// ---------------- Hero 报价提取（执行报价类任务后更新） ----------------
const heroQuote = computed(() => {
  const t = store.task
  const r = t?.status === 'success' ? t.result : null
  if (!r || r.type !== 'table') return null
  const cols = (r.columns || []).map((c) => String(c).toLowerCase())
  const priceIdx = cols.findIndex((c) => /price|last|now|^close$/.test(c))
  const pctIdx = cols.findIndex((c) => /change_pct|pct_chg/.test(c))
  const chgIdx = cols.findIndex((c) => /^change$/.test(c))
  if (priceIdx < 0) return null
  const row = r.rows?.[0]
  if (!row) return null
  const num = (v) => (v === null || v === undefined || v === '' ? null : Number(v))
  const price = num(row[priceIdx])
  const pct = pctIdx >= 0 ? num(row[pctIdx]) : null
  const chg = chgIdx >= 0 ? num(row[chgIdx]) : null
  return { price, pct, chg }
})

function fmtNum(v, digits = 2) {
  if (v === null || !Number.isFinite(v)) return '—'
  return v.toLocaleString('zh-CN', { minimumFractionDigits: digits, maximumFractionDigits: digits })
}

// ---------------- 参数面板 ----------------
function toggleParams() {
  paramsCollapsed.value = !paramsCollapsed.value
}

function toggleFav() {
  if (!store.selectedFunc) return
  store.toggleFav(store.selectedFuncId)
}

// ---------------- 初始化 ----------------
onMounted(async () => {
  await store.init()
  await store.loadNames()
  await store.loadRecent()
  // 消费其它模块（如智能选股「看行情」）交接的标的：选中并自动执行默认视图
  try {
    const raw = localStorage.getItem('finfeed.easytdx.pendingStock')
    if (raw) {
      localStorage.removeItem('finfeed.easytdx.pendingStock')
      const s = JSON.parse(raw)
      if (s && s.code) {
        store.selectStock(s)
        if (currentNeedsStock.value) run()
      }
    }
  } catch { /* 忽略坏数据 */ }
})
onBeforeUnmount(() => store.stopPolling())
</script>

<template>
  <div class="etdx-shell">
    <!-- ══════ 顶部命令条 ══════ -->
    <header class="etdx-top">
      <!-- 模块标题按产品要求移除，h1 保留 sr-only 保文档语义 -->
      <h1 class="ff-sr-only">easy-tdx 投研工作台</h1>

      <div class="etdx-top__search">
        <EasyTdxStockPicker
          ref="pickerRef"
          :stock="store.stock"
          @select="selectStock"
          @clear="clearStock"
        />
      </div>

      <div class="etdx-top__meta">
        <span class="etdx-top__host" title="自动探测最低延迟主机">
          <span class="etdx-top__dot"></span>
          行情在线
        </span>
        <span class="etdx-top__count">{{ store.funcCount }} 项功能</span>
      </div>
    </header>

    <!-- ══════ 主体三栏 ══════ -->
    <div class="etdx-body">
      <!-- 左栏：自选股 + 场景导航 -->
      <aside class="etdx-rail">
        <div class="etdx-rail__watch">
          <EasyTdxWatchlist :stock="store.stock" @select="selectStock" />
        </div>
        <div class="etdx-rail__divider"></div>
        <div class="etdx-rail__nav">
          <EasyTdxNav
            :scenes="SCENES"
            :functions="funcs"
            :active-view="currentView"
            :active-func-id="store.selectedFuncId"
            v-model:query="query"
            @view="onSceneView"
            @select="onNavSelect"
          />
        </div>
      </aside>

      <!-- 中栏：Hero + 快捷任务 + 视图 -->
      <section class="etdx-center">
        <!-- 标的名片 -->
        <div class="etdx-hero">
          <div class="etdx-hero__name">
            <h2>
              {{ store.stock?.name || '未选择标的' }}
              <span v-if="store.stock" class="etdx-hero__mk">{{ store.stock.market }}</span>
            </h2>
            <p v-if="store.stock" class="etdx-hero__code">{{ store.stock.code }} · 输入名称 / 代码即可切换</p>
            <p v-else class="etdx-hero__code">在上方搜索股票名称或代码开始查询，如「茅台」「600519」</p>
          </div>

          <div v-if="heroQuote" class="etdx-hero__quote">
            <span
              class="etdx-hero__px"
              :class="(heroQuote.pct ?? 0) > 0 ? 'is-up' : (heroQuote.pct ?? 0) < 0 ? 'is-down' : ''"
            >{{ fmtNum(heroQuote.price) }}</span>
            <span
              v-if="heroQuote.pct !== null"
              class="etdx-hero__chg"
              :class="heroQuote.pct > 0 ? 'is-up' : heroQuote.pct < 0 ? 'is-down' : ''"
            >{{ heroQuote.pct > 0 ? '+' : '' }}{{ fmtNum(heroQuote.pct) }}%</span>
            <span
              v-if="heroQuote.chg !== null"
              class="etdx-hero__chg"
              :class="heroQuote.chg > 0 ? 'is-up' : heroQuote.chg < 0 ? 'is-down' : ''"
            >{{ heroQuote.chg > 0 ? '+' : '' }}{{ fmtNum(heroQuote.chg) }}</span>
          </div>
          <div v-else class="etdx-hero__quote">
            <span class="etdx-hero__px is-idle">—</span>
            <span class="etdx-hero__hint">执行「实时报价」后显示行情</span>
          </div>

          <div class="etdx-hero__actions">
            <span class="etdx-hero__act-hint" v-if="!store.stock">↑ 先在上方选择标的</span>
            <span v-else class="etdx-hero__act-hint">执行入口在右侧「参数设置」面板</span>
          </div>
        </div>

        <!-- 视图 Tab -->
        <div class="etdx-tabs">
          <button
            v-for="v in VIEWS"
            :key="v.id"
            type="button"
            class="etdx-tabs__item"
            :class="currentView === v.id && 'is-active'"
            @click="activateView(v.id)"
          >
            <AppIcon :name="v.icon" size="sm" />
            {{ v.label }}
          </button>
        </div>

        <!-- 视图内容 -->
        <div class="etdx-viewport">
          <!-- ══ 总览：执行结果 + 最近任务 + 快捷任务 ══ -->
          <div v-if="currentView === 'overview'" class="etdx-overview">
            <div class="etdx-overview__grid">
              <!-- 执行结果（常驻：执行成功后结果统一显示在此，失败显示错误原因） -->
              <div class="etdx-card">
                <div class="etdx-card__head">
                  <AppIcon name="play" size="sm" />
                  <span>{{ store.task ? '执行结果 · ' + taskLabel(store.task) : '执行结果' }}</span>
                  <span class="etdx-card__sp"></span>
                  <span
                    v-if="store.task && store.task.status !== 'running'"
                    class="etdx-task-chip"
                    :class="'etdx-task-chip--' + store.task.status"
                  >
                    <AppIcon
                      :name="store.task.status === 'success' ? 'check-circle' : 'alert-circle'"
                      size="xs"
                    />
                    {{ store.task.status === 'success' ? '已完成' : '失败' }}
                  </span>
                  <span
                    v-else-if="store.task && store.task.status === 'running'"
                    class="etdx-task-chip etdx-task-chip--running"
                  >
                    <AppIcon name="refresh" size="xs" spin />
                    执行中 {{ store.task.progress || 0 }}%
                  </span>
                </div>
                <div class="etdx-card__body">
                  <template v-if="store.task && store.task.status !== 'running'">
                    <EasyTdxResultPanel
                      :result="store.task.status === 'success' ? store.task.result : null"
                      :error="store.task.status === 'error' ? store.task.error : ''"
                      :func="selectedFunc"
                      :loading="false"
                      :stock-names="store.stockNames"
                    />
                  </template>
                  <div v-else class="etdx-empty">
                    <AppIcon name="play" size="lg" />
                    <p>选择功能并点击「执行」，结果将显示在这里</p>
                  </div>
                </div>
              </div>

              <!-- 最近任务 -->
              <div class="etdx-card">
                <div class="etdx-card__head">
                  <AppIcon name="zap" size="sm" />
                  <span>最近任务</span>
                  <span class="etdx-card__hint">点击查看结果</span>
                </div>
                <div class="etdx-card__body">
                  <div v-if="store.recent.length" class="etdx-recent">
                    <button
                      v-for="t in store.recent"
                      :key="t.task_id"
                      type="button"
                      class="etdx-recent__item"
                      @click="loadTask(t.task_id)"
                    >
                      <span
                        class="etdx-recent__dot"
                        :class="t.status === 'success' ? 'is-ok' : t.status === 'error' ? 'is-err' : ''"
                      ></span>
                      <span class="etdx-recent__label">{{ taskLabel(t) }}</span>
                      <span class="etdx-recent__time">{{ t.started_at ? new Date(t.started_at * 1000).toLocaleTimeString('zh-CN', { hour12: false }) : '' }}</span>
                    </button>
                  </div>
                  <div v-else class="etdx-empty">
                    <AppIcon name="clock" size="lg" />
                    <p>暂无任务记录，点击下方快捷任务开始</p>
                  </div>
                </div>
              </div>
            </div>

            <!-- 快速任务网格（复用快捷任务卡片） -->
            <div class="etdx-card">
              <div class="etdx-card__head">
                <AppIcon name="sparkles" size="sm" />
                <span>快捷任务</span>
                <span class="etdx-card__hint">预置参数 · 点击即执行</span>
              </div>
              <div class="etdx-card__body">
                <EasyTdxQuickTasks :has-stock="!!store.stock" @run="runTask" />
              </div>
            </div>
          </div>

          <!-- ══ 执行视图（K线 / 分时 / 资金 / 缠论 / 回测 / 板块榜） ══ -->
          <template v-else-if="selectedFunc">
            <!-- 错误提示 -->
            <div v-if="errMsg" class="etdx-alert etdx-alert--danger">
              <AppIcon name="alert-circle" size="sm" /> {{ errMsg }}
            </div>

            <div class="etdx-card">
              <div class="etdx-card__head">
                <AppIcon :name="VIEWS.find((v) => v.id === currentView)?.icon" size="sm" />
                <span>{{ selectedFunc.label }}</span>
                <AppBadge variant="muted">{{ selectedFunc.group }}</AppBadge>
                <AppBadge variant="brand">{{ selectedFunc.client }}</AppBadge>
                <span v-if="!store.stock && funcNeedsStock(selectedFunc)" class="etdx-card__need">
                  <AppIcon name="alert-triangle" size="xs" /> 需先选择标的
                </span>
                <span class="etdx-card__sp"></span>
                <span
                  v-if="store.task"
                  class="etdx-task-chip"
                  :class="'etdx-task-chip--' + store.task.status"
                >
                  <AppIcon
                    :name="store.task.status === 'success' ? 'check-circle' : store.task.status === 'error' ? 'alert-circle' : 'refresh'"
                    size="xs"
                    :spin="store.task.status === 'running'"
                  />
                  {{ store.task.status === 'success' ? '已完成' : store.task.status === 'error' ? '失败' : '执行中 ' + (store.task.progress || 0) + '%' }}
                </span>
              </div>
              <div class="etdx-card__body">
                <EasyTdxResultPanel
                  :result="store.task && store.task.status !== 'running' ? store.task.result : null"
                  :error="store.task && store.task.status === 'error' ? store.task.error : ''"
                  :func="selectedFunc"
                  :loading="running"
                  :stock-names="store.stockNames"
                />
              </div>
            </div>
          </template>
        </div>
      </section>

      <!-- 右栏：参数面板 -->
      <aside class="etdx-params" :class="{ 'is-collapsed': paramsCollapsed }">
        <div class="etdx-params__head">
          <template v-if="!paramsCollapsed">
            <AppIcon name="sliders" size="sm" />
            <span>参数设置</span>
          </template>
          <button type="button" class="etdx-params__toggle" :title="paramsCollapsed ? '展开' : '收起'" @click="toggleParams">
            <AppIcon :name="paramsCollapsed ? 'chevrons-right' : 'chevrons-left'" size="sm" />
          </button>
        </div>

        <div v-if="!paramsCollapsed" class="etdx-params__body">
          <template v-if="selectedFunc">
            <p v-if="selectedFunc.help" class="etdx-params__help">{{ selectedFunc.help }}</p>
            <EasyTdxParamForm
              :func="selectedFunc"
              :model="store.params"
              :strategies="store.strategies"
              :stock="store.stock"
              @change-stock="changeStock"
            />
            <AppButton
              variant="primary"
              icon="play"
              :loading="running"
              :disabled="running"
              block
              class="etdx-params__apply"
              @click="run"
            >
              {{ running ? '执行中…' : '执行' }}
            </AppButton>
            <p class="etdx-params__tip">调整参数后点击「执行」重新拉取数据。</p>
          </template>
          <div v-else class="etdx-params__empty">
            <AppIcon name="sliders" size="lg" />
            <p>在左侧选择一个功能后，在此调整参数</p>
          </div>
        </div>

        <!-- 折叠态：唯一执行入口 -->
        <button
          v-if="paramsCollapsed && selectedFunc"
          type="button"
          class="etdx-params__mini-run"
          title="执行当前功能"
          :disabled="running"
          @click="run"
        >
          <AppIcon name="play" size="sm" :spin="running" />
        </button>
      </aside>
    </div>

    <!-- ══════ 底部任务中心 ══════ -->
    <footer class="etdx-taskbar">
      <!-- 运行状态 -->
      <div v-if="store.task" class="etdx-taskbar__state">
        <template v-if="store.task.status === 'running'">
          <AppIcon name="refresh" size="sm" spin />
          <span class="etdx-taskbar__title">执行中</span>
          <span class="etdx-taskbar__pct">{{ store.task.progress || 0 }}%</span>
          <div class="etdx-taskbar__bar">
            <div class="etdx-taskbar__bar-fill" :style="{ width: (store.task.progress || 0) + '%' }" />
          </div>
        </template>
        <template v-else-if="store.task.status === 'success'">
          <AppIcon name="check-circle" size="sm" />
          <span class="etdx-taskbar__title">已完成</span>
          <span class="etdx-taskbar__log">{{ store.task.logs?.slice(-1)[0]?.msg || '' }}</span>
        </template>
        <template v-else-if="store.task.status === 'error'">
          <AppIcon name="alert-circle" size="sm" />
          <span class="etdx-taskbar__title">执行失败</span>
          <span class="etdx-taskbar__log etdx-taskbar__log--err">{{ store.task.error || '' }}</span>
        </template>
      </div>
      <div v-else class="etdx-taskbar__state" :class="errMsg ? 'is-err' : 'etdx-taskbar__state--idle'">
        <AppIcon :name="errMsg ? 'alert-circle' : 'dot'" size="sm" />
        <span class="etdx-taskbar__title">{{ errMsg ? '提示' : '空闲' }}</span>
        <span class="etdx-taskbar__log" :class="errMsg && 'etdx-taskbar__log--err'">{{ errMsg || '选择一个视图或快捷任务开始查询' }}</span>
      </div>

      <div class="etdx-taskbar__sp"></div>

      <!-- 最近任务 -->
      <div v-if="store.recent.length" class="etdx-taskbar__recent">
        <button
          v-for="t in store.recent.slice(0, 5)"
          :key="'c' + t.task_id"
          type="button"
          class="etdx-taskbar__chip"
          :title="taskLabel(t)"
          @click="loadTask(t.task_id)"
        >
          <span class="etdx-taskbar__chip-dot" :class="t.status === 'success' ? 'is-ok' : t.status === 'error' ? 'is-err' : ''"></span>
          {{ taskLabel(t) }}
        </button>
      </div>
    </footer>
  </div>
</template>

<style scoped>
/* ═══════════ 外壳：占满内容区 ═══════════ */
.etdx-shell {
  height: 100%;
  min-height: 0;
  display: flex;
  flex-direction: column;
  gap: 0;
}

/* ═══════════ 顶部命令条 ═══════════ */
.etdx-top {
  flex: none;
  display: flex;
  align-items: center;
  gap: var(--ff-space-4);
  padding: 0 var(--ff-space-4);
  height: 58px;
  background: var(--ff-bg-surface);
  border: 1px solid var(--ff-border);
  border-radius: var(--ff-radius-lg);
  box-shadow: var(--ff-shadow-sm, none);
  margin-bottom: var(--ff-space-3);
}
.etdx-top__title {
  display: flex;
  align-items: center;
  gap: var(--ff-space-3);
  min-width: 240px;
}
.etdx-top__mark {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 34px;
  height: 34px;
  flex: none;
  border-radius: 10px;
  background: var(--ff-bg-brand);
  color: #fff;
  box-shadow: 0 2px 8px rgba(37, 99, 235, 0.3);
}
.etdx-top__name {
  font-size: var(--ff-fs-h3);
  font-weight: 700;
  line-height: 1.2;
  letter-spacing: -0.01em;
}
.etdx-top__sub {
  font-size: var(--ff-fs-caption);
  color: var(--ff-text-tertiary);
}
.etdx-top__search {
  flex: 1;
  max-width: 420px;
}
.etdx-top__meta {
  margin-left: auto;
  display: flex;
  align-items: center;
  gap: var(--ff-space-3);
}
.etdx-top__host {
  display: inline-flex;
  align-items: center;
  gap: 7px;
  padding: 5px 12px;
  border: 1px solid var(--ff-border);
  border-radius: var(--ff-radius-pill);
  font-size: var(--ff-fs-caption);
  color: var(--ff-text-secondary);
  background: var(--ff-bg-surface);
}
.etdx-top__dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  background: var(--ff-down);
  box-shadow: 0 0 0 3px var(--ff-down-subtle);
  animation: etdx-pulse 2s infinite;
}
@keyframes etdx-pulse {
  0%, 100% { opacity: 1; }
  50% { opacity: 0.55; }
}
.etdx-top__count {
  font-size: var(--ff-fs-caption);
  color: var(--ff-text-tertiary);
  white-space: nowrap;
}

/* ═══════════ 主体三栏 ═══════════ */
.etdx-body {
  flex: 1;
  min-height: 0;
  display: flex;
  gap: var(--ff-space-3);
}

/* —— 左栏 —— */
.etdx-rail {
  width: 252px;
  flex: none;
  display: flex;
  flex-direction: column;
  min-height: 0;
  background: var(--ff-bg-surface);
  border: 1px solid var(--ff-border);
  border-radius: var(--ff-radius-lg);
  overflow: hidden;
}
.etdx-rail__watch {
  flex: none;
  max-height: 34%;
  overflow-y: auto;
  padding: var(--ff-space-3);
}
.etdx-rail__divider {
  flex: none;
  height: 1px;
  background: var(--ff-border-subtle);
  margin: 0 var(--ff-space-3);
}
.etdx-rail__nav {
  flex: 1;
  min-height: 0;
  overflow-y: auto;
  padding: var(--ff-space-3);
}

/* —— 中栏 —— */
.etdx-center {
  flex: 1;
  min-width: 0;
  min-height: 0;
  display: flex;
  flex-direction: column;
  gap: var(--ff-space-3);
}

/* Hero 标的名片 */
.etdx-hero {
  flex: none;
  display: flex;
  align-items: center;
  gap: var(--ff-space-4);
  padding: var(--ff-space-3) var(--ff-space-4);
  background: var(--ff-bg-surface);
  border: 1px solid var(--ff-border);
  border-radius: var(--ff-radius-lg);
  box-shadow: var(--ff-shadow-sm, none);
  flex-wrap: wrap;
}
.etdx-hero__name {
  min-width: 180px;
}
.etdx-hero__name h2 {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: var(--ff-fs-h3);
  font-weight: 700;
}
.etdx-hero__mk {
  font-size: 10.5px;
  font-weight: 600;
  color: #fff;
  background: var(--ff-bg-brand);
  border-radius: 4px;
  padding: 2px 6px;
  letter-spacing: 0.05em;
}
.etdx-hero__code {
  font-size: var(--ff-fs-caption);
  color: var(--ff-text-tertiary);
  margin-top: 2px;
}
.etdx-hero__quote {
  display: flex;
  align-items: baseline;
  gap: 10px;
  min-width: 150px;
}
.etdx-hero__px {
  font-size: 28px;
  font-weight: 700;
  font-family: var(--ff-font-mono, monospace);
  letter-spacing: -0.02em;
  font-variant-numeric: tabular-nums;
}
.etdx-hero__px.is-up { color: var(--ff-up-text); }
.etdx-hero__px.is-down { color: var(--ff-down-text); }
.etdx-hero__px.is-idle { color: var(--ff-text-tertiary); }
.etdx-hero__chg {
  font-size: var(--ff-fs-body);
  font-weight: 600;
  font-family: var(--ff-font-mono, monospace);
  font-variant-numeric: tabular-nums;
}
.etdx-hero__chg.is-up { color: var(--ff-up-text); }
.etdx-hero__chg.is-down { color: var(--ff-down-text); }
.etdx-hero__hint {
  font-size: var(--ff-fs-caption);
  color: var(--ff-text-tertiary);
}
.etdx-hero__actions {
  margin-left: auto;
}
.etdx-hero__act-hint {
  font-size: var(--ff-fs-caption);
  color: var(--ff-text-tertiary);
}

/* 视图 Tab */
.etdx-tabs {
  flex: none;
  display: flex;
  gap: 2px;
  border-bottom: 1px solid var(--ff-border);
  overflow-x: auto;
}
.etdx-tabs__item {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 9px 14px;
  border-bottom: 2px solid transparent;
  font-size: var(--ff-fs-body-sm);
  font-weight: 500;
  color: var(--ff-text-secondary);
  white-space: nowrap;
  transition: color var(--ff-dur-fast), border-color var(--ff-dur-fast);
}
.etdx-tabs__item:hover {
  color: var(--ff-text-primary);
}
.etdx-tabs__item.is-active {
  color: var(--ff-text-brand);
  font-weight: 600;
  border-bottom-color: var(--ff-brand);
}

/* 视图内容滚动区 */
.etdx-viewport {
  flex: 1;
  min-height: 0;
  overflow-y: auto;
  padding-bottom: var(--ff-space-2);
}

/* —— 通用卡片 —— */
.etdx-card {
  background: var(--ff-bg-surface);
  border: 1px solid var(--ff-border);
  border-radius: var(--ff-radius-lg);
  box-shadow: var(--ff-shadow-sm, none);
  margin-bottom: var(--ff-space-3);
  overflow: hidden;
}
.etdx-card__head {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 11px 14px;
  border-bottom: 1px solid var(--ff-border-subtle);
  font-size: var(--ff-fs-body-sm);
  font-weight: 600;
  color: var(--ff-text-secondary);
}
.etdx-card__head > svg {
  color: var(--ff-text-brand);
}
.etdx-card__hint {
  font-weight: 400;
  color: var(--ff-text-tertiary);
  font-size: var(--ff-fs-caption);
  margin-left: auto;
}
.etdx-card__sp {
  margin-left: auto;
}
.etdx-card__need {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  font-size: var(--ff-fs-caption);
  font-weight: 500;
  color: var(--ff-text-warning);
  background: var(--ff-bg-warning-subtle);
  border-radius: var(--ff-radius-pill);
  padding: 2px 8px;
}
/* 任务状态徽章（卡片头部） */
.etdx-task-chip {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  padding: 2px 10px;
  border-radius: var(--ff-radius-pill);
  font-size: var(--ff-fs-caption);
  font-weight: 600;
  flex: none;
}
.etdx-task-chip--running {
  background: var(--ff-bg-brand-subtle);
  color: var(--ff-text-brand);
}
.etdx-task-chip--success {
  background: var(--ff-bg-up-subtle);
  color: var(--ff-up-text);
}
.etdx-task-chip--error {
  background: var(--ff-bg-down-subtle);
  color: var(--ff-down-text);
}
.etdx-card__body {
  padding: var(--ff-space-3) var(--ff-space-4);
}

/* 总览 */
.etdx-overview__grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: var(--ff-space-3);
}
.etdx-recent {
  display: flex;
  flex-direction: column;
  gap: 4px;
}
.etdx-recent__item {
  display: flex;
  align-items: center;
  gap: 8px;
  width: 100%;
  padding: 7px 10px;
  border-radius: var(--ff-radius-sm);
  text-align: left;
  font-size: var(--ff-fs-body-sm);
  transition: background var(--ff-dur-fast);
}
.etdx-recent__item:hover {
  background: var(--ff-bg-hover);
}
.etdx-recent__dot {
  width: 7px;
  height: 7px;
  flex: none;
  border-radius: 50%;
  background: var(--ff-icon-muted);
}
.etdx-recent__dot.is-ok { background: var(--ff-down); }
.etdx-recent__dot.is-err { background: var(--ff-up); }
.etdx-recent__label {
  flex: 1;
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  color: var(--ff-text-primary);
}
.etdx-recent__time {
  font-size: var(--ff-fs-caption);
  font-family: var(--ff-font-mono, monospace);
  color: var(--ff-text-tertiary);
  flex: none;
}
.etdx-empty {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 8px;
  padding: 28px 16px;
  color: var(--ff-text-tertiary);
  font-size: var(--ff-fs-body-sm);
  text-align: center;
}

/* 错误提示 */
.etdx-alert {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 10px 14px;
  border-radius: var(--ff-radius-md);
  font-size: var(--ff-fs-body-sm);
  margin-bottom: var(--ff-space-3);
}
.etdx-alert--danger {
  background: var(--ff-bg-down-subtle);
  color: var(--ff-down-text);
}

/* —— 右栏参数面板 —— */
.etdx-params {
  width: 288px;
  flex: none;
  display: flex;
  flex-direction: column;
  min-height: 0;
  background: var(--ff-bg-surface);
  border: 1px solid var(--ff-border);
  border-radius: var(--ff-radius-lg);
  overflow: hidden;
  transition: width var(--ff-dur-normal);
}
.etdx-params.is-collapsed {
  width: 44px;
}
.etdx-params__head {
  flex: none;
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 11px 14px;
  border-bottom: 1px solid var(--ff-border-subtle);
  font-size: var(--ff-fs-body-sm);
  font-weight: 600;
  color: var(--ff-text-secondary);
}
.etdx-params__head > svg {
  color: var(--ff-text-brand);
}
.etdx-params__toggle {
  margin-left: auto;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 26px;
  height: 26px;
  border-radius: var(--ff-radius-sm);
  color: var(--ff-icon-muted);
  transition: background var(--ff-dur-fast);
}
.etdx-params__toggle:hover {
  background: var(--ff-bg-hover);
  color: var(--ff-text-primary);
}
.etdx-params.is-collapsed .etdx-params__toggle {
  margin-left: 0;
}
.etdx-params__body {
  flex: 1;
  min-height: 0;
  overflow-y: auto;
  padding: var(--ff-space-3);
  display: flex;
  flex-direction: column;
  gap: var(--ff-space-3);
}
.etdx-params__help {
  font-size: var(--ff-fs-caption);
  color: var(--ff-text-tertiary);
  line-height: 1.6;
  background: var(--ff-bg-subtle);
  border-radius: var(--ff-radius-md);
  padding: 8px 10px;
}
.etdx-params__apply {
  margin-top: 2px;
}
.etdx-params__tip {
  font-size: var(--ff-fs-caption);
  color: var(--ff-text-tertiary);
  line-height: 1.6;
  border: 1px dashed var(--ff-border);
  border-radius: var(--ff-radius-md);
  padding: 8px 10px;
}
.etdx-params__empty {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 10px;
  padding: 32px 12px;
  color: var(--ff-text-tertiary);
  text-align: center;
  font-size: var(--ff-fs-body-sm);
}
/* 折叠态：唯一执行入口（竖排按钮） */
.etdx-params__mini-run {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 6px;
  margin: 12px auto;
  width: 30px;
  padding: 10px 0;
  border-radius: var(--ff-radius-md);
  background: var(--ff-bg-brand);
  color: #fff;
  box-shadow: 0 2px 8px rgba(37, 99, 235, 0.3);
  transition: background var(--ff-dur-fast), transform var(--ff-dur-fast);
}
.etdx-params__mini-run:hover {
  background: var(--ff-brand-hover);
  transform: translateY(-1px);
}
.etdx-params__mini-run:disabled {
  opacity: 0.6;
  cursor: not-allowed;
}

/* ═══════════ 底部任务中心 ═══════════ */
.etdx-taskbar {
  flex: none;
  display: flex;
  align-items: center;
  gap: var(--ff-space-3);
  padding: 0 var(--ff-space-4);
  height: 44px;
  background: var(--ff-bg-surface);
  border: 1px solid var(--ff-border);
  border-radius: var(--ff-radius-lg);
  margin-top: var(--ff-space-3);
  font-size: var(--ff-fs-caption);
}
.etdx-taskbar__state {
  display: flex;
  align-items: center;
  gap: 8px;
  min-width: 0;
  color: var(--ff-text-secondary);
}
.etdx-taskbar__state > svg {
  color: var(--ff-text-brand);
  flex: none;
}
.etdx-taskbar__state--idle > svg {
  color: var(--ff-icon-muted);
}
.etdx-taskbar__state.is-err > svg {
  color: var(--ff-up-text);
}
.etdx-taskbar__title {
  font-weight: 600;
  color: var(--ff-text-primary);
  flex: none;
}
.etdx-taskbar__pct {
  font-family: var(--ff-font-mono, monospace);
  font-weight: 600;
  color: var(--ff-text-secondary);
  flex: none;
}
.etdx-taskbar__bar {
  width: 140px;
  height: 5px;
  flex: none;
  border-radius: var(--ff-radius-pill);
  background: var(--ff-bg-subtle);
  overflow: hidden;
}
.etdx-taskbar__bar-fill {
  height: 100%;
  background: linear-gradient(90deg, var(--ff-brand), var(--ff-brand-hover));
  border-radius: var(--ff-radius-pill);
  transition: width 0.4s var(--ff-ease-standard);
}
.etdx-taskbar__log {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  max-width: 300px;
  color: var(--ff-text-tertiary);
  font-family: var(--ff-font-mono, monospace);
  font-size: 11.5px;
}
.etdx-taskbar__log--err {
  color: var(--ff-up-text);
}
.etdx-taskbar__sp {
  flex: 1;
}
.etdx-taskbar__recent {
  display: flex;
  gap: 6px;
  overflow-x: auto;
  max-width: 46%;
}
.etdx-taskbar__chip {
  flex: none;
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 3px 10px;
  border-radius: var(--ff-radius-pill);
  background: var(--ff-bg-subtle);
  font-size: 11.5px;
  color: var(--ff-text-secondary);
  transition: background var(--ff-dur-fast), color var(--ff-dur-fast);
}
.etdx-taskbar__chip:hover {
  background: var(--ff-bg-brand-subtle);
  color: var(--ff-text-brand);
}
.etdx-taskbar__chip-dot {
  width: 6px;
  height: 6px;
  flex: none;
  border-radius: 50%;
  background: var(--ff-icon-muted);
}
.etdx-taskbar__chip-dot.is-ok { background: var(--ff-down); }
.etdx-taskbar__chip-dot.is-err { background: var(--ff-up); }

/* ═══════════ 响应式 ═══════════ */
@media (max-width: 1180px) {
  .etdx-rail { width: 216px; }
  .etdx-params { width: 252px; }
  .etdx-overview__grid { grid-template-columns: 1fr; }
}
@media (max-width: 980px) {
  .etdx-rail { display: none; }
  .etdx-params { display: none; }
  .etdx-top__meta { display: none; }
}
</style>
