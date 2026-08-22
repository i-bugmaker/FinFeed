// 智能选股全局状态：配置 / 任务 / 结果 / 最近任务
import { defineStore } from 'pinia'
import screenerApi from '../api/screener'

const POLL_INTERVAL = 800
const TASK_IDLE_TIMEOUT = 60_000

export const useScreenerStore = defineStore('screener', {
  state: () => ({
    config: null,
    task: null,
    running: false,
    errMsg: '',
    recent: [],
    pollTimer: null,
    lastSignalAt: 0,
  }),

  getters: {
    result: (s) => s.task?.result || null,
    strongCount: (s) => {
      if (!s.task?.result?.scores) return 0
      return s.task.result.scores.filter((x) => x.tier === 'strong').length
    },
    watchCount: (s) => {
      if (!s.task?.result?.scores) return 0
      return s.task.result.scores.filter((x) => x.tier === 'watch').length
    },
    observeCount: (s) => {
      if (!s.task?.result?.scores) return 0
      return s.task.result.scores.filter((x) => x.tier === 'observe').length
    },
  },

  actions: {
    async loadConfig() {
      try {
        this.config = await screenerApi.config()
      } catch (e) {
        this.errMsg = '加载选股配置失败：' + (e.message || e)
      }
    },

    async loadRecent() {
      try {
        const r = await screenerApi.tasks(8)
        this.recent = r.tasks || []
      } catch {
        /* 静默降级 */
      }
    },

    async loadTask(taskId) {
      try {
        const t = await screenerApi.task(taskId)
        this.task = t
        this.running = t.status === 'running'
      } catch {
        this.errMsg = '加载任务详情失败'
      }
    },

    startPolling(taskId) {
      this.stopPolling()
      this.lastSignalAt = Date.now()
      this.pollTimer = setInterval(() => this.pollTask(taskId), POLL_INTERVAL)
      this.pollTask(taskId)
    },

    stopPolling() {
      if (this.pollTimer) {
        clearInterval(this.pollTimer)
        this.pollTimer = null
      }
    },

    async pollTask(taskId) {
      try {
        const t = await screenerApi.task(taskId)
        const prev = this.task
        if (!prev || prev.progress !== t.progress || (prev.logs?.length || 0) !== (t.logs?.length || 0)) {
          this.lastSignalAt = Date.now()
        } else if (Date.now() - this.lastSignalAt > TASK_IDLE_TIMEOUT) {
          this.stopPolling()
          this.running = false
          this.errMsg = '任务长时间无进展，可能已卡死。请刷新后重试。'
          return
        }
        this.task = t
        if (t.status === 'success' || t.status === 'error') {
          this.stopPolling()
          this.running = false
          this.loadRecent()
        }
      } catch {
        /* 单次轮询失败不打断 */
      }
    },

    async run(params = {}) {
      this.errMsg = ''
      this.task = null
      this.running = true
      try {
        const r = await screenerApi.run(params)
        this.startPolling(r.task_id)
        return true
      } catch (e) {
        this.running = false
        this.errMsg = '提交失败：' + (e.message || e)
        return false
      }
    },
  },
})
