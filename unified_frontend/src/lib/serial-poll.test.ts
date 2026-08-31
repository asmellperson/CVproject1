// 文件说明：包含`serial-poll.test` 模块的自动化测试、测试夹具与断言辅助代码。
// 数据流：接收属性、状态或响应数据，并将结果交给组件、接口层或测试断言。

import type { useSerialPoll } from '../hooks/use-serial-poll'
import { createSerialPoller, type PollTimerHandle } from './serial-poll'

type UseSerialPollContract = (
  task: (signal: AbortSignal) => Promise<void>,
  options: {
    intervalMs: number
    timeoutMs: number
    enabled?: boolean
    onError?: (error: unknown) => void
    restartKey?: string | number
  },
) => void

type IsAssignable<From, To> = [From] extends [To] ? true : false
type AssertTrue<Value extends true> = Value

export type UseSerialPollContractAssertions = [
  AssertTrue<IsAssignable<typeof useSerialPoll, UseSerialPollContract>>,
  AssertTrue<IsAssignable<UseSerialPollContract, typeof useSerialPoll>>,
]

type Deferred = {
  promise: Promise<void>
  /**
   * 功能：计算或解析 `resolve` 对应的`serial-poll.test` 模块逻辑；输入由参数提供，处理结果见返回值说明
   * 参数：无。
   * 返回：void；返回函数类型契约声明的处理结果。
   * 调用关系：
   *   - 调用方：`unified_frontend/src/lib/serial-poll.test.ts` 的 `flushAsyncWork` 调用本符号；`unified_frontend/src/lib/serial-poll.test.ts`
   *         的 `testSerialExecutionAndSettledScheduling` 调用本符号；`unified_frontend/src/lib/serial-poll.test.ts` 的
   *         `testPauseResumeAndStopCleanup` 调用本符号；`unified_frontend/src/lib/serial-poll.test.ts` 的
   *         `testResumeDuringInFlightRunsImmediatelyAfterSettlement` 调用本符号；另有 67 处静态调用
   *   - 内部调用：不调用其他项目函数，仅进行字段声明、值返回或原地计算。
   * 副作用/注意事项：无明显外部副作用；下层调用失败时可能继续抛出异常。
   */
  resolve: () => void
  /**
   * 功能：实现 `reject` 对应的`serial-poll.test` 模块逻辑；输入由参数提供，处理结果见返回值说明
   * 参数：
   *   - `error`（unknown）：待报告、转换或判断的异常对象
   * 返回：void；返回函数类型契约声明的处理结果。
   * 调用关系：
   *   - 调用方：`unified_frontend/src/lib/serial-poll.test.ts` 的 `testTimeoutAbortsWithoutReportingAnError`
   *         调用本符号；`unified_frontend/src/lib/serial-poll.test.ts` 的 `testRealErrorsAreReportedOnce`
   *         调用本符号；`unified_frontend/src/lib/serial-poll.test.ts` 的 `testPauseResumeAndStopCleanup`
   *         调用本符号；`unified_frontend/src/lib/serial-poll.test.ts` 的 `testResumeDuringTimedOutRoundRunsImmediatelyAfterSettlement`
   *         调用本符号；另有 1 处静态调用
   *   - 内部调用：不调用其他项目函数，仅进行字段声明、值返回或原地计算。
   * 副作用/注意事项：无明显外部副作用；下层调用失败时可能继续抛出异常。
   */
  reject: (error: unknown) => void
}

type PendingTimer = {
  /**
   * 功能：实现 `callback` 对应的`serial-poll.test` 模块逻辑；输入由参数提供，处理结果见返回值说明
   * 参数：无。
   * 返回：void；返回函数类型契约声明的处理结果。
   * 调用关系：
   *   - 调用方：`unified_frontend/src/lib/serial-poll.test.ts` 的 `FakeTimers::advanceBy`
   *         调用本符号；`AiVision/platform/violation/evidence_recorder.py` 的 `AlarmEvidenceRecorder::_finish_task` 调用本符号
   *   - 内部调用：不调用其他项目函数，仅进行字段声明、值返回或原地计算。
   * 副作用/注意事项：无明显外部副作用；下层调用失败时可能继续抛出异常。
   */
  callback: () => void
  dueAtMs: number
}

/**
 * 功能：定义 `FakeTimers` 类，封装`serial-poll.test` 模块相关的状态、约束与操作
 * 参数：无。
 * 返回：FakeTimers；返回新建的 `FakeTimers` 实例。
 * 调用关系：
 *   - 调用方：`unified_frontend/src/lib/serial-poll.test.ts` 的 `testSerialExecutionAndSettledScheduling`
 *         实例化本符号；`unified_frontend/src/lib/serial-poll.test.ts` 的 `testTimeoutAbortsWithoutReportingAnError`
 *         实例化本符号；`unified_frontend/src/lib/serial-poll.test.ts` 的 `testRealErrorsAreReportedOnce`
 *         实例化本符号；`unified_frontend/src/lib/serial-poll.test.ts` 的 `testPauseResumeAndStopCleanup` 实例化本符号；另有 9 处静态调用
 *   - 内部调用：`Map`、`set`、`delete`、`advanceBy`、`entries`、`filter`、`sort`、`Number`、`callback`、`pendingCount` 等共 14 个调用。
 * 副作用/注意事项：无明显外部副作用；下层调用失败时可能继续抛出异常。
 */
class FakeTimers {
  private nowMs = 0
  private nextHandle = 1
  /**
   * 功能：实现 `timers` 对应的`serial-poll.test` 模块逻辑；输入由参数提供，处理结果见返回值说明
   * 参数：无。
   * 返回：void（由实现推断）；仅执行处理流程，不返回业务数据。
   * 调用关系：
   *   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
   *   - 内部调用：`Map`、`PollTimerHandle`。
   * 副作用/注意事项：无明显外部副作用；下层调用失败时可能继续抛出异常。
   */
  private readonly timers = new Map<PollTimerHandle, PendingTimer>()

  /**
   * 功能：更新或保存 `setTimeout` 对应的`serial-poll.test` 模块逻辑；输入由参数提供，处理结果见返回值说明
   * 参数：无。
   * 返回：未显式标注（由 TypeScript 推断）；返回实现中 `return` 表达式计算得到的结果。
   * 调用关系：
   *   - 调用方：`unified_frontend/src/lib/serial-poll.ts` 的 `createSerialPoller`
   *         调用本符号；`unified_frontend/src/components/feature_dashboard/useFeatureDashboardAlarms.ts` 的 `useFeatureDashboardAlarms`
   *         调用本符号；`unified_frontend/src/components/human_dwell/useHumanDwellMonitor.ts` 的 `useHumanDwellMonitor`
   *         调用本符号；`unified_frontend/src/components/logistics_single_person/useLogisticsSinglePersonMonitor.ts` 的
   *         `useLogisticsSinglePersonMonitor` 调用本符号
   *   - 内部调用：`set`。
   * 副作用/注意事项：无明显外部副作用；下层调用失败时可能继续抛出异常。
   */
  readonly setTimeout = (callback: () => void, delayMs: number): PollTimerHandle => {
    const handle = this.nextHandle as unknown as PollTimerHandle
    this.nextHandle += 1
    this.timers.set(handle, {
      callback,
      dueAtMs: this.nowMs + delayMs,
    })
    return handle
  }

  /**
   * 功能：删除或清理 `clearTimeout` 对应的`serial-poll.test` 模块逻辑；输入由参数提供，处理结果见返回值说明
   * 参数：无。
   * 返回：void（由实现推断）；仅执行处理流程，不返回业务数据。
   * 调用关系：
   *   - 调用方：`unified_frontend/src/lib/serial-poll.ts` 的 `createSerialPoller`
   *         调用本符号；`unified_frontend/src/components/feature_dashboard/useFeatureDashboardAlarms.ts` 的 `useFeatureDashboardAlarms`
   *         调用本符号；`unified_frontend/src/components/human_dwell/useHumanDwellMonitor.ts` 的 `useHumanDwellMonitor`
   *         调用本符号；`unified_frontend/src/components/logistics_single_person/useLogisticsSinglePersonMonitor.ts` 的
   *         `useLogisticsSinglePersonMonitor` 调用本符号
   *   - 内部调用：`delete`。
   * 副作用/注意事项：无明显外部副作用；下层调用失败时可能继续抛出异常。
   */
  readonly clearTimeout = (handle: PollTimerHandle) => {
    this.timers.delete(handle)
  }

  /**
   * 功能：实现 `advanceBy` 对应的`serial-poll.test` 模块逻辑；输入由参数提供，处理结果见返回值说明
   * 参数：
   *   - `delayMs`（number）：`delayMs` 对应的时间间隔或时长
   * 返回：void（由实现推断）；仅执行处理流程，不返回业务数据。
   * 调用关系：
   *   - 调用方：`unified_frontend/src/lib/serial-poll.test.ts` 的 `testSerialExecutionAndSettledScheduling`
   *         调用本符号；`unified_frontend/src/lib/serial-poll.test.ts` 的 `testTimeoutAbortsWithoutReportingAnError`
   *         调用本符号；`unified_frontend/src/lib/serial-poll.test.ts` 的 `testPauseResumeAndStopCleanup`
   *         调用本符号；`unified_frontend/src/lib/serial-poll.test.ts` 的 `testResumeDuringTimedOutRoundRunsImmediatelyAfterSettlement`
   *         调用本符号
   *   - 内部调用：`entries`、`filter`、`sort`、`Number`、`delete`、`callback`。
   * 副作用/注意事项：无明显外部副作用；下层调用失败时可能继续抛出异常。
   */
  advanceBy(delayMs: number) {
    const targetMs = this.nowMs + delayMs

    while (true) {
      const nextTimer = [...this.timers.entries()]
        .filter(([, timer]) => timer.dueAtMs <= targetMs)
        .sort(
          ([firstHandle, first], [secondHandle, second]) =>
            first.dueAtMs - second.dueAtMs || Number(firstHandle) - Number(secondHandle),
        )[0]

      if (!nextTimer) {
        break
      }

      const [handle, timer] = nextTimer
      this.nowMs = timer.dueAtMs
      this.timers.delete(handle)
      timer.callback()
    }

    this.nowMs = targetMs
  }

  /**
   * 功能：实现 `pendingCount` 对应的`serial-poll.test` 模块逻辑；输入由参数提供，处理结果见返回值说明
   * 参数：无。
   * 返回：未显式标注（由 TypeScript 推断）；返回实现中 `return` 表达式计算得到的结果。
   * 调用关系：
   *   - 调用方：`unified_frontend/src/lib/serial-poll.test.ts` 的 `testSerialExecutionAndSettledScheduling`
   *         调用本符号；`unified_frontend/src/lib/serial-poll.test.ts` 的 `testTimeoutAbortsWithoutReportingAnError`
   *         调用本符号；`unified_frontend/src/lib/serial-poll.test.ts` 的 `testPauseResumeAndStopCleanup`
   *         调用本符号；`unified_frontend/src/lib/serial-poll.test.ts` 的 `testPauseClearsPendingResume` 调用本符号；另有 1 处静态调用
   *   - 内部调用：不调用其他项目函数，仅进行字段声明、值返回或原地计算。
   * 副作用/注意事项：无明显外部副作用；下层调用失败时可能继续抛出异常。
   */
  pendingCount() {
    return this.timers.size
  }

  /**
   * 功能：实现 `pendingDelays` 对应的`serial-poll.test` 模块逻辑；输入由参数提供，处理结果见返回值说明
   * 参数：无。
   * 返回：未显式标注（由 TypeScript 推断）；返回实现中 `return` 表达式计算得到的结果。
   * 调用关系：
   *   - 调用方：`unified_frontend/src/lib/serial-poll.test.ts` 的 `testSerialExecutionAndSettledScheduling`
   *         调用本符号；`unified_frontend/src/lib/serial-poll.test.ts` 的 `testTimeoutAbortsWithoutReportingAnError`
   *         调用本符号；`unified_frontend/src/lib/serial-poll.test.ts` 的 `testRealErrorsAreReportedOnce`
   *         调用本符号；`unified_frontend/src/lib/serial-poll.test.ts` 的 `testPauseResumeAndStopCleanup` 调用本符号；另有 4 处静态调用
   *   - 内部调用：`values`、`map`、`sort`。
   * 副作用/注意事项：无明显外部副作用；下层调用失败时可能继续抛出异常。
   */
  pendingDelays() {
    return [...this.timers.values()]
      .map((timer) => timer.dueAtMs - this.nowMs)
      .sort((first, second) => first - second)
  }
}

/**
 * 功能：实现 `deferred` 对应的`serial-poll.test` 模块逻辑；输入由参数提供，处理结果见返回值说明
 * 参数：无。
 * 返回：Deferred；返回该函数计算、请求或构造得到的结果；具体语义由类型及调用方使用方式确定。
 * 调用关系：
 *   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
 *   - 内部调用：`Promise`。
 * 副作用/注意事项：无明显外部副作用；下层调用失败时可能继续抛出异常。
 */
function deferred(): Deferred {
  let resolve!: () => void
  let reject!: (error: unknown) => void
  const promise = new Promise<void>((resolvePromise, rejectPromise) => {
    resolve = resolvePromise
    reject = rejectPromise
  })
  return { promise, resolve, reject }
}

/**
 * 功能：实现 `assertEqual` 对应的`serial-poll.test` 模块逻辑；输入由参数提供，处理结果见返回值说明
 * 参数：
 *   - `actual`（unknown）：`actual` 对应的业务输入值
 *   - `expected`（unknown）：`expected` 对应的业务输入值
 *   - `message`（string）：用于展示、记录或发送的文本消息
 * 返回：void（由实现推断）；仅执行处理流程，不返回业务数据。
 * 调用关系：
 *   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
 *   - 内部调用：`Error`、`String`。
 * 副作用/注意事项：校验或请求失败时会主动抛出异常。
 */
function assertEqual(actual: unknown, expected: unknown, message: string) {
  if (actual !== expected) {
    throw new Error(`${message}: expected ${String(expected)}, got ${String(actual)}`)
  }
}

/**
 * 功能：实现 `assertNumbers` 对应的`serial-poll.test` 模块逻辑；输入由参数提供，处理结果见返回值说明
 * 参数：
 *   - `actual`（number[]）：`actual` 对应的业务输入值
 *   - `expected`（number[]）：`expected` 对应的业务输入值
 *   - `message`（string）：用于展示、记录或发送的文本消息
 * 返回：void（由实现推断）；仅执行处理流程，不返回业务数据。
 * 调用关系：
 *   - 调用方：`unified_frontend/src/lib/serial-poll.test.ts` 的 `testSerialExecutionAndSettledScheduling`
 *         调用本符号；`unified_frontend/src/lib/serial-poll.test.ts` 的 `testTimeoutAbortsWithoutReportingAnError`
 *         调用本符号；`unified_frontend/src/lib/serial-poll.test.ts` 的 `testRealErrorsAreReportedOnce`
 *         调用本符号；`unified_frontend/src/lib/serial-poll.test.ts` 的 `testPauseResumeAndStopCleanup` 调用本符号；另有 4 处静态调用
 *   - 内部调用：`assertEqual`、`stringify`。
 * 副作用/注意事项：无明显外部副作用；下层调用失败时可能继续抛出异常。
 */
function assertNumbers(actual: number[], expected: number[], message: string) {
  assertEqual(JSON.stringify(actual), JSON.stringify(expected), message)
}

/**
 * 功能：实现 `flushAsyncWork` 对应的`serial-poll.test` 模块逻辑；输入由参数提供，处理结果见返回值说明
 * 参数：无。
 * 返回：void（由实现推断）；仅执行处理流程，不返回业务数据。
 * 调用关系：
 *   - 调用方：`unified_frontend/src/lib/serial-poll.test.ts` 的 `testSerialExecutionAndSettledScheduling`
 *         调用本符号；`unified_frontend/src/lib/serial-poll.test.ts` 的 `testTimeoutAbortsWithoutReportingAnError`
 *         调用本符号；`unified_frontend/src/lib/serial-poll.test.ts` 的 `testRealErrorsAreReportedOnce`
 *         调用本符号；`unified_frontend/src/lib/serial-poll.test.ts` 的 `testPauseResumeAndStopCleanup` 调用本符号；另有 9 处静态调用
 *   - 内部调用：`resolve`。
 * 副作用/注意事项：无明显外部副作用；下层调用失败时可能继续抛出异常。
 */
async function flushAsyncWork() {
  await Promise.resolve()
  await Promise.resolve()
  await Promise.resolve()
  await Promise.resolve()
}

/**
 * 功能：验证 `testSerialExecutionAndSettledScheduling` 对应的`serial-poll.test` 模块逻辑；输入由参数提供，处理结果见返回值说明
 * 参数：无。
 * 返回：未显式标注（由 TypeScript 推断）；返回实现中 `return` 表达式计算得到的结果。
 * 调用关系：
 *   - 调用方：`unified_frontend/src/lib/serial-poll.test.ts` 的 `main` 调用本符号
 *   - 内部调用：`FakeTimers`、`createSerialPoller`、`deferred`、`push`、`start`、`assertEqual`、`assertNumbers`、`pendingDelays`、`runNow`、`advanceBy`
 *          等共 15 个调用。
 * 副作用/注意事项：会更新 React 状态并触发相关组件重新渲染。
 */
async function testSerialExecutionAndSettledScheduling() {
  const timers = new FakeTimers()
  const attempts: Array<{ completion: Deferred; signal: AbortSignal }> = []
  const poller = createSerialPoller({
    task: (signal) => {
      const completion = deferred()
      attempts.push({ completion, signal })
      return completion.promise
    },
    intervalMs: 3000,
    timeoutMs: 8000,
    setTimeoutFn: timers.setTimeout,
    clearTimeoutFn: timers.clearTimeout,
  })

  poller.start()
  assertEqual(attempts.length, 1, 'start runs immediately')
  assertNumbers(timers.pendingDelays(), [8000], 'only the request timeout is scheduled in flight')

  poller.runNow()
  timers.advanceBy(7000)
  poller.runNow()
  assertEqual(attempts.length, 1, 'runNow never overlaps an in-flight task')
  assertNumbers(timers.pendingDelays(), [1000], 'no interval is scheduled before settlement')

  attempts[0].completion.resolve()
  await flushAsyncWork()
  assertEqual(attempts.length, 2, 'queued runNow starts immediately after settlement')
  assertNumbers(timers.pendingDelays(), [8000], 'the queued round owns only its request timeout')

  poller.setPaused(false)
  assertEqual(attempts.length, 2, 'repeated setPaused(false) does not overlap the queued round')

  poller.runNow()
  poller.runNow()
  timers.advanceBy(3000)
  assertEqual(attempts.length, 2, 'repeated runNow calls coalesce without overlap')

  attempts[1].completion.resolve()
  await flushAsyncWork()
  assertEqual(attempts.length, 3, 'coalesced runNow starts one replacement round')
  attempts[2].completion.resolve()
  await flushAsyncWork()
  timers.advanceBy(2999)
  assertEqual(attempts.length, 3, 'the interval waits for its full delay')
  timers.advanceBy(1)
  assertEqual(attempts.length, 4, 'the next round begins after the settled interval')

  attempts[3].completion.resolve()
  await flushAsyncWork()
  poller.stop()
  assertEqual(timers.pendingCount(), 0, 'stop clears the next-round timer')
}

/**
 * 功能：验证 `testTimeoutAbortsWithoutReportingAnError` 对应的`serial-poll.test` 模块逻辑；输入由参数提供，处理结果见返回值说明
 * 参数：无。
 * 返回：未显式标注（由 TypeScript 推断）；返回实现中 `return` 表达式计算得到的结果。
 * 调用关系：
 *   - 调用方：`unified_frontend/src/lib/serial-poll.test.ts` 的 `main` 调用本符号
 *   - 内部调用：`FakeTimers`、`createSerialPoller`、`push`、`Promise`、`addEventListener`、`reject`、`Error`、`start`、`advanceBy`、`assertEqual`
 *          等共 15 个调用。
 * 副作用/注意事项：无明显外部副作用；下层调用失败时可能继续抛出异常。
 */
async function testTimeoutAbortsWithoutReportingAnError() {
  const timers = new FakeTimers()
  const signals: AbortSignal[] = []
  const errors: unknown[] = []
  const poller = createSerialPoller({
    task: (signal) => {
      signals.push(signal)
      return new Promise<void>((_resolve, reject) => {
        signal.addEventListener('abort', () => reject(new Error('request aborted')), {
          once: true,
        })
      })
    },
    intervalMs: 3000,
    timeoutMs: 8000,
    onError: (error) => errors.push(error),
    setTimeoutFn: timers.setTimeout,
    clearTimeoutFn: timers.clearTimeout,
  })

  poller.start()
  timers.advanceBy(7999)
  assertEqual(signals[0].aborted, false, 'the request remains active before eight seconds')

  timers.advanceBy(1)
  assertEqual(signals[0].aborted, true, 'the request is aborted at eight seconds')
  await flushAsyncWork()
  assertEqual(errors.length, 0, 'a timeout abort is not reported as a real error')
  assertNumbers(timers.pendingDelays(), [3000], 'timeout settlement schedules one next round')

  timers.advanceBy(3000)
  assertEqual(signals.length, 2, 'polling continues after a timed-out round settles')
  poller.stop()
  await flushAsyncWork()
  assertEqual(errors.length, 0, 'a stop abort is not reported as a real error')
  assertEqual(timers.pendingCount(), 0, 'stop clears the active request timeout')
}

/**
 * 功能：验证 `testRealErrorsAreReportedOnce` 对应的`serial-poll.test` 模块逻辑；输入由参数提供，处理结果见返回值说明
 * 参数：无。
 * 返回：void（由实现推断）；仅执行处理流程，不返回业务数据。
 * 调用关系：
 *   - 调用方：`unified_frontend/src/lib/serial-poll.test.ts` 的 `main` 调用本符号
 *   - 内部调用：`FakeTimers`、`Error`、`createSerialPoller`、`reject`、`push`、`start`、`flushAsyncWork`、`assertEqual`、`assertNumbers`、`pendingDelays`
 *          等共 11 个调用。
 * 副作用/注意事项：无明显外部副作用；下层调用失败时可能继续抛出异常。
 */
async function testRealErrorsAreReportedOnce() {
  const timers = new FakeTimers()
  const errors: unknown[] = []
  const failure = new Error('network failed')
  const poller = createSerialPoller({
    task: () => Promise.reject(failure),
    intervalMs: 3000,
    timeoutMs: 8000,
    onError: (error) => errors.push(error),
    setTimeoutFn: timers.setTimeout,
    clearTimeoutFn: timers.clearTimeout,
  })

  poller.start()
  await flushAsyncWork()
  assertEqual(errors.length, 1, 'a real task error is reported exactly once')
  assertEqual(errors[0], failure, 'onError receives the original failure')
  assertNumbers(timers.pendingDelays(), [3000], 'a failed round schedules the next round after settlement')
  poller.stop()
}

/**
 * 功能：验证 `testPauseResumeAndStopCleanup` 对应的`serial-poll.test` 模块逻辑；输入由参数提供，处理结果见返回值说明
 * 参数：无。
 * 返回：未显式标注（由 TypeScript 推断）；返回实现中 `return` 表达式计算得到的结果。
 * 调用关系：
 *   - 调用方：`unified_frontend/src/lib/serial-poll.test.ts` 的 `main` 调用本符号
 *   - 内部调用：`FakeTimers`、`createSerialPoller`、`deferred`、`addEventListener`、`reject`、`Error`、`push`、`setPaused`、`start`、`assertEqual`
 *          等共 18 个调用。
 * 副作用/注意事项：会更新 React 状态并触发相关组件重新渲染。
 */
async function testPauseResumeAndStopCleanup() {
  const timers = new FakeTimers()
  const attempts: Array<{ completion: Deferred; signal: AbortSignal }> = []
  const errors: unknown[] = []
  const poller = createSerialPoller({
    task: (signal) => {
      const completion = deferred()
      signal.addEventListener('abort', () => completion.reject(new Error('request aborted')), {
        once: true,
      })
      attempts.push({ completion, signal })
      return completion.promise
    },
    intervalMs: 3000,
    timeoutMs: 8000,
    onError: (error) => errors.push(error),
    setTimeoutFn: timers.setTimeout,
    clearTimeoutFn: timers.clearTimeout,
  })

  poller.setPaused(true)
  poller.start()
  assertEqual(attempts.length, 0, 'start does not run while paused')
  assertEqual(timers.pendingCount(), 0, 'paused start does not schedule timers')

  poller.setPaused(false)
  assertEqual(attempts.length, 1, 'resume starts immediately when idle')
  poller.setPaused(true)
  assertEqual(attempts[0].signal.aborted, false, 'pause does not abort an active request')

  attempts[0].completion.resolve()
  await flushAsyncWork()
  assertEqual(timers.pendingCount(), 0, 'a task settled while paused does not schedule another round')

  poller.setPaused(false)
  assertEqual(attempts.length, 2, 'resume starts a new round after paused settlement')
  attempts[1].completion.resolve()
  await flushAsyncWork()
  assertNumbers(timers.pendingDelays(), [3000], 'an active poller schedules its next round')

  poller.setPaused(true)
  assertEqual(timers.pendingCount(), 0, 'pause clears the scheduled next round')
  poller.setPaused(false)
  assertEqual(attempts.length, 3, 'resume immediately replaces the cleared next round')

  poller.stop()
  assertEqual(attempts[2].signal.aborted, true, 'stop aborts the active request')
  assertEqual(timers.pendingCount(), 0, 'stop clears all active timers')
  await flushAsyncWork()
  assertEqual(errors.length, 0, 'stop-triggered rejection is not reported')

  poller.runNow()
  timers.advanceBy(100_000)
  assertEqual(attempts.length, 3, 'a stopped poller does not continue scheduling')
}

/**
 * 功能：验证 `testResumeDuringInFlightRunsImmediatelyAfterSettlement` 对应的`serial-poll.test` 模块逻辑；输入由参数提供，处理结果见返回值说明
 * 参数：无。
 * 返回：未显式标注（由 TypeScript 推断）；返回实现中 `return` 表达式计算得到的结果。
 * 调用关系：
 *   - 调用方：`unified_frontend/src/lib/serial-poll.test.ts` 的 `main` 调用本符号
 *   - 内部调用：`FakeTimers`、`createSerialPoller`、`deferred`、`push`、`start`、`setPaused`、`assertEqual`、`assertNumbers`、`pendingDelays`、`resolve`
 *          等共 12 个调用。
 * 副作用/注意事项：会更新 React 状态并触发相关组件重新渲染。
 */
async function testResumeDuringInFlightRunsImmediatelyAfterSettlement() {
  const timers = new FakeTimers()
  const attempts: Array<{ completion: Deferred; signal: AbortSignal }> = []
  const poller = createSerialPoller({
    task: (signal) => {
      const completion = deferred()
      attempts.push({ completion, signal })
      return completion.promise
    },
    intervalMs: 3000,
    timeoutMs: 8000,
    setTimeoutFn: timers.setTimeout,
    clearTimeoutFn: timers.clearTimeout,
  })

  poller.start()
  poller.setPaused(true)
  poller.setPaused(false)
  assertEqual(attempts.length, 1, 'resume does not overlap an in-flight task')
  assertNumbers(timers.pendingDelays(), [8000], 'resume keeps only the active request timeout')

  attempts[0].completion.resolve()
  await flushAsyncWork()
  assertEqual(attempts.length, 2, 'resume runs immediately after the in-flight task settles')
  assertNumbers(timers.pendingDelays(), [8000], 'immediate resume does not wait for an interval')

  attempts[1].completion.resolve()
  await flushAsyncWork()
  poller.stop()
}

/**
 * 功能：验证 `testResumeDuringTimedOutRoundRunsImmediatelyAfterSettlement` 对应的`serial-poll.test` 模块逻辑；输入由参数提供，处理结果见返回值说明
 * 参数：无。
 * 返回：未显式标注（由 TypeScript 推断）；返回实现中 `return` 表达式计算得到的结果。
 * 调用关系：
 *   - 调用方：`unified_frontend/src/lib/serial-poll.test.ts` 的 `main` 调用本符号
 *   - 内部调用：`FakeTimers`、`createSerialPoller`、`push`、`max`、`Promise`、`addEventListener`、`reject`、`Error`、`finally`、`start` 等共 17
 *          个调用。
 * 副作用/注意事项：会更新 React 状态并触发相关组件重新渲染。
 */
async function testResumeDuringTimedOutRoundRunsImmediatelyAfterSettlement() {
  const timers = new FakeTimers()
  const signals: AbortSignal[] = []
  const errors: unknown[] = []
  let activeTasks = 0
  let maxActiveTasks = 0
  const poller = createSerialPoller({
    task: (signal) => {
      signals.push(signal)
      activeTasks += 1
      maxActiveTasks = Math.max(maxActiveTasks, activeTasks)
      return new Promise<void>((_resolve, reject) => {
        signal.addEventListener('abort', () => reject(new Error('request aborted')), {
          once: true,
        })
      }).finally(() => {
        activeTasks -= 1
      })
    },
    intervalMs: 3000,
    timeoutMs: 8000,
    onError: (error) => errors.push(error),
    setTimeoutFn: timers.setTimeout,
    clearTimeoutFn: timers.clearTimeout,
  })

  poller.start()
  poller.setPaused(true)
  poller.setPaused(false)
  assertEqual(signals.length, 1, 'resume does not overlap the round waiting to time out')

  timers.advanceBy(8000)
  assertEqual(signals[0].aborted, true, 'the in-flight round is aborted at its timeout')
  assertEqual(signals.length, 1, 'the replacement waits for timeout settlement')
  await flushAsyncWork()

  assertEqual(signals.length, 2, 'timeout settlement immediately runs the pending resume')
  assertEqual(maxActiveTasks, 1, 'timeout recovery never overlaps tasks')
  assertEqual(activeTasks, 1, 'only the replacement task remains active')
  assertEqual(errors.length, 0, 'the timeout abort is not reported as a real error')
  assertNumbers(timers.pendingDelays(), [8000], 'timeout recovery does not wait for an interval')

  poller.stop()
  await flushAsyncWork()
  assertEqual(errors.length, 0, 'stopping the replacement task does not report an error')
}

/**
 * 功能：验证 `testPauseClearsPendingResume` 对应的`serial-poll.test` 模块逻辑；输入由参数提供，处理结果见返回值说明
 * 参数：无。
 * 返回：未显式标注（由 TypeScript 推断）；返回实现中 `return` 表达式计算得到的结果。
 * 调用关系：
 *   - 调用方：`unified_frontend/src/lib/serial-poll.test.ts` 的 `main` 调用本符号
 *   - 内部调用：`FakeTimers`、`createSerialPoller`、`deferred`、`push`、`start`、`setPaused`、`resolve`、`flushAsyncWork`、`assertEqual`、`pendingCount`
 *          等共 13 个调用。
 * 副作用/注意事项：会更新 React 状态并触发相关组件重新渲染。
 */
async function testPauseClearsPendingResume() {
  const timers = new FakeTimers()
  const attempts: Deferred[] = []
  const poller = createSerialPoller({
    task: () => {
      const completion = deferred()
      attempts.push(completion)
      return completion.promise
    },
    intervalMs: 3000,
    timeoutMs: 8000,
    setTimeoutFn: timers.setTimeout,
    clearTimeoutFn: timers.clearTimeout,
  })

  poller.start()
  poller.setPaused(true)
  poller.setPaused(false)
  poller.setPaused(true)
  attempts[0].resolve()
  await flushAsyncWork()

  assertEqual(attempts.length, 1, 'pausing again clears the pending immediate resume')
  assertEqual(timers.pendingCount(), 0, 'settlement while paused leaves no timers')

  poller.setPaused(false)
  assertEqual(attempts.length, 2, 'a later resume still starts normally')
  attempts[1].resolve()
  await flushAsyncWork()
  assertEqual(attempts.length, 2, 'the cleared resume does not leak into a later round')
  assertNumbers(timers.pendingDelays(), [3000], 'the later round returns to interval scheduling')
  poller.stop()
}

/**
 * 功能：验证 `testStopClearsPendingResume` 对应的`serial-poll.test` 模块逻辑；输入由参数提供，处理结果见返回值说明
 * 参数：无。
 * 返回：未显式标注（由 TypeScript 推断）；返回实现中 `return` 表达式计算得到的结果。
 * 调用关系：
 *   - 调用方：`unified_frontend/src/lib/serial-poll.test.ts` 的 `main` 调用本符号
 *   - 内部调用：`FakeTimers`、`createSerialPoller`、`deferred`、`push`、`start`、`setPaused`、`stop`、`assertEqual`、`resolve`、`flushAsyncWork`
 *          等共 13 个调用。
 * 副作用/注意事项：会更新 React 状态并触发相关组件重新渲染。
 */
async function testStopClearsPendingResume() {
  const timers = new FakeTimers()
  const attempts: Array<{ completion: Deferred; signal: AbortSignal }> = []
  const poller = createSerialPoller({
    task: (signal) => {
      const completion = deferred()
      attempts.push({ completion, signal })
      return completion.promise
    },
    intervalMs: 3000,
    timeoutMs: 8000,
    setTimeoutFn: timers.setTimeout,
    clearTimeoutFn: timers.clearTimeout,
  })

  poller.start()
  poller.setPaused(true)
  poller.setPaused(false)
  poller.stop()
  assertEqual(attempts[0].signal.aborted, true, 'stop aborts the task with a pending resume')

  attempts[0].completion.resolve()
  await flushAsyncWork()
  assertEqual(attempts.length, 1, 'stop prevents a pending immediate run after settlement')
  assertEqual(timers.pendingCount(), 0, 'stop leaves no pending timers after settlement')

  poller.start()
  assertEqual(attempts.length, 2, 'the stopped poller can start cleanly later')
  attempts[1].completion.resolve()
  await flushAsyncWork()
  assertEqual(attempts.length, 2, 'the stopped resume intent does not leak across restart')
  assertNumbers(timers.pendingDelays(), [3000], 'restart uses normal interval scheduling')
  poller.stop()
}

/**
 * 功能：验证 `testIndependentEndpointPollersStartOnceWithoutOverlap` 对应的`serial-poll.test` 模块逻辑；输入由参数提供，处理结果见返回值说明
 * 参数：无。
 * 返回：未显式标注（由 TypeScript 推断）；返回实现中 `return` 表达式计算得到的结果。
 * 调用关系：
 *   - 调用方：`unified_frontend/src/lib/serial-poll.test.ts` 的 `main` 调用本符号
 *   - 内部调用：`FakeTimers`、`Map`、`map`、`createSerialPoller`、`deferred`、`get`、`push`、`set`、`max`、`finally` 等共 16 个调用。
 * 副作用/注意事项：无明显外部副作用；下层调用失败时可能继续抛出异常。
 */
async function testIndependentEndpointPollersStartOnceWithoutOverlap() {
  const timers = new FakeTimers()
  const endpointNames = ['list', 'status', 'summary', 'frame'] as const
  const attempts = new Map<string, Deferred[]>()
  const active = new Map<string, number>()
  const maxActive = new Map<string, number>()
  const pollers = endpointNames.map((endpoint) => createSerialPoller({
    task: () => {
      const completion = deferred()
      const endpointAttempts = attempts.get(endpoint) ?? []
      endpointAttempts.push(completion)
      attempts.set(endpoint, endpointAttempts)
      const nextActive = (active.get(endpoint) ?? 0) + 1
      active.set(endpoint, nextActive)
      maxActive.set(endpoint, Math.max(maxActive.get(endpoint) ?? 0, nextActive))
      return completion.promise.finally(() => {
        active.set(endpoint, (active.get(endpoint) ?? 1) - 1)
      })
    },
    intervalMs: 1000,
    timeoutMs: 8000,
    setTimeoutFn: timers.setTimeout,
    clearTimeoutFn: timers.clearTimeout,
  }))

  pollers.forEach((poller) => {
    poller.start()
    poller.start()
  })
  endpointNames.forEach((endpoint) => {
    assertEqual(attempts.get(endpoint)?.length, 1, `${endpoint} starts exactly one initial request`)
    assertEqual(maxActive.get(endpoint), 1, `${endpoint} never overlaps its own request`)
  })

  endpointNames.forEach((endpoint) => attempts.get(endpoint)?.[0].resolve())
  await flushAsyncWork()
  endpointNames.forEach((endpoint) => {
    assertEqual(attempts.get(endpoint)?.length, 1, `${endpoint} waits one interval after settlement`)
    assertEqual(maxActive.get(endpoint), 1, `${endpoint} remains serial after settlement`)
  })
  pollers.forEach((poller) => poller.stop())
}

/**
 * 功能：验证 `testRunNowQueuesBehindUnsettledRound` 对应的`serial-poll.test` 模块逻辑；输入由参数提供，处理结果见返回值说明
 * 参数：无。
 * 返回：未显式标注（由 TypeScript 推断）；返回实现中 `return` 表达式计算得到的结果。
 * 调用关系：
 *   - 调用方：`unified_frontend/src/lib/serial-poll.test.ts` 的 `main` 调用本符号
 *   - 内部调用：`FakeTimers`、`createSerialPoller`、`deferred`、`push`、`max`、`finally`、`start`、`runNow`、`assertEqual`、`resolve` 等共 12 个调用。
 * 副作用/注意事项：无明显外部副作用；下层调用失败时可能继续抛出异常。
 */
async function testRunNowQueuesBehindUnsettledRound() {
  const timers = new FakeTimers()
  const attempts: Deferred[] = []
  let activeTasks = 0
  let maxActiveTasks = 0
  const poller = createSerialPoller({
    task: () => {
      const completion = deferred()
      attempts.push(completion)
      activeTasks += 1
      maxActiveTasks = Math.max(maxActiveTasks, activeTasks)
      return completion.promise.finally(() => {
        activeTasks -= 1
      })
    },
    intervalMs: 1000,
    timeoutMs: 8000,
    setTimeoutFn: timers.setTimeout,
    clearTimeoutFn: timers.clearTimeout,
  })

  poller.start()
  poller.runNow()
  poller.runNow()
  assertEqual(attempts.length, 1, 'runNow does not overlap the unsettled initial round')
  assertEqual(maxActiveTasks, 1, 'only one task is active before settlement')

  attempts[0].resolve()
  await flushAsyncWork()
  assertEqual(attempts.length, 2, 'coalesced runNow runs immediately after settlement')
  assertEqual(maxActiveTasks, 1, 'runNow execution remains serial')

  attempts[1].resolve()
  await flushAsyncWork()
  poller.stop()
}

/**
 * 功能：验证 `testStopStartQueuesBehindAbortIgnoringRound` 对应的`serial-poll.test` 模块逻辑；输入由参数提供，处理结果见返回值说明
 * 参数：无。
 * 返回：未显式标注（由 TypeScript 推断）；返回实现中 `return` 表达式计算得到的结果。
 * 调用关系：
 *   - 调用方：`unified_frontend/src/lib/serial-poll.test.ts` 的 `main` 调用本符号
 *   - 内部调用：`FakeTimers`、`createSerialPoller`、`deferred`、`push`、`max`、`finally`、`start`、`stop`、`assertEqual`、`resolve` 等共 11 个调用。
 * 副作用/注意事项：无明显外部副作用；下层调用失败时可能继续抛出异常。
 */
async function testStopStartQueuesBehindAbortIgnoringRound() {
  const timers = new FakeTimers()
  const attempts: Deferred[] = []
  let activeTasks = 0
  let maxActiveTasks = 0
  const poller = createSerialPoller({
    task: () => {
      const completion = deferred()
      attempts.push(completion)
      activeTasks += 1
      maxActiveTasks = Math.max(maxActiveTasks, activeTasks)
      return completion.promise.finally(() => {
        activeTasks -= 1
      })
    },
    intervalMs: 1000,
    timeoutMs: 8000,
    setTimeoutFn: timers.setTimeout,
    clearTimeoutFn: timers.clearTimeout,
  })

  poller.start()
  poller.stop()
  poller.start()
  assertEqual(attempts.length, 1, 'stop/start does not overlap an abort-ignoring task')

  attempts[0].resolve()
  await flushAsyncWork()
  assertEqual(attempts.length, 2, 'restart waits for the stopped task to settle')
  assertEqual(maxActiveTasks, 1, 'stop/start handoff remains serial')

  attempts[1].resolve()
  await flushAsyncWork()
  poller.stop()
}

/**
 * 功能：验证 `testRunNowAbortsCooperativeRoundBeforeLatestTask` 对应的`serial-poll.test` 模块逻辑；输入由参数提供，处理结果见返回值说明
 * 参数：无。
 * 返回：未显式标注（由 TypeScript 推断）；返回实现中 `return` 表达式计算得到的结果。
 * 调用关系：
 *   - 调用方：`unified_frontend/src/lib/serial-poll.test.ts` 的 `main` 调用本符号
 *   - 内部调用：`FakeTimers`、`createSerialPoller`、`deferred`、`push`、`max`、`addEventListener`、`reject`、`Error`、`finally`、`start` 等共 15
 *          个调用。
 * 副作用/注意事项：无明显外部副作用；下层调用失败时可能继续抛出异常。
 */
async function testRunNowAbortsCooperativeRoundBeforeLatestTask() {
  const timers = new FakeTimers()
  const attempts: Array<{ label: string; completion: Deferred; signal: AbortSignal }> = []
  let currentLabel = 'A'
  let activeTasks = 0
  let maxActiveTasks = 0
  const poller = createSerialPoller({
    task: (signal) => {
      const completion = deferred()
      const attempt = { label: currentLabel, completion, signal }
      attempts.push(attempt)
      activeTasks += 1
      maxActiveTasks = Math.max(maxActiveTasks, activeTasks)
      signal.addEventListener('abort', () => completion.reject(new Error('request aborted')), {
        once: true,
      })
      return completion.promise.finally(() => {
        activeTasks -= 1
      })
    },
    intervalMs: 1000,
    timeoutMs: 8000,
    setTimeoutFn: timers.setTimeout,
    clearTimeoutFn: timers.clearTimeout,
  })

  poller.start()
  currentLabel = 'B'
  poller.runNow()
  assertEqual(attempts[0].signal.aborted, true, 'runNow aborts the stale cooperative request')
  await flushAsyncWork()
  assertEqual(attempts.length, 2, 'latest task starts as soon as abort settles the old request')
  assertEqual(attempts[1].label, 'B', 'replacement uses the latest task identity')
  assertEqual(maxActiveTasks, 1, 'cooperative abort handoff remains serial')

  attempts[1].completion.resolve()
  await flushAsyncWork()
  poller.stop()
}

/**
 * 功能：验证 `testRapidSelectionChangesCoalesceToLatestTask` 对应的`serial-poll.test` 模块逻辑；输入由参数提供，处理结果见返回值说明
 * 参数：无。
 * 返回：未显式标注（由 TypeScript 推断）；返回实现中 `return` 表达式计算得到的结果。
 * 调用关系：
 *   - 调用方：`unified_frontend/src/lib/serial-poll.test.ts` 的 `main` 调用本符号
 *   - 内部调用：`FakeTimers`、`createSerialPoller`、`deferred`、`push`、`max`、`finally`、`start`、`runNow`、`assertEqual`、`resolve` 等共 12 个调用。
 * 副作用/注意事项：无明显外部副作用；下层调用失败时可能继续抛出异常。
 */
async function testRapidSelectionChangesCoalesceToLatestTask() {
  const timers = new FakeTimers()
  const attempts: Array<{ label: string; completion: Deferred; signal: AbortSignal }> = []
  let currentLabel = 'A:first'
  let activeTasks = 0
  let maxActiveTasks = 0
  const poller = createSerialPoller({
    task: (signal) => {
      const completion = deferred()
      attempts.push({ label: currentLabel, completion, signal })
      activeTasks += 1
      maxActiveTasks = Math.max(maxActiveTasks, activeTasks)
      return completion.promise.finally(() => {
        activeTasks -= 1
      })
    },
    intervalMs: 1000,
    timeoutMs: 8000,
    setTimeoutFn: timers.setTimeout,
    clearTimeoutFn: timers.clearTimeout,
  })

  poller.start()
  currentLabel = 'B'
  poller.runNow()
  currentLabel = 'A:latest'
  poller.runNow()
  assertEqual(attempts.length, 1, 'A to B to A does not overlap an abort-ignoring request')
  assertEqual(attempts[0].signal.aborted, true, 'rapid selection change still requests stale abort')

  attempts[0].completion.resolve()
  await flushAsyncWork()
  assertEqual(attempts.length, 2, 'rapid changes coalesce to one replacement request')
  assertEqual(attempts[1].label, 'A:latest', 'replacement uses only the latest selection task')
  assertEqual(maxActiveTasks, 1, 'rapid selection handoff remains serial')

  attempts[1].completion.resolve()
  await flushAsyncWork()
  poller.stop()
}

/**
 * 功能：实现 `main` 对应的`serial-poll.test` 模块逻辑；输入由参数提供，处理结果见返回值说明
 * 参数：无。
 * 返回：void（由实现推断）；仅执行处理流程，不返回业务数据。
 * 调用关系：
 *   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
 *   - 内部调用：`testSerialExecutionAndSettledScheduling`、`testTimeoutAbortsWithoutReportingAnError`、`testRealErrorsAreReportedOnce`、`testPauseResumeAndStopCleanup`、`testResumeDuringInFlightRunsImmediatelyAfterSettlement`、`testResumeDuringTimedOutRoundRunsImmediatelyAfterSettlement`、`testPauseClearsPendingResume`、`testStopClearsPendingResume`、`testIndependentEndpointPollersStartOnceWithoutOverlap`、`testRunNowQueuesBehindUnsettledRound`
 *          等共 14 个调用。
 * 副作用/注意事项：无明显外部副作用；下层调用失败时可能继续抛出异常。
 */
async function main() {
  await testSerialExecutionAndSettledScheduling()
  await testTimeoutAbortsWithoutReportingAnError()
  await testRealErrorsAreReportedOnce()
  await testPauseResumeAndStopCleanup()
  await testResumeDuringInFlightRunsImmediatelyAfterSettlement()
  await testResumeDuringTimedOutRoundRunsImmediatelyAfterSettlement()
  await testPauseClearsPendingResume()
  await testStopClearsPendingResume()
  await testIndependentEndpointPollersStartOnceWithoutOverlap()
  await testRunNowQueuesBehindUnsettledRound()
  await testStopStartQueuesBehindAbortIgnoringRound()
  await testRunNowAbortsCooperativeRoundBeforeLatestTask()
  await testRapidSelectionChangesCoalesceToLatestTask()
  console.log('serial poll tests passed')
}

export const serialPollTestRun = main()
