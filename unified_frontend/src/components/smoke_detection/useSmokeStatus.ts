import { useEffect, useState } from 'react'
import type { DepartmentId } from '@/auth/permissions'
import { useSerialPoll } from '@/hooks/use-serial-poll'
import { readSmokeStatus, type SmokeStatus } from './api'

export function useSmokeStatus(cameraKey: string, department: DepartmentId) {
  const key = `${department}:${cameraKey}`
  const [snapshot, setSnapshot] = useState<{ key: string; value: SmokeStatus | null; expiresAt: number; error: string } | null>(null)
  useSerialPoll(async (signal) => {
    const startedAt = performance.now()
    const value = await readSmokeStatus(cameraKey, department, signal)
    const remaining = Math.max(0, (value.valid_for_seconds ?? 0) * 1000 - (performance.now() - startedAt))
    const current = remaining <= 0 && value.connection_state === 'connected'
      ? { ...value, connection_state: 'unknown', alarm_state: 'unknown' as const, alarm: null, reason: 'unknown' } : value
    if (!signal.aborted) setSnapshot({ key, value: current, expiresAt: performance.now() + remaining, error: '' })
  }, {
    enabled: Boolean(cameraKey), restartKey: key, intervalMs: 1000, timeoutMs: 5000,
    onError: (error) => setSnapshot({ key, value: null, expiresAt: 0, error: String(error) }),
  })
  useEffect(() => {
    if (snapshot?.key !== key || snapshot.value?.connection_state !== 'connected') return
    const timeout = setTimeout(() => setSnapshot((current) => current === snapshot
      ? { ...current, value: { ...current.value!, connection_state: 'unknown', alarm_state: 'unknown', alarm: null, reason: 'unknown' } } : current),
    Math.max(0, snapshot.expiresAt - performance.now()))
    return () => clearTimeout(timeout)
  }, [key, snapshot])
  return snapshot?.key === key ? snapshot : null
}
