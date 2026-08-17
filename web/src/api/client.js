import axios from 'axios'

// 开发态由 vite proxy 转发；生产态由 FastAPI 同源托管，base 为空即可。
const http = axios.create({
  baseURL: '/api',
  timeout: 20000,
})

http.interceptors.response.use(
  (r) => r,
  (err) => {
    const data = err.response && err.response.data
    if (data && data.error) err.message = data.error
    return Promise.reject(err)
  },
)

// LLM 推理（chat / analyze / report / provider test）经常超过 20s，
// 单独走长超时实例，避免「timeout of 20000ms exceeded」误导为服务端故障。
const httpLlm = axios.create({
  baseURL: '/api',
  timeout: 120000,
})
httpLlm.interceptors.response.use(
  (r) => r,
  (err) => {
    const data = err.response && err.response.data
    if (data && data.error) err.message = data.error
    return Promise.reject(err)
  },
)

export const api = {
  health: () => http.get('/health').then((r) => r.data),
  stats: () => http.get('/stats').then((r) => r.data),
  // 轻量全局运行态：最近成功抓取时间 + 离线告警，供状态栏高频轮询
  monitorStatus: () => http.get('/monitor/status').then((r) => r.data),
  // 原「新闻流」(news) 已拆分为快讯(flash)与财经文章(articles)两个独立模块
  flash: (params) => http.get('/flash', { params }).then((r) => r.data),
  articles: (params) => http.get('/articles', { params }).then((r) => r.data),
  sentiment: (params) => http.get('/sentiment', { params }).then((r) => r.data),
  favorites: (params) => http.get('/favorites', { params }).then((r) => r.data),
  search: (q, limit = 100) => http.get('/search', { params: { q, limit } }).then((r) => r.data),
  detail: (id) => http.get('/detail', { params: { id } }).then((r) => r.data),
  stockNames: () => http.get('/stock_names').then((r) => r.data),
  dateRange: () => http.get('/daterange').then((r) => r.data),
  exportNews: (format, opts = {}) =>
    http
      .get('/export', { params: { format, ...opts }, responseType: 'blob' })
      .then((r) => r),
  downloadBlob,
  toggleFavorite: (id) => http.post('/favorite', { id }).then((r) => r.data),
  markRead: (id, read = true) => http.post('/read', { id, read }).then((r) => r.data),

  // LLM / 日历 / 市场 透传
  llm: (path, params, config = {}) =>
    httpLlm.get('/llm' + path, { ...config, params }).then((r) => r.data),
  llmPost: (path, data, config = {}) =>
    httpLlm.post('/llm' + path, data, config).then((r) => r.data),
  calendar: (path, params) => http.get('/calendar' + path, { params }).then((r) => r.data),
  market: (sub, params) => http.get('/market/' + sub, { params }).then((r) => r.data),
  marketAction: (params) => http.get('/market/action', { params }).then((r) => r.data),
}

export function downloadBlob(response, fallbackName) {
  const cd = response.headers['content-disposition'] || ''
  const m = cd.match(/filename="?([^"]+)"?/)
  const name = m ? decodeURIComponent(m[1]) : fallbackName
  const url = URL.createObjectURL(response.data)
  const a = document.createElement('a')
  a.href = url
  a.download = name
  document.body.appendChild(a)
  a.click()
  a.remove()
  URL.revokeObjectURL(url)
}

export default http
