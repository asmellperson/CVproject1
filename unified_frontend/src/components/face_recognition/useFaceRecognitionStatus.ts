import { useEffect, useState } from 'react'
import { useSerialPoll } from '@/hooks/use-serial-poll'
import { getFaceRecognitionStatus, type FaceRecognitionStatus } from './api'

// 与 Orchestrator 的标注帧/status 新鲜度窗口一致。
export const FACE_STATUS_FRESH_MS = 2000

export function freshFaceDetections(status: FaceRecognitionStatus | null | undefined, now = Date.now()) {
  const updatedAt = status?.updated_at ? Date.parse(status.updated_at) : NaN
  return status?.online && status.count !== null && Number.isFinite(updatedAt)
    && now - updatedAt <= FACE_STATUS_FRESH_MS ? status.detections : []
}

export function useFaceRecognitionStatus(cameraKey: string, enabled: boolean) {
  const [state, setState] = useState<{ key: string; status: FaceRecognitionStatus | null; error: string } | null>(null)
  useEffect(() => {
    if (!enabled || !state?.status) return
    const updatedAt = Date.parse(state.status.updated_at || '')
    const remaining = Number.isFinite(updatedAt)
      ? Math.min(FACE_STATUS_FRESH_MS, Math.max(0, updatedAt + FACE_STATUS_FRESH_MS - Date.now())) : 0
    // 下一次请求挂起时也到期清空，不等待网络超时或依赖视频请求。
    const timer = setTimeout(() => setState((current) => current === state
      ? { ...current, status: null } : current), remaining)
    return () => clearTimeout(timer)
  }, [enabled, state])
  useSerialPoll(async (signal) => {
    const status = await getFaceRecognitionStatus(cameraKey, signal)
    if (!signal.aborted) setState({ key: cameraKey, status, error: '' })
  }, {
    enabled: enabled && Boolean(cameraKey), restartKey: cameraKey,
    intervalMs: 500, timeoutMs: 5000,
    onError: (error) => setState({ key: cameraKey, status: null, error: error instanceof Error ? error.message : '识别状态读取失败' }),
  })
  return enabled && state?.key === cameraKey ? state : null
}
