import { useEffect, useState } from 'react'
import { useSerialPoll } from '@/hooks/use-serial-poll'
import { getFenceStatus, type FenceStatus } from './api'

export function useFenceStatus(cameraKey: string) {
  const [result, setResult] = useState<{ key: string; value: FenceStatus | null; error: string } | null>(null)
  useSerialPoll(async (signal) => {
    const value = await getFenceStatus(cameraKey, signal)
    if (!signal.aborted) setResult({ key: cameraKey, value, error: '' })
  }, { enabled: Boolean(cameraKey), restartKey: cameraKey, intervalMs: 500, timeoutMs: 5000,
    onError: (error) => setResult({ key: cameraKey, value: null, error: String(error) }) })
  useEffect(() => {
    if (!result?.value || !['ready', 'error'].includes(result.value.state)) return
    const updated = Date.parse(result.value.updated_at || '')
    const remaining = Number.isFinite(updated) ? Math.max(0, Math.min(5000, updated + 5000 - Date.now())) : 0
    const timer = setTimeout(() => setResult((current) => current === result
      ? { key: cameraKey, value: null, error: '检测结果已过期，等待更新。' } : current), remaining)
    return () => clearTimeout(timer)
  }, [cameraKey, result])
  return result?.key === cameraKey ? result : null
}
