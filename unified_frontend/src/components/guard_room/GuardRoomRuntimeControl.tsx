import type { DepartmentId } from '@/auth/permissions'
import { useState } from 'react'

import { DetectionRuntimeControl, type DetectionRuntimeState } from '@/components/detection/DetectionRuntimeControl'
import { useSerialPoll } from '@/hooks/use-serial-poll'
import {
  getGuardRoomSiteStatus,
  startGuardRoomSiteRuntime,
  stopGuardRoomSiteRuntime,
} from '@/lib/api'
import type { BackendStatus, GuardRoomSite } from '@/types'

const POLL_INTERVAL_MS = 5_000
const REQUEST_TIMEOUT_MS = 8_000

type GuardRoomRuntimeControlProps = {
  site: GuardRoomSite | null
  department: DepartmentId
  isAdmin: boolean
  onChanged: () => void | Promise<void>
}

export function GuardRoomRuntimeControl({ site, department, isAdmin, onChanged }: GuardRoomRuntimeControlProps) {
  const [status, setStatus] = useState<BackendStatus | null>(null)
  const [busyAction, setBusyAction] = useState<'start' | 'stop' | null>(null)
  const [error, setError] = useState('')

  const loadStatus = async () => {
    if (!site) {
      setStatus(null)
      setError('')
      return
    }
    const next = await getGuardRoomSiteStatus(site.id, department)
    setStatus(next)
    setError('')
  }

  useSerialPoll(loadStatus, {
    intervalMs: POLL_INTERVAL_MS,
    timeoutMs: REQUEST_TIMEOUT_MS,
    enabled: Boolean(site),
    restartKey: `${department}:${site?.id ?? ''}`,
    onError: (reason) => setError(reason instanceof Error ? reason.message : String(reason)),
  })

  const changeState = async (action: 'start' | 'stop') => {
    if (!site) return
    setBusyAction(action)
    setError('')
    try {
      if (action === 'start') await startGuardRoomSiteRuntime(site.id, department)
      else await stopGuardRoomSiteRuntime(site.id, department)
      await loadStatus()
      await onChanged()
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : String(reason))
    } finally {
      setBusyAction(null)
    }
  }

  const runtimeState: DetectionRuntimeState = !site
    ? 'stopped'
    : status?.running
      ? 'running'
      : error && status === null
        ? 'error'
        : status === null
          ? 'loading'
          : 'stopped'

  return (
    <DetectionRuntimeControl
      scope={`当前保安室 · ${site?.name ?? '未选择保安室'}`}
      state={runtimeState}
      busyAction={busyAction}
      isAdmin={isAdmin}
      disabled={!site}
      error={error}
      onStart={() => void changeState('start')}
      onStop={() => void changeState('stop')}
    />
  )
}
