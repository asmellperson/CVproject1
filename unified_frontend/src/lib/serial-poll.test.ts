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
  resolve: () => void
  reject: (error: unknown) => void
}

type PendingTimer = {
  callback: () => void
  dueAtMs: number
}

class FakeTimers {
  private nowMs = 0
  private nextHandle = 1
  private readonly timers = new Map<PollTimerHandle, PendingTimer>()

  readonly setTimeout = (callback: () => void, delayMs: number): PollTimerHandle => {
    const handle = this.nextHandle as unknown as PollTimerHandle
    this.nextHandle += 1
    this.timers.set(handle, {
      callback,
      dueAtMs: this.nowMs + delayMs,
    })
    return handle
  }

  readonly clearTimeout = (handle: PollTimerHandle) => {
    this.timers.delete(handle)
  }

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

  pendingCount() {
    return this.timers.size
  }

  pendingDelays() {
    return [...this.timers.values()]
      .map((timer) => timer.dueAtMs - this.nowMs)
      .sort((first, second) => first - second)
  }
}

function deferred(): Deferred {
  let resolve!: () => void
  let reject!: (error: unknown) => void
  const promise = new Promise<void>((resolvePromise, rejectPromise) => {
    resolve = resolvePromise
    reject = rejectPromise
  })
  return { promise, resolve, reject }
}

function assertEqual(actual: unknown, expected: unknown, message: string) {
  if (actual !== expected) {
    throw new Error(`${message}: expected ${String(expected)}, got ${String(actual)}`)
  }
}

function assertNumbers(actual: number[], expected: number[], message: string) {
  assertEqual(JSON.stringify(actual), JSON.stringify(expected), message)
}

async function flushAsyncWork() {
  await Promise.resolve()
  await Promise.resolve()
  await Promise.resolve()
  await Promise.resolve()
}

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
  assertNumbers(timers.pendingDelays(), [3000], 'the next round is scheduled after settlement')

  timers.advanceBy(1000)
  poller.setPaused(false)
  assertEqual(attempts.length, 1, 'repeated setPaused(false) does not run while already active')
  assertNumbers(timers.pendingDelays(), [2000], 'repeated setPaused(false) preserves the interval')

  poller.runNow()
  assertEqual(attempts.length, 2, 'runNow starts immediately while idle')
  assertNumbers(timers.pendingDelays(), [8000], 'runNow replaces the scheduled next round')

  poller.runNow()
  timers.advanceBy(3000)
  assertEqual(attempts.length, 2, 'runNow and stale timer callbacks do not overlap a task')

  attempts[1].completion.resolve()
  await flushAsyncWork()
  timers.advanceBy(2999)
  assertEqual(attempts.length, 2, 'the interval waits for its full delay')
  timers.advanceBy(1)
  assertEqual(attempts.length, 3, 'the next round begins after the settled interval')

  attempts[2].completion.resolve()
  await flushAsyncWork()
  poller.stop()
  assertEqual(timers.pendingCount(), 0, 'stop clears the next-round timer')
}

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
    poller.runNow()
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
  console.log('serial poll tests passed')
}

void main()
