import { cn } from '@/lib/utils'
import { navGroups } from '@/lib/nav'
import { filterNavGroupsByPermission } from '@/auth/permissions'
import { useAuth } from '@/auth/useAuth'
import { useEffect, useState } from 'react'
import { Activity, AlertTriangle, ChevronRight, ChevronsLeft, X } from 'lucide-react'
import { getPlatformStatus, type PlatformStatus } from '@/lib/api'

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
  const { user } = useAuth()
  const visibleNavGroups = filterNavGroupsByPermission(user, navGroups)
  const [platformStatus, setPlatformStatus] = useState<PlatformStatus | null>(null)

  useEffect(() => {
    let cancelled = false

    const load = async () => {
      try {
        const status = await getPlatformStatus()
        if (!cancelled) setPlatformStatus(status)
      } catch {
        if (!cancelled) setPlatformStatus(null)
      }
    }

    load()
    const timer = window.setInterval(load, 10000)
    return () => {
      cancelled = true
      window.clearInterval(timer)
    }
  }, [])

  const statusLevel = platformStatus?.level || 'down'
  const statusLabel =
    statusLevel === 'healthy'
      ? '系统正常'
      : statusLevel === 'degraded'
        ? '部分异常'
        : '模块离线'
  const statusDetail = platformStatus
    ? `${platformStatus.summary.service_online}/${platformStatus.summary.service_total} 模块在线 · ${platformStatus.summary.camera_online}/${platformStatus.summary.camera_total} 摄像头`
    : '平台连接异常'
  const statusTone =
    statusLevel === 'healthy'
      ? 'emerald'
      : statusLevel === 'degraded'
        ? 'amber'
        : 'red'

  return (
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
        <div className="flex items-center gap-3 overflow-hidden">
          <div className="flex h-11 w-11 shrink-0 items-center justify-center overflow-hidden rounded-full bg-white shadow-[0_12px_26px_rgba(37,99,235,0.18)] ring-4 ring-blue-50 dark:bg-slate-900 dark:ring-slate-800">
            <img
              src="/mascot.png"
              alt="福达视觉平台"
              className="h-full w-full object-cover object-top"
            />
          </div>
          {!compact && (
            <div className="min-w-0">
              <h1 className="truncate text-lg font-black tracking-[0] text-[#071d3d] dark:text-slate-100">福达视觉平台</h1>
              <p className="mt-0.5 truncate text-xs font-medium text-slate-500">AI Vision Platform</p>
            </div>
          )}
        </div>
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
              {group.items.map((item) => {
                const Icon = item.icon
                const isActive = currentPage === item.id
                return (
                  <button
                    key={item.id}
                    onClick={() => onPageChange(item.id)}
                    title={compact ? item.label : undefined}
                    className={cn(
                      'group relative flex w-full items-center gap-4 rounded-xl px-4 py-3 text-[15px] font-semibold transition-all',
                      'focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring',
                      compact && 'justify-center px-0',
                      isActive
                        ? 'bg-gradient-to-r from-[#001b43] to-[#063579] text-white shadow-[0_12px_26px_rgba(0,27,67,0.22)] dark:from-blue-600 dark:to-cyan-500 dark:shadow-blue-950/35'
                        : 'text-[#40557a] hover:bg-white hover:text-[#09265a] hover:shadow-[0_8px_20px_rgba(31,58,97,0.08)] dark:text-slate-300 dark:hover:bg-slate-800/80 dark:hover:text-white',
                    )}
                  >
                    <Icon className="h-[18px] w-[18px] shrink-0" />
                    {!compact && <span className="truncate">{item.label}</span>}
                    {isActive && !compact && <ChevronRight className="ml-auto h-4 w-4" />}
                  </button>
                )
              })}
            </div>
          </div>
        ))}
      </nav>

      <div className="relative z-[1] border-t border-slate-200/70 p-5 dark:border-slate-800/80">
        {compact ? (
          <button
            onClick={onToggleCollapsed}
            className="flex h-10 w-full items-center justify-center rounded-lg text-slate-500 transition hover:bg-white hover:text-[#09265a] dark:text-slate-300 dark:hover:bg-slate-800 dark:hover:text-white"
            aria-label="展开侧边栏"
          >
            <ChevronsLeft className="h-4 w-4 rotate-180" />
          </button>
        ) : (
          <div className="rounded-xl border border-slate-200 bg-white/72 p-4 shadow-sm dark:border-slate-800 dark:bg-slate-900/72">
            <div className="mb-1 flex items-center gap-2">
              <span className="relative flex h-2.5 w-2.5">
                <span
                  className={cn(
                    'absolute inline-flex h-full w-full animate-ping rounded-full opacity-60',
                    statusTone === 'emerald' && 'bg-emerald-400',
                    statusTone === 'amber' && 'bg-amber-400',
                    statusTone === 'red' && 'bg-red-400',
                  )}
                />
                <span
                  className={cn(
                    'relative inline-flex h-2.5 w-2.5 rounded-full',
                    statusTone === 'emerald' && 'bg-emerald-500',
                    statusTone === 'amber' && 'bg-amber-500',
                    statusTone === 'red' && 'bg-red-500',
                  )}
                />
              </span>
              <span className="text-sm font-bold text-[#09265a] dark:text-slate-100">{statusLabel}</span>
              {statusLevel === 'healthy' ? (
                <Activity className="ml-auto h-4 w-4 text-slate-400" />
              ) : (
                <AlertTriangle className="ml-auto h-4 w-4 text-amber-500" />
              )}
            </div>
            <p className="text-xs leading-5 text-slate-500">{statusDetail}</p>
          </div>
        )}
      </div>
    </aside>
  )
}
