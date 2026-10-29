import { useEffect, useState } from 'react'
import { useSerialPoll } from '@/hooks/use-serial-poll'
import { apiGet } from '@/lib/api'

export type DetectionDetail = { label: string; state: string; confidence?: number | null; duration_seconds?: number; hits?: number }
export type DetectionStatus = {
  camera_key: string; feature: string; online: boolean; count: number | null; alarm: boolean; reason: string
  updated_at: string | null; valid_for_seconds?: number; duration_seconds?: number | null
  threshold_seconds?: number | null; change_ratio?: number | null; hits?: number; details?: DetectionDetail[]
}

export function useDetectionStatus(cameraKey: string, feature: string, enabled = true) {
  const key = `${feature}:${cameraKey}`
  const [snapshot, setSnapshot] = useState<{ key: string; status: DetectionStatus | null; error: string; expiresAt: number } | null>(null)
  useEffect(() => {
    if (!snapshot?.status?.updated_at) return
    const timeout = window.setTimeout(() => setSnapshot((current) => current === snapshot
      ? { ...current, status: { ...current.status!, count: null, alarm: false, reason: 'stale', details: [], updated_at: null } } : current),
    Math.max(0, snapshot.expiresAt - Date.now()))
    return () => clearTimeout(timeout)
  }, [snapshot])
  useSerialPoll(async (signal) => {
    const startedAt = performance.now()
    const status = await apiGet<DetectionStatus>(`/features/${encodeURIComponent(feature)}/cameras/${encodeURIComponent(cameraKey)}/status`, { signal })
    const remaining = Math.max(0, Math.min(2, status.valid_for_seconds ?? 2) * 1000 - (performance.now() - startedAt))
    // 传输途中到期的采样不能短暂闪现为当前正常结果。
    const current = remaining <= 0 && status.updated_at
      ? { ...status, count: null, alarm: false, reason: 'stale', details: [], updated_at: null } : status
    if (!signal.aborted) setSnapshot({ key, status: current, error: '', expiresAt: Date.now() + remaining })
  }, { enabled: enabled && !!cameraKey, intervalMs: 250, timeoutMs: 5000, restartKey: key,
    onError: (error) => setSnapshot({ key, status: null, error: error instanceof Error ? error.message : '检测结果读取失败', expiresAt: 0 }) })
  return enabled && snapshot?.key === key ? snapshot : null
}
