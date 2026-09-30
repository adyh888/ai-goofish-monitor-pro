import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'
import path from 'path'
import fs from 'fs'

// 读取项目根 .env 的 SERVER_PORT（默认 8000），保证前端 dev 代理与后端端口一致
function backendPort(): string {
  if (process.env.SERVER_PORT) return process.env.SERVER_PORT
  try {
    const env = fs.readFileSync(path.resolve(__dirname, '../.env'), 'utf-8')
    const match = env.match(/^SERVER_PORT\s*=\s*(\d+)/m)
    if (match) return match[1]
  } catch {
    // .env 不存在时使用默认端口
  }
  return '8000'
}

const port = backendPort()

// https://vite.dev/config/
export default defineConfig({
  plugins: [vue()],
  build: {
    outDir: path.resolve(__dirname, '../dist'),
    emptyOutDir: true,
  },
  resolve: {
    alias: {
      '@': path.resolve(__dirname, './src'),
    },
  },
  server: {
    proxy: {
      '/api': {
        target: `http://127.0.0.1:${port}`,
        changeOrigin: true,
      },
      '/auth': {
        target: `http://127.0.0.1:${port}`,
        changeOrigin: true,
      },
      '/ws': {
        target: `ws://127.0.0.1:${port}`,
        ws: true,
      },
    },
  },
})
