import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'

// 构建产物输出到 dist/，由 FastAPI 静态托管（见 finfeed/ui/web_fastapi/app.py）。
// 开发态通过 proxy 把 /api 转发到 8866 的 FastAPI 服务。
export default defineConfig({
  plugins: [vue()],
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
      },
      '/docs': { target: 'http://127.0.0.1:8866', changeOrigin: true, agent: false, timeout: 30000, proxyTimeout: 30000 },
      '/openapi.json': { target: 'http://127.0.0.1:8866', changeOrigin: true, agent: false, timeout: 30000, proxyTimeout: 30000 },
    },
  },
  build: {
    outDir: 'dist',
    emptyOutDir: true,
    chunkSizeWarningLimit: 1200,
  },
})
