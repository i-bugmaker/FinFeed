// 股票监控模块 API（/api/stock-monitor/*）
import http from '../shared/api/client'

const BASE = '/stock-monitor'

/** 监控列表条目（feed 聚合返回的轻量结构） */
export interface StockFeedItem {
  code?: string
  name?: string
  [key: string]: unknown
}

export const stockMonitorApi = {
  // ---- 监控列表管理 ----
  listStocks: (): Promise<unknown> => http.get(`${BASE}/stocks`).then((r) => r.data),
  suggest: (q: string, limit = 8): Promise<unknown[]> =>
    http.get(`${BASE}/suggest`, { params: { q, limit } }).then((r) => r.data.suggestions || []),
  importText: (text: string): Promise<unknown> =>
    http.post(`${BASE}/stocks`, { text }).then((r) => r.data),
  importImage: (file: File): Promise<unknown> => {
    const form = new FormData()
    form.append('file', file)
    return http.post(`${BASE}/stocks/import/image`, form, {
      headers: { 'Content-Type': 'multipart/form-data' },
      timeout: 120000,
    }).then((r) => r.data)
  },
  updateNote: (code: string, note: string): Promise<unknown> =>
    http.put(`${BASE}/stocks/${encodeURIComponent(code)}`, { note }).then((r) => r.data),
  deleteStock: (code: string): Promise<unknown> =>
    http.delete(`${BASE}/stocks/${encodeURIComponent(code)}`).then((r) => r.data),

  // ---- 监控信息聚合 ----
  feed: (params?: Record<string, unknown>): Promise<unknown> =>
    http.get(`${BASE}/feed`, { params }).then((r) => r.data),
  refresh: (): Promise<unknown> => http.post(`${BASE}/refresh`).then((r) => r.data),
  status: (): Promise<unknown> => http.get(`${BASE}/status`).then((r) => r.data),

  // ---- AI 分析 ----
  analyze: (code: string): Promise<unknown> =>
    http.post(`${BASE}/analyze/${encodeURIComponent(code)}`).then((r) => r.data),
  analysisTask: (id: string | number): Promise<unknown> =>
    http.get(`${BASE}/analyze/task/${id}`).then((r) => r.data),
  analysisLatest: (code: string): Promise<unknown> =>
    http.get(`${BASE}/analyze/${encodeURIComponent(code)}/latest`).then((r) => r.data),
  analysisHistory: (code: string, limit = 10): Promise<unknown> =>
    http.get(`${BASE}/analyze/${encodeURIComponent(code)}/history`, { params: { limit } })
      .then((r) => r.data),
}

/**
 * 订阅股票舆情实时推送（SSE，事件名 feed）。
 * 返回取消订阅函数。onError 后由 EventSource 自动重连。
 */
export function subscribeStockFeed(
  codes: string[],
  handlers: {
    onItems?: (items: StockFeedItem[], payload: any) => void
    onConnected?: (payload: any) => void
    onError?: () => void
  },
) {
  const qs = codes && codes.length ? `?codes=${encodeURIComponent(codes.join(','))}` : ''
  const es = new EventSource(`/api/stock-monitor/feed/stream${qs}`)
  es.addEventListener('connected', (e) => {
    let payload: any = {}
    try { payload = JSON.parse(e.data) } catch { /* ignore */ }
    handlers.onConnected?.(payload)
  })
  es.addEventListener('feed', (e) => {
    try {
      const payload = JSON.parse(e.data)
      if (Array.isArray(payload.items)) handlers.onItems?.(payload.items, payload)
    } catch { /* 忽略坏帧 */ }
  })
  es.onerror = () => handlers.onError?.()
  return () => es.close()
}

export default stockMonitorApi
