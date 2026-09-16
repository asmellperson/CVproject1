import { useEffect, useState } from 'react'
import type { DepartmentId } from '../auth/permissions'

import {
  getPlatformStatus,
  PLATFORM_STATUS_POLL_INTERVAL_MS,
  PLATFORM_STATUS_REQUEST_TIMEOUT_MS,
  type PlatformStatus,
} from '../lib/api'
import { useSerialPoll } from './use-serial-poll'
import { PLATFORM_CAMERAS_CHANGED_EVENT } from '../lib/camera-events'
import { PLATFORM_RUNTIME_CHANGED_EVENT } from '../lib/runtime-events'

export function usePlatformStatus(department: DepartmentId | null): PlatformStatus | null {
  const [platformStatus, setPlatformStatus] = useState<{ department: DepartmentId; status: PlatformStatus } | null>(null)
  const [cameraRevision, setCameraRevision] = useState(0)

  useEffect(() => {
    const refresh = () => setCameraRevision((value) => value + 1)
    window.addEventListener(PLATFORM_CAMERAS_CHANGED_EVENT, refresh)
    window.addEventListener(PLATFORM_RUNTIME_CHANGED_EVENT, refresh)
    return () => {
      window.removeEventListener(PLATFORM_CAMERAS_CHANGED_EVENT, refresh)
      window.removeEventListener(PLATFORM_RUNTIME_CHANGED_EVENT, refresh)
    }
  }, [])

  useSerialPoll(
    async (signal) => {
      if (!department) return
      const status = await getPlatformStatus(department, { signal })
      if (!signal.aborted) setPlatformStatus({ department, status })
    },
    {
      enabled: department !== null,
      intervalMs: PLATFORM_STATUS_POLL_INTERVAL_MS,
      timeoutMs: PLATFORM_STATUS_REQUEST_TIMEOUT_MS,
      onError: () => setPlatformStatus(null),
      restartKey: `${department}:${cameraRevision}`,
    },
  )

  return platformStatus?.department === department ? platformStatus.status : null
}
