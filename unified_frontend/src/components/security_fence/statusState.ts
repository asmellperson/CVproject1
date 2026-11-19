import type { FenceStatus } from './api'
import { hasTimedStatus, statusFreshness, type StatusFreshness, type StatusRequestTiming } from '@/lib/status-freshness'

export type FenceStatusResult = {
  key: string
  value: FenceStatus | null
  error: string
  freshness: StatusFreshness | null
}

export function expireFenceStatus(result: FenceStatusResult): FenceStatusResult {
  return { ...result, value: null, error: '检测结果已过期，等待更新。' }
}

export function receiveFenceStatus(
  current: FenceStatusResult | null,
  value: FenceStatus,
  timing: StatusRequestTiming,
): FenceStatusResult {
  const previous = current?.key === value.camera_key ? current.freshness : null
  const result = { key: value.camera_key, value, error: '', freshness: previous }
  if (!hasTimedStatus(value.state)) return result

  result.freshness = statusFreshness(value.updated_at, value.valid_for_seconds, timing, previous)
  return result.freshness.expiresAt > timing.receivedAt ? result : expireFenceStatus(result)
}

export function failFenceStatus(
  current: FenceStatusResult | null,
  cameraKey: string,
  error: string,
  now: number,
): FenceStatusResult {
  // 短暂通信失败保留同一摄像头尚未过期的统计值，正常放行结论不能无限保留。
  if (current?.key === cameraKey) {
    if (hasTimedStatus(current.value?.state) && current.freshness && current.freshness.expiresAt > now) return { ...current, error }
    return { ...current, value: null, error }
  }
  return { key: cameraKey, value: null, error, freshness: null }
}
