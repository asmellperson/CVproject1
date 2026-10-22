import { useEffect, useState } from 'react'
import { useSerialPoll } from '@/hooks/use-serial-poll'
import { apiGet } from '@/lib/api'
import { expireTailgatingStatus, failTailgatingStatus, receiveTailgatingStatus } from './statusState'
import type { TailgatingStatus, TailgatingStatusResult } from './statusState'

export function useTailgatingStatus(cameraKey: string) {
  const [result, setResult] = useState<TailgatingStatusResult | null>(null)
  useSerialPoll(async (signal) => {
    const requestStartedAt = performance.now()
    const value = await apiGet<TailgatingStatus>(`/tailgating/cameras/${encodeURIComponent(cameraKey)}/status`, { signal, cache: 'no-store' })
    const receivedAt = performance.now()
    if (!signal.aborted) setResult((current) => receiveTailgatingStatus(current, value, requestStartedAt, receivedAt))
  }, { enabled: Boolean(cameraKey), restartKey: cameraKey, intervalMs: 500, timeoutMs: 5000,
    onError: (error) => {
      const now = performance.now()
      setResult((current) => failTailgatingStatus(current, cameraKey, String(error), now))
    } })
  useEffect(() => {
    if (result?.key !== cameraKey || result.expiresAt === null) return
    const remaining = Math.max(0, Math.ceil(result.expiresAt - performance.now()))
    const timer = setTimeout(() => setResult((current) => current === result
      ? expireTailgatingStatus(current) : current), remaining)
    return () => clearTimeout(timer)
  }, [cameraKey, result])
  return result?.key === cameraKey ? result : null
}
