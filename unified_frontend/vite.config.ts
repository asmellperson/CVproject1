// 文件说明：实现配置相关的基础能力。
// 数据流：接收属性、状态或响应数据，并将结果交给组件、接口层或测试断言。

import path from "path"
import react from "@vitejs/plugin-react"
import { defineConfig, loadEnv } from "vite"
import { inspectAttr } from 'kimi-plugin-inspect-react'

export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd(), '')
  const backendTarget = env.VITE_BACKEND_TARGET || 'http://127.0.0.1:5000'
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
          target: backendTarget,
          changeOrigin: true,
          secure: false,
          ws: false,
        },
        '/api/aivision': {
          target: backendTarget,
          changeOrigin: true,
          secure: false,
          ws: false,
        },
        '/api/ai': {
          target: backendTarget,
          changeOrigin: true,
          secure: false,
          ws: false,
        },
        '/security-vlm': {
          target: backendTarget,
          changeOrigin: true,
          secure: false,
          ws: false,
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
