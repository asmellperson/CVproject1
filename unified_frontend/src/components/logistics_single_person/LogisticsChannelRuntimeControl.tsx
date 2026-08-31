// 文件说明：实现运行时的 React 展示与交互。
// 数据流：接收属性、状态或响应数据，并将结果交给组件、接口层或测试断言。

import { useState } from 'react'

import { DetectionRuntimeControl } from '@/components/detection/DetectionRuntimeControl'

import { updateLogisticsChannel } from './api'
import type { LogisticsChannelDetail, LogisticsFeatureName } from './types'

type LogisticsChannelRuntimeControlProps = {
  feature: LogisticsFeatureName
  channel: LogisticsChannelDetail | null
  loading: boolean
  isAdmin: boolean
  /**
   * 功能：处理 `onChanged` 对应的运行时逻辑；输入由参数提供，处理结果见返回值说明
   * 参数：无。
   * 返回：void；返回函数类型契约声明的处理结果。
   * 调用关系：
   *   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
   *   - 内部调用：不调用其他项目函数，仅进行字段声明、值返回或原地计算。
   * 副作用/注意事项：无明显外部副作用；下层调用失败时可能继续抛出异常。
   */
  onChanged: () => void
}

/**
 * 功能：渲染 `LogisticsChannelRuntimeControl` React 组件，根据输入属性组织界面并返回 JSX 节点
 * 参数：
 *   - `props`（LogisticsChannelRuntimeControlProps）：React 组件属性对象；解构字段包括 feature, channel, loading, isAdmin, onChanged
 * 返回：JSX.Element（由 React 推断）；返回用于界面渲染的 React 元素树。
 * 调用关系：
 *   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
 *   - 内部调用：`useState`、`async`、`setBusyAction`、`setError`、`updateLogisticsChannel`、`onChanged`、`String`、`return`、`changeState`、`DetectionRuntimeControl`。
 * 副作用/注意事项：会更新 React 状态并触发相关组件重新渲染。
 */
export function LogisticsChannelRuntimeControl({
  feature,
  channel,
  loading,
  isAdmin,
  onChanged,
}: LogisticsChannelRuntimeControlProps) {
  const [busyAction, setBusyAction] = useState<'start' | 'stop' | null>(null)
  const [error, setError] = useState('')

  const changeState = async (enabled: boolean) => {
    if (!channel) return
    setBusyAction(enabled ? 'start' : 'stop')
    setError('')
    try {
      await updateLogisticsChannel(feature, channel.id, { enabled })
      onChanged()
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : String(reason))
    } finally {
      setBusyAction(null)
    }
  }

  return (
    <DetectionRuntimeControl
      scope={`当前通道 · ${channel?.name ?? '未选择通道'}`}
      state={loading && !channel ? 'loading' : channel?.enabled ? 'running' : 'stopped'}
      busyAction={busyAction}
      isAdmin={isAdmin}
      disabled={!channel}
      error={error}
      onStart={() => void changeState(true)}
      onStop={() => void changeState(false)}
    />
  )
}
