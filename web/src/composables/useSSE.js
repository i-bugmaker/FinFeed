import { onMounted, onUnmounted } from 'vue'
import { useAppStore } from '../store/app'

// 连接 /api/events，复用 FastAPI 桥接的 legacy SSE 通道。
// 收到 'news' 事件（type=new_news）时，把增量条目推入 store.pendingNews。
export function useSSE() {
  const store = useAppStore()
  let sawOffline = false
  let es = null

  function connect() {
    if (es) return
    es = new EventSource('/api/events')
    es.addEventListener('connected', () => {
      store.setLive(true)
      // 断线恢复：通知列表页重拉第一页（断线期间的新闻不会经 SSE 补送全部）
      if (sawOffline) {
        sawOffline = false
        store.markReconnect()
      }
    })
    es.addEventListener('news', (ev) => {
      try {
        const payload = JSON.parse(ev.data)
        if (payload && payload.type === 'new_news' && Array.isArray(payload.items)) {
          store.pushPending(payload.items, !!payload.truncated)
        }
      } catch (e) {
        /* ignore */
      }
    })
    es.onerror = () => {
      store.setLive(false)
      sawOffline = true
      // EventSource 会自动重连；此处仅标记离线
    }
  }

  function disconnect() {
    if (es) {
      es.close()
      es = null
    }
    store.setLive(false)
  }

  onMounted(connect)
  onUnmounted(disconnect)

  return { connect, disconnect }
}
