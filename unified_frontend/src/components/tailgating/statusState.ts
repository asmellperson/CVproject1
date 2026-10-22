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
  expiresAt: number | null
}

export function expireTailgatingStatus(result: TailgatingStatusResult): TailgatingStatusResult {
  return { key: result.key, value: null, error: '检测结果已过期，等待更新。', expiresAt: null }
}

export function receiveTailgatingStatus(
  current: TailgatingStatusResult | null,
  value: TailgatingStatus,
  requestStartedAt: number,
  receivedAt: number,
): TailgatingStatusResult {
  const result = { key: value.camera_key, value, error: '', expiresAt: null }
  if (value.state !== 'ready' && value.state !== 'error') return result

  // 使用单调时钟并扣除整个请求耗时，避免延长后端给出的剩余有效期。
  let expiresAt = requestStartedAt + (Number.isFinite(value.valid_for_seconds) ? value.valid_for_seconds * 1000 : 0)
  if (current?.key === value.camera_key && current.value?.updated_at === value.updated_at && current.expiresAt !== null) {
    expiresAt = Math.min(expiresAt, current.expiresAt)
  }
  // 已在传输途中失效的结果不能先展示再清空，否则统计卡片会闪烁。
  return expiresAt > receivedAt ? { ...result, expiresAt } : expireTailgatingStatus(result)
}

export function failTailgatingStatus(
  current: TailgatingStatusResult | null,
  cameraKey: string,
  error: string,
  now: number,
): TailgatingStatusResult {
  // 短暂请求失败保留仍然有效的快照，截止时间不顺延，也不复用其他摄像头的数据。
  if (current?.key === cameraKey && current.expiresAt !== null && current.expiresAt > now) {
    return { ...current, error }
  }
  return { key: cameraKey, value: null, error, expiresAt: null }
}
