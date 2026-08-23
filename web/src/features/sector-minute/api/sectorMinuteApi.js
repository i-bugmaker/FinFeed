import http from '@/shared/api/client'

const BASE_PATH = '/sector-minute'

export const sectorMinuteApi = Object.freeze({
  health: () => http.get(`${BASE_PATH}/health`).then((response) => response.data),
  refresh: () => http.post(`${BASE_PATH}/refresh`).then((response) => response.data),
  boards: (boardType) => http.get(`${BASE_PATH}/boards`, { params: { board_type: boardType } }).then((response) => response.data),
  indices: () => http.get(`${BASE_PATH}/indices`).then((response) => response.data),
  getSubscriptions: () => http.get(`${BASE_PATH}/subscriptions`).then((response) => response.data),
  setSubscriptions: (items) => http.post(`${BASE_PATH}/subscriptions`, { items }).then((response) => response.data),
  charts: (date = '') => http.get(`${BASE_PATH}/charts`, { params: { date: date || undefined } }).then((response) => response.data),
  stocks: (kw = '') => http.get(`${BASE_PATH}/stocks`, { params: { kw } }).then((response) => response.data),
})
