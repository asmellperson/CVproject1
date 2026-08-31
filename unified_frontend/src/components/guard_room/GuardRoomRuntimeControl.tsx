// 文件说明：实现运行时的 React 展示与交互。
// 数据流：接收属性、状态或响应数据，并将结果交给组件、接口层或测试断言。

import { useState } from 'react'

import { DetectionRuntimeControl, type DetectionRuntimeState } from '@/components/detection/DetectionRuntimeControl'
import { useSerialPoll } from '@/hooks/use-serial-poll'
import {
  getGuardRoomSiteStatus,
  startGuardRoomSiteRuntime,
  stopGuardRoomSiteRuntime,
} from '@/lib/api'
import type { BackendStatus, GuardRoomSite } from '@/types'

const POLL_INTERVAL_MS = 5_000
const REQUEST_TIMEOUT_MS = 8_000

type GuardRoomRuntimeControlProps = {
  site: GuardRoomSite | null
  department?: string
  isAdmin: boolean
  /**
   * 功能：处理 `onChanged` 对应的运行时逻辑；输入由参数提供，处理结果见返回值说明
   * 参数：无。
   * 返回：void | Promise<void>；返回函数类型契约声明的处理结果。
   * 调用关系：
   *   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
   *   - 内部调用：不调用其他项目函数，仅进行字段声明、值返回或原地计算。
   * 副作用/注意事项：无明显外部副作用；下层调用失败时可能继续抛出异常。
   */
  onChanged: () => void | Promise<void>
}

/**
 * 功能：渲染 `GuardRoomRuntimeControl` React 组件，根据输入属性组织界面并返回 JSX 节点
 * 参数：
 *   - `props`（GuardRoomRuntimeControlProps）：React 组件属性对象；解构字段包括 site, department, isAdmin, onChanged
 * 返回：JSX.Element（由 React 推断）；返回用于界面渲染的 React 元素树。
 * 调用关系：
 *   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
 *   - 内部调用：`useState`、`async`、`setStatus`、`setError`、`getGuardRoomSiteStatus`、`useSerialPoll`、`Boolean`、`String`、`setBusyAction`、`startGuardRoomSiteRuntime`
 *          等共 17 个调用。
 * 副作用/注意事项：会更新 React 状态并触发相关组件重新渲染。
 */
export function GuardRoomRuntimeControl({ site, department, isAdmin, onChanged }: GuardRoomRuntimeControlProps) {
  const [status, setStatus] = useState<BackendStatus | null>(null)
  const [busyAction, setBusyAction] = useState<'start' | 'stop' | null>(null)
  const [error, setError] = useState('')

  const loadStatus = async () => {
    if (!site) {
      setStatus(null)
      setError('')
      return
    }
    const next = await getGuardRoomSiteStatus(site.id, department)
    setStatus(next)
    setError('')
  }

  useSerialPoll(loadStatus, {
    intervalMs: POLL_INTERVAL_MS,
    timeoutMs: REQUEST_TIMEOUT_MS,
    enabled: Boolean(site),
    restartKey: `${department ?? ''}:${site?.id ?? ''}`,
    onError: (reason) => setError(reason instanceof Error ? reason.message : String(reason)),
  })

  const changeState = async (action: 'start' | 'stop') => {
    if (!site) return
    setBusyAction(action)
    setError('')
    try {
      if (action === 'start') await startGuardRoomSiteRuntime(site.id)
      else await stopGuardRoomSiteRuntime(site.id)
      await loadStatus()
      await onChanged()
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : String(reason))
    } finally {
      setBusyAction(null)
    }
  }

  const runtimeState: DetectionRuntimeState = !site
    ? 'stopped'
    : status?.running
      ? 'running'
      : error && status === null
        ? 'error'
        : status === null
          ? 'loading'
          : 'stopped'

  return (
    <DetectionRuntimeControl
      scope={`当前保安室 · ${site?.name ?? '未选择保安室'}`}
      state={runtimeState}
      busyAction={busyAction}
      isAdmin={isAdmin}
      disabled={!site}
      error={error}
      onStart={() => void changeState('start')}
      onStop={() => void changeState('stop')}
    />
  )
}
