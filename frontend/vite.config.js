import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'

// API-ul Flask, prin proxy: interfața și API-ul sunt aceeași origine, deci
// backend-ul nu are nevoie de CORS (vezi backend/app.py)
const backend = `http://127.0.0.1:${process.env.DETOATE_PORT || 5000}`

export default defineConfig({
  plugins: [vue()],
  server: {
    port: 5173,
    strictPort: true,
    proxy: { '/api': backend },
  },
})
