import { AlertTriangle, LoaderCircle, Pause, Play } from 'lucide-react'
import { useState } from 'react'

import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { useSerialPoll } from '@/hooks/use-serial-poll'
import {
  getAiVisionCapabilities,
  startAiVisionCapability,
  stopAiVisionCapability,
  type AiVisionCapabilityStatus,
} from '@/lib/aivision'
import { cn } from '@/lib/utils'

const CAPABILITY_POLL_INTERVAL_MS = 5_000
const CAPABILITY_REQUEST_TIMEOUT_MS = 8_000

type Props = {
  feature: string
  isAdmin: boolean
}

export function AiVisionFeatureRuntimeControl({ feature, isAdmin }: Props) {
  const [status, setStatus] = useState<AiVisionCapabilityStatus | null>(null)
  const [busyAction, setBusyAction] = useState<'start' | 'stop' | null>(null)
  const [error, setError] = useState('')

  const loadStatus = async (signal?: AbortSignal) => {
    const items = await getAiVisionCapabilities(signal)
    const next = items.find((item) => item.feature === feature)
    if (!next) throw new Error(`未找到检测能力：${feature}`)
    setStatus(next)
    setError('')
  }

  useSerialPoll(
    async (signal) => loadStatus(signal),
    {
      intervalMs: CAPABILITY_POLL_INTERVAL_MS,
      timeoutMs: CAPABILITY_REQUEST_TIMEOUT_MS,
      onError: (reason) => setError(reason instanceof Error ? reason.message : String(reason)),
    },
  )

  const changeState = async (action: 'start' | 'stop') => {
    setBusyAction(action)
    setError('')
    try {
      const next = action === 'start'
        ? await startAiVisionCapability(feature)
        : await stopAiVisionCapability(feature)
      setStatus(next)
    } catch (reason) {
      const message = reason instanceof Error ? reason.message : String(reason)
      try {
        await loadStatus()
      } catch {
        // 后续仍显示原始启停错误，便于管理员判断失败原因。
      }
      setError(message)
    } finally {
      setBusyAction(null)
    }
  }

  const running = Boolean(status?.running)
  const waiting = status === null && !error
  const stateLabel = waiting
    ? '读取中'
    : running
      ? '运行中'
      : status?.state === 'error'
        ? '启动异常'
        : error && status === null
          ? '状态异常'
          : '已关闭'

  return (
    <div className="w-full rounded-2xl border border-slate-200/80 bg-white px-3 py-2 shadow-sm dark:border-slate-800 dark:bg-slate-900 sm:w-auto sm:min-w-[320px]">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div className="flex items-center gap-2">
          <span className="text-xs font-bold text-slate-600 dark:text-slate-300">检测控制</span>
          <Badge
            className={cn(
              'border-0 shadow-none',
              running && 'bg-emerald-50 text-emerald-600 dark:bg-emerald-950/60 dark:text-emerald-300',
              status?.state === 'error' && 'bg-amber-50 text-amber-700 dark:bg-amber-950/60 dark:text-amber-300',
              error && status === null && 'bg-amber-50 text-amber-700 dark:bg-amber-950/60 dark:text-amber-300',
              !running && status?.state !== 'error' && !(error && status === null) && 'bg-slate-100 text-slate-500 dark:bg-slate-800 dark:text-slate-300',
            )}
          >
            {waiting && <LoaderCircle className="mr-1 h-3 w-3 animate-spin" />}
            {(status?.state === 'error' || (error && status === null)) && <AlertTriangle className="mr-1 h-3 w-3" />}
            {stateLabel}
          </Badge>
        </div>
        <div className="flex items-center gap-1.5">
          <Button
            type="button"
            size="sm"
            variant="outline"
            className="h-8 gap-1.5 rounded-lg border-emerald-200 px-2.5 text-emerald-700 hover:bg-emerald-50 dark:border-emerald-900 dark:text-emerald-300 dark:hover:bg-emerald-950/60"
            disabled={!isAdmin || busyAction !== null || running || waiting}
            onClick={() => void changeState('start')}
          >
            {busyAction === 'start' ? <LoaderCircle className="h-3.5 w-3.5 animate-spin" /> : <Play className="h-3.5 w-3.5" />}
            开启
          </Button>
          <Button
            type="button"
            size="sm"
            variant="outline"
            className="h-8 gap-1.5 rounded-lg border-rose-200 px-2.5 text-rose-700 hover:bg-rose-50 dark:border-rose-900 dark:text-rose-300 dark:hover:bg-rose-950/60"
            disabled={!isAdmin || busyAction !== null || (!running && status?.state !== 'error') || waiting}
            onClick={() => void changeState('stop')}
          >
            {busyAction === 'stop' ? <LoaderCircle className="h-3.5 w-3.5 animate-spin" /> : <Pause className="h-3.5 w-3.5" />}
            关闭
          </Button>
        </div>
      </div>
      {error && <p className="mt-1.5 max-w-[360px] text-xs text-rose-600 dark:text-rose-300">{error}</p>}
      {!isAdmin && !error && <p className="mt-1 text-[11px] text-slate-400">仅管理员可启停，配置仍可正常查看。</p>}
    </div>
  )
}
