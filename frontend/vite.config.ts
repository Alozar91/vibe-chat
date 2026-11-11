import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

// https://vite.dev/config/
export default defineConfig({
  plugins: [react()],
  server: {
    proxy: {
      // dev: REST и WS — через vite proxy на backend (Docs/concept.md §13)
      '/api/v1': {
        target: 'http://localhost:8000',
        ws: true,
      },
    },
  },
})
