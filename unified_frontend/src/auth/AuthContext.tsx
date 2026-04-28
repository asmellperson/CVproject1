import { createContext, useCallback, useContext, useEffect, useMemo, useState } from 'react'
import type { ReactNode } from 'react'

export type AuthUser = {
  employee_id: string
  name: string
  role: 'admin' | 'viewer' | string
}

type AuthContextValue = {
  user: AuthUser | null
  loading: boolean
  isAdmin: boolean
  login: (employeeId: string, password: string) => Promise<void>
  logout: () => Promise<void>
  refreshMe: () => Promise<void>
  handleUnauthorized: () => void
}

const AuthContext = createContext<AuthContextValue | null>(null)

async function readError(response: Response) {
  const text = await response.text().catch(() => '')
  try {
    const parsed = JSON.parse(text) as { detail?: string }
    return parsed.detail || text
  } catch {
    return text || `${response.status} ${response.statusText}`
  }
}

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<AuthUser | null>(null)
  const [loading, setLoading] = useState(true)

  const handleUnauthorized = useCallback(() => {
    setUser(null)
  }, [])

  const refreshMe = useCallback(async () => {
    const response = await fetch('/api/auth/me', {
      method: 'GET',
      credentials: 'include',
    })
    if (response.status === 401) {
      setUser(null)
      return
    }
    if (!response.ok) {
      throw new Error(await readError(response))
    }
    const payload = (await response.json()) as { user: AuthUser }
    setUser(payload.user)
  }, [])

  useEffect(() => {
    refreshMe()
      .catch(() => setUser(null))
      .finally(() => setLoading(false))
  }, [refreshMe])

  useEffect(() => {
    const listener = () => handleUnauthorized()
    window.addEventListener('aicv:unauthorized', listener)
    return () => window.removeEventListener('aicv:unauthorized', listener)
  }, [handleUnauthorized])

  const login = useCallback(async (employeeId: string, password: string) => {
    const response = await fetch('/api/auth/login', {
      method: 'POST',
      credentials: 'include',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ employee_id: employeeId, password }),
    })
    if (!response.ok) {
      throw new Error(await readError(response))
    }
    const payload = (await response.json()) as { user: AuthUser }
    setUser(payload.user)
  }, [])

  const logout = useCallback(async () => {
    await fetch('/api/auth/logout', {
      method: 'POST',
      credentials: 'include',
    }).catch(() => undefined)
    setUser(null)
  }, [])

  const value = useMemo<AuthContextValue>(
    () => ({
      user,
      loading,
      isAdmin: user?.role === 'admin',
      login,
      logout,
      refreshMe,
      handleUnauthorized,
    }),
    [handleUnauthorized, loading, login, logout, refreshMe, user],
  )

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>
}

export function useAuth() {
  const context = useContext(AuthContext)
  if (!context) {
    throw new Error('useAuth must be used within AuthProvider')
  }
  return context
}
