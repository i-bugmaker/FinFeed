import axios from 'axios'
import { API_BASE_URL, API_TIMEOUTS } from '@/shared/config/runtime'

/** A stable error shape for views and stores, independent of Axios internals. */
export class ApiError extends Error {
  constructor(message, { code = 'REQUEST_FAILED', status = 0, cause } = {}) {
    super(message)
    this.name = 'ApiError'
    this.code = code
    this.status = status
    this.cause = cause
  }
}

function errorMessage(data, fallback) {
  if (typeof data?.error === 'string') return data.error
  if (typeof data?.detail === 'string') return data.detail
  if (typeof data?.message === 'string') return data.message
  if (typeof data?.error?.message === 'string') return data.error.message
  return fallback || '请求失败，请稍后重试'
}

function normalizeError(error) {
  if (error instanceof ApiError) return error
  const response = error.response
  return new ApiError(errorMessage(response?.data, error.message), {
    code: response?.data?.error?.code || error.code,
    status: response?.status,
    cause: error,
  })
}

function createHttpClient(timeout) {
  const client = axios.create({ baseURL: API_BASE_URL, timeout })
  client.interceptors.response.use(
    (response) => response,
    (error) => Promise.reject(normalizeError(error)),
  )
  return client
}

const http = createHttpClient(API_TIMEOUTS.default)
const httpLlm = createHttpClient(API_TIMEOUTS.longRunning)

// GET requests are idempotent. Retrying only connection-level failures keeps
// interactive pages resilient without risking duplicate mutations.
http.interceptors.response.use(undefined, (error) => {
  const config = error.cause?.config
  const retry = (config?._retryCount || 0) + 1
  const isNetworkError = !error.status && /network|socket|reset|timeout/i.test(error.message)
  if (config?.method === 'get' && isNetworkError && retry <= 2) {
    config._retryCount = retry
    return new Promise((resolve) => setTimeout(resolve, 600 * retry)).then(() => http(config))
  }
  return Promise.reject(error)
})

export { httpLlm }
export default http
