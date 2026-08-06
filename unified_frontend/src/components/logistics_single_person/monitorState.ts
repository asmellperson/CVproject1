import type { AlarmEvent } from '@/lib/api'

export type LogisticsCountState = 'unknown' | 'normal' | 'empty' | 'multiple'

export type LogisticsMonitorEvent = {
  id: string
  state: Exclude<LogisticsCountState, 'unknown'>
  label: string
  occurredAt: string
}

export function classifyLogisticsCount(count: number | null | undefined): LogisticsCountState {
  if (!Number.isFinite(count)) return 'unknown'
  if (count === 1) return 'normal'
  if (count === 0) return 'empty'
  return Number(count) >= 2 ? 'multiple' : 'unknown'
}

export function logisticsEventLabel(state: LogisticsCountState, count: number | null | undefined) {
  if (state === 'normal') return 'ROI 内人数恢复正常：1 人'
  if (state === 'empty') return 'ROI 内无人异常：0 人'
  if (state === 'multiple') return `ROI 内多人异常：${count} 人`
  return ''
}

export function appendLogisticsTransitionEvent({
  events,
  previousState,
  count,
  occurredAt = new Date(),
  limit = 8,
}: {
  events: LogisticsMonitorEvent[]
  previousState: LogisticsCountState
  count: number | null | undefined
  occurredAt?: Date
  limit?: number
}) {
  const nextState = classifyLogisticsCount(count)
  if (nextState === 'unknown' || nextState === previousState) {
    return { events, state: nextState === 'unknown' ? previousState : nextState }
  }
  const nextEvent: LogisticsMonitorEvent = {
    id: `${occurredAt.getTime()}-${nextState}`,
    state: nextState,
    label: logisticsEventLabel(nextState, count),
    occurredAt: occurredAt.toISOString(),
  }
  return {
    events: [nextEvent, ...events].slice(0, limit),
    state: nextState,
  }
}

function isSameLocalDay(value: string | undefined, now: Date) {
  if (!value) return false
  const parsed = new Date(value)
  return !Number.isNaN(parsed.getTime())
    && parsed.getFullYear() === now.getFullYear()
    && parsed.getMonth() === now.getMonth()
    && parsed.getDate() === now.getDate()
}

export function filterTodayLogisticsAlarms(
  alarms: AlarmEvent[],
  cameraKey: string,
  cameraName: string,
  now = new Date(),
) {
  return alarms.filter((alarm) =>
    alarm.event_type === 'detect_logistics_single_person'
    && (alarm.camera_no === cameraKey || (!alarm.camera_no && alarm.camera_name === cameraName))
    && isSameLocalDay(alarm.created_at, now),
  )
}
