export type PollTimerHandle = ReturnType<typeof window.setTimeout>

export type SerialPoller = {
  start(): void
  stop(): void
  runNow(): void
  setPaused(paused: boolean): void
  configure(intervalMs: number, timeoutMs: number): void
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
  let pendingImmediateRun = false
  let nextTimer: PollTimerHandle | undefined
  let requestTimer: PollTimerHandle | undefined
  let activeController: AbortController | undefined
  let intervalMs = options.intervalMs
  let timeoutMs = options.timeoutMs

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
    }, intervalMs)
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
    }, timeoutMs)
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
        const shouldRunImmediately = pendingImmediateRun && started && !paused
        pendingImmediateRun = false
        if (shouldRunImmediately) {
          runRound()
        } else {
          scheduleNext()
        }
      }
    })()
  }

  return {
    start() {
      if (started) {
        return
      }
      started = true
      if (inFlight) {
        pendingImmediateRun = true
        activeController?.abort()
        return
      }
      runRound()
    },
    stop() {
      started = false
      pendingImmediateRun = false
      clearNextTimer()
      clearRequestTimer()
      activeController?.abort()
      activeController = undefined
    },
    runNow() {
      if (!started || paused) {
        return
      }
      if (inFlight) {
        pendingImmediateRun = true
        activeController?.abort()
        return
      }
      runRound()
    },
    setPaused(nextPaused) {
      if (paused === nextPaused) {
        return
      }
      paused = nextPaused
      if (paused) {
        pendingImmediateRun = false
        clearNextTimer()
        return
      }
      if (inFlight) {
        pendingImmediateRun = true
        return
      }
      runRound()
    },
    configure(nextIntervalMs, nextTimeoutMs) {
      const intervalChanged = intervalMs !== nextIntervalMs
      intervalMs = nextIntervalMs
      timeoutMs = nextTimeoutMs
      if (intervalChanged && started && !paused && !inFlight) {
        clearNextTimer()
        scheduleNext()
      }
    },
  }
}
