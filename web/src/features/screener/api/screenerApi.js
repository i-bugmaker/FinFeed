import http from '@/shared/api/client'

export const screenerApi = Object.freeze({
  config: () => http.get('/screener/config').then((response) => response.data),
  run: (params = {}) => http.post('/screener/run', params).then((response) => response.data),
  task: (taskId) => http.get(`/screener/task/${taskId}`).then((response) => response.data),
  tasks: (limit = 20) => http.get('/screener/tasks', { params: { limit } }).then((response) => response.data),
  compare: (a, b, technical = false, top = 200) =>
    http.post('/screener/compare', { a, b, technical, top }).then((response) => response.data),
  templates: () => http.get('/screener/templates').then((response) => response.data),
  saveTemplate: (name, request) =>
    http.post('/screener/templates', { name, request }).then((response) => response.data),
  deleteTemplate: (name) =>
    http.delete(`/screener/templates/${encodeURIComponent(name)}`).then((response) => response.data),
  evaluate: (payload = {}) =>
    http.post('/screener/evaluate', payload).then((response) => response.data),
})

export default screenerApi
