import { useEffect, useState } from 'react'
import { useSerialPoll } from '@/hooks/use-serial-poll'
import { getFenceStatus } from './api'
import { expireFenceStatus, failFenceStatus, receiveFenceStatus } from './statusState'
import type { FenceStatusResult } from './statusState'

export function useFenceStatus(cameraKey: string) {
  const [result, setResult] = useState<FenceStatusResult | null>(null)
  useSerialPoll(async (signal) => {
    const requestStartedAt = performance.now()
    const value = await getFenceStatus(cameraKey, signal)
    const receivedAt = performance.now()
    if (!signal.aborted) setResult((current) => receiveFenceStatus(current, value, requestStartedAt, receivedAt))
  }, { enabled: Boolean(cameraKey), restartKey: cameraKey, intervalMs: 500, timeoutMs: 5000,
    onError: (error) => {
      const now = performance.now()
      setResult((current) => failFenceStatus(current, cameraKey, String(error), now))
    } })
  useEffect(() => {
    if (result?.key !== cameraKey || result.expiresAt === null) return
    const remaining = Math.max(0, Math.ceil(result.expiresAt - performance.now()))
    const timer = setTimeout(() => setResult((current) => current === result
      ? expireFenceStatus(current) : current), remaining)
    return () => clearTimeout(timer)
  }, [cameraKey, result])
  return result?.key === cameraKey ? result : null
}
