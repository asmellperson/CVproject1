import { useState } from 'react'
import { useSerialPoll } from '@/hooks/use-serial-poll'
import { getFaceRecognitionStatus, type FaceRecognitionStatus } from './api'

export function useFaceRecognitionStatus(cameraKey: string, enabled: boolean) {
  const [state, setState] = useState<{ key: string; status: FaceRecognitionStatus | null; error: string } | null>(null)
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
