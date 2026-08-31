// 文件说明：实现告警的 React 展示与交互。
// 数据流：接收属性、状态或响应数据，并将结果交给组件、接口层或测试断言。

import { useEffect, useMemo, useState } from 'react'
import { getAlarms, type AlarmEvent } from '@/lib/api'
import { buildFeatureAlarmSummary, type FeatureDashboardKey } from './monitorState'

const ALARM_POLL_MS = 5000

/**
 * 功能：封装 `useFeatureDashboardAlarms` React Hook，向调用组件提供告警状态与操作
 * 参数：
 *   - `props`（未显式标注）：React 组件属性对象；解构字段包括 enabled, feature, selectedCamera, selectedCameraName, enabled, boolean, feature,
 *     FeatureDashboardKey
 * 返回：未显式标注（由 TypeScript 推断）；返回实现中 `return` 表达式计算得到的结果。
 * 调用关系：
 *   - 调用方：`unified_frontend/src/components/AiVisionMonitor.tsx` 的 `AiVisionMonitor` 调用本符号
 *   - 内部调用：`useState`、`useEffect`、`setAlarmState`、`async`、`getAlarms`、`setTimeout`、`loadAlarms`、`return`、`clearTimeout`、`useMemo`
 *          等共 11 个调用。
 * 副作用/注意事项：会更新 React 状态并触发相关组件重新渲染；会读取或修改浏览器全局对象/DOM 状态。
 */
export function useFeatureDashboardAlarms({
  enabled,
  feature,
  selectedCamera,
  selectedCameraName,
}: {
  enabled: boolean
  feature: FeatureDashboardKey
  selectedCamera: string
  selectedCameraName: string
}) {
  const [alarmState, setAlarmState] = useState<{ cameraKey: string; value: AlarmEvent[] } | null>(null)

  useEffect(() => {
    setAlarmState(null)
  }, [enabled, feature, selectedCamera])

  useEffect(() => {
    if (!enabled || !selectedCamera) return
    let mounted = true
    let timer: number | undefined

    const loadAlarms = async () => {
      try {
        const value = await getAlarms(1000, [feature])
        if (mounted) setAlarmState({ cameraKey: selectedCamera, value })
      } catch {
        // Keep the latest successful list for this camera when a refresh fails.
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

  const summary = useMemo(
    () => {
      const alarms = alarmState?.cameraKey === selectedCamera ? alarmState.value : []
      return buildFeatureAlarmSummary(alarms, feature, selectedCamera, selectedCameraName)
    },
    [alarmState, feature, selectedCamera, selectedCameraName],
  )

  return summary
}
