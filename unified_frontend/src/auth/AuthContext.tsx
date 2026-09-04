import { useCallback, useEffect, useMemo, useState } from 'react'
import type { ReactNode } from 'react'
import { getUserRole } from '@/auth/permissions'
import { AuthContext } from '@/auth/auth-context'
import type { AuthContextValue, AuthUser } from '@/auth/auth-context'

async function readError(response: Response) {
  const text = await response.text().catch(() => '')
  try {
    const parsed = JSON.parse(text) as { detail?: string }
    return parsed.detail || text
  } catch {
    return text || `${response.status} ${response.statusText}`
  }
}

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
