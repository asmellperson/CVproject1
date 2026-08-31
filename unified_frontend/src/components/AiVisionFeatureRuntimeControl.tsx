// 文件说明：实现运行时的 React 展示与交互。
// 数据流：接收属性、状态或响应数据，并将结果交给组件、接口层或测试断言。

import { useState } from 'react'

import { DetectionRuntimeControl, type DetectionRuntimeState } from '@/components/detection/DetectionRuntimeControl'
import { useSerialPoll } from '@/hooks/use-serial-poll'
import {
  getAiVisionCapabilities,
  startAiVisionCapability,
  stopAiVisionCapability,
  type AiVisionCapabilityStatus,
} from '@/lib/aivision'

const CAPABILITY_POLL_INTERVAL_MS = 5_000
const CAPABILITY_REQUEST_TIMEOUT_MS = 8_000

type Props = {
  feature: string
  isAdmin: boolean
}

/**
 * 功能：渲染 `AiVisionFeatureRuntimeControl` React 组件，根据输入属性组织界面并返回 JSX 节点
 * 参数：
 *   - `props`（Props）：React 组件属性对象；解构字段包括 feature, isAdmin
 * 返回：JSX.Element（由 React 推断）；返回用于界面渲染的 React 元素树。
 * 调用关系：
 *   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
 *   - 内部调用：`useState`、`async`、`getAiVisionCapabilities`、`find`、`Error`、`setStatus`、`setError`、`useSerialPoll`、`loadStatus`、`String`
 *          等共 18 个调用。
 * 副作用/注意事项：会更新 React 状态并触发相关组件重新渲染；校验或请求失败时会主动抛出异常。
 */
export function AiVisionFeatureRuntimeControl({ feature, isAdmin }: Props) {
  const [status, setStatus] = useState<AiVisionCapabilityStatus | null>(null)
  const [busyAction, setBusyAction] = useState<'start' | 'stop' | null>(null)
  const [error, setError] = useState('')

  const loadStatus = async (signal?: AbortSignal) => {
    const items = await getAiVisionCapabilities(signal)
    const next = items.find((item) => item.feature === feature)
    if (!next) throw new Error(`未找到检测能力：${feature}`)
    setStatus(next)
    setError('')
  }

  useSerialPoll(
    async (signal) => loadStatus(signal),
    {
      intervalMs: CAPABILITY_POLL_INTERVAL_MS,
      timeoutMs: CAPABILITY_REQUEST_TIMEOUT_MS,
      onError: (reason) => setError(reason instanceof Error ? reason.message : String(reason)),
    },
  )

  const changeState = async (action: 'start' | 'stop') => {
    setBusyAction(action)
    setError('')
    try {
      const next = action === 'start'
        ? await startAiVisionCapability(feature)
        : await stopAiVisionCapability(feature)
      setStatus(next)
    } catch (reason) {
      const message = reason instanceof Error ? reason.message : String(reason)
      try {
        await loadStatus()
      } catch {
        // 后续仍显示原始启停错误，便于管理员判断失败原因。
      }
      setError(message)
    } finally {
      setBusyAction(null)
    }
  }

  const running = Boolean(status?.running)
  const waiting = status === null && !error
  const runtimeState: DetectionRuntimeState = waiting
    ? 'loading'
    : running
      ? 'running'
      : status?.state === 'error' || (error && status === null)
        ? 'error'
        : 'stopped'

  return (
    <DetectionRuntimeControl
      scope="检测控制 · 本检测功能"
      state={runtimeState}
      busyAction={busyAction}
      isAdmin={isAdmin}
      error={error}
      allowStopWhenError
      onStart={() => void changeState('start')}
      onStop={() => void changeState('stop')}
    />
  )
}
