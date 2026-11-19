import { useEffect, useState } from 'react'
import { useSerialPoll } from '@/hooks/use-serial-poll'
import { hasTimedStatus } from '@/lib/status-freshness'
import { getFenceStatus } from './api'
import { expireFenceStatus, failFenceStatus, receiveFenceStatus } from './statusState'
import type { FenceStatusResult } from './statusState'

export function useFenceStatus(cameraKey: string) {
  const [result, setResult] = useState<FenceStatusResult | null>(null)
  useSerialPoll(async (signal) => {
    const { value, timing } = await getFenceStatus(cameraKey, signal)
    if (!signal.aborted) setResult((current) => receiveFenceStatus(current, value, timing))
  }, { enabled: Boolean(cameraKey), restartKey: cameraKey, intervalMs: 500, timeoutMs: 5000,
    onError: (error) => {
      const now = performance.now()
      setResult((current) => failFenceStatus(current, cameraKey, String(error), now))
    } })
  useEffect(() => {
    if (result?.key !== cameraKey || !result.freshness || !hasTimedStatus(result.value?.state)) return
    const remaining = Math.max(0, Math.ceil(result.freshness.expiresAt - performance.now()))
    const timer = setTimeout(() => setResult((current) => current === result
      ? expireFenceStatus(current) : current), remaining)
    return () => clearTimeout(timer)
  }, [cameraKey, result])
  return result?.key === cameraKey ? result : null
}
