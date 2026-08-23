// easy-tdx 全局状态：标的上下文 / 功能选择 / 参数 / 任务 / 收藏与最近 / UI 面板状态
import { defineStore } from 'pinia'
import easytdxApi from '@/features/easytdx/api/easytdxApi'
import { loadStockNames } from '../components/easytdx/stockNames'
import { createTaskRunner } from '../composables/useTaskRunner'
import {
  loadFavorites, saveFavorites, toggleFavorite,
  loadRecentFuncs, saveRecentFuncs, pushRecentFunc,
  loadRecentStocks, saveRecentStocks, pushRecentStock,
} from '../composables/useRecentFunctions'

// 场景化分组（与后端 group_meta 匹配）
const SCENES = [
  { id: 'quote', label: '行情数据', icon: 'trending-up', groups: ['kline', 'minute', 'transaction', 'macquote', 'mackline', 'mactick', 'ex'] },
  { id: 'stock', label: '个股资料', icon: 'file-text', groups: ['finance', 'cninfo', 'block'] },
  { id: 'market', label: '市场扫描', icon: 'activity', groups: ['market', 'fundflow', 'macboard', 'maccapital', 'macmonitor'] },
  { id: 'tools', label: '高级工具', icon: 'candles', groups: ['chanlun', 'backtest', 'file'] },
  { id: 'conn', label: '系统连接', icon: 'database', groups: ['conn'] },
]

export const useEasytdxStore = defineStore('easytdx', {
  state: () => ({
    meta: null,
    strategies: [],
    navGroups: [],
    groupLabels: {},
    // 标的上下文
    stock: null,
    stockNames: {},
    // 功能与参数
    selectedFuncId: '',
    params: {},
    // 任务
    task: null,
    running: false,
    errMsg: '',
    recent: [],
    // 记忆
    favorites: loadFavorites(),
    recentFuncs: loadRecentFuncs(),
    recentStocks: loadRecentStocks(),
    // UI 面板状态
    ui: {
      railTab: 'all', // all | fav | recent
      query: '',
      railCollapsed: false,
      paramPanelOpen: true,
      dockOpen: false,
      dockPinned: false,
      focusMode: false,
      paneWidth: 320,
      paletteOpen: false,
    },
    // 任务执行器（bindRunner 惰性创建；必须声明为 state 才能被 getter 稳定读取）
    _runner: null,
  }),

  getters: {
    selectedFunc: (s) => s.meta?.functions.find((f) => f.id === s.selectedFuncId) || null,
    groupLabelOf: (s) => (groupId) => s.groupLabels[groupId] || groupId || '',
    funcCount: (s) => s.navGroups.reduce((n, g) => n + g.items.length, 0),
    isFavorite: (s) => (id) => s.favorites.includes(id),
    runningTask: (s) => s.running,
    // 任务执行器实例（注意：必须放在 getters 中；放在 actions 里会被 Pinia 当作 action 包装，
    // 导致 store.runner 变成函数而非 { run, stopPolling } 对象，调用时抛
    // 「this.runner.run is not a function」）
    runner: (s) => s._runner,
  },

  actions: {
    // ---------------- 初始化 ----------------
    async init() {
      try {
        const [m, st] = await Promise.all([easytdxApi.meta(), easytdxApi.strategies()])
        this.meta = m
        this.strategies = st.strategies || []
        this.buildNav(m.group_meta || [], m.functions || [])
        if (m.functions?.length) {
          this.selectFunc(m.functions[0].id, { autoInject: false })
        }
      } catch (e) {
        this.errMsg = '加载功能清单失败：' + (e.message || e)
      }
    },

    async loadNames() {
      this.stockNames = await loadStockNames()
    },

    async loadRecent() {
      try {
        const r = await easytdxApi.tasks(8)
        this.recent = r.tasks || []
      } catch {
        /* 静默降级 */
      }
    },

    // 加载历史任务详情（结果查看，不重新执行）
    async loadTask(taskId) {
      try {
        const t = await easytdxApi.task(taskId)
        this.task = t
        this.running = false
      } catch {
        this.errMsg = '加载任务详情失败'
      }
    },

    // ---------------- 导航构建 ----------------
    buildNav(groups, functions) {
      const labels = {}
      for (const g of groups) labels[g.id] = g.label
      this.groupLabels = labels
      this.navGroups = SCENES
        .map((scene) => ({
          id: scene.id,
          label: scene.label,
          icon: scene.icon,
          items: functions
            .filter((f) => scene.groups.includes(f.group))
            .map((f) => ({ id: f.id, label: f.label, tag: labels[f.group] })),
        }))
        .filter((scene) => scene.items.length)
    },

    // ---------------- 标的上下文 ----------------
    selectStock(s) {
      this.stock = s
      this.errMsg = ''
      this.recentStocks = pushRecentStock(this.recentStocks, s)
      saveRecentStocks(this.recentStocks)
      this.injectStockToFunc()
    },

    clearStock() {
      this.stock = null
    },

    // 把当前标的注入到功能参数（market/code 或 stocklist）
    injectStockToFunc() {
      if (!this.stock || !this.selectedFunc) return
      const func = this.selectedFunc
      const hasCode = func.params?.some((p) => p.key === 'code')
      const hasStocks = func.params?.some((p) => p.key === 'stocks')
      if (hasCode) {
        this.params.code = this.stock.code
        if (func.params.some((p) => p.key === 'market')) this.params.market = this.stock.market
      } else if (hasStocks) {
        this.params.stocks = `${this.stock.market} ${this.stock.code}`
      }
    },

    // ---------------- 功能选择与参数 ----------------
    resetParams(func) {
      const next = {}
      for (const p of func?.params || []) {
        next[p.key] = p.default ?? (p.type === 'bool' ? false : '')
      }
      this.params = next
    },

    selectFunc(id, { autoInject = true } = {}) {
      this.errMsg = ''
      this.selectedFuncId = id
      const func = this.meta?.functions.find((f) => f.id === id)
      if (func) {
        this.resetParams(func)
        if (autoInject) this.injectStockToFunc()
      }
      this.task = null
      // 记录最近使用
      this.recentFuncs = pushRecentFunc(this.recentFuncs, id)
      saveRecentFuncs(this.recentFuncs)
    },

    // 设置单个参数（ParamField v-model 绑定用）
    setParam(key, value) {
      this.params[key] = value
    },

    // ---------------- 收藏 ----------------
    toggleFav(id) {
      const { list, added } = toggleFavorite(this.favorites, id)
      this.favorites = list
      saveFavorites(list)
      return added
    },

    moveFavorite(from, to) {
      if (to < 0 || to >= this.favorites.length) return
      const next = this.favorites.slice()
      const [item] = next.splice(from, 1)
      next.splice(to, 0, item)
      this.favorites = next
      saveFavorites(next)
    },

    // ---------------- 执行（绑定任务执行器） ----------------
    bindRunner() {
      if (this._runner) return
      this._runner = createTaskRunner(this)
    },

    async run() {
      if (!this.selectedFunc) return
      this.bindRunner() // 确保执行器已创建（getter 无副作用）
      return this.runner.run(this.selectedFuncId, this.params)
    },

    // 快捷任务：选择功能 → 填充预置参数 → 注入标的 → 执行
    async runTask(t) {
      if (t.needsStock && !this.stock) {
        this.errMsg = '请先选择股票标的（输入名称或代码），再执行「' + t.label + '」'
        return false
      }
      this.selectedFuncId = t.func
      this.errMsg = ''
      const func = this.meta?.functions.find((f) => f.id === t.func)
      if (func) {
        this.resetParams(func)
        Object.assign(this.params, t.params || {})
        if (t.needsStock && this.stock) this.injectStockToFunc()
      }
      this.task = null
      this.recentFuncs = pushRecentFunc(this.recentFuncs, t.func)
      saveRecentFuncs(this.recentFuncs)
      return this.runner.run(t.func, this.params)
    },

    stopPolling() {
      this._runner?.stopPolling()
    },

    // ---------------- UI 面板 ----------------
    setRailTab(tab) {
      this.ui.railTab = tab
    },
    setQuery(q) {
      this.ui.query = q
    },
    toggleRailCollapsed() {
      this.ui.railCollapsed = !this.ui.railCollapsed
    },
    toggleParamPanel() {
      this.ui.paramPanelOpen = !this.ui.paramPanelOpen
    },
    setDockOpen(v) {
      this.ui.dockOpen = v
      if (v) this.ui.dockPinned = false
    },
    toggleDockPin() {
      this.ui.dockPinned = !this.ui.dockPinned
    },
    toggleFocusMode() {
      this.ui.focusMode = !this.ui.focusMode
    },
    setPalette(v) {
      this.ui.paletteOpen = v
    },
  },
})
