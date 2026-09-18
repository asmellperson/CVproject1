import type { GuardMember, SiteStatus } from './types'

export function summarizeGuardMonitor(status: SiteStatus | null, members: GuardMember[]) {
  const online = members.filter((member) => member.physical_enabled && status?.camera_online[String(member.camera_id)] === true).length
  const metrics = status?.running ? members.filter((member) => member.member_enabled && member.physical_enabled
    && status.camera_states[String(member.camera_id)] === 'READY')
    .map((member) => status.camera_metrics?.[String(member.camera_id)]).filter((value) => value != null) : []
  const counts = metrics.map((value) => value.guard_count).filter((value): value is number => value !== null && Number.isFinite(value))
  const confidences = metrics.map((value) => value.guard_confidence).filter((value): value is number => value !== null && Number.isFinite(value))
  const rates = metrics.map((value) => value.fps).filter((value): value is number => value !== null && Number.isFinite(value))
  return {
    online,
    guards: counts.length ? Math.max(...counts) : null,
    guardConfidence: confidences.length ? Math.max(...confidences) : null,
    fps: rates.length ? rates.reduce((sum, value) => sum + value, 0) / rates.length : null,
    abnormalCount: status ? [status.absence, status.phone, status.prone, status.vehicle].filter((rule) => rule.state === 'alarm').length : null,
    videoLabel: !members.length ? '未配置' : !status ? '待确认' : online === members.length ? '在线' : online > 0 ? '部分在线'
      : members.every((member) => !member.physical_enabled || status.camera_online[String(member.camera_id)] === false) ? '离线' : '待确认',
  }
}
