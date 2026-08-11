import { AlertTriangle, LoaderCircle, Power, PowerOff } from 'lucide-react'

import { Button } from '@/components/ui/button'
import { cn } from '@/lib/utils'

export type DetectionRuntimeState = 'loading' | 'running' | 'stopped' | 'error'

type DetectionRuntimeControlProps = {
  scope: string
  state: DetectionRuntimeState
  busyAction?: 'start' | 'stop' | null
  isAdmin: boolean
  disabled?: boolean
  allowStopWhenError?: boolean
  error?: string
  onStart: () => void
  onStop: () => void
}

const STATE_LABELS: Record<DetectionRuntimeState, string> = {
  loading: '读取中',
  running: '运行中',
  stopped: '已关闭',
  error: '状态异常',
}

export function DetectionRuntimeControl({
  scope,
  state,
  busyAction = null,
  isAdmin,
  disabled = false,
  allowStopWhenError = false,
  error,
  onStart,
  onStop,
}: DetectionRuntimeControlProps) {
  const running = state === 'running'
  const waiting = state === 'loading'
  const unavailable = disabled || waiting
  const stopAvailable = running || (state === 'error' && allowStopWhenError)

  return (
    <div className="w-full rounded-2xl border border-[#E2E7F2] bg-white px-3 py-2 shadow-[0_8px_24px_rgba(20,38,76,0.08)] dark:border-slate-800 dark:bg-slate-900 sm:w-auto">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="min-w-[132px]">
          <p className="max-w-56 truncate text-[11px] font-semibold text-[#6B7699] dark:text-slate-400">{scope}</p>
          <div className="mt-1 flex items-center gap-2 text-sm font-bold text-[#1E2A4A] dark:text-slate-100">
            {state === 'loading' ? (
              <LoaderCircle className="h-3.5 w-3.5 animate-spin text-blue-500" />
            ) : state === 'error' ? (
              <AlertTriangle className="h-3.5 w-3.5 text-amber-500" />
            ) : (
              <span className="relative flex h-2.5 w-2.5">
                {running ? <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-emerald-400 opacity-60" /> : null}
                <span className={cn('relative inline-flex h-2.5 w-2.5 rounded-full', running ? 'bg-emerald-500' : 'bg-slate-400')} />
              </span>
            )}
            {STATE_LABELS[state]}
          </div>
        </div>

        <div className="flex items-center gap-1.5">
          <Button
            type="button"
            size="sm"
            className={cn(
              'h-9 gap-1.5 rounded-xl px-3 shadow-sm',
              running
                ? 'border border-slate-200 bg-slate-100 text-slate-400 shadow-none hover:bg-slate-100 dark:border-slate-700 dark:bg-slate-800 dark:text-slate-500'
                : 'border-0 bg-gradient-to-br from-blue-600 to-indigo-600 text-white shadow-blue-200 hover:from-blue-700 hover:to-indigo-700 dark:shadow-none',
            )}
            disabled={!isAdmin || busyAction !== null || running || unavailable}
            onClick={onStart}
          >
            {busyAction === 'start' ? <LoaderCircle className="h-3.5 w-3.5 animate-spin" /> : <Power className="h-3.5 w-3.5" />}
            开启检测
          </Button>
          <Button
            type="button"
            size="sm"
            variant="outline"
            className={cn(
              'h-9 gap-1.5 rounded-xl px-3 shadow-none',
              stopAvailable
                ? 'border-rose-200 bg-rose-50 text-rose-600 hover:bg-rose-100 dark:border-rose-900 dark:bg-rose-950/50 dark:text-rose-300'
                : 'border-slate-200 bg-slate-50 text-slate-400 hover:bg-slate-50 dark:border-slate-700 dark:bg-slate-800 dark:text-slate-500',
            )}
            disabled={!isAdmin || busyAction !== null || !stopAvailable || unavailable}
            onClick={onStop}
          >
            {busyAction === 'stop' ? <LoaderCircle className="h-3.5 w-3.5 animate-spin" /> : <PowerOff className="h-3.5 w-3.5" />}
            关闭检测
          </Button>
        </div>
      </div>
      {error ? <p className="mt-1.5 max-w-96 text-xs text-rose-600 dark:text-rose-300">{error}</p> : null}
      {!isAdmin && !error ? <p className="mt-1 text-[11px] text-slate-400">仅管理员可启停，当前账号可以查看状态。</p> : null}
    </div>
  )
}
