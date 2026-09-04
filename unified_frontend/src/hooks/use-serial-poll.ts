import { useEffect, useRef } from 'react'

import { createSerialPoller, type SerialPoller } from '../lib/serial-poll'

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
  const restartKeyRef = useRef(restartKey)
  const restartEnabledRef = useRef(enabled)
  const pollerRef = useRef<SerialPoller | null>(null)
  const scheduleRef = useRef({ enabled, intervalMs, timeoutMs })

  useEffect(() => {
    taskRef.current = task
  }, [task])

  useEffect(() => {
    onErrorRef.current = onError
  }, [onError])

  useEffect(() => {
    scheduleRef.current = { enabled, intervalMs, timeoutMs }
  }, [enabled, intervalMs, timeoutMs])

  useEffect(() => {
    let poller = pollerRef.current
    if (poller === null) {
      const schedule = scheduleRef.current
      poller = createSerialPoller({
        task: (signal) => taskRef.current(signal),
        intervalMs: schedule.intervalMs,
        timeoutMs: schedule.timeoutMs,
        onError: (error) => onErrorRef.current?.(error),
      })
      pollerRef.current = poller
    }
    const syncVisibility = () => {
      poller.setPaused(!scheduleRef.current.enabled || document.visibilityState === 'hidden')
    }

    syncVisibility()
    poller.start()
    document.addEventListener('visibilitychange', syncVisibility)

    return () => {
      document.removeEventListener('visibilitychange', syncVisibility)
      poller.stop()
    }
  }, [])

  useEffect(() => {
    pollerRef.current?.configure(intervalMs, timeoutMs)
  }, [intervalMs, timeoutMs])

  useEffect(() => {
    pollerRef.current?.setPaused(!enabled || document.visibilityState === 'hidden')
  }, [enabled])

  useEffect(() => {
    const wasEnabled = restartEnabledRef.current
    const keyChanged = !Object.is(restartKeyRef.current, restartKey)
    restartEnabledRef.current = enabled
    restartKeyRef.current = restartKey
    if (!keyChanged || !enabled || !wasEnabled) {
      return
    }
    pollerRef.current?.runNow()
  }, [enabled, restartKey])
}
