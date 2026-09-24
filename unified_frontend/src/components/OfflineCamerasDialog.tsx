import type { ReactNode } from 'react'
import { AlertTriangle, Building2, CheckCircle2, Clock3, Pause, VideoOff } from 'lucide-react'
import { DEPARTMENT_LABELS } from '@/auth/permissions'
import type { OverviewState } from '@/hooks/use-overview'
import { cn } from '@/lib/utils'
import {
  Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle, DialogTrigger,
} from '@/components/ui/dialog'

type OfflineCamerasDialogProps = {
  children: ReactNode
  overviewState: OverviewState
}

export function OfflineCamerasDialog({ children, overviewState }: OfflineCamerasDialogProps) {
  const { data, error, loading } = overviewState
  // 与汇总保持同一口径：所有未在线设备都列出，停用状态单独标识。
  const cameras = (data?.cameras ?? []).filter((camera) => !camera.online)
  const offlineCount = cameras.filter((camera) => camera.enabled).length
  const disabledCount = cameras.length - offlineCount
  const ready = data !== null && !error && !loading

  return (
    <Dialog>
      <DialogTrigger asChild>{children}</DialogTrigger>
      <DialogContent className="flex max-h-[85dvh] flex-col gap-0 overflow-hidden rounded-2xl border-slate-200 bg-white p-0 shadow-2xl dark:border-slate-700 dark:bg-slate-900 sm:max-w-2xl">
        <DialogHeader className="shrink-0 border-b border-blue-100 bg-gradient-to-br from-blue-50 via-slate-50 to-white px-5 pb-5 pt-6 text-left dark:border-slate-800 dark:from-blue-950/70 dark:via-slate-900 dark:to-slate-900 sm:px-6">
          <div className="flex items-center gap-3 pr-6">
            <div className="flex size-12 shrink-0 items-center justify-center rounded-2xl border border-blue-200/70 bg-white text-blue-600 shadow-sm dark:border-blue-800 dark:bg-blue-950 dark:text-blue-300">
              <VideoOff className="size-6" aria-hidden="true" />
            </div>
            <div className="min-w-0">
              <p className="mb-1.5 text-xs font-medium tracking-wide text-blue-600 dark:text-blue-300">设备状态 · 当前可见范围</p>
              <DialogTitle className="flex flex-wrap items-baseline gap-x-2 gap-y-1 text-xl font-semibold leading-7 text-slate-900 dark:text-slate-100">
                离线摄像头
                {ready && <span className="text-sm font-normal text-slate-500 dark:text-slate-400">共 {cameras.length} 台</span>}
              </DialogTitle>
            </div>
          </div>
          <DialogDescription className="mt-2 leading-6 text-slate-500 dark:text-slate-400">
            查看未在线设备及所属事业部，已停用的摄像头单独标记。
          </DialogDescription>
          {ready && cameras.length > 0 && (
            <div className="mt-3 flex flex-wrap gap-2 text-xs font-medium">
              <span className="inline-flex items-center gap-1.5 rounded-full border border-amber-200/80 bg-amber-50 px-3 py-1.5 text-amber-700 dark:border-amber-900 dark:bg-amber-950/40 dark:text-amber-300">
                <span aria-hidden="true" className="size-1.5 rounded-full bg-amber-500" />离线 {offlineCount} 台
              </span>
              <span className="inline-flex items-center gap-1.5 rounded-full border border-slate-200 bg-white/80 px-3 py-1.5 text-slate-600 dark:border-slate-700 dark:bg-slate-800 dark:text-slate-300">
                <Pause aria-hidden="true" className="size-3" />已停用 {disabledCount} 台
              </span>
            </div>
          )}
        </DialogHeader>

        <div className="min-h-0 flex-1 overflow-y-auto overscroll-contain bg-slate-50/60 px-4 py-4 dark:bg-slate-950/20 sm:px-6">
          {error ? (
            <div role="alert" className="flex gap-3 rounded-xl border border-amber-200 bg-amber-50 p-4 text-sm leading-6 text-amber-800 dark:border-amber-900 dark:bg-amber-950/40 dark:text-amber-200">
              <AlertTriangle aria-hidden="true" className="mt-0.5 size-5 shrink-0" />
              <div><p className="font-semibold">暂时无法获取离线清单</p><p className="mt-1 break-words">{error}</p></div>
            </div>
          ) : !ready ? (
            <p role="status" className="py-12 text-center text-sm text-slate-500 dark:text-slate-400">正在加载摄像头状态…</p>
          ) : cameras.length === 0 ? (
            <div role="status" className="flex flex-col items-center px-4 py-10 text-center">
              <div className="mb-4 rounded-full bg-emerald-50 p-4 ring-8 ring-emerald-50/50 dark:bg-emerald-950/50 dark:ring-emerald-950/20">
                <CheckCircle2 aria-hidden="true" className="size-8 text-emerald-600 dark:text-emerald-400" />
              </div>
              <p className="text-base font-semibold text-slate-800 dark:text-slate-100">当前暂无离线摄像头</p>
              <p className="mt-2 text-sm text-slate-500 dark:text-slate-400">当前可见范围内没有未在线设备。</p>
            </div>
          ) : (
            <ul aria-label="离线摄像头列表" className="space-y-2.5">
              {cameras.map((camera) => (
                <li key={camera.key} className="flex items-start gap-3 rounded-xl border border-slate-200/80 bg-white p-4 shadow-sm dark:border-slate-800 dark:bg-slate-900">
                  <div className={cn('flex size-10 shrink-0 items-center justify-center rounded-xl', camera.enabled ? 'bg-amber-50 text-amber-600 dark:bg-amber-950/40 dark:text-amber-400' : 'bg-slate-100 text-slate-400 dark:bg-slate-800 dark:text-slate-500')}>
                    {camera.enabled ? <VideoOff aria-hidden="true" className="size-5" /> : <Pause aria-hidden="true" className="size-5" />}
                  </div>
                  <div className="min-w-0 flex-1">
                    <div className="flex flex-wrap items-start justify-between gap-x-3 gap-y-2">
                      <p className="min-w-0 flex-1 break-words text-sm font-semibold leading-6 text-slate-800 dark:text-slate-100">{camera.name}</p>
                      <span className={cn('shrink-0 rounded-md px-2 py-1 text-xs font-medium', camera.enabled ? 'bg-amber-50 text-amber-700 dark:bg-amber-950/40 dark:text-amber-300' : 'bg-slate-100 text-slate-500 dark:bg-slate-800 dark:text-slate-400')}>
                        {camera.enabled ? '离线' : '已停用'}
                      </span>
                    </div>
                    <div className="mt-1.5 flex items-start gap-1.5 text-xs leading-5 text-slate-500 dark:text-slate-400">
                      <Building2 aria-hidden="true" className="mt-0.5 size-3.5 shrink-0" />
                      <span>{DEPARTMENT_LABELS[camera.department]}</span>
                    </div>
                    <p className="mt-1 break-all text-xs leading-5 text-slate-400 dark:text-slate-500">设备编号 · {camera.camera_id}</p>
                  </div>
                </li>
              ))}
            </ul>
          )}
        </div>

        <div className="flex shrink-0 flex-wrap items-center justify-between gap-x-4 gap-y-1 border-t border-slate-200/80 bg-white px-5 py-3 text-xs leading-5 text-slate-500 dark:border-slate-800 dark:bg-slate-900 dark:text-slate-400 sm:px-6">
          <span className="inline-flex items-center gap-1.5"><Clock3 aria-hidden="true" className="size-3.5" />随平台总览每 30 秒更新</span>
          <span>汇总数量包含已停用设备</span>
        </div>
      </DialogContent>
    </Dialog>
  )
}
