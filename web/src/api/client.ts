// Compatibility facade. New feature code imports shared/api/client directly.
// 阶段2-d：本模块已 TS 化；新闻链路端点的返回类型来自 npm run gen:api
// 生成的 src/api/schema.d.ts（后端契约 ui/web_fastapi/schemas.py）。
import type { components } from '@/api/schema'
import http, { httpLlm } from '@/shared/api/client'
import { API_BASE_URL } from '@/shared/config/runtime'
import type { AxiosResponse } from 'axios'

type Schemas = components['schemas']
export type NewsItem = Schemas['NewsItemOut']
export type NewsList = Schemas['NewsListOut']
export type NewsDetail = Schemas['NewsDetailOut']
export type MutationResult = Schemas['MutationOut']

/** 新闻列表通用查询参数 */
export interface NewsQuery {
  page?: number
  page_size?: number
  keyword?: string
  source?: string
  sentiment?: string
  importance?: number
  [key: string]: unknown
}

export const api = {
  health: (): Promise<unknown> => http.get('/health').then((r) => r.data),
  stats: (): Promise<unknown> => http.get('/stats').then((r) => r.data),
  // 轻量全局运行态：最近成功抓取时间 + 离线告警，供状态栏高频轮询
  monitorStatus: (): Promise<unknown> => http.get('/monitor/status').then((r) => r.data),
  // 原「新闻流」(news) 已拆分为快讯(flash)与财经文章(articles)两个独立模块
  flash: (params: NewsQuery = {}): Promise<NewsList> =>
    http.get('/flash', { params }).then((r) => r.data),
  articles: (params: NewsQuery = {}): Promise<NewsList> =>
    http.get('/articles', { params }).then((r) => r.data),
  sentiment: (params: NewsQuery = {}): Promise<NewsList> =>
    http.get('/sentiment', { params }).then((r) => r.data),
  favorites: (params: NewsQuery = {}): Promise<NewsList> =>
    http.get('/favorites', { params }).then((r) => r.data),
  search: (q: string, limit = 100): Promise<Schemas['SearchOut']> =>
    http.get('/search', { params: { q, limit } }).then((r) => r.data),
  detail: (id: number): Promise<NewsDetail> =>
    http.get('/detail', { params: { id } }).then((r) => r.data),
  stockNames: (): Promise<Schemas['StockNamesOut']> =>
    http.get('/stock_names').then((r) => r.data),
  dateRange: (): Promise<Schemas['DateRangeOut']> =>
    http.get('/daterange').then((r) => r.data),
  exportNews: (format: string, opts: Record<string, unknown> = {}): Promise<AxiosResponse<Blob>> =>
    http
      .get('/export', { params: { format, ...opts }, responseType: 'blob' })
      .then((r) => r),
  downloadBlob,
  toggleFavorite: (id: number): Promise<MutationResult> =>
    http.post('/favorite', { id }).then((r) => r.data),
  markRead: (id: number, read = true): Promise<MutationResult> =>
    http.post('/read', { id, read }).then((r) => r.data),

  // LLM / 日历 / 市场 透传
  llm: (path: string, params?: unknown, config: Record<string, unknown> = {}): Promise<unknown> =>
    httpLlm.get('/llm' + path, { ...config, params }).then((r) => r.data),
  llmPost: (path: string, data?: unknown, config: Record<string, unknown> = {}): Promise<unknown> =>
    httpLlm.post('/llm' + path, data, config).then((r) => r.data),

  /**
   * 订阅 LLM 分析任务事件流（SSE）。
   * handlers: { onStage, onDelta, onReset, onDone, onError }
   * delta 事件携带模型增量文本；reset 表示清空半成品缓冲（后端流式回退时发出）。
   * 返回取消订阅函数（幂等）。
   */
  llmTaskStream(taskId: string, handlers: {
    onStage?: (d: any) => void
    onDelta?: (text: string) => void
    onReset?: () => void
    onDone?: (d: any) => void
    onError?: () => void
  } = {}) {
    const es = new EventSource(`${API_BASE_URL}/llm/task/stream?id=${encodeURIComponent(taskId)}`)
    const bind = (event: string, fn?: (d: any) => void) => {
      if (typeof fn !== 'function') return
      es.addEventListener(event, (e) => {
        try {
          fn(e.data ? JSON.parse(e.data) : {})
        } catch { /* 忽略单条坏帧 */ }
      })
    }
    bind('stage', handlers.onStage)
    bind('delta', (d) => handlers.onDelta?.(d.text || ''))
    bind('reset', () => handlers.onReset?.())
    bind('done', (d) => {
      handlers.onDone?.(d)
      es.close()
    })
    es.onerror = () => handlers.onError?.()
    return () => es.close()
  },
  // 模型配置列表（供 AI 分析选择调用哪个已配置的模型）
  providers: (): Promise<unknown> => httpLlm.get('/llm/providers').then((r) => r.data),

  /**
   * 轻量洞察任务（非新闻报告口径）：提交 → SSE 增量 → 任务查询取回全文。
   * 当前唯一场景：连板天梯「AI 分析」。
   */
  insightLimitUp: (payload: unknown): Promise<unknown> =>
    httpLlm.post('/llm/insight/limitup', payload).then((r) => r.data),
  insightTask: (id: string): Promise<unknown> =>
    httpLlm.get('/llm/insight/task', { params: { id } }).then((r) => r.data),
  insightCancel: (taskId: string): Promise<unknown> =>
    httpLlm.post('/llm/insight/cancel', { task_id: taskId }).then((r) => r.data),
  // 连板天地 AI 分析历史归档：列表 + 按 id 读取归档全文
  insightHistory: (limit = 20): Promise<unknown> =>
    httpLlm.get('/llm/insight/history', { params: { limit } }).then((r) => r.data),
  insightReport: (id: string): Promise<unknown> =>
    httpLlm.get('/llm/report', { params: { id } }).then((r) => r.data),
  insightStream(taskId: string, handlers: {
    onStage?: (d: any) => void
    onDelta?: (text: string) => void
    onReset?: () => void
    onDone?: (d: any) => void
    onError?: () => void
  } = {}) {
    const es = new EventSource(`${API_BASE_URL}/llm/insight/stream?id=${encodeURIComponent(taskId)}`)
    const bind = (event: string, fn?: (d: any) => void) => {
      if (typeof fn !== 'function') return
      es.addEventListener(event, (e) => {
        try {
          fn(e.data ? JSON.parse(e.data) : {})
        } catch { /* 忽略单条坏帧 */ }
      })
    }
    bind('stage', handlers.onStage)
    bind('delta', (d) => handlers.onDelta?.(d.text || ''))
    bind('reset', () => handlers.onReset?.())
    bind('done', (d) => {
      handlers.onDone?.(d)
      es.close()
    })
    es.onerror = () => handlers.onError?.()
    return () => es.close()
  },

  calendar: (path: string, params?: unknown): Promise<unknown> =>
    http.get('/calendar' + path, { params }).then((r) => r.data),
  market: (sub: string, params?: unknown): Promise<unknown> =>
    http.get('/market/' + sub, { params }).then((r) => r.data),
  marketAction: (params?: unknown): Promise<unknown> =>
    http.get('/market/action', { params }).then((r) => r.data),
}

export function downloadBlob(response: AxiosResponse<Blob>, fallbackName?: string) {
  const cd = (response.headers['content-disposition'] as string) || ''
  const m = cd.match(/filename="?([^"]+)"?/)
  const name = m ? decodeURIComponent(m[1]) : fallbackName
  const url = URL.createObjectURL(response.data)
  const a = document.createElement('a')
  a.href = url
  a.download = name || 'export'
  document.body.appendChild(a)
  a.click()
  a.remove()
  URL.revokeObjectURL(url)
}

export default http
