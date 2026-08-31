// 文件说明：实现监控展示的 React 展示与交互。
// 数据流：接收属性、状态或响应数据，并将结果交给组件、接口层或测试断言。

import { useEffect, useMemo, useRef, useState } from 'react'
import { getAlarms, type AlarmEvent } from '@/lib/api'
import { getAiVisionHumanDwellStatus, type AiVisionHumanDwellStatus } from '@/lib/aivision'
import {
  appendHumanDwellTransitionEvent,
  filterTodayHumanDwellAlarms,
  type HumanDwellMonitorEvent,
  type HumanDwellSample,
} from './monitorState'

const STATUS_POLL_MS = 1000
const ALARM_POLL_MS = 5000

/**
 * 功能：封装 `useHumanDwellMonitor` React Hook，向调用组件提供监控展示状态与操作
 * 参数：
 *   - `props`（未显式标注）：React 组件属性对象；解构字段包括 enabled, feature, selectedCamera, selectedCameraName, enabled, boolean, feature, string
 * 返回：未显式标注（由 TypeScript 推断）；返回实现中 `return` 表达式计算得到的结果。
 * 调用关系：
 *   - 调用方：`unified_frontend/src/components/AiVisionMonitor.tsx` 的 `AiVisionMonitor` 调用本符号
 *   - 内部调用：`useState`、`useRef`、`useEffect`、`setStatusState`、`setEventState`、`async`、`getAiVisionHumanDwellStatus`、`appendHumanDwellTransitionEvent`、`setTimeout`、`loadStatus`
 *          等共 18 个调用。
 * 副作用/注意事项：会更新 React 状态并触发相关组件重新渲染；会读取或修改浏览器全局对象/DOM 状态。
 */
export function useHumanDwellMonitor({
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
  const [statusState, setStatusState] = useState<{ cameraKey: string; value: AiVisionHumanDwellStatus | null } | null>(null)
  const [alarms, setAlarms] = useState<AlarmEvent[]>([])
  const [eventState, setEventState] = useState<{ cameraKey: string; value: HumanDwellMonitorEvent[] } | null>(null)
  const previousRef = useRef<{ cameraKey: string; value: HumanDwellSample } | null>(null)

  useEffect(() => {
    setStatusState(null)
    setEventState(null)
    previousRef.current = null
  }, [enabled, feature, selectedCamera])

  useEffect(() => {
    if (!enabled || !selectedCamera) return
    let mounted = true
    let timer: number | undefined

    const loadStatus = async () => {
      try {
        const nextStatus = await getAiVisionHumanDwellStatus(selectedCamera, feature)
        if (!mounted) return
        setStatusState({ cameraKey: selectedCamera, value: nextStatus })

        const nextSample: HumanDwellSample = {
          count: nextStatus.count,
          durationSeconds: nextStatus.duration_seconds,
          alarm: nextStatus.alarm,
        }
        const previous = previousRef.current?.cameraKey === selectedCamera ? previousRef.current.value : null
        setEventState((current) => ({
          cameraKey: selectedCamera,
          value: appendHumanDwellTransitionEvent({
            events: current?.cameraKey === selectedCamera ? current.value : [],
            previous,
            next: nextSample,
          }),
        }))
        previousRef.current = { cameraKey: selectedCamera, value: nextSample }
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
    () => filterTodayHumanDwellAlarms(alarms, selectedCamera, selectedCameraName, feature),
    [alarms, feature, selectedCamera, selectedCameraName],
  )

  return {
    status: statusState?.cameraKey === selectedCamera ? statusState.value : null,
    events: eventState?.cameraKey === selectedCamera && previousRef.current?.cameraKey === selectedCamera
      ? eventState.value
      : [],
    todayAlarmCount: todayAlarms.length,
    latestAlarmAt: todayAlarms[0]?.created_at || null,
  }
}
