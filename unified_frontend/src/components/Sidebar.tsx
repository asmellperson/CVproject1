import { cn } from '@/lib/utils'
import { navGroups } from '@/lib/nav'
import { filterNavGroupsByPermission } from '@/lib/permissions'
import { useAuth } from '@/auth/useAuth'
import { Activity, ChevronRight, ChevronsLeft, X } from 'lucide-react'

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
          'relative z-[1] flex h-[76px] items-center border-b border-slate-200/70 px-4 sm:h-[86px] sm:px-5',
          compact ? 'justify-center' : 'justify-between',
        )}
      >
        <div className="flex items-center gap-3 overflow-hidden">
          <div className="flex h-11 w-11 shrink-0 items-center justify-center overflow-hidden rounded-full bg-white shadow-[0_12px_26px_rgba(37,99,235,0.18)] ring-4 ring-blue-50">
            <img
              src="/mascot.png"
              alt="福达视觉平台"
              className="h-full w-full object-cover object-top"
            />
          </div>
          {!compact && (
            <div className="min-w-0">
              <h1 className="truncate text-lg font-black tracking-[0] text-[#071d3d]">福达视觉平台</h1>
              <p className="mt-0.5 truncate text-xs font-medium text-slate-500">AI Vision Platform</p>
            </div>
          )}
        </div>
        {isMobile ? (
          <button
            onClick={onMobileClose}
            className="flex h-10 w-10 items-center justify-center rounded-xl border border-slate-200 bg-white text-slate-500 shadow-sm transition hover:bg-slate-50 hover:text-[#09265a]"
            aria-label="关闭侧边栏"
          >
            <X className="h-4 w-4" />
          </button>
        ) : !compact && (
          <button
            onClick={onToggleCollapsed}
            className="flex h-10 w-10 items-center justify-center rounded-xl border border-slate-200 bg-white text-slate-500 shadow-sm transition hover:bg-slate-50 hover:text-[#09265a]"
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
                        ? 'bg-gradient-to-r from-[#001b43] to-[#063579] text-white shadow-[0_12px_26px_rgba(0,27,67,0.22)]'
                        : 'text-[#40557a] hover:bg-white hover:text-[#09265a] hover:shadow-[0_8px_20px_rgba(31,58,97,0.08)]',
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

      <div className="relative z-[1] border-t border-slate-200/70 p-5">
        {compact ? (
          <button
            onClick={onToggleCollapsed}
            className="flex h-10 w-full items-center justify-center rounded-lg text-slate-500 transition hover:bg-white hover:text-[#09265a]"
            aria-label="展开侧边栏"
          >
            <ChevronsLeft className="h-4 w-4 rotate-180" />
          </button>
        ) : (
          <div className="rounded-xl border border-slate-200 bg-white/72 p-4 shadow-sm">
            <div className="mb-1 flex items-center gap-2">
              <span className="relative flex h-2.5 w-2.5">
                <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-emerald-400 opacity-60" />
                <span className="relative inline-flex h-2.5 w-2.5 rounded-full bg-emerald-500" />
              </span>
              <span className="text-sm font-bold text-[#09265a]">系统正常</span>
              <Activity className="ml-auto h-4 w-4 text-slate-400" />
            </div>
            <p className="text-xs text-slate-500">MVP阶段</p>
          </div>
        )}
      </div>
    </aside>
  )
}
