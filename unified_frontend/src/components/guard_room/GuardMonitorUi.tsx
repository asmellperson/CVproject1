// 文件说明：实现监控展示的 React 展示与交互。
// 数据流：接收属性、状态或响应数据，并将结果交给组件、接口层或测试断言。

import type { LucideIcon } from 'lucide-react'
import { CheckCircle2, CircleAlert } from 'lucide-react'
import { cn } from '@/lib/utils'

type StatTone = 'emerald' | 'amber' | 'indigo' | 'rose'

const statToneClasses: Record<StatTone, { icon: string; ping: string }> = {
  emerald: { icon: 'bg-emerald-50 text-emerald-600', ping: 'bg-emerald-500' },
  amber: { icon: 'bg-amber-50 text-amber-600', ping: 'bg-amber-500' },
  indigo: { icon: 'bg-[#EAF0FE] text-[#1B3FA0] dark:bg-blue-950/60 dark:text-blue-300', ping: 'bg-indigo-500' },
  rose: { icon: 'bg-rose-50 text-rose-600', ping: 'bg-rose-500' },
}

/**
 * 功能：渲染 `GuardMonitorStatCard` React 组件，根据输入属性组织界面并返回 JSX 节点
 * 参数：
 *   - `props`（未显式标注）：React 组件属性对象；解构字段包括 label, value, detail, icon, Icon, tone, ping, false
 * 返回：JSX.Element（由 React 推断）；返回用于界面渲染的 React 元素树。
 * 调用关系：
 *   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
 *   - 内部调用：`return`、`cn`、`Icon`。
 * 副作用/注意事项：会参与 React 渲染；事件回调可能更新状态或触发外部操作。
 */
export function GuardMonitorStatCard({
  label,
  value,
  detail,
  icon: Icon,
  tone,
  ping = false,
}: {
  label: string
  value: string
  detail: string
  icon: LucideIcon
  tone: StatTone
  ping?: boolean
}) {
  const toneClasses = statToneClasses[tone]

  return (
    <article className="relative rounded-2xl border border-slate-200/70 bg-white p-4 shadow-sm dark:border-slate-800 dark:bg-slate-900">
      <div className={cn('flex h-9 w-9 items-center justify-center rounded-xl', toneClasses.icon)}>
        <Icon className="h-[18px] w-[18px]" aria-hidden="true" />
      </div>
      {ping && (
        <span className="absolute right-4 top-4 flex h-2.5 w-2.5" aria-label="全部在线">
          <span className={cn('absolute inline-flex h-full w-full animate-ping rounded-full opacity-60', toneClasses.ping)} />
          <span className={cn('relative inline-flex h-2.5 w-2.5 rounded-full', toneClasses.ping)} />
        </span>
      )}
      <p className="mt-4 text-xs font-medium text-slate-400">{label}</p>
      <p className="mt-1 text-[22px] font-bold leading-tight text-slate-950 dark:text-slate-100">{value}</p>
      <p className="mt-1.5 truncate text-xs text-slate-400" title={detail}>{detail}</p>
    </article>
  )
}

/**
 * 功能：渲染 `GuardDetectionStatusRow` React 组件，根据输入属性组织界面并返回 JSX 节点
 * 参数：
 *   - `props`（未显式标注）：React 组件属性对象；解构字段包括 label, icon, Icon, state, stateLabel, label, string, icon
 * 返回：JSX.Element（由 React 推断）；返回用于界面渲染的 React 元素树。
 * 调用关系：
 *   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
 *   - 内部调用：`return`、`cn`、`Icon`、`CheckCircle2`、`CircleAlert`。
 * 副作用/注意事项：会参与 React 渲染；事件回调可能更新状态或触发外部操作。
 */
export function GuardDetectionStatusRow({
  label,
  icon: Icon,
  state,
  stateLabel,
}: {
  label: string
  icon: LucideIcon
  state: 'normal' | 'warning' | 'danger'
  stateLabel: string
}) {
  const normal = state === 'normal'

  return (
    <div className="flex items-center justify-between gap-3 border-b border-slate-100 py-3 last:border-b-0 dark:border-slate-800">
      <div className="flex min-w-0 items-center gap-3 text-sm font-medium text-slate-600 dark:text-slate-300">
        <Icon className="h-4 w-4 shrink-0 text-slate-400" aria-hidden="true" />
        <span className="truncate">{label}</span>
      </div>
      <span
        className={cn(
          'inline-flex shrink-0 items-center gap-1 rounded-full px-2.5 py-1 text-xs font-medium',
          normal && 'bg-emerald-50 text-emerald-600',
          state === 'warning' && 'bg-amber-50 text-amber-600',
          state === 'danger' && 'bg-rose-50 text-rose-600',
        )}
      >
        {normal ? <CheckCircle2 className="h-3.5 w-3.5" /> : <CircleAlert className="h-3.5 w-3.5" />}
        {stateLabel}
      </span>
    </div>
  )
}

/**
 * 功能：渲染 `GuardVideoStatusPill` React 组件，根据输入属性组织界面并返回 JSX 节点
 * 参数：
 *   - `props`（未显式标注）：React 组件属性对象；解构字段包括 label, state, neutral, showDot, false, label, string, state
 * 返回：JSX.Element（由 React 推断）；返回用于界面渲染的 React 元素树。
 * 调用关系：
 *   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
 *   - 内部调用：`return`、`cn`。
 * 副作用/注意事项：会参与 React 渲染；事件回调可能更新状态或触发外部操作。
 */
export function GuardVideoStatusPill({
  label,
  state = 'neutral',
  showDot = false,
}: {
  label: string
  state?: 'normal' | 'danger' | 'neutral'
  showDot?: boolean
}) {
  return (
    <span
      className={cn(
        'inline-flex items-center gap-1.5 rounded-full bg-black/45 px-2.5 py-1 text-xs font-medium text-white backdrop-blur-sm',
        state === 'danger' && 'text-rose-300',
      )}
    >
      {showDot && (
        <span
          className={cn(
            'h-1.5 w-1.5 rounded-full',
            state === 'normal' && 'bg-emerald-400',
            state === 'danger' && 'bg-rose-400',
            state === 'neutral' && 'bg-slate-400',
          )}
        />
      )}
      {label}
    </span>
  )
}
