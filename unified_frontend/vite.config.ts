import path from "path"
import react from "@vitejs/plugin-react"
import { defineConfig, loadEnv } from "vite"
import { inspectAttr } from 'kimi-plugin-inspect-react'

export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd(), '')
  const backendTarget = env.VITE_BACKEND_TARGET || 'http://127.0.0.1:5000'
  const aivisionTarget = env.VITE_AIVISION_BACKEND_TARGET || 'http://127.0.0.1:7862'
  const securityVlmTarget = env.VITE_SECURITY_VLM_BACKEND_TARGET || 'http://127.0.0.1:8000'
  const devPort = Number(env.VITE_DEV_PORT || 3000)

  return {
    base: './',
    plugins: [inspectAttr(), react()],
    resolve: {
      alias: {
        '@': path.resolve(__dirname, './src'),
      },
    },
    server: {
      host: '0.0.0.0',
      allowedHosts: ['aicv.fudar.com'],
      port: devPort,
      strictPort: true,
      proxy: {
        '/aivision': {
          target: aivisionTarget,
          changeOrigin: true,
          secure: false,
          ws: false,
          rewrite: (proxyPath) => proxyPath.replace(/^\/aivision/, '') || '/',
        },
        '/api/aivision': {
          target: aivisionTarget,
          changeOrigin: true,
          secure: false,
          ws: false,
        },
        '/api/ai': {
          target: aivisionTarget,
          changeOrigin: true,
          secure: false,
          ws: false,
        },
        '/security-vlm': {
          target: securityVlmTarget,
          changeOrigin: true,
          secure: false,
          ws: false,
          rewrite: (proxyPath) => proxyPath.replace(/^\/security-vlm/, '') || '/',
        },
        '/api': {
          target: backendTarget,
          changeOrigin: true,
          secure: false,
          ws: false,
        },
        '/ws': {
          target: backendTarget,
          changeOrigin: true,
          secure: false,
          ws: true,
        },
      },
    },
    preview: {
      host: '0.0.0.0',
      allowedHosts: ['aicv.fudar.com'],
      port: devPort,
      strictPort: true,
    },
  }
})
