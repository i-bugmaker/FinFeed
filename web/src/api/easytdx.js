import http from './client'

// easy-tdx 模块后端接口（FastAPI 路由前缀 /api/easytdx）
const easytdxApi = {
  // 功能注册表：分组 + 功能 + 参数 schema，供前端动态渲染
  meta: () => http.get('/easytdx/meta').then((r) => r.data),
  // 回测策略列表（含参数 schema）
  strategies: () => http.get('/easytdx/strategies').then((r) => r.data),
  // 提交一次功能调用，返回 { task_id, ... }
  run: (functionId, params) =>
    http.post('/easytdx/run', { function: functionId, params }).then((r) => r.data),
  // 轮询任务状态 / 日志 / 进度 / 结果
  task: (taskId) => http.get(`/easytdx/task/${taskId}`).then((r) => r.data),
  // 最近任务列表
  tasks: (limit = 20) =>
    http.get('/easytdx/tasks', { params: { limit } }).then((r) => r.data),
  // 文件类结果下载地址
  downloadUrl: (taskId) => `/api/easytdx/download/${taskId}`,
}

export default easytdxApi
