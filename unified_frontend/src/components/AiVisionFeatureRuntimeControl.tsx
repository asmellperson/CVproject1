import { useState } from 'react'

import { DetectionRuntimeControl, type DetectionRuntimeState } from '@/components/detection/DetectionRuntimeControl'
import { useSerialPoll } from '@/hooks/use-serial-poll'
import {
  getAiVisionCapabilities,
  startAiVisionCapability,
  stopAiVisionCapability,
  type AiVisionCapabilityStatus,
} from '@/lib/aivision'

const CAPABILITY_POLL_INTERVAL_MS = 5_000
const CAPABILITY_REQUEST_TIMEOUT_MS = 8_000

type Props = {
  feature: string
  isAdmin: boolean
}

export function AiVisionFeatureRuntimeControl({ feature, isAdmin }: Props) {
  const [status, setStatus] = useState<AiVisionCapabilityStatus | null>(null)
  const [busyAction, setBusyAction] = useState<'start' | 'stop' | null>(null)
  const [error, setError] = useState('')

  const loadStatus = async (signal?: AbortSignal) => {
    const items = await getAiVisionCapabilities(signal)
    const next = items.find((item) => item.feature === feature)
    if (!next) throw new Error(`未找到检测能力：${feature}`)
    setStatus(next)
    setError('')
  }

  useSerialPoll(
    async (signal) => loadStatus(signal),
    {
      intervalMs: CAPABILITY_POLL_INTERVAL_MS,
      timeoutMs: CAPABILITY_REQUEST_TIMEOUT_MS,
      onError: (reason) => setError(reason instanceof Error ? reason.message : String(reason)),
    },
  )

  const changeState = async (action: 'start' | 'stop') => {
    setBusyAction(action)
    setError('')
    try {
      const next = action === 'start'
        ? await startAiVisionCapability(feature)
        : await stopAiVisionCapability(feature)
      setStatus(next)
    } catch (reason) {
      const message = reason instanceof Error ? reason.message : String(reason)
      try {
        await loadStatus()
      } catch {
        // 后续仍显示原始启停错误，便于管理员判断失败原因。
      }
      setError(message)
    } finally {
      setBusyAction(null)
    }
  }

  const running = Boolean(status?.running)
  const waiting = status === null && !error
  const runtimeState: DetectionRuntimeState = waiting
    ? 'loading'
    : running
      ? 'running'
      : status?.state === 'error' || (error && status === null)
        ? 'error'
        : 'stopped'

  return (
    <DetectionRuntimeControl
      scope="检测控制 · 本检测功能"
      state={runtimeState}
      busyAction={busyAction}
      isAdmin={isAdmin}
      error={error}
      allowStopWhenError
      onStart={() => void changeState('start')}
      onStop={() => void changeState('stop')}
    />
  )
}
