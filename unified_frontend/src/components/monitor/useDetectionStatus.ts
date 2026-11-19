import { useEffect, useState } from 'react'
import { useSerialPoll } from '@/hooks/use-serial-poll'
import { apiGetStatus } from '@/lib/api'
import { statusFreshness, type StatusFreshness } from '@/lib/status-freshness'

export type DetectionDetail = { label: string; state: string; confidence?: number | null; duration_seconds?: number; hits?: number }
export type DetectionStatus = {
  camera_key: string; feature: string; online: boolean; count: number | null; alarm: boolean; reason: string
  updated_at: string | null; valid_for_seconds?: number; duration_seconds?: number | null
  threshold_seconds?: number | null; change_ratio?: number | null; hits?: number; details?: DetectionDetail[]
}

function expiredStatus(status: DetectionStatus): DetectionStatus {
  return { ...status, count: null, alarm: false, reason: 'stale', details: [], updated_at: null }
}

export function useDetectionStatus(cameraKey: string, feature: string, enabled = true) {
  const key = `${feature}:${cameraKey}`
  const [snapshot, setSnapshot] = useState<{
    key: string; status: DetectionStatus | null; error: string; freshness: StatusFreshness | null
  } | null>(null)
  useEffect(() => {
    if (!snapshot?.status?.updated_at || !snapshot.freshness) return
    const expired = expiredStatus(snapshot.status)
    const timeout = window.setTimeout(() => setSnapshot((current) => current === snapshot
      ? { ...current, status: expired } : current),
    Math.max(0, Math.ceil(snapshot.freshness.expiresAt - performance.now())))
    return () => clearTimeout(timeout)
  }, [snapshot])
  useSerialPoll(async (signal) => {
    const { value, timing } = await apiGetStatus<DetectionStatus>(
      `/features/${encodeURIComponent(feature)}/cameras/${encodeURIComponent(cameraKey)}/status`, signal,
    )
    if (!signal.aborted) setSnapshot((current) => {
      const previous = current?.key === key ? current.freshness : null
      const freshness = value.updated_at
        ? statusFreshness(value.updated_at, Math.min(2, value.valid_for_seconds ?? 2), timing, previous) : previous
      const status = value.updated_at && freshness && freshness.expiresAt <= timing.receivedAt ? expiredStatus(value) : value
      return { key, status, error: '', freshness }
    })
  }, { enabled: enabled && !!cameraKey, intervalMs: 250, timeoutMs: 5000, restartKey: key,
    onError: (error) => setSnapshot((current) => ({ key, status: null,
      error: error instanceof Error ? error.message : '检测结果读取失败', freshness: current?.key === key ? current.freshness : null })) })
  return enabled && snapshot?.key === key ? snapshot : null
}
