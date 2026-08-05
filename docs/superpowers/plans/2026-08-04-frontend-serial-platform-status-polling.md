# Frontend Serial Platform-Status Polling Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把 `Sidebar` 与 `HomeSection` 的 `/api/platform/status` 合并为浏览器内唯一一条串行轮询，为每次请求增加 8 秒取消保护，并在页面隐藏时暂停新请求。

**Architecture:** 新增一个与 React 无关、可注入定时器的串行轮询调度器，再由轻量 React hook 管理组件生命周期和 `document.visibilityState`。专用 `usePlatformStatus` hook 只在共同父级 `App` 调用一次，状态通过 props 传给常驻 `Sidebar` 与条件渲染的 `HomeSection`，从所有权上杜绝两处重复请求。`getPlatformStatus` 继续复用现有 `apiGet`，仅开放可选 `RequestInit` 以传入 `AbortSignal`。本阶段只迁移平台状态请求；首页报警与摄像头刷新仍保持现有 10 秒行为，留到设计中的阶段四单独治理。

**Tech Stack:** React 19、TypeScript、原生 `fetch` / `AbortController`、现有无测试框架的 TypeScript 脚本测试、ESLint、Vite build

---

## 范围与约束

- 本计划对应设计文档的“阶段一：前端串行状态轮询”，不修改后端聚合、动态 import、实时帧或部署方式。
- 不增加 npm 依赖。
- 不触碰当前工作区中已有的 `SecurityVlmSection` 等无关修改。
- 用户此前要求不要运行现有项目；执行时必须再次确认后，才能运行下面列出的隔离 TypeScript 测试、ESLint 或生产构建。无论是否获准，都不得启动开发服务器、后端服务、模型进程或占用现有端口。
- 每个任务只暂存并提交列出的文件，避免把用户已有修改带入提交。

## Task 1: 用测试锁定串行调度器行为

**Files:**

- Create: `unified_frontend/src/lib/serial-poll.test.ts`
- Create: `unified_frontend/src/lib/serial-poll.ts`

- [ ] **Step 1: 先写调度器契约测试**

创建 `unified_frontend/src/lib/serial-poll.test.ts`。测试使用可控的假定时器和 deferred promise，不启动浏览器或服务：

```ts
import { createSerialPoller, type PollTimerHandle } from './serial-poll'

function assert(condition: unknown, message: string): asserts condition {
  if (!condition) throw new Error(message)
}

function deferred<T>() {
  let resolve!: (value: T | PromiseLike<T>) => void
  let reject!: (reason?: unknown) => void
  const promise = new Promise<T>((nextResolve, nextReject) => {
    resolve = nextResolve
    reject = nextReject
  })
  return { promise, resolve, reject }
}

async function flushMicrotasks() {
  await Promise.resolve()
  await Promise.resolve()
}

class FakeTimers {
  private nextId = 1
  private entries = new Map<number, { callback: () => void; delayMs: number }>()

  readonly setTimeout = (callback: () => void, delayMs: number): PollTimerHandle => {
    const id = this.nextId++
    this.entries.set(id, { callback, delayMs })
    return id
  }

  readonly clearTimeout = (handle: PollTimerHandle) => {
    this.entries.delete(handle)
  }

  get size() {
    return this.entries.size
  }

  hasDelay(delayMs: number) {
    return [...this.entries.values()].some((entry) => entry.delayMs === delayMs)
  }

  runDelay(delayMs: number) {
    const match = [...this.entries.entries()].find(([, entry]) => entry.delayMs === delayMs)
    if (!match) throw new Error(`missing timer with delay ${delayMs}`)
    const [id, entry] = match
    this.entries.delete(id)
    entry.callback()
  }
}

async function testDoesNotOverlapAndSchedulesAfterSettlement() {
  const timers = new FakeTimers()
  const firstRun = deferred<void>()
  let calls = 0
  const poller = createSerialPoller({
    task: async () => {
      calls += 1
      if (calls === 1) await firstRun.promise
    },
    intervalMs: 30_000,
    timeoutMs: 8_000,
    setTimeoutFn: timers.setTimeout,
    clearTimeoutFn: timers.clearTimeout,
  })

  poller.start()
  poller.runNow()
  assert(calls === 1, 'an in-flight task must not overlap')

  firstRun.resolve()
  await flushMicrotasks()
  assert(timers.hasDelay(30_000), 'next run must be scheduled after settlement')

  timers.runDelay(30_000)
  assert(calls === 2, 'scheduled run must execute once')
  poller.stop()
}

async function testTimeoutAbortsWithoutReportingAnError() {
  const timers = new FakeTimers()
  let capturedSignal: AbortSignal | undefined
  let errorCount = 0
  const poller = createSerialPoller({
    task: (signal) => {
      capturedSignal = signal
      return new Promise<void>((_resolve, reject) => {
        signal.addEventListener('abort', () => reject(signal.reason), { once: true })
      })
    },
    intervalMs: 30_000,
    timeoutMs: 8_000,
    onError: () => { errorCount += 1 },
    setTimeoutFn: timers.setTimeout,
    clearTimeoutFn: timers.clearTimeout,
  })

  poller.start()
  timers.runDelay(8_000)
  await flushMicrotasks()
  assert(capturedSignal?.aborted, 'timeout must abort the current signal')
  assert(errorCount === 0, 'an intentional timeout must not be reported as a real error')
  poller.stop()
}

async function testPauseResumeAndStop() {
  const timers = new FakeTimers()
  const pending = deferred<void>()
  let calls = 0
  let signal: AbortSignal | undefined
  const poller = createSerialPoller({
    task: async (nextSignal) => {
      calls += 1
      signal = nextSignal
      await pending.promise
    },
    intervalMs: 30_000,
    timeoutMs: 8_000,
    setTimeoutFn: timers.setTimeout,
    clearTimeoutFn: timers.clearTimeout,
  })

  poller.setPaused(true)
  poller.start()
  assert(calls === 0, 'a hidden page must not start a request')

  poller.setPaused(false)
  assert(calls === 1, 'becoming visible must refresh immediately')

  poller.stop()
  assert(signal?.aborted, 'stop must abort the in-flight request')
  assert(timers.size === 0, 'stop must clear every timer')
  pending.resolve()
  await flushMicrotasks()
}

async function main() {
  await testDoesNotOverlapAndSchedulesAfterSettlement()
  await testTimeoutAbortsWithoutReportingAnError()
  await testPauseResumeAndStop()
  console.log('serial poll tests passed')
}

void main()
```

- [ ] **Step 2: 在获准运行验证后，确认测试先失败**

```bash
cd /usr/zyy/Fuda_CVPreject_V3/unified_frontend
FRONTEND_SERIAL_POLL_TEST_DIR="$(mktemp -d /tmp/frontend-serial-poll-test.XXXXXX)"
./node_modules/.bin/tsc \
  --target ES2022 \
  --module commonjs \
  --moduleResolution node \
  --lib ES2022,DOM \
  --skipLibCheck \
  --outDir "$FRONTEND_SERIAL_POLL_TEST_DIR" \
  src/lib/serial-poll.test.ts
```

Expected: `tsc` 报告找不到 `./serial-poll`，证明测试先于实现存在。若用户未授权运行，则记录“未运行”，不要声称测试已失败。

- [ ] **Step 3: 实现最小串行轮询调度器**

创建 `unified_frontend/src/lib/serial-poll.ts`：

```ts
export type PollTimerHandle = ReturnType<typeof window.setTimeout>

export type SerialPoller = {
  start: () => void
  stop: () => void
  runNow: () => void
  setPaused: (paused: boolean) => void
}

type SerialPollerOptions = {
  task: (signal: AbortSignal) => Promise<void>
  intervalMs: number
  timeoutMs: number
  onError?: (error: unknown) => void
  setTimeoutFn?: (callback: () => void, delayMs: number) => PollTimerHandle
  clearTimeoutFn?: (handle: PollTimerHandle) => void
}

export function createSerialPoller({
  task,
  intervalMs,
  timeoutMs,
  onError,
  setTimeoutFn = window.setTimeout,
  clearTimeoutFn = window.clearTimeout,
}: SerialPollerOptions): SerialPoller {
  let started = false
  let paused = false
  let running = false
  let nextTimer: PollTimerHandle | undefined
  let timeoutTimer: PollTimerHandle | undefined
  let controller: AbortController | undefined

  const clearNextTimer = () => {
    if (nextTimer === undefined) return
    clearTimeoutFn(nextTimer)
    nextTimer = undefined
  }

  const clearRequestTimer = () => {
    if (timeoutTimer === undefined) return
    clearTimeoutFn(timeoutTimer)
    timeoutTimer = undefined
  }

  const scheduleNext = () => {
    if (!started || paused || running) return
    clearNextTimer()
    nextTimer = setTimeoutFn(() => {
      nextTimer = undefined
      void run()
    }, intervalMs)
  }

  const run = async () => {
    if (!started || paused || running) return
    clearNextTimer()
    running = true
    const currentController = new AbortController()
    controller = currentController
    timeoutTimer = setTimeoutFn(() => currentController.abort(), timeoutMs)

    try {
      await task(currentController.signal)
    } catch (error) {
      if (!currentController.signal.aborted) onError?.(error)
    } finally {
      clearRequestTimer()
      if (controller === currentController) controller = undefined
      running = false
      scheduleNext()
    }
  }

  return {
    start() {
      if (started) return
      started = true
      if (!paused) void run()
    },
    stop() {
      started = false
      clearNextTimer()
      clearRequestTimer()
      controller?.abort()
      controller = undefined
    },
    runNow() {
      void run()
    },
    setPaused(nextPaused) {
      if (paused === nextPaused) return
      paused = nextPaused
      if (paused) {
        clearNextTimer()
      } else if (started && !running) {
        void run()
      }
    },
  }
}
```

- [ ] **Step 4: 在获准后运行调度器测试**

```bash
cd /usr/zyy/Fuda_CVPreject_V3/unified_frontend
FRONTEND_SERIAL_POLL_TEST_DIR="$(mktemp -d /tmp/frontend-serial-poll-test.XXXXXX)"
./node_modules/.bin/tsc \
  --target ES2022 \
  --module commonjs \
  --moduleResolution node \
  --lib ES2022,DOM \
  --skipLibCheck \
  --outDir "$FRONTEND_SERIAL_POLL_TEST_DIR" \
  src/lib/serial-poll.test.ts \
  src/lib/serial-poll.ts
node "$FRONTEND_SERIAL_POLL_TEST_DIR/serial-poll.test.js"
```

Expected: `serial poll tests passed`。测试仅编译并运行纯 TypeScript 文件，不启动前端或访问端口。

- [ ] **Step 5: 只提交调度器及测试**

```bash
git add -- unified_frontend/src/lib/serial-poll.ts unified_frontend/src/lib/serial-poll.test.ts
git commit -m "test: cover serial frontend polling"
```

## Task 2: 添加 React 生命周期与页面可见性适配层

**Files:**

- Create: `unified_frontend/src/hooks/use-serial-poll.ts`
- Modify: `unified_frontend/src/lib/serial-poll.test.ts`

- [ ] **Step 1: 补充 hidden / visible 的调度边界测试**

在 `testPauseResumeAndStop` 中，在恢复可见后先完成当前任务，再断言隐藏会清掉已安排的下一轮：

```ts
  poller.setPaused(false)
  assert(calls === 1, 'becoming visible must refresh immediately')

  pending.resolve()
  await flushMicrotasks()
  assert(timers.hasDelay(30_000), 'a visible page must schedule its next run')

  poller.setPaused(true)
  assert(timers.size === 0, 'becoming hidden must clear the scheduled run')

  poller.setPaused(false)
  assert(calls === 2, 'becoming visible again must refresh immediately')
  poller.stop()
  assert(signal?.aborted, 'stop must abort the in-flight request')
  assert(timers.size === 0, 'stop must clear every timer')
```

删除原来在 `poller.stop()` 后才调用的 `pending.resolve()`，避免同一个 deferred 的完成顺序与新增断言冲突。

- [ ] **Step 2: 在获准后运行测试，确认调度核心已支持可见性语义**

执行 Task 1 Step 4 的命令。

Expected: `serial poll tests passed`。

- [ ] **Step 3: 实现 React hook**

创建 `unified_frontend/src/hooks/use-serial-poll.ts`：

```ts
import { useEffect, useRef } from 'react'
import { createSerialPoller } from '@/lib/serial-poll'

type UseSerialPollOptions = {
  intervalMs: number
  timeoutMs: number
  enabled?: boolean
  onError?: (error: unknown) => void
}

export function useSerialPoll(
  task: (signal: AbortSignal) => Promise<void>,
  {
    intervalMs,
    timeoutMs,
    enabled = true,
    onError,
  }: UseSerialPollOptions,
) {
  const taskRef = useRef(task)
  const onErrorRef = useRef(onError)

  useEffect(() => {
    taskRef.current = task
  }, [task])

  useEffect(() => {
    onErrorRef.current = onError
  }, [onError])

  useEffect(() => {
    if (!enabled) return

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
  }, [enabled, intervalMs, timeoutMs])
}
```

更新 ref 的 effects 不会重建轮询器；最新回调由 ref 提供，轮询生命周期只在配置真正变化时重建。

- [ ] **Step 4: 在获准后对新增文件做定点 lint**

```bash
cd /usr/zyy/Fuda_CVPreject_V3/unified_frontend
./node_modules/.bin/eslint \
  src/lib/serial-poll.ts \
  src/lib/serial-poll.test.ts \
  src/hooks/use-serial-poll.ts
```

Expected: exit code `0`，无 lint 输出。

- [ ] **Step 5: 只提交 hook 与测试调整**

```bash
git add -- unified_frontend/src/hooks/use-serial-poll.ts unified_frontend/src/lib/serial-poll.test.ts
git commit -m "feat: add serial polling hook"
```

## Task 3: 建立全局唯一的平台状态所有者并迁移 Sidebar

**Files:**

- Modify: `unified_frontend/src/lib/api.ts`
- Create: `unified_frontend/src/hooks/use-platform-status.ts`
- Modify: `unified_frontend/src/App.tsx`
- Modify: `unified_frontend/src/components/Sidebar.tsx`

- [ ] **Step 1: 为平台状态 API 开放取消信号并统一配置常量**

在 `unified_frontend/src/lib/api.ts` 的 `PlatformStatus` 定义后增加：

```ts
export const PLATFORM_STATUS_POLL_INTERVAL_MS = 30_000
export const PLATFORM_STATUS_REQUEST_TIMEOUT_MS = 8_000

export const getPlatformStatus = (init?: RequestInit) =>
  apiGet<PlatformStatus>('/platform/status', init)
```

替换当前无参数的 `getPlatformStatus`。无参数调用仍然兼容，`signal` 会由现有 `apiGet` 的 `...init` 传入 `fetch`。

- [ ] **Step 2: 创建专用的平台状态 hook**

创建 `unified_frontend/src/hooks/use-platform-status.ts`：

```ts
import { useState } from 'react'
import { useSerialPoll } from '@/hooks/use-serial-poll'
import {
  getPlatformStatus,
  PLATFORM_STATUS_POLL_INTERVAL_MS,
  PLATFORM_STATUS_REQUEST_TIMEOUT_MS,
  type PlatformStatus,
} from '@/lib/api'

export function usePlatformStatus() {
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
```

调度器会吞掉由 8 秒时限或卸载产生的 abort，因此这两种情况保留最后一次成功状态；只有真实 HTTP / 网络错误调用 `onError`，沿用当前“平台连接异常”表现。

- [ ] **Step 3: 在 App 中只调用一次并向下传递状态**

在 `unified_frontend/src/App.tsx` 引入并调用 hook：

```ts
import { usePlatformStatus } from '@/hooks/use-platform-status'

function App() {
  const { user } = useAuth()
  const platformStatus = usePlatformStatus()
```

所有 `HomeSection` 分支都传入同一个状态：

```tsx
return <HomeSection onNavigate={handlePageChange} platformStatus={platformStatus} />
```

向常驻 Sidebar 传入状态：

```tsx
<Sidebar
  currentPage={activePage}
  onPageChange={handlePageChange}
  collapsed={sidebarCollapsed}
  onToggleCollapsed={() => setSidebarCollapsed((v) => !v)}
  mobileOpen={mobileSidebarOpen}
  onMobileClose={() => setMobileSidebarOpen(false)}
  isMobile={isMobile}
  platformStatus={platformStatus}
/>
```

`App` 在认证后的应用生命周期内常驻，因此切换页面不会销毁或新建这条轮询。

- [ ] **Step 4: 把 Sidebar 改成纯状态消费者**

调整 `unified_frontend/src/components/Sidebar.tsx` 的 imports：

```ts
import { useMemo, useState } from 'react'
import type { PlatformStatus } from '@/lib/api'
```

为 props 增加状态：

```tsx
interface SidebarProps {
  currentPage: string
  onPageChange: (page: string) => void
  collapsed: boolean
  onToggleCollapsed: () => void
  mobileOpen?: boolean
  onMobileClose?: () => void
  isMobile?: boolean
  platformStatus: PlatformStatus | null
}

export function Sidebar({
  currentPage,
  onPageChange,
  collapsed,
  onToggleCollapsed,
  mobileOpen = false,
  onMobileClose,
  isMobile = false,
  platformStatus,
}: SidebarProps) {
```

删除 Sidebar 内部的 `platformStatus` state 和整个状态轮询 effect；下方 `statusLevel`、`statusDetail`、`statusTone` 展示逻辑保持不变。

- [ ] **Step 5: 静态确认平台状态 hook 只有一个所有者**

```bash
rg -n "usePlatformStatus|getPlatformStatus|setInterval" \
  unified_frontend/src/App.tsx \
  unified_frontend/src/hooks/use-platform-status.ts \
  unified_frontend/src/components/Sidebar.tsx
```

Expected:

- `usePlatformStatus()` 只在 `App.tsx` 调用一次。
- `getPlatformStatus({ signal })` 只在 `use-platform-status.ts` 出现。
- `Sidebar.tsx` 不再包含 `getPlatformStatus` 或 `setInterval`。

- [ ] **Step 6: 在获准后执行定点 lint**

```bash
cd /usr/zyy/Fuda_CVPreject_V3/unified_frontend
./node_modules/.bin/eslint \
  src/lib/api.ts \
  src/App.tsx \
  src/components/Sidebar.tsx \
  src/lib/serial-poll.ts \
  src/hooks/use-serial-poll.ts \
  src/hooks/use-platform-status.ts
```

Expected: exit code `0`，无 lint 输出。

- [ ] **Step 7: 只提交全局所有权与 Sidebar 集成**

```bash
git add -- \
  unified_frontend/src/lib/api.ts \
  unified_frontend/src/hooks/use-platform-status.ts \
  unified_frontend/src/App.tsx \
  unified_frontend/src/components/Sidebar.tsx
git commit -m "fix: centralize platform status polling"
```

## Task 4: 将 HomeSection 改成共享状态消费者

**Files:**

- Modify: `unified_frontend/src/sections/HomeSection.tsx`

- [ ] **Step 1: 通过 props 接收 App 的平台状态**

`HomeSection.tsx` 中仍保留 `useEffect`（其他设置读取仍需要它），但从 API import 删除 `getPlatformStatus`：

```ts
import {
  getAlarms,
  type AlarmEvent,
  type PlatformServiceStatus,
  type PlatformStatus,
} from '@/lib/api'
```

给组件 props 增加共享状态，并删除组件内部的同名 `useState`：

```tsx
interface HomeSectionProps {
  onNavigate: (page: string) => void
  platformStatus: PlatformStatus | null
}

export function HomeSection({ onNavigate, platformStatus }: HomeSectionProps) {
```

删除：

```ts
const [platformStatus, setPlatformStatus] = useState<PlatformStatus | null>(null)
```

- [ ] **Step 2: 让摄像头总数直接来自现有状态摘要**

`scopedStatusSummary` 已经由最新 `platformStatus` 和 `aiVisionCameras` 推导，因此不再把同一数值重复存入 `overview`：

```ts
type OverviewState = {
  todayAlarms: number
  pendingAlarms: number
  latestAlarm: AlarmEvent | null
}

const defaultOverview: OverviewState = {
  todayAlarms: 0,
  pendingAlarms: 0,
  latestAlarm: null,
}
```

并把“接入摄像头”指标改成：

```tsx
<MetricTile
  title="接入摄像头"
  value={scopedStatusSummary.cameraTotal}
  detail="平台接入总摄像头数"
  icon={<ScanFace className="h-5 w-5" />}
  tone="cyan"
/>
```

这样平台状态成功后会立即刷新摄像头总数，也不需要因为状态变化而重启报警/摄像头 effect。

- [ ] **Step 3: 让原有 10 秒总览 effect 只读取报警和摄像头**

把 `loadOverview` 改为：

```ts
    async function loadOverview() {
      const [alarms, cameras] = await Promise.allSettled([
        getAlarms(100),
        getAiVisionCameras(),
      ])

      if (cancelled) return
      const currentAiVisionCameras = cameras.status === 'fulfilled' ? cameras.value : []
      setAiVisionCameras(currentAiVisionCameras)

      const allowedAlarmTypes = accessibleAlarmEventTypes ? new Set(accessibleAlarmEventTypes) : null
      const alarmItems = alarms.status === 'fulfilled'
        ? alarms.value.filter((alarm) => !allowedAlarmTypes || allowedAlarmTypes.has(alarm.event_type))
        : []

      setOverview({
        todayAlarms: alarmItems.filter((alarm) => isToday(alarm.created_at)).length,
        pendingAlarms: alarmItems.filter((alarm) => (alarm.disposition_status || 'pending') === 'pending').length,
        latestAlarm: alarmItems[0] || null,
      })
    }
```

同时：

- 从这个 effect 中删除 `getPlatformStatus()`、`currentStatus` 和 `setPlatformStatus(currentStatus)`。
- 首次 `loadOverview()` 失败时只执行 `setOverview(defaultOverview)`，不再清空来自 App 的平台状态。
- interval 内失败时不再调用 `setPlatformStatus(null)`；该 setter 已不存在。
- effect 依赖改为 `[accessibleAlarmEventTypes]`；该 effect 的 10 秒频率和报警/摄像头失败降级语义保持不变。

- [ ] **Step 4: 静态检查不存在遗留的第二个状态调用**

```bash
rg -n "getPlatformStatus|usePlatformStatus|setInterval" \
  unified_frontend/src/App.tsx \
  unified_frontend/src/hooks/use-platform-status.ts \
  unified_frontend/src/components/Sidebar.tsx \
  unified_frontend/src/sections/HomeSection.tsx
```

Expected:

- `getPlatformStatus({ signal })` 只在 `use-platform-status.ts` 出现一次。
- `usePlatformStatus()` 只在 `App.tsx` 调用一次。
- `Sidebar` 不包含请求或 `setInterval`。
- `HomeSection` 不包含平台状态请求；只保留一个用于报警和摄像头的 `setInterval`。

这是文本检查，不启动或执行项目。

- [ ] **Step 5: 在获准后执行定点 lint 与生产类型构建**

```bash
cd /usr/zyy/Fuda_CVPreject_V3/unified_frontend
./node_modules/.bin/eslint \
  src/lib/serial-poll.ts \
  src/lib/serial-poll.test.ts \
  src/hooks/use-serial-poll.ts \
  src/hooks/use-platform-status.ts \
  src/lib/api.ts \
  src/App.tsx \
  src/components/Sidebar.tsx \
  src/sections/HomeSection.tsx
npm run build
```

Expected: ESLint exit code `0`；Vite build 完成并输出 `dist`，无 TypeScript 错误。该命令不启动服务或占用端口，但仍须先获得用户允许。

- [ ] **Step 6: 只提交 HomeSection 集成**

```bash
git add -- unified_frontend/src/sections/HomeSection.tsx
git commit -m "fix: isolate home status polling"
```

## Task 5: 第一阶段最终复核与交付

**Files:**

- Verify only: `unified_frontend/src/lib/serial-poll.ts`
- Verify only: `unified_frontend/src/lib/serial-poll.test.ts`
- Verify only: `unified_frontend/src/hooks/use-serial-poll.ts`
- Verify only: `unified_frontend/src/hooks/use-platform-status.ts`
- Verify only: `unified_frontend/src/lib/api.ts`
- Verify only: `unified_frontend/src/App.tsx`
- Verify only: `unified_frontend/src/components/Sidebar.tsx`
- Verify only: `unified_frontend/src/sections/HomeSection.tsx`

- [ ] **Step 1: 检查提交范围，确认没有夹带用户修改**

```bash
git status --short
git diff --check HEAD~4..HEAD
git diff --stat HEAD~4..HEAD
```

Expected: 仅出现本计划列出的八个文件；`git diff --check` 无输出。若执行期间提交数量有调整，应使用实际的起始提交替代 `HEAD~4`。

- [ ] **Step 2: 在获准后重新执行最小完整验证**

依次执行 Task 1 Step 4 的纯 TypeScript 测试，以及 Task 4 Step 5 的定点 ESLint 和 `npm run build`。

Expected:

- `serial poll tests passed`
- ESLint exit code `0`
- Vite production build 成功

- [ ] **Step 3: 记录当前阶段能证明和不能证明的结论**

交付说明必须包含：

1. 修改的八个文件及职责；
2. `App` 现在拥有唯一一条平台状态轮询：“完成后等待 30 秒再发下一次”，单请求 8 秒取消；Sidebar 与 HomeSection 共享它的结果；
3. hidden 页面不发起新一轮，visible 后立即刷新；
4. 若未获准运行验证，明确写“仅完成静态实现，未运行测试或构建”；
5. 即使自动验证通过，也不能声称闲置卡死已完全解决，因为后端聚合、动态模块错误边界和 20 分钟现场观察仍属于后续阶段；
6. 下一小任务是设计文档阶段二“后端平台状态聚合服务”。

## 计划自检

- 设计目标覆盖：App 内唯一轮询、立即首轮、无重叠、8 秒 abort、卸载取消、hidden 暂停、visible 立即刷新、30 秒间隔、abort 保留最后成功状态、真实错误沿用原 UI。
- API 兼容：`getPlatformStatus()` 的无参数调用仍合法。
- 阶段边界：未迁移报警、摄像头或其他页面轮询，未修改后端和动态 import。
- 类型一致：调度器、测试与 hook 共用 `PollTimerHandle` / `AbortSignal`；测试编译命令包含 DOM 类型，测试代码不依赖 Node 全局类型。
- 无占位内容：所有目标文件、代码片段、验证命令和预期结果均已给出。
