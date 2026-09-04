import { useState } from 'react'

import { DetectionRuntimeControl } from '@/components/detection/DetectionRuntimeControl'

import { updateLogisticsChannel } from './api'
import type { LogisticsChannelDetail, LogisticsFeatureName } from './types'

type LogisticsChannelRuntimeControlProps = {
  feature: LogisticsFeatureName
  channel: LogisticsChannelDetail | null
  loading: boolean
  isAdmin: boolean
  onChanged: () => void
}

export function LogisticsChannelRuntimeControl({
  feature,
  channel,
  loading,
  isAdmin,
  onChanged,
}: LogisticsChannelRuntimeControlProps) {
  const [busyAction, setBusyAction] = useState<'start' | 'stop' | null>(null)
  const [error, setError] = useState('')

  const changeState = async (enabled: boolean) => {
    if (!channel) return
    setBusyAction(enabled ? 'start' : 'stop')
    setError('')
    try {
      await updateLogisticsChannel(feature, channel.id, { enabled })
      onChanged()
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : String(reason))
    } finally {
      setBusyAction(null)
    }
  }

  return (
    <DetectionRuntimeControl
      scope={`当前通道 · ${channel?.name ?? '未选择通道'}`}
      state={loading && !channel ? 'loading' : channel?.enabled ? 'running' : 'stopped'}
      busyAction={busyAction}
      isAdmin={isAdmin}
      disabled={!channel}
      error={error}
      onStart={() => void changeState(true)}
      onStop={() => void changeState(false)}
    />
  )
}
