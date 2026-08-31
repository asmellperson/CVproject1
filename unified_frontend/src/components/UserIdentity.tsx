// 文件说明：实现`UserIdentity` 模块的 React 展示与交互。
// 数据流：接收属性、状态或响应数据，并将结果交给组件、接口层或测试断言。

import type { AuthUser } from '@/auth/auth-context'
import { cn } from '@/lib/utils'

interface UserIdentityProps {
  user: AuthUser
  className?: string
  detailsClassName?: string
}

/**
 * 功能：渲染 `UserIdentity` React 组件，根据输入属性组织界面并返回 JSX 节点
 * 参数：
 *   - `props`（UserIdentityProps）：React 组件属性对象；解构字段包括 user, className, detailsClassName
 * 返回：JSX.Element（由 React 推断）；返回用于界面渲染的 React 元素树。
 * 调用关系：
 *   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
 *   - 内部调用：`return`、`cn`、`slice`。
 * 副作用/注意事项：会参与 React 渲染；事件回调可能更新状态或触发外部操作。
 */
export function UserIdentity({ user, className, detailsClassName }: UserIdentityProps) {
  return (
    <div className={cn('flex min-w-0 items-center gap-2.5', className)}>
      <div
        className="user-identity-avatar flex h-9 w-9 shrink-0 items-center justify-center rounded-full bg-gradient-to-br from-cyan-500 to-indigo-600 text-sm font-bold text-white shadow-sm"
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
