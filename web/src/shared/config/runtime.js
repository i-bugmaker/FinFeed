/** Runtime configuration shared by every browser-facing adapter.
 *
 * Keep environment decisions here instead of scattering `import.meta.env.DEV`
 * throughout feature code. Features only depend on the API client.
 *
 * DEV 与生产统一走相对路径 '/api'：
 *   * 生产 —— FastAPI 同源托管前端，'/api' 即后端；
 *   * DEV  —— 请求经 vite.config.js 的 proxy 转发到 127.0.0.1:8866。
 *     该 proxy 针对 Windows localhost→IPv6 解析错误、uvicorn keep-alive
 *     半关闭 socket 复用挂起等问题做了专门处理（agent:false + error 降级），
 *     直连绝对 URL 会绕过这层防护，导致请求挂起/重置，切勿回退。
 */
export const API_BASE_URL = '/api'

export const API_TIMEOUTS = Object.freeze({
  default: 20_000,
  longRunning: 120_000,
})
