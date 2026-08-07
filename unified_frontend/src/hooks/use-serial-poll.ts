import { useEffect, useRef } from 'react'

import { createSerialPoller } from '../lib/serial-poll'

export type UseSerialPollOptions = {
  intervalMs: number
  timeoutMs: number
  enabled?: boolean
  onError?: (error: unknown) => void
  restartKey?: string | number
}

export function useSerialPoll(
  task: (signal: AbortSignal) => Promise<void>,
  { intervalMs, timeoutMs, enabled = true, onError, restartKey }: UseSerialPollOptions,
): void {
  const taskRef = useRef(task)
  const onErrorRef = useRef(onError)

  useEffect(() => {
    taskRef.current = task
  }, [task])

  useEffect(() => {
    onErrorRef.current = onError
  }, [onError])

  useEffect(() => {
    if (!enabled) {
      return
    }

    const poller = createSerialPoller({
      task: (signal) => taskRef.current(signal),
      intervalMs,
      timeoutMs,
      onError: (error) => onErrorRef.current?.(error),
    })
    const syncVisibility = () => {
      poller.setPaused(document.visibilityState === 'hidden')
    }

    syncVisibility()
    poller.start()
    document.addEventListener('visibilitychange', syncVisibility)

    return () => {
      document.removeEventListener('visibilitychange', syncVisibility)
      poller.stop()
    }
  }, [enabled, intervalMs, restartKey, timeoutMs])
}
