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

export function useLogisticsSinglePersonMonitor({
  enabled,
  selectedCamera,
  selectedCameraName,
}: {
  enabled: boolean
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
        const nextStatus = await getAiVisionLogisticsSinglePersonStatus(selectedCamera)
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
  }, [enabled, selectedCamera])

  useEffect(() => {
    if (!enabled || !selectedCamera) return
    let mounted = true
    let timer: number | undefined

    const loadAlarms = async () => {
      try {
        const nextAlarms = await getAlarms(1000, ['detect_logistics_single_person'])
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
    () => filterTodayLogisticsAlarms(alarms, selectedCamera, selectedCameraName),
    [alarms, selectedCamera, selectedCameraName],
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
