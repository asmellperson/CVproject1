// 文件说明：封装认证授权的 React 状态与副作用。
// 数据流：接收属性、状态或响应数据，并将结果交给组件、接口层或测试断言。

import { useContext } from 'react'
import { AuthContext } from '@/auth/auth-context'

/**
 * 功能：封装 `useAuth` React Hook，向调用组件提供认证授权状态与操作
 * 参数：无。
 * 返回：未显式标注（由 TypeScript 推断）；返回实现中 `return` 表达式计算得到的结果。
 * 调用关系：
 *   - 调用方：`unified_frontend/src/components/ProtectedRoute.tsx` 的 `ProtectedRoute`
 *         调用本符号；`unified_frontend/src/components/Topbar.tsx` 的 `Topbar` 调用本符号；`unified_frontend/src/pages/LoginPage.tsx` 的
 *         `LoginPage` 调用本符号；`unified_frontend/src/components/AiVisionModelConfig.tsx` 的 `AiVisionModelConfig` 调用本符号；另有 16 处静态调用
 *   - 内部调用：`useContext`、`Error`。
 * 副作用/注意事项：校验或请求失败时会主动抛出异常。
 */
export function useAuth() {
  const context = useContext(AuthContext)
  if (!context) {
    throw new Error('useAuth must be used within AuthProvider')
  }
  return context
}
