export type PollTimerHandle = ReturnType<typeof window.setTimeout>
export type PollIntervalMode = 'after-complete' | 'from-start'

export type SerialPoller = {
  start(): void
  stop(): void
  runNow(): void
  setPaused(paused: boolean): void
  configure(intervalMs: number, timeoutMs: number, intervalMode?: PollIntervalMode): void
}

export function createSerialPoller(options: {
  task: (signal: AbortSignal) => Promise<void>
  intervalMs: number
  timeoutMs: number
  intervalMode?: PollIntervalMode
  now?: () => number
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
  const now = options.now ?? (() => performance.now())

  let started = false
  let paused = false
  let inFlight = false
  let pendingImmediateRun = false
  let nextTimer: PollTimerHandle | undefined
  let requestTimer: PollTimerHandle | undefined
  let activeController: AbortController | undefined
  let intervalMs = options.intervalMs
  let timeoutMs = options.timeoutMs
  let intervalMode = options.intervalMode ?? 'after-complete'
  let lastRoundStartedAt: number | undefined

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

    // 预览把取图耗时计入刷新周期，业务状态轮询仍按完成后的间隔调度。
    const delayMs = intervalMode === 'from-start' && lastRoundStartedAt !== undefined
      ? Math.max(0, intervalMs - (now() - lastRoundStartedAt)) : intervalMs
    const handle = setTimeoutFn(() => {
      if (nextTimer !== handle) {
        return
      }
      nextTimer = undefined
      runRound()
    }, delayMs)
    nextTimer = handle
  }

  const runRound = () => {
    if (!started || paused || inFlight) {
      return
    }

    clearNextTimer()
    inFlight = true
    lastRoundStartedAt = now()
    const controller = new AbortController()
    activeController = controller

    const timeoutHandle = setTimeoutFn(() => {
      if (requestTimer !== timeoutHandle || activeController !== controller) {
        return
      }
      requestTimer = undefined
      controller.abort(new DOMException('请求超时', 'TimeoutError'))
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
    configure(nextIntervalMs, nextTimeoutMs, nextIntervalMode = intervalMode) {
      const intervalChanged = intervalMs !== nextIntervalMs || intervalMode !== nextIntervalMode
      intervalMs = nextIntervalMs
      timeoutMs = nextTimeoutMs
      intervalMode = nextIntervalMode
      if (intervalChanged && started && !paused && !inFlight) {
        clearNextTimer()
        scheduleNext()
      }
    },
  }
}
