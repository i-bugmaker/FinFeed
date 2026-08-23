// 板块分时 —— API 客户端
import http from './client'

const BASE = '/sector-minute'

export const sectorMinuteApi = {
  // 模块运行状态（最后刷新时间 / 订阅数 / 错误 / server_date）
  health: () => http.get(`${BASE}/health`).then((r) => r.data),
  // 手动触发一轮后台刷新
  refresh: () => http.post(`${BASE}/refresh`).then((r) => r.data),
  // 指定类型板块列表（hy 行业 / hy2 二级行业 / gn 概念 / fg 风格 / dq 地区）
  boards: (boardType) => http.get(`${BASE}/boards`, { params: { board_type: boardType } }).then((r) => r.data),
  // 常见指数池（宽基 / 风格）
  indices: () => http.get(`${BASE}/indices`).then((r) => r.data),
  // 当前对比标的列表
  getSubscriptions: () => http.get(`${BASE}/subscriptions`).then((r) => r.data),
  // 整体替换对比标的列表
  setSubscriptions: (items) => http.post(`${BASE}/subscriptions`, { items }).then((r) => r.data),
  // 订阅标的分时图集合；date 为 YYYY-MM-DD（历史交易日）或空（今天/实时）
  charts: (date = '') => http.get(`${BASE}/charts`, { params: { date: date || undefined } }).then((r) => r.data),
  // 个股池搜索（代码 / 名称模糊）
  stocks: (kw = '') => http.get(`${BASE}/stocks`, { params: { kw } }).then((r) => r.data),
}
