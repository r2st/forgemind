import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'

// Local-dev proxy target.
//
// Inside Docker the frontend is served by nginx (see frontend/nginx.conf),
// which proxies /api/ to the `api-gateway` service on the compose network.
// When you run `npm run dev` on the host, that hostname does not resolve,
// so we proxy to the host-exposed port instead: docker-compose maps
// api-gateway to 8080:8000, so http://localhost:8080 is the right target.
//
// Override with VITE_API_URL if your api-gateway is somewhere else.
const API_TARGET = process.env.VITE_API_URL || 'http://localhost:8080'

export default defineConfig({
  plugins: [vue()],
  server: {
    host: '0.0.0.0',
    port: 5173,
    proxy: {
      '/api': {
        target: API_TARGET,
        changeOrigin: true,
      },
    },
  },
})
