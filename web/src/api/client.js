import axios from 'axios'

// 开发态直连后端（绕开 vite proxy 在 Windows 下 http-proxy 的并发 ECONNRESET bug，
// 后端已开放 CORS allow_origins=*）；生产态由 FastAPI 同源托管，base 为空即可。
const API_BASE = import.meta.env.DEV ? 'http://127.0.0.1:8866/api' : '/api'

const http = axios.create({
  baseURL: API_BASE,
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

// GET 自动重试：本机安全软件/代理可能对本地回环连接随机 RST（ConnectionReset），
// 网络层错误（无 HTTP 响应）时按 0.6s/1.2s 重试 2 次，吸收偶发失败。
// 仅对 GET 生效——POST 可能非幂等（交易/删除类），不自动重试。
http.interceptors.response.use(
  (r) => r,
  (err) => {
    const cfg = err.config
    if (!cfg || cfg.method !== 'get') return Promise.reject(err)
    const retry = (cfg._retryCount || 0) + 1
    // 无 HTTP 响应（网络层错误：RST / ECONNRESET / socket hang up / Network Error）才重试
    const isNetworkErr = !err.response && (err.code === 'ECONNABORTED' || /network|socket|reset/i.test(err.message || ''))
    if (isNetworkErr && retry <= 2) {
      cfg._retryCount = retry
      return new Promise((resolve) => setTimeout(resolve, 600 * retry)).then(() => http(cfg))
    }
    return Promise.reject(err)
  },
)

// LLM 推理（chat / analyze / report / provider test）经常超过 20s，
// 单独走长超时实例，避免「timeout of 20000ms exceeded」误导为服务端故障。
const httpLlm = axios.create({
  baseURL: API_BASE,
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
