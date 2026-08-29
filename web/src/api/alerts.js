import http from '@/shared/api/client'

const BASE = '/alerts'

/** 告警推送配置 API（/api/alerts/*） */
export const alertsApi = {
  // 渠道类型元数据
  channels: () => http.get(`${BASE}/channels`).then((r) => r.data),

  // Webhook 渠道 CRUD
  listWebhooks: () => http.get(`${BASE}/webhooks`).then((r) => r.data),
  createWebhook: (data) => http.post(`${BASE}/webhooks`, data).then((r) => r.data),
  updateWebhook: (id, data) => http.put(`${BASE}/webhooks/${id}`, data).then((r) => r.data),
  deleteWebhook: (id) => http.delete(`${BASE}/webhooks/${id}`).then((r) => r.data),
  testWebhook: (id) => http.post(`${BASE}/webhooks/${id}/test`, null, { timeout: 20000 }).then((r) => r.data),

  // 全局设置
  getSettings: () => http.get(`${BASE}/settings`).then((r) => r.data),
  updateSettings: (data) => http.put(`${BASE}/settings`, data).then((r) => r.data),

  // 主题订阅
  listTopics: () => http.get(`${BASE}/topics`).then((r) => r.data),
  createTopic: (data) => http.post(`${BASE}/topics`, data).then((r) => r.data),
  updateTopic: (id, data) => http.put(`${BASE}/topics/${id}`, data).then((r) => r.data),
  deleteTopic: (id) => http.delete(`${BASE}/topics/${id}`).then((r) => r.data),

  // 自选股订阅（只读视图）
  watchlist: () => http.get(`${BASE}/watchlist`).then((r) => r.data),

  // 运行状态
  regime: () => http.get(`${BASE}/regime`).then((r) => r.data),
  logs: (limit = 30) => http.get(`${BASE}/logs`, { params: { limit } }).then((r) => r.data),
  calibration: () => http.get(`${BASE}/calibration`).then((r) => r.data),
  runCalibration: () => http.post(`${BASE}/calibration/run`).then((r) => r.data),
}
