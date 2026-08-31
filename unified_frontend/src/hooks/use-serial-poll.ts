// 文件说明：封装`use-serial-poll` 模块的 React 状态与副作用。
// 数据流：接收属性、状态或响应数据，并将结果交给组件、接口层或测试断言。

import { useEffect, useRef } from 'react'

import { createSerialPoller, type SerialPoller } from '../lib/serial-poll'

export type UseSerialPollOptions = {
  intervalMs: number
  timeoutMs: number
  enabled?: boolean
  /**
   * 功能：处理 `onError` 对应的`use-serial-poll` 模块逻辑；输入由参数提供，处理结果见返回值说明
   * 参数：
   *   - `error`（unknown）：待报告、转换或判断的异常对象
   * 返回：void；返回函数类型契约声明的处理结果。
   * 调用关系：
   *   - 调用方：`unified_frontend/src/lib/serial-poll.ts` 的 `createSerialPoller` 调用本符号
   *   - 内部调用：不调用其他项目函数，仅进行字段声明、值返回或原地计算。
   * 副作用/注意事项：无明显外部副作用；下层调用失败时可能继续抛出异常。
   */
  onError?: (error: unknown) => void
  restartKey?: string | number
}

/**
 * 功能：封装 `useSerialPoll` React Hook，向调用组件提供`use-serial-poll` 模块状态与操作
 * 参数：
 *   - `task`（(signal: AbortSignal) => Promise<void>）：`task` 对应的业务输入值；声明包含默认值 `> Promise<void>`
 *   - `props`（UseSerialPollOptions）：React 组件属性对象；解构字段包括 intervalMs, timeoutMs, enabled, true, onError, restartKey
 * 返回：void；返回该函数计算、请求或构造得到的结果；具体语义由类型及调用方使用方式确定。
 * 调用关系：
 *   - 调用方：`unified_frontend/src/components/logistics_single_person/useLogisticsChannels.ts` 的 `useLogisticsChannels`
 *         调用本符号；`unified_frontend/src/components/logistics_single_person/useLogisticsChannels.ts` 的 `useLogisticsChannelStatus`
 *         调用本符号；`unified_frontend/src/hooks/use-platform-status.ts` 的 `usePlatformStatus`
 *         调用本符号；`unified_frontend/src/components/AiVisionFeatureRuntimeControl.tsx` 的 `AiVisionFeatureRuntimeControl` 调用本符号；另有 1
 *         处静态调用
 *   - 内部调用：`useRef`、`useEffect`、`createSerialPoller`、`current`、`setPaused`、`syncVisibility`、`start`、`addEventListener`、`return`、`removeEventListener`
 *          等共 15 个调用。
 * 副作用/注意事项：会更新 React 状态并触发相关组件重新渲染；会读取或修改浏览器全局对象/DOM 状态。
 */
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
