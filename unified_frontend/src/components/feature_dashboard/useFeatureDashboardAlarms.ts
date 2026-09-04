import { useEffect, useMemo, useState } from 'react'
import { getAlarms, type AlarmEvent } from '@/lib/api'
import { buildFeatureAlarmSummary, type FeatureDashboardKey } from './monitorState'

const ALARM_POLL_MS = 5000

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
        void 0
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
