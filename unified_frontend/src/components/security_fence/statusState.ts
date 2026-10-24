import type { FenceStatus } from './api'

export type FenceStatusResult = {
  key: string
  value: FenceStatus | null
  error: string
  expiresAt: number | null
}

export function expireFenceStatus(result: FenceStatusResult): FenceStatusResult {
  return { key: result.key, value: null, error: '检测结果已过期，等待更新。', expiresAt: null }
}

export function receiveFenceStatus(
  current: FenceStatusResult | null,
  value: FenceStatus,
  requestStartedAt: number,
  receivedAt: number,
): FenceStatusResult {
  const result = { key: value.camera_key, value, error: '', expiresAt: null }
  if (value.state !== 'ready' && value.state !== 'error') return result

  // 沿用非法闯闸的单调计时方式，并扣除请求耗时，避免客户端时间差造成卡片闪烁。
  let expiresAt = requestStartedAt + (Number.isFinite(value.valid_for_seconds) ? value.valid_for_seconds * 1000 : 0)
  if (current?.key === value.camera_key && current.value?.updated_at === value.updated_at && current.expiresAt !== null) {
    expiresAt = Math.min(expiresAt, current.expiresAt)
  }
  // 传输途中失效的快照不先展示再撤销；同一快照也不能通过轮询反复续期。
  return expiresAt > receivedAt ? { ...result, expiresAt } : expireFenceStatus(result)
}

export function failFenceStatus(
  current: FenceStatusResult | null,
  cameraKey: string,
  error: string,
  now: number,
): FenceStatusResult {
  // 短暂通信失败保留同一摄像头尚未过期的统计值，正常放行结论不能无限保留。
  if (current?.key === cameraKey && current.expiresAt !== null && current.expiresAt > now) {
    return { ...current, error }
  }
  return { key: cameraKey, value: null, error, expiresAt: null }
}
