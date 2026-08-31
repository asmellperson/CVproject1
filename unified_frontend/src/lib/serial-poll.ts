// 文件说明：实现`serial-poll` 模块相关的基础能力。
// 数据流：接收属性、状态或响应数据，并将结果交给组件、接口层或测试断言。

export type PollTimerHandle = ReturnType<typeof window.setTimeout>

export type SerialPoller = {
  /**
   * 功能：启动或执行 `start` 对应的`serial-poll` 模块逻辑；输入由参数提供，处理结果见返回值说明
   * 参数：无。
   * 返回：void；返回该函数计算、请求或构造得到的结果；具体语义由类型及调用方使用方式确定。
   * 调用关系：
   *   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
   *   - 内部调用：不调用其他项目函数，仅进行字段声明、值返回或原地计算。
   * 副作用/注意事项：无明显外部副作用；下层调用失败时可能继续抛出异常。
   */
  start(): void
  /**
   * 功能：停止并释放 `stop` 对应的`serial-poll` 模块逻辑；输入由参数提供，处理结果见返回值说明
   * 参数：无。
   * 返回：void；返回该函数计算、请求或构造得到的结果；具体语义由类型及调用方使用方式确定。
   * 调用关系：
   *   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
   *   - 内部调用：不调用其他项目函数，仅进行字段声明、值返回或原地计算。
   * 副作用/注意事项：无明显外部副作用；下层调用失败时可能继续抛出异常。
   */
  stop(): void
  /**
   * 功能：启动或执行 `runNow` 对应的`serial-poll` 模块逻辑；输入由参数提供，处理结果见返回值说明
   * 参数：无。
   * 返回：void；返回该函数计算、请求或构造得到的结果；具体语义由类型及调用方使用方式确定。
   * 调用关系：
   *   - 调用方：`unified_frontend/src/lib/serial-poll.test.ts` 的 `testSerialExecutionAndSettledScheduling`
   *         调用本符号；`unified_frontend/src/lib/serial-poll.test.ts` 的 `testPauseResumeAndStopCleanup`
   *         调用本符号；`unified_frontend/src/lib/serial-poll.test.ts` 的 `testRunNowQueuesBehindUnsettledRound`
   *         调用本符号；`unified_frontend/src/lib/serial-poll.test.ts` 的 `testRunNowAbortsCooperativeRoundBeforeLatestTask` 调用本符号；另有 2
   *         处静态调用
   *   - 内部调用：不调用其他项目函数，仅进行字段声明、值返回或原地计算。
   * 副作用/注意事项：无明显外部副作用；下层调用失败时可能继续抛出异常。
   */
  runNow(): void
  /**
   * 功能：更新或保存 `setPaused` 对应的`serial-poll` 模块逻辑；输入由参数提供，处理结果见返回值说明
   * 参数：
   *   - `paused`（boolean）：`paused` 对应的业务输入值
   * 返回：void；返回该函数计算、请求或构造得到的结果；具体语义由类型及调用方使用方式确定。
   * 调用关系：
   *   - 调用方：`unified_frontend/src/lib/serial-poll.test.ts` 的 `testSerialExecutionAndSettledScheduling`
   *         调用本符号；`unified_frontend/src/lib/serial-poll.test.ts` 的 `testPauseResumeAndStopCleanup`
   *         调用本符号；`unified_frontend/src/lib/serial-poll.test.ts` 的 `testResumeDuringInFlightRunsImmediatelyAfterSettlement`
   *         调用本符号；`unified_frontend/src/lib/serial-poll.test.ts` 的 `testResumeDuringTimedOutRoundRunsImmediatelyAfterSettlement`
   *         调用本符号；另有 3 处静态调用
   *   - 内部调用：不调用其他项目函数，仅进行字段声明、值返回或原地计算。
   * 副作用/注意事项：会更新 React 状态并触发相关组件重新渲染。
   */
  setPaused(paused: boolean): void
  /**
   * 功能：初始化或配置 `configure` 对应的`serial-poll` 模块逻辑；输入由参数提供，处理结果见返回值说明
   * 参数：
   *   - `intervalMs`（number）：`intervalMs` 对应的时间间隔或时长
   *   - `timeoutMs`（number）：`timeoutMs` 对应的时间间隔或时长
   * 返回：void；返回该函数计算、请求或构造得到的结果；具体语义由类型及调用方使用方式确定。
   * 调用关系：
   *   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
   *   - 内部调用：不调用其他项目函数，仅进行字段声明、值返回或原地计算。
   * 副作用/注意事项：无明显外部副作用；下层调用失败时可能继续抛出异常。
   */
  configure(intervalMs: number, timeoutMs: number): void
}

/**
 * 功能：创建或构建 `createSerialPoller` 对应的`serial-poll` 模块逻辑；输入由参数提供，处理结果见返回值说明
 * 参数：
 *   - `options`（{   task: (signal: AbortSignal) => Promise<void>   intervalMs: number   timeoutMs: number   onError?: (error:
 *     unknown) => void   setTimeoutFn?: (callback: () => void, delayMs: number) => PollTimerHandle   clearTimeoutFn?: (handle:
 *     PollTimerHandle) => void }）：`options` 对应的业务输入值；声明包含默认值 `> Promise<void>   intervalMs: number   timeoutMs: number   onError?:
 *     (error: unknown) => void   setTimeoutFn?: (callback: () => void, delayMs: number) => PollTimerHandle   clearTimeoutFn?:
 *     (handle: PollTimerHandle) => void }`
 * 返回：SerialPoller；返回该函数计算、请求或构造得到的结果；具体语义由类型及调用方使用方式确定。
 * 调用关系：
 *   - 调用方：`unified_frontend/src/lib/serial-poll.test.ts` 的 `testSerialExecutionAndSettledScheduling`
 *         调用本符号；`unified_frontend/src/lib/serial-poll.test.ts` 的 `testTimeoutAbortsWithoutReportingAnError`
 *         调用本符号；`unified_frontend/src/lib/serial-poll.test.ts` 的 `testRealErrorsAreReportedOnce`
 *         调用本符号；`unified_frontend/src/lib/serial-poll.test.ts` 的 `testPauseResumeAndStopCleanup` 调用本符号；另有 10 处静态调用
 *   - 内部调用：`setTimeout`、`clearTimeout`、`clearTimeoutFn`、`setTimeoutFn`、`runRound`、`clearNextTimer`、`AbortController`、`abort`、`void`、`async`
 *          等共 18 个调用。
 * 副作用/注意事项：会更新 React 状态并触发相关组件重新渲染；会读取或修改浏览器全局对象/DOM 状态。
 */
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
