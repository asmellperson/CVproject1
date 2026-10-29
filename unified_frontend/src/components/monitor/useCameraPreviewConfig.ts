import { useState } from 'react'
import { useSerialPoll } from '@/hooks/use-serial-poll'
import { getAiVisionFeatureConfig } from '@/lib/aivision'

export function useCameraPreviewConfig(cameraKey: string, feature: string, enabled = true) {
  const key = `${feature}:${cameraKey}`
  const [snapshot, setSnapshot] = useState<{ key: string; value: Record<string, unknown> | null; error: string } | null>(null)
  useSerialPoll(async (signal) => {
    const response = await getAiVisionFeatureConfig(feature, cameraKey, signal)
    if (!signal.aborted) setSnapshot({ key, value: response.config.value || {}, error: '' })
  }, { enabled: enabled && !!cameraKey, intervalMs: 5000, timeoutMs: 8000, restartKey: key,
    onError: (error) => setSnapshot({ key, value: null, error: `检测区域读取失败：${error instanceof Error ? error.message : String(error)}` }) })
  return snapshot?.key === key ? snapshot : { key, value: null, error: '' }
}
