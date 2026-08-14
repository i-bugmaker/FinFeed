import { ref, onUnmounted } from 'vue'

/**
 * useMarketSocket —— 行情 WebSocket 客户端 composable
 *
 * 负责的健壮性要点：
 *  - **断线重连**：指数退避（base=1s，×2 递增，上限 30s）+ 随机抖动，避免重连风暴；
 *    连接成功即重置退避计数。无限重试（行情通道应常驻）。
 *  - **心跳保活**：每 15s 向服务端发送 ping；同时响应服务端下发的 ping（回 pong）。
 *    若超过 40s 未收到任何消息（含服务端心跳），判定通道僵死并强制重连。
 *  - **消息解析**：约定 JSON 文本协议，按 type 分发（hello / snapshot / alert / ping / pong）。
 *    非法 JSON 或未知类型一律忽略，绝不抛错中断连接。
 *  - **异常恢复**：onclose / onerror 统一进入重连流程；发送失败不阻塞。
 *
 * 返回响应式状态：connected / data / alerts / lastUpdate / error / reconnectAttempts，
 * 以及 close() 主动断开。
 */
export function useMarketSocket({ autoConnect = true } = {}) {
  const connected = ref(false)
  const connecting = ref(false)
  const data = ref(null)
  const alerts = ref([])
  const lastUpdate = ref(0)
  const error = ref('')
  const reconnectAttempts = ref(0)

  let ws = null
  let reconnectTimer = null
  let heartbeatTimer = null
  let watchdogTimer = null
  let lastMsgTs = 0
  let closedByUser = false

  const HEARTBEAT = 15000
  const DEAD_TIMEOUT = 40000
  const MAX_BACKOFF = 30000

  function buildUrl() {
    const proto = location.protocol === 'https:' ? 'wss' : 'ws'
    return `${proto}://${location.host}/ws/market`
  }

  function send(obj) {
    if (ws && ws.readyState === WebSocket.OPEN) {
      try {
        ws.send(JSON.stringify(obj))
      } catch (e) {
        /* 发送失败不阻塞 */
      }
    }
  }

  function handleMessage(ev) {
    lastMsgTs = Date.now()
    let msg
    try {
      msg = JSON.parse(ev.data)
    } catch (e) {
      return // 非法 JSON 忽略
    }
    if (!msg || typeof msg !== 'object') return
    switch (msg.type) {
      case 'hello':
        break
      case 'snapshot':
        data.value = msg.data || null
        lastUpdate.value = Date.now()
        break
      case 'alert':
        if (msg.data) {
          alerts.value.unshift(msg.data)
          if (alerts.value.length > 50) alerts.value.pop()
        }
        break
      case 'ping':
        // 服务端探活，立即应答 pong
        send({ type: 'pong' })
        break
      case 'pong':
        // 对端对我们 ping 的应答
        break
      default:
        break
    }
  }

  function onOpen() {
    connected.value = true
    connecting.value = false
    reconnectAttempts.value = 0
    error.value = ''
    lastMsgTs = Date.now()
    // 启动心跳
    clearInterval(heartbeatTimer)
    heartbeatTimer = setInterval(() => {
      send({ type: 'ping' })
    }, HEARTBEAT)
    // 启动看门狗：长时间无消息则强制重连
    clearInterval(watchdogTimer)
    watchdogTimer = setInterval(() => {
      if (Date.now() - lastMsgTs > DEAD_TIMEOUT) {
        // 僵死：强制断开触发 onclose -> 重连
        forceReconnect('心跳超时，通道疑似僵死')
      }
    }, 10000)
  }

  function onClose() {
    connected.value = false
    connecting.value = false
    clearInterval(heartbeatTimer)
    clearInterval(watchdogTimer)
    if (closedByUser) return
    scheduleReconnect()
  }

  function onError(err) {
    error.value = err && err.message ? err.message : 'WebSocket 错误'
    // onclose 会随后触发，统一走重连
  }

  function scheduleReconnect() {
    if (reconnectTimer) return
    const attempt = reconnectAttempts.value
    const backoff = Math.min(MAX_BACKOFF, 1000 * 2 ** attempt)
    const jitter = Math.floor(Math.random() * 500)
    const delay = backoff + jitter
    reconnectAttempts.value = attempt + 1
    reconnectTimer = setTimeout(() => {
      reconnectTimer = null
      connect()
    }, delay)
  }

  function forceReconnect(reason) {
    error.value = reason || '强制重连'
    try {
      if (ws) ws.close()
    } catch (e) {
      /* noop */
    }
  }

  function connect() {
    if (ws && (ws.readyState === WebSocket.OPEN || ws.readyState === WebSocket.CONNECTING)) {
      return
    }
    closedByUser = false
    connecting.value = true
    let socket
    try {
      socket = new WebSocket(buildUrl())
    } catch (e) {
      connecting.value = false
      error.value = e.message || 'WebSocket 构造失败'
      scheduleReconnect()
      return
    }
    ws = socket
    ws.onopen = onOpen
    ws.onmessage = handleMessage
    ws.onclose = onClose
    ws.onerror = onError
  }

  function close() {
    closedByUser = true
    if (reconnectTimer) {
      clearTimeout(reconnectTimer)
      reconnectTimer = null
    }
    clearInterval(heartbeatTimer)
    clearInterval(watchdogTimer)
    if (ws) {
      try {
        ws.close()
      } catch (e) {
        /* noop */
      }
      ws = null
    }
    connected.value = false
  }

  onUnmounted(() => {
    close()
  })

  if (autoConnect) connect()

  return {
    connected,
    connecting,
    data,
    alerts,
    lastUpdate,
    error,
    reconnectAttempts,
    connect,
    close,
  }
}
