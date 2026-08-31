// 文件说明：实现`Topbar` 模块的 React 展示与交互。
// 数据流：接收属性、状态或响应数据，并将结果交给组件、接口层或测试断言。

import { Menu, Moon, Sun } from 'lucide-react'
import { cn } from '@/lib/utils'
import { findNavItem } from '@/lib/nav'
import { getPageDisplayOverride } from '@/auth/permissions'
import { useTheme } from '@/hooks/use-theme'
import { useAuth } from '@/auth/useAuth'
import { UserIdentity } from '@/components/UserIdentity'

interface TopbarProps {
  currentPage: string
  onToggleSidebar: () => void
}

/**
 * 功能：渲染 `Topbar` React 组件，根据输入属性组织界面并返回 JSX 节点
 * 参数：
 *   - `props`（TopbarProps）：React 组件属性对象；解构字段包括 currentPage, onToggleSidebar
 * 返回：JSX.Element（由 React 推断）；返回用于界面渲染的 React 元素树。
 * 调用关系：
 *   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
 *   - 内部调用：`useTheme`、`useAuth`、`findNavItem`、`getPageDisplayOverride`、`return`、`cn`、`Menu`、`UserIdentity`、`Sun`、`Moon`。
 * 副作用/注意事项：会参与 React 渲染；事件回调可能更新状态或触发外部操作。
 */
export function Topbar({ currentPage, onToggleSidebar }: TopbarProps) {
  const { theme, toggleTheme } = useTheme()
  const { user } = useAuth()
  const current = findNavItem(currentPage)
  const displayOverride = getPageDisplayOverride(user, currentPage)
  const isHome = currentPage === 'home' || currentPage === 'overview'
  const title = displayOverride?.label ?? current?.label ?? '统一监控平台'
  const subtitle = displayOverride?.description ?? current?.description ?? '一体化监控与告警平台'

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

      {user && (
        <UserIdentity
          user={user}
          className="shrink-0"
          detailsClassName="hidden xl:flex"
        />
      )}

      <button
        onClick={toggleTheme}
        className="flex h-10 w-10 items-center justify-center rounded-xl text-[#40557a] transition hover:bg-slate-100 hover:text-[#09265a] dark:text-slate-300 dark:hover:bg-slate-800 dark:hover:text-white"
        aria-label="切换主题"
      >
        {theme === 'dark' ? <Sun className="h-4 w-4" /> : <Moon className="h-4 w-4" />}
      </button>
    </header>
  )
}
