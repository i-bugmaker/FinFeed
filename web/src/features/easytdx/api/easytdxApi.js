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
})

export default easytdxApi
