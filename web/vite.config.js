import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'

// 构建产物输出到 dist/，由 FastAPI 静态托管（见 finfeed/ui/web_fastapi/app.py）。
// 开发态通过 proxy 把 /api 转发到 8866 的 FastAPI 服务。
export default defineConfig({
  plugins: [vue()],
  base: './',
  server: {
    port: 5173,
    proxy: {
      '/api': 'http://localhost:8866',
      '/docs': 'http://localhost:8866',
      '/openapi.json': 'http://localhost:8866',
    },
  },
  build: {
    outDir: 'dist',
    emptyOutDir: true,
    chunkSizeWarningLimit: 1200,
  },
})
