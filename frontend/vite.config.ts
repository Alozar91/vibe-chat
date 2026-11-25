import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'
import path from 'node:path'

// https://vite.dev/config/
export default defineConfig(({ mode }) => ({
  plugins: [react(), tailwindcss()],
  // деплой под подпуть (§13, системный nginx → location /chat): VITE_BASE_PATH=/chat/
  // при сборке; локально (dev и build) — корень '/'
  base: mode === 'production' ? (process.env.VITE_BASE_PATH ?? '/') : '/',
  resolve: {
    alias: {
      '@': path.resolve(__dirname, './src'),
    },
  },
  server: {
    proxy: {
      // dev: REST и WS — через vite proxy на backend (Docs/concept.md §13).
      // Порт бэкенда переопределяется (8010 — исторический локальный dev-порт,
      // 8002 — порт, на котором ходит мобильный dev-стенд):
      //   VITE_API_PROXY=http://localhost:8002 npm run dev
      '/api/v1': {
        target: process.env.VITE_API_PROXY ?? 'http://localhost:8010',
        ws: true,
      },
    },
  },
}))
