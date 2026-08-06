import type { AuthUser } from '@/auth/auth-context'
import { cn } from '@/lib/utils'

interface UserIdentityProps {
  user: AuthUser
  className?: string
  detailsClassName?: string
}

export function UserIdentity({ user, className, detailsClassName }: UserIdentityProps) {
  return (
    <div className={cn('flex min-w-0 items-center gap-2.5', className)}>
      <div
        className="flex h-9 w-9 shrink-0 items-center justify-center rounded-full bg-gradient-to-br from-cyan-500 to-indigo-600 text-sm font-bold text-white shadow-sm"
        aria-hidden="true"
      >
        {user.name.slice(-1)}
      </div>
      <div className={cn('flex min-w-0 flex-col', detailsClassName)}>
        <div className="flex min-w-0 items-center gap-2">
          <span className="truncate text-sm font-semibold text-[#09265a] dark:text-slate-100">{user.name}</span>
          <span className="shrink-0 rounded bg-indigo-50 px-1.5 py-0.5 text-[10px] font-bold uppercase tracking-wide text-indigo-600 dark:bg-indigo-950/70 dark:text-indigo-300">
            {user.role}
          </span>
        </div>
        <span className="truncate text-xs text-slate-500 dark:text-slate-400">工号：{user.employee_id}</span>
      </div>
    </div>
  )
}
