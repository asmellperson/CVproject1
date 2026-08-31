// 文件说明：作为程序启动入口并装配依赖。
// 数据流：接收属性、状态或响应数据，并将结果交给组件、接口层或测试断言。

import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import './index.css'
import App from './App.tsx'
import { AuthProvider } from '@/auth/AuthContext'
import { ProtectedRoute } from '@/components/ProtectedRoute'

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <AuthProvider>
      <ProtectedRoute>
        <App />
      </ProtectedRoute>
    </AuthProvider>
  </StrictMode>,
)
