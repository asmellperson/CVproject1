import { useState } from 'react'
import { AlertTriangle } from 'lucide-react'
import { useSerialPoll } from '@/hooks/use-serial-poll'
import type { AlarmEvent } from '@/lib/api'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { getLatestAlarm } from './api'

export function GuardLatestAlarm({ siteId }: { siteId: number | undefined }) {
  const [alarm, setAlarm] = useState<AlarmEvent | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  useSerialPoll(async (signal) => {
    if (!siteId) return
    const next = await getLatestAlarm(siteId, signal)
    if (!signal.aborted) { setAlarm(next); setLoading(false); setError('') }
  }, { intervalMs: 5000, timeoutMs: 8000, enabled: !!siteId,
    onError: (cause) => { setAlarm(null); setLoading(false); setError(cause instanceof Error ? cause.message : String(cause)) } })
  return <Card className="rounded-2xl border-slate-200/70 bg-white shadow-sm dark:border-slate-800 dark:bg-slate-900">
    <CardHeader className="p-5 pb-3"><CardTitle className="flex items-center gap-2 text-base font-bold"><AlertTriangle className="h-4 w-4 text-amber-500" />最近报警</CardTitle></CardHeader>
    <CardContent className="px-5 pb-5">
      {error ? <p role="alert" className="text-sm text-rose-600 dark:text-rose-300">报警读取失败：{error}</p>
        : alarm ? <div className="space-y-2 rounded-xl border border-rose-100 bg-rose-50 p-4 dark:border-rose-900 dark:bg-rose-950/30">
          <p className="font-semibold text-slate-900 dark:text-slate-100">{alarm.event_label || alarm.event_type}</p>
          <p className="text-sm text-slate-600 dark:text-slate-300">{alarm.reason}</p>
          <p className="text-xs text-slate-500 dark:text-slate-400">{alarm.created_at}</p>
        </div> : <p className="text-sm text-slate-500">{!siteId ? '请选择保安室' : loading ? '正在读取报警…' : '暂无报警'}</p>}
    </CardContent>
  </Card>
}
