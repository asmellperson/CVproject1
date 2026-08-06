import type { AlarmEvent } from '@/lib/api'

export type HumanDwellSample = {
  count: number | null
  durationSeconds: number | null
  alarm: boolean
}

export type HumanDwellMonitorEvent = {
  id: string
  tone: 'danger' | 'neutral'
  label: string
  occurredAt: string
}

function roundedSeconds(value: number | null | undefined) {
  return Math.max(0, Math.round(Number(value) || 0))
}

export function appendHumanDwellTransitionEvent({
  events,
  previous,
  next,
  occurredAt = new Date(),
  limit = 8,
}: {
  events: HumanDwellMonitorEvent[]
  previous: HumanDwellSample | null
  next: HumanDwellSample
  occurredAt?: Date
  limit?: number
}) {
  let event: HumanDwellMonitorEvent | null = null

  if (next.alarm && previous && !previous.alarm) {
    const duration = roundedSeconds(next.durationSeconds)
    event = {
      id: `${occurredAt.getTime()}-loitering`,
      tone: 'danger',
      label: `人员在区域内逗留 ${duration} 秒，触发告警`,
      occurredAt: occurredAt.toISOString(),
    }
  } else if (previous && !previous.alarm && (previous.count ?? 0) > 0 && next.count === 0) {
    const count = previous.count ?? 0
    const duration = roundedSeconds(previous.durationSeconds)
    event = {
      id: `${occurredAt.getTime()}-left`,
      tone: 'neutral',
      label: `区域人数 ${count}，停留 ${duration} 秒后离开，未告警`,
      occurredAt: occurredAt.toISOString(),
    }
  }

  return event ? [event, ...events].slice(0, limit) : events
}

function isSameLocalDay(value: string | undefined, now: Date) {
  if (!value) return false
  const parsed = new Date(value)
  return !Number.isNaN(parsed.getTime())
    && parsed.getFullYear() === now.getFullYear()
    && parsed.getMonth() === now.getMonth()
    && parsed.getDate() === now.getDate()
}

export function filterTodayHumanDwellAlarms(
  alarms: AlarmEvent[],
  cameraKey: string,
  cameraName: string,
  now = new Date(),
) {
  return alarms.filter((alarm) =>
    alarm.event_type === 'detect_human'
    && (alarm.camera_no === cameraKey || (!alarm.camera_no && alarm.camera_name === cameraName))
    && isSameLocalDay(alarm.created_at, now),
  )
}
