// 文件说明：实现`DetectionPageHeader` 模块的 React 展示与交互。
// 数据流：接收属性、状态或响应数据，并将结果交给组件、接口层或测试断言。

import type { ReactNode } from 'react'
import { Settings2, ShieldCheck, Video } from 'lucide-react'

import { TabsList, TabsTrigger } from '@/components/ui/tabs'

type DetectionPageHeaderProps = {
  title: string
  subtitle: string
  departmentLabel: string
  runtimeControl?: ReactNode
  monitorValue?: string
  configValue?: string
}

/**
 * 功能：渲染 `DetectionPageHeader` React 组件，根据输入属性组织界面并返回 JSX 节点
 * 参数：
 *   - `props`（DetectionPageHeaderProps）：React 组件属性对象；解构字段包括 title, subtitle, departmentLabel, runtimeControl, monitorValue,
 *     monitor, configValue, config
 * 返回：JSX.Element（由 React 推断）；返回用于界面渲染的 React 元素树。
 * 调用关系：
 *   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
 *   - 内部调用：`return`、`ShieldCheck`、`TabsList`、`TabsTrigger`、`Video`、`Settings2`。
 * 副作用/注意事项：会参与 React 渲染；事件回调可能更新状态或触发外部操作。
 */
export function DetectionPageHeader({
  title,
  subtitle,
  departmentLabel,
  runtimeControl,
  monitorValue = 'monitor',
  configValue = 'config',
}: DetectionPageHeaderProps) {
  return (
    <div className="flex flex-col gap-4 xl:flex-row xl:items-end xl:justify-between">
      <div className="min-w-0 max-w-3xl">
        <div className="inline-flex items-center gap-1.5 rounded-lg border border-blue-100 bg-white/90 px-2.5 py-1 text-[11px] font-bold text-blue-700 shadow-sm dark:border-blue-900 dark:bg-slate-900 dark:text-blue-300">
          <ShieldCheck className="h-3.5 w-3.5" />
          {departmentLabel}
        </div>
        <h1 className="mt-2 flex flex-wrap items-baseline gap-x-2 text-2xl font-black tracking-tight text-[#0B1226] dark:text-slate-100 sm:text-[28px]">
          <span>{title}</span>
          <span className="bg-gradient-to-br from-blue-600 to-indigo-600 bg-clip-text text-transparent">监控与配置</span>
        </h1>
        <p className="mt-1 text-sm text-[#6B7699] dark:text-slate-400 sm:text-base">{subtitle}</p>
      </div>

      <div className="flex w-full flex-col gap-3 sm:items-stretch xl:w-auto xl:flex-row xl:items-center">
        {runtimeControl}
        <TabsList className="grid h-auto w-full shrink-0 grid-cols-2 rounded-2xl border border-slate-200/70 bg-white p-1 shadow-sm dark:border-slate-800 dark:bg-slate-900 sm:w-auto">
          <TabsTrigger
            value={monitorValue}
            className="h-10 gap-2 rounded-xl px-4 text-slate-500 shadow-none data-[state=active]:bg-[#0B1226] data-[state=active]:text-white data-[state=active]:shadow-md"
          >
            <Video className="h-4 w-4" />
            实时监控
          </TabsTrigger>
          <TabsTrigger
            value={configValue}
            className="h-10 gap-2 rounded-xl px-4 text-slate-500 shadow-none data-[state=active]:bg-[#0B1226] data-[state=active]:text-white data-[state=active]:shadow-md"
          >
            <Settings2 className="h-4 w-4" />
            配置管理
          </TabsTrigger>
        </TabsList>
      </div>
    </div>
  )
}
