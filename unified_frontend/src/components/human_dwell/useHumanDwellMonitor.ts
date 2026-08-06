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

export function useHumanDwellMonitor({
  enabled,
  selectedCamera,
  selectedCameraName,
}: {
  enabled: boolean
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
  }, [enabled, selectedCamera])

  useEffect(() => {
    if (!enabled || !selectedCamera) return
    let mounted = true
    let timer: number | undefined

    const loadStatus = async () => {
      try {
        const nextStatus = await getAiVisionHumanDwellStatus(selectedCamera)
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
  }, [enabled, selectedCamera])

  useEffect(() => {
    if (!enabled || !selectedCamera) return
    let mounted = true
    let timer: number | undefined

    const loadAlarms = async () => {
      try {
        const nextAlarms = await getAlarms(1000, ['detect_human'])
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
  }, [enabled, selectedCamera])

  const todayAlarms = useMemo(
    () => filterTodayHumanDwellAlarms(alarms, selectedCamera, selectedCameraName),
    [alarms, selectedCamera, selectedCameraName],
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
