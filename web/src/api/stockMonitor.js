// 股票监控模块 API（/api/stock-monitor/*）
import http from '../shared/api/client'

const BASE = '/stock-monitor'

export const stockMonitorApi = {
  // ---- 监控列表管理 ----
  listStocks: () => http.get(`${BASE}/stocks`).then((r) => r.data),
  suggest: (q, limit = 8) =>
    http.get(`${BASE}/suggest`, { params: { q, limit } }).then((r) => r.data.suggestions || []),
  importText: (text) => http.post(`${BASE}/stocks`, { text }).then((r) => r.data),
  importImage: (file) => {
    const form = new FormData()
    form.append('file', file)
    return http.post(`${BASE}/stocks/import/image`, form, {
      headers: { 'Content-Type': 'multipart/form-data' },
      timeout: 120000,
    }).then((r) => r.data)
  },
  updateNote: (code, note) =>
    http.put(`${BASE}/stocks/${encodeURIComponent(code)}`, { note }).then((r) => r.data),
  deleteStock: (code) =>
    http.delete(`${BASE}/stocks/${encodeURIComponent(code)}`).then((r) => r.data),

  // ---- 舆情聚合 ----
  feed: (params) => http.get(`${BASE}/feed`, { params }).then((r) => r.data),
  refresh: () => http.post(`${BASE}/refresh`).then((r) => r.data),
  status: () => http.get(`${BASE}/status`).then((r) => r.data),

  // ---- AI 分析 ----
  analyze: (code) => http.post(`${BASE}/analyze/${encodeURIComponent(code)}`).then((r) => r.data),
  analysisTask: (id) => http.get(`${BASE}/analyze/task/${id}`).then((r) => r.data),
  analysisLatest: (code) =>
    http.get(`${BASE}/analyze/${encodeURIComponent(code)}/latest`).then((r) => r.data),
  analysisHistory: (code, limit = 10) =>
    http.get(`${BASE}/analyze/${encodeURIComponent(code)}/history`, { params: { limit } }).then((r) => r.data),
}

/**
 * 订阅股票舆情实时推送（SSE，事件名 feed）。
 * 返回取消订阅函数。onError 后由 EventSource 自动重连。
 */
export function subscribeStockFeed(codes, { onItems, onConnected, onError }) {
  const qs = codes && codes.length ? `?codes=${encodeURIComponent(codes.join(','))}` : ''
  const es = new EventSource(`/api/stock-monitor/feed/stream${qs}`)
  es.addEventListener('connected', (e) => {
    let payload = {}
    try { payload = JSON.parse(e.data) } catch { /* ignore */ }
    onConnected?.(payload)
  })
  es.addEventListener('feed', (e) => {
    try {
      const payload = JSON.parse(e.data)
      if (Array.isArray(payload.items)) onItems?.(payload.items, payload)
    } catch { /* 忽略坏帧 */ }
  })
  es.onerror = () => onError?.()
  return () => es.close()
}

export default stockMonitorApi
