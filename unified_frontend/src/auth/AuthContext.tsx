// 文件说明：实现认证授权相关的基础能力。
// 数据流：接收属性、状态或响应数据，并将结果交给组件、接口层或测试断言。

import { useCallback, useEffect, useMemo, useState } from 'react'
import type { ReactNode } from 'react'
import { getUserRole } from '@/auth/permissions'
import { AuthContext } from '@/auth/auth-context'
import type { AuthContextValue, AuthUser } from '@/auth/auth-context'

/**
 * 功能：读取或查询 `readError` 对应的认证授权逻辑；输入由参数提供，处理结果见返回值说明
 * 参数：
 *   - `response`（Response）：待读取或更新的 HTTP 响应
 * 返回：未显式标注（由 TypeScript 推断）；返回实现中 `return` 表达式计算得到的结果。
 * 调用关系：
 *   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
 *   - 内部调用：`text`、`parse`。
 * 副作用/注意事项：无明显外部副作用；下层调用失败时可能继续抛出异常。
 */
async function readError(response: Response) {
  const text = await response.text().catch(() => '')
  try {
    const parsed = JSON.parse(text) as { detail?: string }
    return parsed.detail || text
  } catch {
    return text || `${response.status} ${response.statusText}`
  }
}

/**
 * 功能：读取或查询 `fetchCurrentUser` 对应的认证授权逻辑；输入由参数提供，处理结果见返回值说明
 * 参数：无。
 * 返回：未显式标注（由 TypeScript 推断）；返回实现中 `return` 表达式计算得到的结果。
 * 调用关系：
 *   - 调用方：`unified_frontend/src/auth/AuthContext.tsx` 的 `AuthProvider` 调用本符号
 *   - 内部调用：`fetch`、`Error`、`readError`、`json`。
 * 副作用/注意事项：会发起 HTTP/WebSocket 请求，失败时可能抛出或上报异常；校验或请求失败时会主动抛出异常。
 */
async function fetchCurrentUser() {
  const response = await fetch('/api/auth/me', {
    method: 'GET',
    credentials: 'include',
  })
  if (response.status === 401) return null
  if (!response.ok) {
    throw new Error(await readError(response))
  }
  const payload = (await response.json()) as { user: AuthUser }
  return payload.user
}

/**
 * 功能：渲染 `AuthProvider` React 组件，根据输入属性组织界面并返回 JSX 节点
 * 参数：
 *   - `props`（未显式标注）：React 组件属性对象；解构字段包括 children, children, ReactNode
 * 返回：JSX.Element（由 React 推断）；返回用于界面渲染的 React 元素树。
 * 调用关系：
 *   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
 *   - 内部调用：`useState`、`useCallback`、`setUser`、`async`、`fetchCurrentUser`、`useEffect`、`then`、`finally`、`setLoading`、`return` 等共 23
 *          个调用。
 * 副作用/注意事项：会发起 HTTP/WebSocket 请求，失败时可能抛出或上报异常；会更新 React 状态并触发相关组件重新渲染；会读取或修改浏览器全局对象/DOM 状态；校验或请求失败时会主动抛出异常。
 */
export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<AuthUser | null>(null)
  const [loading, setLoading] = useState(true)

  const handleUnauthorized = useCallback(() => {
    setUser(null)
  }, [])

  const refreshMe = useCallback(async () => {
    setUser(await fetchCurrentUser())
  }, [])

  useEffect(() => {
    let cancelled = false
    fetchCurrentUser()
      .then((nextUser) => {
        if (!cancelled) setUser(nextUser)
      })
      .catch(() => {
        if (!cancelled) setUser(null)
      })
      .finally(() => {
        if (!cancelled) setLoading(false)
      })
    return () => {
      cancelled = true
    }
  }, [])

  useEffect(() => {
    const listener = () => handleUnauthorized()
    window.addEventListener('aicv:unauthorized', listener)
    return () => window.removeEventListener('aicv:unauthorized', listener)
  }, [handleUnauthorized])

  const login = useCallback(async (account: string, password: string) => {
    const response = await fetch('/api/auth/login', {
      method: 'POST',
      credentials: 'include',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ employee_id: account, password }),
    })
    if (!response.ok) {
      throw new Error(await readError(response))
    }
    const payload = (await response.json()) as { user: AuthUser }
    setUser(payload.user)
  }, [])

  const changePassword = useCallback(async (currentPassword: string, newPassword: string) => {
    const response = await fetch('/api/auth/password', {
      method: 'POST',
      credentials: 'include',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ current_password: currentPassword, new_password: newPassword }),
    })
    if (response.status === 401) {
      handleUnauthorized()
    }
    if (!response.ok) {
      throw new Error(await readError(response))
    }
    const payload = (await response.json()) as { user: AuthUser }
    setUser(payload.user)
  }, [handleUnauthorized])

  const logout = useCallback(async () => {
    await fetch('/api/auth/logout', {
      method: 'POST',
      credentials: 'include',
    }).catch(() => undefined)
    setUser(null)
  }, [])

  const value = useMemo<AuthContextValue>(
    () => {
      const normalizedRole = getUserRole(user)
      return {
        user,
        loading,
        isAdmin: normalizedRole === 'admin',
        login,
        changePassword,
        logout,
        refreshMe,
        handleUnauthorized,
      }
    },
    [changePassword, handleUnauthorized, loading, login, logout, refreshMe, user],
  )

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>
}
