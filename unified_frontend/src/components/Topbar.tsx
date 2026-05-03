import { LogOut, Menu, Moon, Sun } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { cn } from '@/lib/utils'
import { findNavItem } from '@/lib/nav'
import { getPageDisplayOverride } from '@/lib/permissions'
import { useTheme } from '@/hooks/use-theme'
import { useAuth } from '@/auth/useAuth'

interface TopbarProps {
  currentPage: string
  onToggleSidebar: () => void
}

export function Topbar({ currentPage, onToggleSidebar }: TopbarProps) {
  const { theme, toggleTheme } = useTheme()
  const { user, logout } = useAuth()
  const current = findNavItem(currentPage)
  const displayOverride = getPageDisplayOverride(user, currentPage)
  const isHome = currentPage === 'home' || currentPage === 'overview'
  const title = displayOverride?.label ?? current?.label ?? '统一监控平台'
  const subtitle = displayOverride?.description ?? current?.description ?? '一体化监控与告警平台'

  return (
    <header
      className={cn(
        'sticky top-0 z-20 flex h-16 items-center gap-3 border-b border-slate-200/70 bg-white/78 px-3 shadow-sm shadow-slate-900/[0.03] sm:h-[72px] sm:gap-4 sm:px-4',
        'backdrop-blur-xl supports-[backdrop-filter]:bg-white/72 lg:px-7',
      )}
    >
      <button
        onClick={onToggleSidebar}
        className="flex h-10 w-10 items-center justify-center rounded-xl text-[#40557a] transition hover:bg-slate-100 hover:text-[#09265a]"
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
          <h2 className="truncate text-base font-semibold leading-tight text-[#09265a] sm:hidden">福达视觉平台</h2>
        )}
      </div>

      <button
        onClick={toggleTheme}
        className="flex h-10 w-10 items-center justify-center rounded-xl text-[#40557a] transition hover:bg-slate-100 hover:text-[#09265a]"
        aria-label="切换主题"
      >
        {theme === 'dark' ? <Sun className="h-4 w-4" /> : <Moon className="h-4 w-4" />}
      </button>

      {user && (
        <div className="hidden min-w-0 items-center gap-2 rounded-lg border border-slate-200 bg-white px-3 py-2 text-xs text-slate-600 shadow-sm md:flex">
          <span className="font-semibold text-[#09265a]">{user.employee_id}</span>
          <span className="max-w-24 truncate">{user.name}</span>
          <span className="rounded bg-slate-100 px-1.5 py-0.5 uppercase">{user.role}</span>
        </div>
      )}

      <Button variant="outline" size="sm" className="gap-2" onClick={logout}>
        <LogOut className="h-4 w-4" />
        退出
      </Button>

    </header>
  )
}
