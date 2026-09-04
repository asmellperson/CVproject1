import type { ReactNode } from 'react'
import { LoginPage } from '@/pages/LoginPage'
import { useAuth } from '@/auth/useAuth'

export function ProtectedRoute({ children }: { children: ReactNode }) {
  const { loading, user } = useAuth()

  if (loading) {
    return (
      <div className="flex min-h-screen items-center justify-center bg-slate-100 text-slate-500 dark:bg-slate-950 dark:text-slate-400">
        正在校验登录状态...
      </div>
    )
  }

  if (!user) {
    return <LoginPage />
  }

  return <>{children}</>
}
