import { useState } from 'react'
import { useSerialPoll } from '@/hooks/use-serial-poll'
import { getAgvRequestStatus, type AgvMonitorStatus } from './api'

export function useAgvRequestStatus(cameraKey: string) {
  const [result, setResult] = useState<{ key: string; value: AgvMonitorStatus | null; error: string } | null>(null)
  useSerialPoll(async (signal) => {
    const value = await getAgvRequestStatus(cameraKey, signal)
    if (!signal.aborted) setResult({ key: cameraKey, value, error: '' })
  }, {
    enabled: Boolean(cameraKey), restartKey: cameraKey, intervalMs: 500, timeoutMs: 5000,
    onError: () => setResult({ key: cameraKey, value: null, error: '请求状态读取失败，正在重试。' }),
  })
  return result?.key === cameraKey ? result : null
}
