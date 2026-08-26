import http from '@/shared/api/client'

export const easytdxApi = Object.freeze({
  meta: () => http.get('/easytdx/meta').then((response) => response.data),
  strategies: () => http.get('/easytdx/strategies').then((response) => response.data),
  run: (functionId, params) =>
    http.post('/easytdx/run', { function: functionId, params }).then((response) => response.data),
  task: (taskId) => http.get(`/easytdx/task/${taskId}`).then((response) => response.data),
  tasks: (limit = 20) =>
    http.get('/easytdx/tasks', { params: { limit } }).then((response) => response.data),
  downloadUrl: (taskId) => `/api/easytdx/download/${taskId}`,

  // 盘面复盘仪表盘快捷数据（同步 + 后端 60s 缓存）
  dashboard: {
    overview: () =>
      http.get('/easytdx/dashboard/overview').then((response) => response.data),
    boards: (type, sort, top = 15) =>
      http
        .get('/easytdx/dashboard/boards', { params: { type, sort, top } })
        .then((response) => response.data),
    stocks: (list, top = 15) =>
      http
        .get('/easytdx/dashboard/stocks', { params: { list, top } })
        .then((response) => response.data),
    unusual: (count = 20) =>
      http
        .get('/easytdx/dashboard/unusual', { params: { count } })
        .then((response) => response.data),
  },
})

export default easytdxApi
