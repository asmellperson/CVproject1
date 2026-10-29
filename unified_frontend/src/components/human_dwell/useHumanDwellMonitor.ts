import { useEffect, useMemo, useRef, useState } from 'react'
import { getAlarms, type AlarmEvent } from '@/lib/api'
import { useDetectionStatus } from '@/components/monitor/useDetectionStatus'
import {
  appendHumanDwellTransitionEvent,
  filterTodayHumanDwellAlarms,
  type HumanDwellMonitorEvent,
  type HumanDwellSample,
} from './monitorState'

const ALARM_POLL_MS = 5000

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
  const result = useDetectionStatus(selectedCamera, feature, enabled)
  const status = result?.status ?? null
  const [alarms, setAlarms] = useState<AlarmEvent[]>([])
  const [eventState, setEventState] = useState<{ cameraKey: string; value: HumanDwellMonitorEvent[] } | null>(null)
  const previousRef = useRef<{ cameraKey: string; value: HumanDwellSample } | null>(null)

  useEffect(() => {
    setEventState(null)
    previousRef.current = null
  }, [enabled, feature, selectedCamera])

  useEffect(() => {
    if (!enabled || !status) return
    const nextSample: HumanDwellSample = { count: status.count, durationSeconds: status.duration_seconds ?? null, alarm: status.alarm }
    const previous = previousRef.current?.cameraKey === selectedCamera ? previousRef.current.value : null
    setEventState((current) => ({ cameraKey: selectedCamera, value: appendHumanDwellTransitionEvent({
      events: current?.cameraKey === selectedCamera ? current.value : [], previous, next: nextSample,
    }) }))
    previousRef.current = { cameraKey: selectedCamera, value: nextSample }
  }, [enabled, selectedCamera, status])

  useEffect(() => {
    if (!enabled || !selectedCamera) return
    let mounted = true
    let timer: number | undefined

    const loadAlarms = async () => {
      try {
        const nextAlarms = await getAlarms(1000, [feature])
        if (mounted) setAlarms(nextAlarms)
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

  const todayAlarms = useMemo(
    () => filterTodayHumanDwellAlarms(alarms, selectedCamera, selectedCameraName, feature),
    [alarms, feature, selectedCamera, selectedCameraName],
  )

  return {
    status,
    error: result?.error,
    events: eventState?.cameraKey === selectedCamera && previousRef.current?.cameraKey === selectedCamera
      ? eventState.value
      : [],
    todayAlarmCount: todayAlarms.length,
    latestAlarmAt: todayAlarms[0]?.created_at || null,
  }
}
