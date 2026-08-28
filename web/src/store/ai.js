import { defineStore } from 'pinia'
import { api } from '../api/client'

/**
 * AI 投研模块共享状态
 * 工作台 / 分析师 / 报告 / 任务 / 设置 五个页面共用的数据源与轮询逻辑。
 * 单一数据源：任务状态在 TasksView 变更后，工作台与报告列表实时联动。
 */
export const useAiStore = defineStore('ai', {
  state: () => ({
    status: null, // /llm/status
    providers: [],
    presets: [], // 模型预设（向导用）
    scopeOptions: [],
    windowOptions: [24, 48, 72],
    reports: [], // 最近报告（工作台 + 报告页共用，报告页可加载更多）
    reportsTotal: 0,
    reportsLoading: false,
    tasks: [], // 任务列表
    sessions: [], // 会话列表
    activeTask: null, // 运行中任务（供工作台进度条）
    pollTimer: null,
    pollActive: false,
    cmdOpen: false, // 命令面板（顶部按钮打开）
    // REDUCE 阶段流式输出：taskStreamText 为渐进正文，streamTaskId 标识当前订阅
    taskStreamText: '',
    streamTaskId: null,
    streamUnsub: null,
    // 分析默认配置（scope/window/focus）：设置页保存，工作台/生成任务读取
    config: {
      scope: 'all',
      window: 24,
      focus: '',
    },
    // 会话级上下文（分析师页）
    contextStock: null, // { name, code, price, change, ... }
    contextReport: null, // { id, title, section }
  }),

  getters: {
    modelAvailable(state) {
      const s = state.status
      if (!s) return false
      if (typeof s.available === 'boolean') return s.available
      const dp = s.default_provider
      return !!(dp && dp.enabled && (dp.has_api_key || dp.test_status === 1))
    },
    runningTasks(state) {
      return state.tasks.filter((t) => t.status === 'running' || t.status === 'pending')
    },
    scopeLabel(state) {
      return (key) => {
        const hit = state.scopeOptions.find((s) => s.key === key)
        return hit ? hit.label : key === 'all' ? '全部' : key || '全部'
      }
    },
    windowLabel(state) {
      return (hours) => `${hours || 24} 小时`
    },
  },

  actions: {
    // ---------- 基础加载 ----------
    // 读取本地保存的分析默认值（设置页写入）
    loadConfig() {
      try {
        const raw = localStorage.getItem('finfeed_ai_config')
        if (!raw) return
        const c = JSON.parse(raw)
        if (c.scope) this.config.scope = c.scope
        if (c.window) this.config.window = Number(c.window) || 24
        if (c.focus !== undefined) this.config.focus = c.focus
      } catch (e) {}
    },
    saveConfig(patch = {}) {
      this.config = { ...this.config, ...patch }
      try {
        localStorage.setItem('finfeed_ai_config', JSON.stringify(this.config))
      } catch (e) {}
    },
    async loadStatus() {
      try {
        this.status = await api.llm('/status')
      } catch (e) {
        this.status = { error: e.message }
      }
    },
    async loadInit() {
      try {
        const init = await api.llm('/init')
        this.providers = init.providers || []
        this.presets = init.presets || []
        this.scopeOptions = init.scopes || []
        if (init.windows && init.windows.length) this.windowOptions = init.windows
        if (init.status) this.status = init.status
      } catch (e) {}
    },
    async loadProviders() {
      try {
        const r = await api.llm('/providers')
        this.providers = r.providers || []
      } catch (e) {
        this.providers = []
      }
    },
    async loadReports(params = {}) {
      this.reportsLoading = true
      try {
        const r = await api.llm('/reports', params)
        this.reports = r.items || []
        this.reportsTotal = r.total || 0
      } catch (e) {
        // 保留旧数据
      } finally {
        this.reportsLoading = false
      }
    },
    async loadTasks() {
      try {
        const r = await api.llm('/tasks', { limit: 20 })
        this.tasks = r.tasks || []
        this.activeTask =
          this.tasks.find((t) => t.status === 'running' || t.status === 'pending') || null
        // 页面刷新/断线重连后自动续订运行中任务的流式输出
        if (this.activeTask?.task_id && this.streamTaskId !== this.activeTask.task_id) {
          this.startTaskStream(this.activeTask.task_id)
        }
      } catch (e) {}
    },
    async loadSessions() {
      try {
        const r = await api.llm('/sessions', { limit: 100 })
        this.sessions = r.sessions || []
      } catch (e) {
        this.sessions = []
      }
    },

    // ---------- 轮询 ----------
    startPolling(interval = 4000) {
      if (this.pollActive) return
      this.pollActive = true
      this.pollTimer = setInterval(async () => {
        // 仅在存在运行中任务时高频刷新任务；报告/会话低频刷新
        await Promise.all([this.loadTasks(), this.loadStatus()])
      }, interval)
    },
    stopPolling() {
      this.pollActive = false
      if (this.pollTimer) {
        clearInterval(this.pollTimer)
        this.pollTimer = null
      }
    },

    // ---------- 任务动作 ----------
    async submitAnalysis(cfg) {
      const r = await api.llmPost('/analyze', {
        provider_id: cfg.provider_id ? Number(cfg.provider_id) : undefined,
        scope: cfg.scope,
        hours: Number(cfg.window),
        focus: cfg.focus || undefined,
        min_importance: 0,
      })
      await this.loadTasks()
      if (r.ok && r.task_id) this.startTaskStream(r.task_id)
      return r
    },
    async cancelTask(taskId) {
      try {
        await api.llmPost('/task/cancel', { task_id: taskId })
      } catch (e) {}
      await this.loadTasks()
    },
    async retryTask(taskId) {
      const r = await api.llmPost('/task/retry', { task_id: taskId })
      await this.loadTasks()
      if (r.ok && r.task_id) this.startTaskStream(r.task_id)
      return r
    },

    // ---------- 任务流式输出（SSE） ----------
    startTaskStream(taskId) {
      if (!taskId || this.streamTaskId === taskId) return
      this.stopTaskStream()
      this.streamTaskId = taskId
      this.taskStreamText = ''
      this.streamUnsub = api.llmTaskStream(taskId, {
        onStage: () => {}, // 阶段进度仍由轮询驱动，保持单一来源
        onDelta: (text) => {
          if (this.streamTaskId === taskId) this.taskStreamText += text
        },
        onReset: () => {
          if (this.streamTaskId === taskId) this.taskStreamText = ''
        },
        onDone: async (d) => {
          if (this.streamTaskId !== taskId) return
          this.streamUnsub?.()
          this.streamUnsub = null
          await Promise.all([this.loadTasks(), this.loadStatus()])
          if (d?.status === 'success') await this.loadReports({ limit: 6 })
          // 保留正文数秒供「查看报告」过渡，随后清理由下次订阅接管
          setTimeout(() => {
            if (this.streamTaskId === taskId && !this.activeTask) {
              this.taskStreamText = ''
              this.streamTaskId = null
            }
          }, 4000)
        },
        onError: () => {
          // SSE 断开：轮询仍在，静默降级；任务未结束时允许重连由视图层触发
        },
      })
    },
    stopTaskStream() {
      try {
        this.streamUnsub?.()
      } catch (e) {}
      this.streamUnsub = null
      this.streamTaskId = null
      this.taskStreamText = ''
    },

    // ---------- 会话动作 ----------
    async createSession(title = '新会话') {
      const r = await api.llmPost('/sessions', { title })
      await this.loadSessions()
      return r.session || null
    },
    async renameSession(id, title) {
      try {
        await api.llmPost('/sessions/rename', { id, title })
      } catch (e) {}
      await this.loadSessions()
    },
    async deleteSession(id) {
      try {
        await api.llmPost('/sessions/delete', { id })
      } catch (e) {}
      await this.loadSessions()
    },
    async saveMessage(id, role, content) {
      try {
        await api.llmPost('/sessions/messages', { id, role, content })
      } catch (e) {}
    },

    // ---------- 报告动作 ----------
    async deleteReport(id) {
      try {
        await api.llmPost('/report/delete', { id })
      } catch (e) {}
      await this.loadReports()
      await this.loadTasks()
    },
    async deleteReports(ids) {
      for (const id of ids) {
        try {
          await api.llmPost('/report/delete', { id })
        } catch (e) {}
      }
      await this.loadReports()
      await this.loadTasks()
    },
    async pinReport(id, pinned) {
      try {
        await api.llmPost('/report/pin', { id, pinned })
      } catch (e) {}
      await this.loadReports()
    },
    async pinReports(ids, pinned) {
      for (const id of ids) {
        try {
          await api.llmPost('/report/pin', { id, pinned })
        } catch (e) {}
      }
      await this.loadReports()
    },

    // ---------- 上下文 ----------
    setContextStock(stock) {
      this.contextStock = stock || null
    },
    setContextReport(report) {
      this.contextReport = report || null
    },
    clearContext() {
      this.contextStock = null
      this.contextReport = null
    },
  },
})
