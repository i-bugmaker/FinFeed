import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'
import { fileURLToPath, URL } from 'node:url'

// dev server 韧性：HMR/代理的裸 socket 在对端半关闭时抛 ECONNRESET/EPIPE，
// 无人监听 error 事件会以 uncaughtException 直接杀死 Vite 进程。
// 这里只吞掉连接类错误（对开发无影响），其余照常抛出。
process.on('uncaughtException', (err) => {
  if (err && (err.code === 'ECONNRESET' || err.code === 'EPIPE')) {
    console.warn('[vite] ignored socket error:', err.code)
    return
  }
  throw err
})

// 构建产物输出到 dist/，由 FastAPI 静态托管（见 finfeed/ui/web_fastapi/app.py）。
// 开发态通过 proxy 把 /api 转发到 8866 的 FastAPI 服务。
export default defineConfig({
  plugins: [vue()],
  resolve: {
    alias: { '@': fileURLToPath(new URL('./src', import.meta.url)) },
  },
  base: './',
  server: {
    port: 5173,
    // target 用 127.0.0.1（IPv4）而非 localhost：Node 在 Windows 上默认把 localhost
    // 解析为 ::1（IPv6），而后端只监听 IPv4，会导致浏览器里所有 /api 请求 Network Error。
    // agent: false —— 关闭代理的 keep-alive 连接复用：uvicorn 会按 keep-alive 超时
    // 半关闭空闲 socket，http-proxy 若复用该 socket 会导致请求挂起 / ECONNRESET
    //（表现为「点击执行没反应」「功能清单加载失败」），并发请求下尤为明显。
    proxy: {
      '/api': {
        target: 'http://127.0.0.1:8866',
        changeOrigin: true,
        agent: false, // 每次新建连接，规避 uvicorn 半关闭 socket 被复用的挂起/重置
        timeout: 30000,
        proxyTimeout: 30000,
        // uvicorn 半关闭 socket 仍可能在 read 侧抛 ECONNRESET；不挂 error 处理器
        // 会以 unhandled error 直接杀死 Vite 进程，这里降级为日志
        configure: (proxy) => proxy.on('error', (err, req, res) => {
          console.warn('[vite-proxy] /api error:', err.code || err.message)
          if (res && !res.headersSent) res.writeHead(502).end()
          else if (res?.socket) res.socket.destroy()
        }),
      },
      '/docs': { target: 'http://127.0.0.1:8866', changeOrigin: true, agent: false, timeout: 30000, proxyTimeout: 30000 },
      '/openapi.json': { target: 'http://127.0.0.1:8866', changeOrigin: true, agent: false, timeout: 30000, proxyTimeout: 30000 },
    },
  },
  build: {
    outDir: 'dist',
    emptyOutDir: true,
    chunkSizeWarningLimit: 1200,
    rollupOptions: {
      output: {
        // 把体积大、更新频率低的第三方库拆成独立 chunk：
        // ① 命中浏览器长期缓存，改业务代码时无需重新下载；
        // ② 与业务代码并行加载，降低首屏等待。
        manualChunks(id) {
          if (!id.includes('node_modules')) return
          if (id.includes('echarts') || id.includes('zrender')) return 'echarts'
          if (id.includes('vue') || id.includes('pinia') || id.includes('vue-router')) return 'vue-vendor'
          return 'vendor'
        },
      },
    },
  },
})
