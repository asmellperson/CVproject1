// 文件说明：实现监控展示的 React 展示与交互。
// 数据流：接收属性、状态或响应数据，并将结果交给组件、接口层或测试断言。

import { useEffect, useMemo, useRef, useState } from 'react'
import { getAlarms, type AlarmEvent } from '@/lib/api'
import {
  getAiVisionLogisticsSinglePersonStatus,
  type AiVisionLogisticsSinglePersonStatus,
} from '@/lib/aivision'
import {
  appendLogisticsTransitionEvent,
  filterTodayLogisticsAlarms,
  type LogisticsCountState,
  type LogisticsMonitorEvent,
} from './monitorState'

const STATUS_POLL_MS = 1000
const ALARM_POLL_MS = 5000

/**
 * 功能：封装 `useLogisticsSinglePersonMonitor` React Hook，向调用组件提供监控展示状态与操作
 * 参数：
 *   - `props`（未显式标注）：React 组件属性对象；解构字段包括 enabled, feature, selectedCamera, selectedCameraName, enabled, boolean, feature, string
 * 返回：未显式标注（由 TypeScript 推断）；返回实现中 `return` 表达式计算得到的结果。
 * 调用关系：
 *   - 调用方：`unified_frontend/src/components/AiVisionMonitor.tsx` 的 `AiVisionMonitor` 调用本符号
 *   - 内部调用：`useState`、`useRef`、`useEffect`、`async`、`getAiVisionLogisticsSinglePersonStatus`、`setStatusState`、`appendLogisticsTransitionEvent`、`setEventState`、`slice`、`setTimeout`
 *          等共 19 个调用。
 * 副作用/注意事项：会更新 React 状态并触发相关组件重新渲染；会读取或修改浏览器全局对象/DOM 状态。
 */
export function useLogisticsSinglePersonMonitor({
  enabled,
  feature,
  selectedCamera,
  selectedCameraName,
}: {
  enabled: boolean
  feature: string
  selectedCamera: string
  selectedCameraName: string
}) {
  const [statusState, setStatusState] = useState<{
    cameraKey: string
    value: AiVisionLogisticsSinglePersonStatus | null
  } | null>(null)
  const [alarms, setAlarms] = useState<AlarmEvent[]>([])
  const [eventState, setEventState] = useState<{
    cameraKey: string
    value: LogisticsMonitorEvent[]
  } | null>(null)
  const previousStateRef = useRef<{ cameraKey: string; value: LogisticsCountState }>({
    cameraKey: '',
    value: 'unknown',
  })

  useEffect(() => {
    if (!enabled || !selectedCamera) return
    let mounted = true
    let timer: number | undefined

    const loadStatus = async () => {
      try {
        const nextStatus = await getAiVisionLogisticsSinglePersonStatus(selectedCamera, feature)
        if (!mounted) return
        setStatusState({ cameraKey: selectedCamera, value: nextStatus })
        const cameraChanged = previousStateRef.current.cameraKey !== selectedCamera
        const previousState = cameraChanged ? 'unknown' : previousStateRef.current.value
        const transition = appendLogisticsTransitionEvent({
          events: [],
          previousState,
          count: nextStatus.count,
        })
        previousStateRef.current = { cameraKey: selectedCamera, value: transition.state }
        if (transition.events.length > 0) {
          setEventState((current) => ({
            cameraKey: selectedCamera,
            value: [
              transition.events[0],
              ...(!cameraChanged && current?.cameraKey === selectedCamera ? current.value : []),
            ].slice(0, 8),
          }))
        }
      } catch {
        if (mounted) setStatusState({ cameraKey: selectedCamera, value: null })
      } finally {
        if (mounted) timer = window.setTimeout(loadStatus, STATUS_POLL_MS)
      }
    }

    loadStatus()
    return () => {
      mounted = false
      if (timer !== undefined) window.clearTimeout(timer)
    }
  }, [enabled, feature, selectedCamera])

  useEffect(() => {
    if (!enabled || !selectedCamera) return
    let mounted = true
    let timer: number | undefined

    const loadAlarms = async () => {
      try {
        const nextAlarms = await getAlarms(1000, [feature])
        if (mounted) setAlarms(nextAlarms)
      } catch {
        // Keep the last successful alarm list when polling fails.
      } finally {
        if (mounted) timer = window.setTimeout(loadAlarms, ALARM_POLL_MS)
      }
    }

    loadAlarms()
    return () => {
      mounted = false
      if (timer !== undefined) window.clearTimeout(timer)
    }
  }, [enabled, feature, selectedCamera])

  const todayAlarms = useMemo(
    () => filterTodayLogisticsAlarms(alarms, feature, selectedCamera, selectedCameraName),
    [alarms, feature, selectedCamera, selectedCameraName],
  )

  return {
    status: statusState?.cameraKey === selectedCamera ? statusState.value : null,
    events: eventState?.cameraKey === selectedCamera
      && previousStateRef.current.cameraKey === selectedCamera
      ? eventState.value
      : [],
    todayAlarmCount: todayAlarms.length,
  }
}
