import type { ReactNode } from 'react'
import { History, Settings2, ShieldCheck, Video } from 'lucide-react'

import { TabsList, TabsTrigger } from '@/components/ui/tabs'

type DetectionPageHeaderProps = {
  title: string
  subtitle: string
  departmentLabel: string
  runtimeControl?: ReactNode
  monitorValue?: string
  configValue?: string
  recordsValue?: string
}

export function DetectionPageHeader({
  title,
  subtitle,
  departmentLabel,
  runtimeControl,
  monitorValue = 'monitor',
  configValue = 'config',
  recordsValue,
}: DetectionPageHeaderProps) {
  return (
    <div className="flex flex-col gap-3 sm:gap-4 xl:flex-row xl:items-end xl:justify-between">
      <div className="min-w-0 max-w-3xl">
        <div className="inline-flex items-center gap-1.5 rounded-lg border border-blue-100 bg-white/90 px-2.5 py-1 text-[11px] font-bold text-blue-700 shadow-sm dark:border-blue-900 dark:bg-slate-900 dark:text-blue-300">
          <ShieldCheck className="h-3.5 w-3.5" />
          {departmentLabel}
        </div>
        <h1 className="mt-2 flex flex-wrap items-baseline gap-x-2 text-xl font-black tracking-tight text-[#0B1226] dark:text-slate-100 sm:text-[28px]">
          <span>{title}</span>
          <span className="hidden bg-gradient-to-br from-blue-600 to-indigo-600 bg-clip-text text-transparent sm:inline">监控与配置</span>
        </h1>
        <p className="mt-1 text-xs leading-5 text-[#6B7699] dark:text-slate-400 sm:text-base">{subtitle}</p>
      </div>

      <div className="flex w-full flex-col gap-3 sm:items-stretch xl:w-auto xl:flex-row xl:items-center">
        {runtimeControl}
        <TabsList className={`grid h-auto w-full shrink-0 ${recordsValue ? 'grid-cols-3' : 'grid-cols-2'} rounded-2xl border border-slate-200/70 bg-white p-1 shadow-sm dark:border-slate-800 dark:bg-slate-900 sm:w-auto`}>
          <TabsTrigger
            value={monitorValue}
            className="h-11 gap-1.5 rounded-xl px-2 text-slate-500 shadow-none data-[state=active]:bg-[#0B1226] data-[state=active]:text-white data-[state=active]:shadow-md sm:h-10 sm:gap-2 sm:px-4"
          >
            <Video className="h-4 w-4" />
            实时监控
          </TabsTrigger>
          {recordsValue && <TabsTrigger value={recordsValue} className="h-11 gap-1.5 rounded-xl px-2 text-slate-500 shadow-none data-[state=active]:bg-[#0B1226] data-[state=active]:text-white data-[state=active]:shadow-md sm:h-10 sm:gap-2 sm:px-4"><History className="h-4 w-4" />识别记录</TabsTrigger>}
          <TabsTrigger
            value={configValue}
            className="h-11 gap-1.5 rounded-xl px-2 text-slate-500 shadow-none data-[state=active]:bg-[#0B1226] data-[state=active]:text-white data-[state=active]:shadow-md sm:h-10 sm:gap-2 sm:px-4"
          >
            <Settings2 className="h-4 w-4" />
            配置管理
          </TabsTrigger>
        </TabsList>
      </div>
    </div>
  )
}
