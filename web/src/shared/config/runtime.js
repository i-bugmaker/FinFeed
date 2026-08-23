/** Runtime configuration shared by every browser-facing adapter.
 *
 * Keep environment decisions here instead of scattering `import.meta.env.DEV`
 * throughout feature code. Features only depend on the API client.
 */
export const API_BASE_URL = import.meta.env.DEV ? 'http://127.0.0.1:8866/api' : '/api'

export const API_TIMEOUTS = Object.freeze({
  default: 20_000,
  longRunning: 120_000,
})
