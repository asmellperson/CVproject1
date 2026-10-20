import { useEffect, useState } from 'react'
import { useSerialPoll } from '@/hooks/use-serial-poll'
import { apiGet } from '@/lib/api'

export type TailgatingStatus = {
  camera_key: string
  state: 'disabled' | 'offline' | 'waiting' | 'stale' | 'error' | 'ready'
  reason: string
  count: number | null
  alarm: boolean
  persons: Array<{ track_id: number; in_roi: boolean; direction: number | null }>
  events: Array<{ id: string; track_ids: number[]; direction: number; overlap_seconds: number }>
  sample_interval_seconds: number | null
  updated_at: string | null
  error: string | null
}

export function useTailgatingStatus(cameraKey: string) {
  const [result, setResult] = useState<{ key: string; value: TailgatingStatus | null; error: string } | null>(null)
  useSerialPoll(async (signal) => {
    const value = await apiGet<TailgatingStatus>(`/tailgating/cameras/${encodeURIComponent(cameraKey)}/status`, { signal, cache: 'no-store' })
    if (!signal.aborted) setResult({ key: cameraKey, value, error: '' })
  }, { enabled: Boolean(cameraKey), restartKey: cameraKey, intervalMs: 500, timeoutMs: 5000,
    onError: (error) => setResult({ key: cameraKey, value: null, error: String(error) }) })
  useEffect(() => {
    if (!result?.value?.updated_at) return
    const updated = Date.parse(result.value.updated_at)
    const remaining = Number.isFinite(updated) ? Math.max(0, Math.min(2000, updated + 2000 - Date.now())) : 0
    const timer = setTimeout(() => setResult((current) => current === result
      ? { key: cameraKey, value: null, error: '检测结果已过期，等待更新。' } : current), remaining)
    return () => clearTimeout(timer)
  }, [cameraKey, result])
  return result?.key === cameraKey ? result : null
}
