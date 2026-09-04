import http from '@/shared/api/client'

const BASE = '/alerts'

/** 告警推送配置 API（/api/alerts/*） */
export const alertsApi = {
  // 渠道类型元数据
  channels: (): Promise<unknown> => http.get(`${BASE}/channels`).then((r) => r.data),

  // Webhook 渠道 CRUD
  listWebhooks: (): Promise<unknown> => http.get(`${BASE}/webhooks`).then((r) => r.data),
  createWebhook: (data: unknown): Promise<unknown> =>
    http.post(`${BASE}/webhooks`, data).then((r) => r.data),
  updateWebhook: (id: string | number, data: unknown): Promise<unknown> =>
    http.put(`${BASE}/webhooks/${id}`, data).then((r) => r.data),
  deleteWebhook: (id: string | number): Promise<unknown> =>
    http.delete(`${BASE}/webhooks/${id}`).then((r) => r.data),
  testWebhook: (id: string | number): Promise<unknown> =>
    http.post(`${BASE}/webhooks/${id}/test`, null, { timeout: 20000 }).then((r) => r.data),

  // 全局设置
  getSettings: (): Promise<unknown> => http.get(`${BASE}/settings`).then((r) => r.data),
  updateSettings: (data: unknown): Promise<unknown> =>
    http.put(`${BASE}/settings`, data).then((r) => r.data),

  // 主题订阅
  listTopics: (): Promise<unknown> => http.get(`${BASE}/topics`).then((r) => r.data),
  createTopic: (data: unknown): Promise<unknown> =>
    http.post(`${BASE}/topics`, data).then((r) => r.data),
  updateTopic: (id: string | number, data: unknown): Promise<unknown> =>
    http.put(`${BASE}/topics/${id}`, data).then((r) => r.data),
  deleteTopic: (id: string | number): Promise<unknown> =>
    http.delete(`${BASE}/topics/${id}`).then((r) => r.data),

  // 自选股订阅（只读视图）
  watchlist: (): Promise<unknown> => http.get(`${BASE}/watchlist`).then((r) => r.data),

  // 运行状态
  regime: (): Promise<unknown> => http.get(`${BASE}/regime`).then((r) => r.data),
  logs: (limit = 30): Promise<unknown> =>
    http.get(`${BASE}/logs`, { params: { limit } }).then((r) => r.data),
  calibration: (): Promise<unknown> => http.get(`${BASE}/calibration`).then((r) => r.data),
  runCalibration: (): Promise<unknown> => http.post(`${BASE}/calibration/run`).then((r) => r.data),
}
