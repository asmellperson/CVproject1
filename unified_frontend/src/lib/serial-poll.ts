export type PollTimerHandle = ReturnType<typeof window.setTimeout>

export type SerialPoller = {
  start(): void
  stop(): void
  runNow(): void
  setPaused(paused: boolean): void
}

export function createSerialPoller(options: {
  task: (signal: AbortSignal) => Promise<void>
  intervalMs: number
  timeoutMs: number
  onError?: (error: unknown) => void
  setTimeoutFn?: (callback: () => void, delayMs: number) => PollTimerHandle
  clearTimeoutFn?: (handle: PollTimerHandle) => void
}): SerialPoller {
  const setTimeoutFn =
    options.setTimeoutFn ??
    ((callback: () => void, delayMs: number) =>
      window.setTimeout(callback, delayMs) as unknown as PollTimerHandle)
  const clearTimeoutFn =
    options.clearTimeoutFn ?? ((handle: PollTimerHandle) => window.clearTimeout(handle))

  let started = false
  let paused = false
  let inFlight = false
  let nextTimer: PollTimerHandle | undefined
  let requestTimer: PollTimerHandle | undefined
  let activeController: AbortController | undefined

  const clearNextTimer = () => {
    if (nextTimer === undefined) {
      return
    }
    clearTimeoutFn(nextTimer)
    nextTimer = undefined
  }

  const clearRequestTimer = () => {
    if (requestTimer === undefined) {
      return
    }
    clearTimeoutFn(requestTimer)
    requestTimer = undefined
  }

  const scheduleNext = () => {
    if (!started || paused || inFlight || nextTimer !== undefined) {
      return
    }

    const handle = setTimeoutFn(() => {
      if (nextTimer !== handle) {
        return
      }
      nextTimer = undefined
      runRound()
    }, options.intervalMs)
    nextTimer = handle
  }

  const runRound = () => {
    if (!started || paused || inFlight) {
      return
    }

    clearNextTimer()
    inFlight = true
    const controller = new AbortController()
    activeController = controller

    const timeoutHandle = setTimeoutFn(() => {
      if (requestTimer !== timeoutHandle || activeController !== controller) {
        return
      }
      requestTimer = undefined
      controller.abort()
    }, options.timeoutMs)
    requestTimer = timeoutHandle

    void (async () => {
      try {
        await options.task(controller.signal)
      } catch (error) {
        if (!controller.signal.aborted) {
          options.onError?.(error)
        }
      } finally {
        if (activeController === controller) {
          clearRequestTimer()
          activeController = undefined
        }
        inFlight = false
        scheduleNext()
      }
    })()
  }

  return {
    start() {
      if (started) {
        return
      }
      started = true
      runRound()
    },
    stop() {
      started = false
      clearNextTimer()
      clearRequestTimer()
      activeController?.abort()
      activeController = undefined
    },
    runNow() {
      runRound()
    },
    setPaused(nextPaused) {
      if (paused === nextPaused) {
        return
      }
      paused = nextPaused
      if (paused) {
        clearNextTimer()
        return
      }
      runRound()
    },
  }
}
