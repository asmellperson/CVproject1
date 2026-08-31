// 文件说明：实现配置的 React 展示与交互。
// 数据流：接收属性、状态或响应数据，并将结果交给组件、接口层或测试断言。

import type { ComponentType, ReactNode } from 'react'
import { RefreshCw, Save } from 'lucide-react'

import { Button } from '@/components/ui/button'
import { CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { TabsList, TabsTrigger } from '@/components/ui/tabs'
import { cn } from '@/lib/utils'

type IconType = ComponentType<{ className?: string }>
type ConfigTone = 'blue' | 'emerald' | 'rose' | 'violet' | 'amber'

const ICON_TONES: Record<ConfigTone, string> = {
  blue: 'bg-gradient-to-br from-blue-500 to-indigo-600 shadow-blue-200/70 dark:shadow-none',
  emerald: 'bg-gradient-to-br from-emerald-500 to-emerald-700 shadow-emerald-200/70 dark:shadow-none',
  rose: 'bg-gradient-to-br from-rose-400 to-rose-600 shadow-rose-200/70 dark:shadow-none',
  violet: 'bg-gradient-to-br from-violet-500 to-violet-700 shadow-violet-200/70 dark:shadow-none',
  amber: 'bg-gradient-to-br from-amber-400 to-amber-600 shadow-amber-200/70 dark:shadow-none',
}

export const DETECTION_CONFIG_CARD_CLASS = 'overflow-hidden rounded-2xl border border-[#E8ECF5] bg-white shadow-[0_14px_40px_rgba(28,48,88,0.08)] dark:border-slate-800 dark:bg-slate-900'
export const DETECTION_CONFIG_CONTENT_CLASS = [
  'bg-white p-4 sm:p-5 dark:bg-slate-900',
  '[&_[data-slot=input]]:h-11 [&_[data-slot=input]]:rounded-xl [&_[data-slot=input]]:border-[#E2E7F2] [&_[data-slot=input]]:bg-[#FAFBFE]',
  '[&_[data-slot=select-trigger]]:h-11 [&_[data-slot=select-trigger]]:rounded-xl [&_[data-slot=select-trigger]]:border-[#E2E7F2] [&_[data-slot=select-trigger]]:bg-[#FAFBFE]',
  '[&_[data-slot=textarea]]:rounded-xl [&_[data-slot=textarea]]:border-[#E2E7F2] [&_[data-slot=textarea]]:bg-[#FAFBFE]',
  '[&_[data-slot=switch][data-state=checked]]:bg-gradient-to-r [&_[data-slot=switch][data-state=checked]]:from-blue-600 [&_[data-slot=switch][data-state=checked]]:to-indigo-600',
  'dark:[&_[data-slot=input]]:bg-slate-950/40 dark:[&_[data-slot=select-trigger]]:bg-slate-950/40 dark:[&_[data-slot=textarea]]:bg-slate-950/40',
].join(' ')

/**
 * 功能：渲染 `DetectionConfigTabsList` React 组件，根据输入属性组织界面并返回 JSX 节点
 * 参数：
 *   - `props`（未显式标注）：React 组件属性对象；解构字段包括 children, className, children, ReactNode, className, string
 * 返回：JSX.Element（由 React 推断）；返回用于界面渲染的 React 元素树。
 * 调用关系：
 *   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
 *   - 内部调用：`return`、`cn`、`TabsList`。
 * 副作用/注意事项：会参与 React 渲染；事件回调可能更新状态或触发外部操作。
 */
export function DetectionConfigTabsList({ children, className }: { children: ReactNode; className?: string }) {
  return (
    <TabsList className={cn(
      'grid h-auto w-full grid-cols-2 gap-1 rounded-2xl border border-[#E8ECF5] bg-white p-1.5 shadow-[0_6px_22px_rgba(28,48,88,0.06)] dark:border-slate-800 dark:bg-slate-900 sm:grid-cols-3 lg:grid-cols-5',
      className,
    )}>
      {children}
    </TabsList>
  )
}

/**
 * 功能：渲染 `DetectionConfigTab` React 组件，根据输入属性组织界面并返回 JSX 节点
 * 参数：
 *   - `props`（未显式标注）：React 组件属性对象；解构字段包括 value, icon, Icon, children, disabled, value, string, icon
 * 返回：JSX.Element（由 React 推断）；返回用于界面渲染的 React 元素树。
 * 调用关系：
 *   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
 *   - 内部调用：`return`、`TabsTrigger`、`Icon`。
 * 副作用/注意事项：会参与 React 渲染；事件回调可能更新状态或触发外部操作。
 */
export function DetectionConfigTab({ value, icon: Icon, children, disabled }: { value: string; icon: IconType; children: ReactNode; disabled?: boolean }) {
  return (
    <TabsTrigger
      value={value}
      disabled={disabled}
      className="h-10 gap-2 rounded-xl px-3 text-[#6B7699] shadow-none data-[state=active]:bg-[#0B1226] data-[state=active]:text-white data-[state=active]:shadow-md"
    >
      <Icon className="h-4 w-4" />
      {children}
    </TabsTrigger>
  )
}

/**
 * 功能：渲染 `DetectionConfigCardHeader` React 组件，根据输入属性组织界面并返回 JSX 节点
 * 参数：
 *   - `props`（未显式标注）：React 组件属性对象；解构字段包括 icon, Icon, tone, title, description, actions, className, icon
 * 返回：JSX.Element（由 React 推断）；返回用于界面渲染的 React 元素树。
 * 调用关系：
 *   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
 *   - 内部调用：`return`、`cn`、`CardHeader`、`Icon`、`CardTitle`。
 * 副作用/注意事项：会参与 React 渲染；事件回调可能更新状态或触发外部操作。
 */
export function DetectionConfigCardHeader({
  icon: Icon,
  tone,
  title,
  description,
  actions,
  className,
}: {
  icon: IconType
  tone: ConfigTone
  title: ReactNode
  description?: ReactNode
  actions?: ReactNode
  className?: string
}) {
  return (
    <CardHeader className={cn('flex flex-col items-start justify-between gap-4 border-b border-[#EDF0F6] bg-gradient-to-b from-white to-[#FBFCFF] p-4 sm:flex-row sm:items-center sm:px-5 dark:border-slate-800 dark:from-slate-900 dark:to-slate-900', className)}>
      <div className="flex min-w-0 items-center gap-3">
        <span className={cn('flex h-10 w-10 shrink-0 items-center justify-center rounded-xl text-white shadow-lg', ICON_TONES[tone])}>
          <Icon className="h-5 w-5" />
        </span>
        <div className="min-w-0">
          <CardTitle className="text-base font-black text-[#0B1226] dark:text-slate-100 sm:text-lg">{title}</CardTitle>
          {description ? <p className="mt-1 text-xs leading-5 text-[#6B7699] dark:text-slate-400">{description}</p> : null}
        </div>
      </div>
      {actions ? <div className="flex w-full flex-wrap items-center gap-2 sm:w-auto sm:justify-end">{actions}</div> : null}
    </CardHeader>
  )
}

/**
 * 功能：渲染 `DetectionConfigCardContent` React 组件，根据输入属性组织界面并返回 JSX 节点
 * 参数：
 *   - `props`（未显式标注）：React 组件属性对象；解构字段包括 children, className, children, ReactNode, className, string
 * 返回：JSX.Element（由 React 推断）；返回用于界面渲染的 React 元素树。
 * 调用关系：
 *   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
 *   - 内部调用：`cn`、`CardContent`。
 * 副作用/注意事项：会参与 React 渲染；事件回调可能更新状态或触发外部操作。
 */
export function DetectionConfigCardContent({ children, className }: { children: ReactNode; className?: string }) {
  return <CardContent className={cn(DETECTION_CONFIG_CONTENT_CLASS, className)}>{children}</CardContent>
}

/**
 * 功能：渲染 `DetectionFormSection` React 组件，根据输入属性组织界面并返回 JSX 节点
 * 参数：
 *   - `props`（未显式标注）：React 组件属性对象；解构字段包括 title, hint, children, className, title, string, hint, string
 * 返回：JSX.Element（由 React 推断）；返回用于界面渲染的 React 元素树。
 * 调用关系：
 *   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
 *   - 内部调用：`return`、`cn`。
 * 副作用/注意事项：会参与 React 渲染；事件回调可能更新状态或触发外部操作。
 */
export function DetectionFormSection({ title, hint, children, className }: { title: string; hint?: string; children: ReactNode; className?: string }) {
  return (
    <section className={cn('space-y-4', className)}>
      <div className="flex items-center gap-3">
        <h3 className="shrink-0 text-sm font-bold text-[#1E2A4A] dark:text-slate-200">{title}</h3>
        {hint ? <span className="shrink-0 text-xs text-[#9AA3C0]">{hint}</span> : null}
        <span className="h-px flex-1 bg-[#EDF0F6] dark:bg-slate-800" />
      </div>
      {children}
    </section>
  )
}

/**
 * 功能：渲染 `DetectionSaveBar` React 组件，根据输入属性组织界面并返回 JSX 节点
 * 参数：
 *   - `props`（未显式标注）：React 组件属性对象；解构字段包括 message, loading, saving, disabled, onReload, onSave, reloadLabel, saveLabel
 * 返回：JSX.Element（由 React 推断）；返回用于界面渲染的 React 元素树。
 * 调用关系：
 *   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
 *   - 内部调用：`return`、`cn`、`Button`、`RefreshCw`、`Save`。
 * 副作用/注意事项：会参与 React 渲染；事件回调可能更新状态或触发外部操作。
 */
export function DetectionSaveBar({
  message,
  loading,
  saving,
  disabled,
  onReload,
  onSave,
  reloadLabel = '重新读取',
  saveLabel = '保存配置',
}: {
  message: ReactNode
  loading?: boolean
  saving?: boolean
  disabled?: boolean
  onReload?: () => void
  onSave: () => void
  reloadLabel?: string
  saveLabel?: string
}) {
  return (
    <div className="sticky bottom-3 z-20 mt-5 flex flex-col gap-3 rounded-2xl border border-[#E2E7F2]/90 bg-white/90 px-4 py-3 shadow-[0_14px_34px_rgba(28,48,88,0.13)] backdrop-blur-xl dark:border-slate-800 dark:bg-slate-900/90 sm:flex-row sm:items-center sm:justify-between">
      <div className="flex min-w-0 items-center gap-2 text-sm text-[#6B7699] dark:text-slate-300">
        <span className="relative flex h-2.5 w-2.5 shrink-0">
          <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-emerald-400 opacity-50" />
          <span className="relative inline-flex h-2.5 w-2.5 rounded-full bg-emerald-500" />
        </span>
        <span className="min-w-0">{message}</span>
      </div>
      <div className="flex shrink-0 gap-2">
        {onReload ? (
          <Button type="button" variant="outline" className="gap-2 rounded-xl" onClick={onReload} disabled={loading || saving}>
            <RefreshCw className={cn('h-4 w-4', loading && 'animate-spin')} />
            {loading ? '读取中' : reloadLabel}
          </Button>
        ) : null}
        <Button
          type="button"
          className="gap-2 rounded-xl border-0 bg-gradient-to-br from-blue-600 to-indigo-600 text-white shadow-lg shadow-blue-200/60 hover:from-blue-700 hover:to-indigo-700 dark:shadow-none"
          onClick={onSave}
          disabled={disabled || loading || saving}
        >
          <Save className="h-4 w-4" />
          {saving ? '保存中' : saveLabel}
        </Button>
      </div>
    </div>
  )
}
