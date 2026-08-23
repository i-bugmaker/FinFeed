import http from '@/shared/api/client'

export const screenerApi = Object.freeze({
  config: () => http.get('/screener/config').then((response) => response.data),
  run: (params = {}) => http.post('/screener/run', params).then((response) => response.data),
  task: (taskId) => http.get(`/screener/task/${taskId}`).then((response) => response.data),
  tasks: (limit = 20) => http.get('/screener/tasks', { params: { limit } }).then((response) => response.data),
})

export default screenerApi
