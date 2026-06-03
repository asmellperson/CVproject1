import { useState } from 'react'
import type { FormEvent } from 'react'
import { KeyRound, LogOut, Menu, Moon, Sun } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { cn } from '@/lib/utils'
import { findNavItem } from '@/lib/nav'
import { getPageDisplayOverride } from '@/auth/permissions'
import { useTheme } from '@/hooks/use-theme'
import { useAuth } from '@/auth/useAuth'

interface TopbarProps {
  currentPage: string
  onToggleSidebar: () => void
}

export function Topbar({ currentPage, onToggleSidebar }: TopbarProps) {
  const { theme, toggleTheme } = useTheme()
  const { user, logout, changePassword } = useAuth()
  const [passwordOpen, setPasswordOpen] = useState(false)
  const [currentPassword, setCurrentPassword] = useState('')
  const [newPassword, setNewPassword] = useState('')
  const [confirmPassword, setConfirmPassword] = useState('')
  const [passwordMessage, setPasswordMessage] = useState('')
  const [passwordBusy, setPasswordBusy] = useState(false)
  const current = findNavItem(currentPage)
  const displayOverride = getPageDisplayOverride(user, currentPage)
  const isHome = currentPage === 'home' || currentPage === 'overview'
  const title = displayOverride?.label ?? current?.label ?? '统一监控平台'
  const subtitle = displayOverride?.description ?? current?.description ?? '一体化监控与告警平台'

  const resetPasswordForm = () => {
    setCurrentPassword('')
    setNewPassword('')
    setConfirmPassword('')
    setPasswordMessage('')
    setPasswordBusy(false)
  }

  const handleChangePassword = async (event: FormEvent) => {
    event.preventDefault()
    setPasswordMessage('')
    if (newPassword.length < 6) {
      setPasswordMessage('新密码至少需要 6 位。')
      return
    }
    if (newPassword !== confirmPassword) {
      setPasswordMessage('两次输入的新密码不一致。')
      return
    }
    setPasswordBusy(true)
    try {
      await changePassword(currentPassword, newPassword)
      resetPasswordForm()
      setPasswordOpen(false)
    } catch (error) {
      setPasswordMessage(error instanceof Error ? error.message : '密码修改失败')
    } finally {
      setPasswordBusy(false)
    }
  }

  return (
    <header
      className={cn(
        'sticky top-0 z-20 flex h-16 items-center gap-3 border-b border-slate-200/70 bg-white/78 px-3 shadow-sm shadow-slate-900/[0.03] sm:h-[72px] sm:gap-4 sm:px-4',
        'backdrop-blur-xl supports-[backdrop-filter]:bg-white/72 dark:border-slate-800/80 dark:bg-slate-950/78 dark:shadow-slate-950/30 dark:supports-[backdrop-filter]:bg-slate-950/68 lg:px-7',
      )}
    >
      <button
        onClick={onToggleSidebar}
        className="flex h-10 w-10 items-center justify-center rounded-xl text-[#40557a] transition hover:bg-slate-100 hover:text-[#09265a] dark:text-slate-300 dark:hover:bg-slate-800 dark:hover:text-white"
        aria-label="切换侧边栏"
      >
        <Menu className="h-4 w-4" />
      </button>

      <div className="min-w-0 flex-1">
        {!isHome && (
          <>
            <div className="flex items-center gap-2 text-[11px] uppercase tracking-wider text-muted-foreground">
              <span className="truncate">{title}</span>
            </div>
            <h2 className="truncate text-base font-semibold leading-tight sm:text-lg">{subtitle}</h2>
          </>
        )}
        {isHome && (
          <h2 className="truncate text-base font-semibold leading-tight text-[#09265a] dark:text-slate-100 sm:hidden">福达视觉平台</h2>
        )}
      </div>

      <button
        onClick={toggleTheme}
        className="flex h-10 w-10 items-center justify-center rounded-xl text-[#40557a] transition hover:bg-slate-100 hover:text-[#09265a] dark:text-slate-300 dark:hover:bg-slate-800 dark:hover:text-white"
        aria-label="切换主题"
      >
        {theme === 'dark' ? <Sun className="h-4 w-4" /> : <Moon className="h-4 w-4" />}
      </button>

      {user && (
        <div className="hidden min-w-0 items-center gap-2 rounded-lg border border-slate-200 bg-white px-3 py-2 text-xs text-slate-600 shadow-sm dark:border-slate-800 dark:bg-slate-900/80 dark:text-slate-300 md:flex">
          <span className="font-semibold text-[#09265a] dark:text-slate-100">{user.employee_id}</span>
          <span className="max-w-24 truncate">{user.name}</span>
          <span className="rounded bg-slate-100 px-1.5 py-0.5 uppercase dark:bg-slate-800 dark:text-slate-300">{user.role}</span>
        </div>
      )}

      {user && (
        <Button variant="outline" size="sm" className="gap-2" onClick={() => setPasswordOpen(true)}>
          <KeyRound className="h-4 w-4" />
          修改密码
        </Button>
      )}

      <Button variant="outline" size="sm" className="gap-2" onClick={logout}>
        <LogOut className="h-4 w-4" />
        退出
      </Button>

      <Dialog
        open={passwordOpen}
        onOpenChange={(open) => {
          setPasswordOpen(open)
          if (!open) resetPasswordForm()
        }}
      >
        <DialogContent>
          <DialogHeader>
            <DialogTitle>修改密码</DialogTitle>
            <DialogDescription>修改当前账号的登录密码。</DialogDescription>
          </DialogHeader>
          <form className="space-y-4" onSubmit={handleChangePassword}>
            <div className="space-y-2">
              <Label htmlFor="current-password">当前密码</Label>
              <Input
                id="current-password"
                type="password"
                value={currentPassword}
                onChange={(event) => setCurrentPassword(event.target.value)}
                autoComplete="current-password"
                required
              />
            </div>
            <div className="space-y-2">
              <Label htmlFor="new-password">新密码</Label>
              <Input
                id="new-password"
                type="password"
                value={newPassword}
                onChange={(event) => setNewPassword(event.target.value)}
                autoComplete="new-password"
                required
              />
            </div>
            <div className="space-y-2">
              <Label htmlFor="confirm-password">确认新密码</Label>
              <Input
                id="confirm-password"
                type="password"
                value={confirmPassword}
                onChange={(event) => setConfirmPassword(event.target.value)}
                autoComplete="new-password"
                required
              />
            </div>
            {passwordMessage && (
              <div className="rounded-md border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-700 dark:border-red-900/70 dark:bg-red-950/50 dark:text-red-200">
                {passwordMessage}
              </div>
            )}
            <DialogFooter>
              <Button type="button" variant="outline" onClick={() => setPasswordOpen(false)} disabled={passwordBusy}>
                取消
              </Button>
              <Button type="submit" disabled={passwordBusy}>
                {passwordBusy ? '保存中' : '保存'}
              </Button>
            </DialogFooter>
          </form>
        </DialogContent>
      </Dialog>
    </header>
  )
}
