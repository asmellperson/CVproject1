import { useEffect, useState } from 'react'

import {
  getPlatformStatus,
  PLATFORM_STATUS_POLL_INTERVAL_MS,
  PLATFORM_STATUS_REQUEST_TIMEOUT_MS,
  type PlatformStatus,
} from '../lib/api'
import { useSerialPoll } from './use-serial-poll'
import { PLATFORM_CAMERAS_CHANGED_EVENT } from '../lib/camera-events'

export function usePlatformStatus(): PlatformStatus | null {
  const [platformStatus, setPlatformStatus] = useState<PlatformStatus | null>(null)
  const [cameraRevision, setCameraRevision] = useState(0)

  useEffect(() => {
    const refresh = () => setCameraRevision((value) => value + 1)
    window.addEventListener(PLATFORM_CAMERAS_CHANGED_EVENT, refresh)
    return () => window.removeEventListener(PLATFORM_CAMERAS_CHANGED_EVENT, refresh)
  }, [])

  useSerialPoll(
    async (signal) => {
      const status = await getPlatformStatus({ signal })
      setPlatformStatus(status)
    },
    {
      intervalMs: PLATFORM_STATUS_POLL_INTERVAL_MS,
      timeoutMs: PLATFORM_STATUS_REQUEST_TIMEOUT_MS,
      onError: () => setPlatformStatus(null),
      restartKey: cameraRevision,
    },
  )

  return platformStatus
}
