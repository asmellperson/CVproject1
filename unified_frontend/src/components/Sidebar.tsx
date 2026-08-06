import { cn } from '@/lib/utils'
import { navGroups, type NavGroup, type NavItem } from '@/lib/nav'
import { departmentPermissions, filterNavGroupsByPermission } from '@/auth/permissions'
import { useAuth } from '@/auth/useAuth'
import { useMemo, useState } from 'react'
import type { FormEvent } from 'react'
import { ChevronRight, ChevronsLeft, KeyRound, LogOut, X } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { UserIdentity } from '@/components/UserIdentity'

interface SidebarProps {
  currentPage: string
  onPageChange: (page: string) => void
  collapsed: boolean
  onToggleCollapsed: () => void
  mobileOpen?: boolean
  onMobileClose?: () => void
  isMobile?: boolean
}

export function Sidebar({
  currentPage,
  onPageChange,
  collapsed,
  onToggleCollapsed,
  mobileOpen = false,
  onMobileClose,
  isMobile = false,
}: SidebarProps) {
  const compact = !isMobile && collapsed
  const { user, isAdmin, logout, changePassword } = useAuth()
  const [passwordOpen, setPasswordOpen] = useState(false)
  const [currentPassword, setCurrentPassword] = useState('')
  const [newPassword, setNewPassword] = useState('')
  const [confirmPassword, setConfirmPassword] = useState('')
  const [passwordMessage, setPasswordMessage] = useState('')
  const [passwordBusy, setPasswordBusy] = useState(false)
  const visibleNavGroups = useMemo(
    () => buildSidebarNavGroups(user, isAdmin),
    [isAdmin, user],
  )
  const [expandedGroups, setExpandedGroups] = useState<Set<string>>(() => new Set(adminModuleGroups.map((group) => group.id).concat('shared')))

  const activeChildGroupId = useMemo(
    () => visibleNavGroups
      .flatMap((group) => group.children || [])
      .find((child) => child.items.some((item) => item.id === currentPage))
      ?.id,
    [currentPage, visibleNavGroups],
  )

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
    <>
      <aside
      className={cn(
        'sidebar-shell fixed left-0 top-0 z-40 flex h-[100dvh] flex-col overflow-hidden border-r',
        'transition-[width,transform] duration-300 ease-in-out',
        isMobile ? 'w-[min(18rem,86vw)]' : compact ? 'w-[4.75rem]' : 'w-[18rem]',
        isMobile && (mobileOpen ? 'translate-x-0' : '-translate-x-full'),
      )}
    >
      <div
        className={cn(
          'relative z-[1] flex h-[76px] items-center border-b border-slate-200/70 px-4 dark:border-slate-800/80 sm:h-[86px] sm:px-5',
          compact ? 'justify-center' : 'justify-between',
        )}
      >
        {!compact && (
          <div className="min-w-0 overflow-hidden">
            <h1 className="truncate text-lg font-black tracking-[0] text-[#071d3d] dark:text-slate-100">福达视觉平台</h1>
            <p className="mt-0.5 truncate text-xs font-medium text-slate-500 dark:text-slate-400">AI Vision Platform</p>
          </div>
        )}
        {isMobile ? (
          <button
            onClick={onMobileClose}
            className="flex h-10 w-10 items-center justify-center rounded-xl border border-slate-200 bg-white text-slate-500 shadow-sm transition hover:bg-slate-50 hover:text-[#09265a] dark:border-slate-800 dark:bg-slate-900 dark:text-slate-300 dark:hover:bg-slate-800 dark:hover:text-white"
            aria-label="关闭侧边栏"
          >
            <X className="h-4 w-4" />
          </button>
        ) : !compact && (
          <button
            onClick={onToggleCollapsed}
            className="flex h-10 w-10 items-center justify-center rounded-xl border border-slate-200 bg-white text-slate-500 shadow-sm transition hover:bg-slate-50 hover:text-[#09265a] dark:border-slate-800 dark:bg-slate-900 dark:text-slate-300 dark:hover:bg-slate-800 dark:hover:text-white"
            aria-label="收起侧边栏"
          >
            <ChevronsLeft className="h-4 w-4" />
          </button>
        )}
      </div>

      <nav className="relative z-[1] flex-1 overflow-y-auto px-4 py-5">
        {visibleNavGroups.map((group, idx) => (
          <div key={group.id} className={cn(idx !== 0 && 'mt-6')}>
            {!compact && group.label && (
              <div className="mb-3 px-3 text-sm font-bold tracking-[0] text-slate-500">
                {group.label}
              </div>
            )}
            <div className="space-y-2">
              {group.items.map((item) => (
                <SidebarNavButton
                  key={item.id}
                  item={item}
                  compact={compact}
                  active={currentPage === item.id}
                  onClick={() => onPageChange(item.id)}
                />
              ))}
              {group.children?.map((child) => {
                const childActive = activeChildGroupId === child.id
                const expanded = compact || expandedGroups.has(child.id) || activeChildGroupId === child.id
                return (
                <div key={child.id} className={cn(!compact && 'pt-2')}>
                  {!compact && (
                    <button
                      type="button"
                      onClick={() => {
                        setExpandedGroups((prev) => {
                          const next = new Set(prev)
                          if (next.has(child.id)) {
                            next.delete(child.id)
                          } else {
                            next.add(child.id)
                          }
                          return next
                        })
                      }}
                      className={cn(
                        'mb-2 flex w-full items-center gap-2 rounded-lg px-3 py-1.5 text-left text-lg font-black tracking-[0] transition',
                        childActive
                          ? 'bg-gradient-to-r from-[#001b43] to-[#063579] text-white shadow-[0_12px_26px_rgba(0,27,67,0.22)] dark:from-blue-600 dark:to-cyan-500 dark:shadow-blue-950/35'
                          : 'text-[#09265a] hover:bg-white/70 dark:text-slate-100 dark:hover:bg-slate-800/60',
                      )}
                      aria-expanded={expanded}
                    >
                      <ChevronRight
                        className={cn(
                          'h-4 w-4 shrink-0 transition-transform',
                          childActive ? 'text-blue-100 dark:text-white' : 'text-slate-400',
                          expanded && 'rotate-90',
                        )}
                      />
                      <span className="truncate">{child.label}</span>
                    </button>
                  )}
                  <div className={cn('space-y-2 overflow-hidden transition-[max-height,opacity] duration-200 ease-in-out', expanded ? 'max-h-96 opacity-100' : 'max-h-0 opacity-0')}>
                    {child.items.map((item) => (
                      <SidebarNavButton
                        key={item.id}
                        item={item}
                        compact={compact}
                        active={currentPage === item.id}
                        onClick={() => onPageChange(item.id)}
                      />
                    ))}
                  </div>
                </div>
                )
              })}
            </div>
          </div>
        ))}
      </nav>

      <div className={cn('relative z-[1] border-t border-slate-200/70 dark:border-slate-800/80', compact ? 'space-y-2 p-3' : 'p-4')}>
        {compact ? (
          <>
            <button
              onClick={onToggleCollapsed}
              className="flex h-10 w-full items-center justify-center rounded-lg text-slate-500 transition hover:bg-white hover:text-[#09265a] dark:text-slate-300 dark:hover:bg-slate-800 dark:hover:text-white"
              aria-label="展开侧边栏"
            >
              <ChevronsLeft className="h-4 w-4 rotate-180" />
            </button>
            {user && (
              <button
                type="button"
                onClick={() => setPasswordOpen(true)}
                className="flex h-10 w-full items-center justify-center rounded-lg text-slate-500 transition hover:bg-white hover:text-[#09265a] dark:text-slate-300 dark:hover:bg-slate-800 dark:hover:text-white"
                aria-label="修改密码"
                title="修改密码"
              >
                <KeyRound className="h-4 w-4" />
              </button>
            )}
            <button
              type="button"
              onClick={logout}
              className="flex h-10 w-full items-center justify-center rounded-lg text-slate-500 transition hover:bg-red-50 hover:text-red-600 dark:text-slate-300 dark:hover:bg-red-950/40 dark:hover:text-red-300"
              aria-label="退出"
              title="退出"
            >
              <LogOut className="h-4 w-4" />
            </button>
          </>
        ) : (
          <div className="rounded-xl border border-slate-200 bg-white/72 p-3 shadow-sm dark:border-slate-800 dark:bg-slate-900/72">
            {user && (
              <div className="min-w-0 border-b border-slate-200 px-1 pb-3 dark:border-slate-800">
                <UserIdentity user={user} />
              </div>
            )}
            <div className="mt-3 grid grid-cols-2 gap-2">
              {user && (
                <Button variant="outline" size="sm" className="gap-1.5" onClick={() => setPasswordOpen(true)}>
                  <KeyRound className="h-4 w-4" />
                  修改密码
                </Button>
              )}
              <Button variant="outline" size="sm" className="gap-1.5 text-red-600 hover:text-red-700 dark:text-red-300" onClick={logout}>
                <LogOut className="h-4 w-4" />
                退出
              </Button>
            </div>
          </div>
        )}
      </div>
      </aside>

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
    </>
  )
}

const adminModuleGroups = [
  {
    id: 'general_electric',
    label: '通用电气事业部',
    pages: departmentPermissions.general_electric.pages,
  },
  {
    id: 'electronics_electrician',
    label: '电子电工事业部',
    pages: departmentPermissions.electronics_electrician.pages,
  },
  {
    id: 'electrical_components',
    label: '电气部件事业部',
    pages: departmentPermissions.electrical_components.pages,
  },
  {
    id: 'precious_metal_recycling',
    label: '贵金属回收事业部',
    pages: departmentPermissions.precious_metal_recycling.pages,
  },
  {
    id: 'research_institute',
    label: '研究院',
    pages: departmentPermissions.research_institute.pages,
  },
]

function buildSidebarNavGroups(user: Parameters<typeof filterNavGroupsByPermission>[0], isAdmin: boolean): NavGroup[] {
  const visibleGroups = filterNavGroupsByPermission(user, navGroups)
  if (!isAdmin) return visibleGroups

  const modules = visibleGroups.find((group) => group.id === 'modules')
  if (!modules) return visibleGroups

  const moduleItemsById = new Map(modules.items.map((item) => [item.id, item]))
  const groupedIds = new Set<string>()
  const children = adminModuleGroups.map((group) => {
    const items = group.pages.flatMap((pageId) => {
      const item = moduleItemsById.get(pageId)
      if (!item) return []
      groupedIds.add(item.id)
      return [item]
    })
    return { id: group.id, label: group.label, items }
  })
  const sharedItems = modules.items.filter((item) => !groupedIds.has(item.id))
  if (sharedItems.length) {
    children.push({ id: 'shared', label: '公共能力', items: sharedItems })
  }

  return visibleGroups.map((group) => (
    group.id === 'modules' ? { ...group, items: [], children } : group
  ))
}

function SidebarNavButton({
  item,
  compact,
  active,
  onClick,
}: {
  item: NavItem
  compact: boolean
  active: boolean
  onClick: () => void
}) {
  const Icon = item.icon
  return (
    <button
      onClick={onClick}
      title={compact ? item.label : undefined}
      className={cn(
        'group relative flex w-full items-center gap-4 rounded-xl px-4 py-3 text-[15px] font-semibold transition-all',
        'focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring',
        compact && 'justify-center px-0',
        active
          ? 'bg-blue-50/90 text-blue-700 shadow-[0_6px_16px_rgba(37,99,235,0.10)] ring-1 ring-inset ring-blue-200 dark:bg-blue-950/55 dark:text-blue-100 dark:ring-blue-800/80'
          : 'text-[#40557a] hover:bg-white hover:text-[#09265a] hover:shadow-[0_8px_20px_rgba(31,58,97,0.08)] dark:text-slate-300 dark:hover:bg-slate-800/80 dark:hover:text-white',
      )}
    >
      <Icon className="h-[18px] w-[18px] shrink-0" />
      {!compact && <span className="truncate">{item.label}</span>}
      {active && !compact && <ChevronRight className="ml-auto h-4 w-4" />}
    </button>
  )
}
