// 任务执行器：提交 / 轮询 / 中止 / 超时判定。
// 轮询周期与超时策略集中于此；状态写入 Pinia store（store.task / running / errMsg）。
// 挂载方（store）在卸载或切换功能时调用 stopPolling 清理定时器。

import easytdxApi from '@/features/easytdx/api/easytdxApi'

export const POLL_INTERVAL = 800
export const TASK_IDLE_TIMEOUT = 60_000 // 60s 无日志/进度变化判定卡死

export function statusMeta(status) {
  switch (status) {
    case 'success':
      return { label: '已完成', icon: 'check-circle', tone: 'done' }
    case 'error':
      return { label: '失败', icon: 'alert-circle', tone: 'error' }
    case 'running':
      return { label: '执行中', icon: 'refresh', tone: 'running' }
    case 'aborted':
      return { label: '已中止', icon: 'x-circle', tone: 'idle' }
    default:
      return { label: '空闲', icon: 'dot', tone: 'idle' }
  }
}

/**
 * 创建任务执行器
 * @param {object} store Pinia store 实例（含 task/running/errMsg 状态与 loadRecent action）
 * @returns {{ run: Function, stopPolling: Function }}
 */
export function createTaskRunner(store) {
  let pollTimer = null
  let lastSignalAt = 0

  function startPolling(taskId) {
    stopPolling()
    lastSignalAt = Date.now()
    pollTimer = setInterval(() => pollTask(taskId), POLL_INTERVAL)
    pollTask(taskId)
  }

  async function pollTask(taskId) {
    try {
      const t = await easytdxApi.task(taskId)
      const prev = store.task
      // 进度或日志有变化 → 刷新活跃时间戳（判定卡死用）
      if (!prev || prev.progress !== t.progress || (prev.logs?.length || 0) !== (t.logs?.length || 0)) {
        lastSignalAt = Date.now()
      } else if (Date.now() - lastSignalAt > TASK_IDLE_TIMEOUT) {
        stopPolling()
        store.running = false
        store.errMsg = '任务长时间无进展，可能已卡死。请中止后重试。'
        return
      }
      store.task = t
      if (t.status === 'success' || t.status === 'error') {
        stopPolling()
        store.running = false
        store.loadRecent()
      }
    } catch {
      /* 单次轮询失败不打断，等待下次重试 */
    }
  }

  function stopPolling() {
    if (pollTimer) {
      clearInterval(pollTimer)
      pollTimer = null
    }
  }

  /** 提交执行；返回是否成功发起 */
  async function run(functionId, params) {
    if (!functionId) return false
    store.errMsg = ''
    store.task = null
    store.running = true
    try {
      const r = await easytdxApi.run(functionId, { ...params })
      startPolling(r.task_id)
      return true
    } catch (e) {
      store.running = false
      store.errMsg = '提交失败：' + (e.message || e)
      return false
    }
  }

  return { run, stopPolling }
}
