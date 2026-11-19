import { hasTimedStatus, statusFreshness, type StatusFreshness, type StatusRequestTiming } from '@/lib/status-freshness'

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
  valid_for_seconds: number
  error: string | null
}

export type TailgatingStatusResult = {
  key: string
  value: TailgatingStatus | null
  error: string
  freshness: StatusFreshness | null
}

export function expireTailgatingStatus(result: TailgatingStatusResult): TailgatingStatusResult {
  return { ...result, value: null, error: '检测结果已过期，等待更新。' }
}

export function receiveTailgatingStatus(
  current: TailgatingStatusResult | null,
  value: TailgatingStatus,
  timing: StatusRequestTiming,
): TailgatingStatusResult {
  const previous = current?.key === value.camera_key ? current.freshness : null
  const result = { key: value.camera_key, value, error: '', freshness: previous }
  if (!hasTimedStatus(value.state)) return result

  result.freshness = statusFreshness(value.updated_at, value.valid_for_seconds, timing, previous)
  return result.freshness.expiresAt > timing.receivedAt ? result : expireTailgatingStatus(result)
}

export function failTailgatingStatus(
  current: TailgatingStatusResult | null,
  cameraKey: string,
  error: string,
  now: number,
): TailgatingStatusResult {
  // 短暂请求失败保留仍然有效的快照，截止时间不顺延，也不复用其他摄像头的数据。
  if (current?.key === cameraKey) {
    if (hasTimedStatus(current.value?.state) && current.freshness && current.freshness.expiresAt > now) return { ...current, error }
    return { ...current, value: null, error }
  }
  return { key: cameraKey, value: null, error, freshness: null }
}
