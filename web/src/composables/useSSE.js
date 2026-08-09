import { onMounted, onUnmounted } from 'vue'
import { useAppStore } from '../store/app'

// 连接 /api/events，复用 FastAPI 桥接的 legacy SSE 通道。
// 收到 'news' 事件（type=new_news）时，把增量条目推入 store.pendingNews。
export function useSSE() {
  const store = useAppStore()
  let es = null

  function connect() {
    if (es) return
    es = new EventSource('/api/events')
    es.addEventListener('connected', () => store.setLive(true))
    es.addEventListener('news', (ev) => {
      try {
        const payload = JSON.parse(ev.data)
        if (payload && payload.type === 'new_news' && Array.isArray(payload.items)) {
          store.pushPending(payload.items)
        }
      } catch (e) {
        /* ignore */
      }
    })
    es.onerror = () => {
      store.setLive(false)
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
