import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5170,
    proxy: {
      '/api': {
        target: 'http://localhost:8001',
        changeOrigin: true,
        timeout: 0,       // タイムアウト無効（長時間の作曲に対応）
        proxyTimeout: 0,  // プロキシソケットのタイムアウト無効
      },
      '/audio': {
        target: 'http://localhost:8001',
        changeOrigin: true,
      },
    },
  },
})
