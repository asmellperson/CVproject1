import { cn } from '@/lib/utils'
import { navGroups, type NavGroup, type NavItem } from '@/lib/nav'
import { DEPARTMENTS, DEPARTMENT_LABELS, filterNavGroupsByPermission, getAccessibleDepartments, type DepartmentId } from '@/auth/permissions'
import { useAuth } from '@/auth/useAuth'
import { useEffect, useMemo, useRef, useState } from 'react'
import type { CSSProperties, FormEvent, KeyboardEvent, PointerEvent } from 'react'
import { Building2, ChevronRight, ChevronsLeft, Cpu, FlaskConical, Gem, KeyRound, LogOut, PackageOpen, X, Zap } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from '@/components/ui/tooltip'
import { UserIdentity } from '@/components/UserIdentity'
import { getStatistics } from '@/lib/api'

interface SidebarProps {
  currentPage: string
  currentDepartment: DepartmentId | null
  onPageChange: (page: string, department?: DepartmentId) => void
  collapsed: boolean
  onToggleCollapsed: () => void
  width: number
  minWidth: number
  maxWidth: number
  resizing: boolean
  onWidthChange: (width: number) => void
  onWidthCommit: (width: number) => void
  onResizeStateChange: (resizing: boolean) => void
  mobileOpen?: boolean
  onMobileClose?: () => void
  isMobile?: boolean
  monitoringCount?: number | null
  systemRunning?: boolean
}

export function Sidebar({
  currentPage,
  currentDepartment,
  onPageChange,
  collapsed,
  onToggleCollapsed,
  width,
  minWidth,
  maxWidth,
  resizing,
  onWidthChange,
  onWidthCommit,
  onResizeStateChange,
  mobileOpen = false,
  onMobileClose,
  isMobile = false,
  monitoringCount = null,
  systemRunning = true,
}: SidebarProps) {
  const compact = !isMobile && collapsed
  const { user, logout, changePassword } = useAuth()
  const [passwordOpen, setPasswordOpen] = useState(false)
  const [currentPassword, setCurrentPassword] = useState('')
  const [newPassword, setNewPassword] = useState('')
  const [confirmPassword, setConfirmPassword] = useState('')
  const [passwordMessage, setPasswordMessage] = useState('')
  const [passwordBusy, setPasswordBusy] = useState(false)
  const [todayAlarmCount, setTodayAlarmCount] = useState<number | null>(null)
  const visibleNavGroups = useMemo(
    () => buildSidebarNavGroups(user),
    [user],
  )
  const [expandedGroups, setExpandedGroups] = useState<Set<string>>(() => new Set(DEPARTMENTS))

  useEffect(() => {
    let active = true
    const loadAlarmCount = () => {
      void getStatistics()
        .then((result) => {
          const stats = result as { summary?: { today?: number } }
          if (active) setTodayAlarmCount(Number(stats.summary?.today) || 0)
        })
        .catch(() => {
          if (active) setTodayAlarmCount(null)
        })
    }
    loadAlarmCount()
    const timer = window.setInterval(loadAlarmCount, 30_000)
    return () => {
      active = false
      window.clearInterval(timer)
    }
  }, [])

  const activeChildGroupId = useMemo(
    () => visibleNavGroups
      .flatMap((group) => group.children || [])
      .find((child) => child.department === currentDepartment && child.items.some((item) => item.id === currentPage))
      ?.id,
    [currentPage, currentDepartment, visibleNavGroups],
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
        compact && 'is-compact',
        isMobile && 'w-[min(272px,86vw)]',
        resizing && 'duration-0',
        isMobile && (mobileOpen ? 'translate-x-0' : '-translate-x-full'),
      )}
      style={isMobile ? undefined : { width: compact ? 84 : width }}
    >
      <div
        className={cn(
          'sidebar-brand relative z-[1] shrink-0 border-b px-4',
          compact ? 'flex h-[92px] items-center justify-center' : 'h-[132px] pt-5',
        )}
      >
        {compact ? (
          <span className="sidebar-brand-mark" aria-label="福达视觉平台">福</span>
        ) : (
          <div className="min-w-0 overflow-hidden pr-9">
            <h1 className="sidebar-brand-title truncate">福达视觉平台</h1>
            <p className="sidebar-brand-subtitle mt-0.5 truncate">AI Vision Platform</p>
          </div>
        )}
        {isMobile ? (
          <button
            onClick={onMobileClose}
            className="sidebar-collapse-button absolute right-3 top-4 flex h-9 w-9 items-center justify-center rounded-xl"
            aria-label="关闭侧边栏"
          >
            <X className="h-4 w-4" />
          </button>
        ) : !compact && (
          <button
            onClick={onToggleCollapsed}
            className="sidebar-collapse-button absolute right-3 top-4 flex h-9 w-9 items-center justify-center rounded-xl"
            aria-label="收起侧边栏"
          >
            <ChevronsLeft className="h-4 w-4" />
          </button>
        )}
        {!compact && (
          <div className={cn('sidebar-status-bar mt-4 flex h-9 items-center gap-2 rounded-xl px-3', !systemRunning && 'is-offline')}>
            <span className="sidebar-status-dot" aria-hidden="true" />
            <span className="truncate text-[11px] font-semibold">{systemRunning ? '系统运行中' : '系统连接异常'}</span>
            <span className="ml-auto shrink-0 font-mono text-[10px] tracking-wide text-slate-400">
              {monitoringCount === null ? '--' : monitoringCount} 路监控
            </span>
          </div>
        )}
      </div>

      <TooltipProvider delayDuration={120}>
      <nav className={cn('sidebar-nav relative z-[1] flex-1 overflow-y-auto py-5', compact ? 'px-3' : 'px-4')}>
        {visibleNavGroups.map((group, idx) => (
          <div key={group.id} className={cn(idx !== 0 && 'mt-6')}>
            {!compact && group.label && (
              <div className="sidebar-section-label mb-3 flex items-center px-2" style={navToneStyle(sectionTone(group.id))}>
                {group.label}
              </div>
            )}
            <div className="space-y-1.5">
              {group.items.map((item) => (
                <SidebarNavButton
                  key={item.id}
                  item={item}
                  compact={compact}
                  active={currentPage === item.id}
                  onClick={() => onPageChange(item.id)}
                  tone={itemTone(item.id)}
                  badge={item.id === 'alarms' ? todayAlarmCount : null}
                />
              ))}
              {group.children?.map((child) => {
                const childActive = activeChildGroupId === child.id
                const expanded = compact || expandedGroups.has(child.id) || activeChildGroupId === child.id
                const childMeta = sidebarChildMeta[child.id] ?? sidebarChildMeta.shared
                const GroupIcon = childMeta.icon
                return (
                <div key={child.id} className={cn(!compact && 'pt-1')} style={navToneStyle(childMeta.tone)}>
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
                        'sidebar-group-button mb-1.5 flex w-full items-center gap-3 rounded-xl px-2 py-2.5 text-left text-[16px] font-bold',
                        childActive && 'is-active',
                      )}
                      aria-expanded={expanded}
                    >
                      <span className="sidebar-icon-badge"><GroupIcon className="h-[17px] w-[17px]" /></span>
                      <span className="min-w-0 flex-1 truncate">{child.label}</span>
                      <ChevronRight
                        className={cn(
                          'h-4 w-4 shrink-0 transition-transform duration-300',
                          expanded && 'rotate-90',
                        )}
                      />
                    </button>
                  )}
                  <div className={cn('sidebar-child-items space-y-1.5 overflow-hidden transition-[max-height,opacity] duration-300 ease-in-out', expanded ? 'max-h-[40rem] opacity-100' : 'max-h-0 opacity-0')}>
                    {child.items.map((item) => (
                      <SidebarNavButton
                        key={item.id}
                        item={item}
                        compact={compact}
                        active={currentPage === item.id && currentDepartment === child.department}
                        onClick={() => onPageChange(item.id, child.department)}
                        tone={childMeta.tone}
                        nested={!compact}
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
      </TooltipProvider>

      <div className={cn('sidebar-footer relative z-[1] border-t', compact ? 'space-y-2 p-3' : 'p-3')}>
        {compact ? (
          <>
            <button
              onClick={onToggleCollapsed}
              className="sidebar-footer-icon flex h-11 w-full items-center justify-center rounded-xl"
              aria-label="展开侧边栏"
              title="展开侧边栏"
            >
              <ChevronsLeft className="h-4 w-4 rotate-180" />
            </button>
            {user && (
              <button
                type="button"
                onClick={() => setPasswordOpen(true)}
                className="sidebar-footer-icon is-password flex h-11 w-full items-center justify-center rounded-xl"
                aria-label="修改密码"
                title="修改密码"
              >
                <KeyRound className="h-4 w-4" />
              </button>
            )}
            <button
              type="button"
              onClick={logout}
              className="sidebar-footer-icon is-logout flex h-11 w-full items-center justify-center rounded-xl"
              aria-label="退出"
              title="退出"
            >
              <LogOut className="h-4 w-4" />
            </button>
          </>
        ) : (
          <div className="sidebar-user-card relative overflow-hidden rounded-2xl p-3">
            <i className="sidebar-corner-dot is-top-left" aria-hidden="true" />
            <i className="sidebar-corner-dot is-top-right" aria-hidden="true" />
            <i className="sidebar-corner-dot is-bottom-left" aria-hidden="true" />
            <i className="sidebar-corner-dot is-bottom-right" aria-hidden="true" />
            {user && (
              <div className="min-w-0 border-b border-white/10 px-1 pb-3">
                <UserIdentity user={user} className="sidebar-user-identity" />
              </div>
            )}
            <div className="mt-3 grid grid-cols-2 gap-2">
              {user && (
                <Button variant="outline" size="sm" className="sidebar-account-button is-password gap-1.5" onClick={() => setPasswordOpen(true)}>
                  <KeyRound className="h-4 w-4" />
                  修改密码
                </Button>
              )}
              <Button variant="outline" size="sm" className="sidebar-account-button is-logout gap-1.5" onClick={logout}>
                <LogOut className="h-4 w-4" />
                退出
              </Button>
            </div>
          </div>
        )}
      </div>
      {!isMobile && !compact ? (
        <SidebarResizeHandle
          width={width}
          minWidth={minWidth}
          maxWidth={maxWidth}
          onWidthChange={onWidthChange}
          onWidthCommit={onWidthCommit}
          onResizeStateChange={onResizeStateChange}
        />
      ) : null}
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

function SidebarResizeHandle({
  width,
  minWidth,
  maxWidth,
  onWidthChange,
  onWidthCommit,
  onResizeStateChange,
}: {
  width: number
  minWidth: number
  maxWidth: number
  onWidthChange: (width: number) => void
  onWidthCommit: (width: number) => void
  onResizeStateChange: (resizing: boolean) => void
}) {
  const dragRef = useRef<{ pointerId: number; startX: number; startWidth: number; userSelect: string } | null>(null)
  const latestWidthRef = useRef(width)

  useEffect(() => {
    latestWidthRef.current = width
  }, [width])

  useEffect(() => () => {
    const drag = dragRef.current
    if (!drag) return
    document.body.style.userSelect = drag.userSelect
    onResizeStateChange(false)
  }, [onResizeStateChange])

  const clamp = (value: number) => Math.min(maxWidth, Math.max(minWidth, value))

  const finishResize = (event: PointerEvent<HTMLDivElement>) => {
    const drag = dragRef.current
    if (!drag || drag.pointerId !== event.pointerId) return
    if (event.currentTarget.hasPointerCapture(event.pointerId)) {
      event.currentTarget.releasePointerCapture(event.pointerId)
    }
    document.body.style.userSelect = drag.userSelect
    dragRef.current = null
    onResizeStateChange(false)
    onWidthCommit(latestWidthRef.current)
  }

  const handleKeyDown = (event: KeyboardEvent<HTMLDivElement>) => {
    let nextWidth = width
    if (event.key === 'ArrowLeft') nextWidth -= 8
    else if (event.key === 'ArrowRight') nextWidth += 8
    else if (event.key === 'Home') nextWidth = minWidth
    else if (event.key === 'End') nextWidth = maxWidth
    else return
    event.preventDefault()
    nextWidth = clamp(nextWidth)
    latestWidthRef.current = nextWidth
    onWidthChange(nextWidth)
    onWidthCommit(nextWidth)
  }

  return (
    <div
      role="separator"
      aria-label="调整导航栏宽度"
      aria-controls="app-main-content"
      aria-orientation="vertical"
      aria-valuemin={minWidth}
      aria-valuemax={maxWidth}
      aria-valuenow={Math.round(width)}
      tabIndex={0}
      title="拖动调整导航栏宽度"
      className="group absolute inset-y-0 right-0 z-50 flex w-3 touch-none cursor-col-resize items-center justify-end outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-blue-500"
      onPointerDown={(event) => {
        if (event.button !== 0) return
        latestWidthRef.current = width
        dragRef.current = {
          pointerId: event.pointerId,
          startX: event.clientX,
          startWidth: width,
          userSelect: document.body.style.userSelect,
        }
        event.currentTarget.setPointerCapture(event.pointerId)
        document.body.style.userSelect = 'none'
        onResizeStateChange(true)
        event.preventDefault()
      }}
      onPointerMove={(event) => {
        const drag = dragRef.current
        if (!drag || drag.pointerId !== event.pointerId) return
        const nextWidth = clamp(drag.startWidth + event.clientX - drag.startX)
        latestWidthRef.current = nextWidth
        onWidthChange(nextWidth)
      }}
      onPointerUp={finishResize}
      onPointerCancel={finishResize}
      onKeyDown={handleKeyDown}
    >
      <span className="h-full w-px bg-slate-200 transition-colors group-hover:w-0.5 group-hover:bg-blue-500 group-focus-visible:w-0.5 group-focus-visible:bg-blue-500 dark:bg-slate-800" />
    </div>
  )
}

type NavTone = 'cyan' | 'yellow' | 'purple' | 'gold' | 'green' | 'blue' | 'red' | 'magenta' | 'teal' | 'orange'

const navToneRgb: Record<NavTone, string> = {
  cyan: '128 246 255',
  yellow: '250 204 21',
  purple: '168 85 247',
  gold: '251 191 36',
  green: '52 211 153',
  blue: '96 165 250',
  red: '248 81 73',
  magenta: '217 69 238',
  teal: '45 212 191',
  orange: '251 113 43',
}

function navToneStyle(tone: NavTone) {
  return { '--nav-rgb': navToneRgb[tone] } as CSSProperties
}

const sidebarChildMeta: Record<string, { tone: NavTone; icon: typeof Building2 }> = {
  general_electric: { tone: 'cyan', icon: Building2 },
  electronics_electrician: { tone: 'yellow', icon: Zap },
  electrical_components: { tone: 'purple', icon: Cpu },
  precious_metal_recycling: { tone: 'gold', icon: Gem },
  haoda_company: { tone: 'magenta', icon: Building2 },
  research_institute: { tone: 'green', icon: FlaskConical },
  shared: { tone: 'blue', icon: PackageOpen },
}

function sectionTone(groupId: string): NavTone {
  if (groupId === 'data') return 'magenta'
  if (groupId === 'system') return 'teal'
  return 'cyan'
}

function itemTone(itemId: string): NavTone {
  if (itemId === 'alarms') return 'red'
  if (itemId === 'statistics') return 'magenta'
  if (itemId === 'user-management') return 'teal'
  if (itemId === 'access-audit') return 'orange'
  return 'blue'
}

export function buildSidebarNavGroups(user: Parameters<typeof filterNavGroupsByPermission>[0]): NavGroup[] {
  const visibleGroups = filterNavGroupsByPermission(user, navGroups)
  return visibleGroups.map((group) => group.id === 'modules' ? {
    ...group,
    items: [],
    children: getAccessibleDepartments(user).map((department) => ({
      id: department, department, label: DEPARTMENT_LABELS[department], items: group.items,
    })),
  } : group)
}

function SidebarNavButton({
  item,
  compact,
  active,
  onClick,
  tone,
  nested = false,
  badge = null,
}: {
  item: NavItem
  compact: boolean
  active: boolean
  onClick: () => void
  tone: NavTone
  nested?: boolean
  badge?: number | null
}) {
  const Icon = item.icon
  const button = (
    <button
      onClick={onClick}
      aria-current={active ? 'page' : undefined}
      style={navToneStyle(tone)}
      className={cn(
        'sidebar-nav-button group relative flex w-full items-center gap-3 rounded-xl px-2.5 py-2 text-[15px] font-medium',
        'focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-cyan-300/80',
        compact && 'justify-center px-0',
        nested && 'is-nested',
        active && 'is-active',
      )}
    >
      <span className="sidebar-icon-badge"><Icon className="h-[17px] w-[17px] shrink-0" /></span>
      {!compact && <span className="relative z-[1] min-w-0 flex-1 truncate text-left">{item.label}</span>}
      {badge !== null && (
        <span className={cn('sidebar-alarm-badge', compact && 'is-compact')} aria-label={`今日报警 ${badge} 条`}>
          {badge > 99 ? '99+' : badge}
        </span>
      )}
      {active && !compact && <ChevronRight className="relative z-[1] ml-auto h-4 w-4" />}
    </button>
  )

  if (!compact) return button
  return (
    <Tooltip>
      <TooltipTrigger asChild>{button}</TooltipTrigger>
      <TooltipContent side="right" sideOffset={12} className="sidebar-nav-tooltip">
        {item.label}
      </TooltipContent>
    </Tooltip>
  )
}
