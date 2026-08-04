import { useState } from 'react'

import {
  getPlatformStatus,
  PLATFORM_STATUS_POLL_INTERVAL_MS,
  PLATFORM_STATUS_REQUEST_TIMEOUT_MS,
  type PlatformStatus,
} from '../lib/api'
import { useSerialPoll } from './use-serial-poll'

export function usePlatformStatus(): PlatformStatus | null {
  const [platformStatus, setPlatformStatus] = useState<PlatformStatus | null>(null)

  useSerialPoll(
    async (signal) => {
      const status = await getPlatformStatus({ signal })
      setPlatformStatus(status)
    },
    {
      intervalMs: PLATFORM_STATUS_POLL_INTERVAL_MS,
      timeoutMs: PLATFORM_STATUS_REQUEST_TIMEOUT_MS,
      onError: () => setPlatformStatus(null),
    },
  )

  return platformStatus
}
