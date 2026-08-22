import http from './client'

// 智能选股模块后端接口（FastAPI 路由前缀 /api/screener）
const screenerApi = {
  // 评分方法论与配置权重
  config: () => http.get('/screener/config').then((r) => r.data),
  // 提交一次选股任务，返回 { task_id, status, label }
  run: (params = {}) => http.post('/screener/run', params).then((r) => r.data),
  // 轮询任务状态 / 进度 / 结果
  task: (taskId) => http.get(`/screener/task/${taskId}`).then((r) => r.data),
  // 最近任务列表
  tasks: (limit = 20) => http.get('/screener/tasks', { params: { limit } }).then((r) => r.data),
}

export default screenerApi
