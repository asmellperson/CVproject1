import { useState } from 'react'
import type { FormEvent } from 'react'
import { LockKeyhole, LogIn } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { useAuth } from '@/auth/useAuth'

export function LoginPage() {
  const { login } = useAuth()
  const [account, setAccount] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState('')
  const [submitting, setSubmitting] = useState(false)

  const onSubmit = async (event: FormEvent) => {
    event.preventDefault()
    setError('')
    setSubmitting(true)
    try {
      await login(account.trim(), password)
    } catch (err) {
      setError(err instanceof Error ? err.message : '登录失败')
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <div className="flex min-h-screen items-center justify-center bg-slate-100 px-4 py-8 text-slate-900 dark:bg-slate-950 dark:text-slate-100">
      <div className="w-full max-w-[420px] rounded-lg border border-slate-200 bg-white p-7 shadow-xl shadow-slate-900/8 dark:border-slate-800 dark:bg-slate-900/95 dark:shadow-slate-950/40">
        <div className="mb-7 flex items-center gap-3">
          <div className="flex h-11 w-11 items-center justify-center rounded-lg bg-[#09265a] text-white dark:bg-blue-500">
            <LockKeyhole className="h-5 w-5" />
          </div>
          <div>
            <h1 className="text-xl font-bold">福达视觉平台</h1>
            <p className="text-sm text-slate-500 dark:text-slate-400">统一登录鉴权</p>
          </div>
        </div>

        <form className="space-y-5" onSubmit={onSubmit}>
          <div className="space-y-2">
            <Label htmlFor="account">工号或姓名</Label>
            <Input
              id="account"
              value={account}
              onChange={(event) => setAccount(event.target.value)}
              autoComplete="username"
              placeholder="请输入工号或姓名"
              required
            />
          </div>

          <div className="space-y-2">
            <Label htmlFor="password">密码</Label>
            <Input
              id="password"
              type="password"
              value={password}
              onChange={(event) => setPassword(event.target.value)}
              autoComplete="current-password"
              placeholder="请输入密码"
              required
            />
          </div>

          {error && (
            <div className="rounded-md border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-700 dark:border-red-900/70 dark:bg-red-950/50 dark:text-red-200">
              {error}
            </div>
          )}

          <Button type="submit" className="w-full gap-2" disabled={submitting}>
            <LogIn className="h-4 w-4" />
            {submitting ? '登录中' : '登录'}
          </Button>
        </form>
      </div>
    </div>
  )
}
