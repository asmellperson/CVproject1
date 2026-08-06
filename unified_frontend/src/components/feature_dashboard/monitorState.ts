import type { AlarmEvent } from '@/lib/api'

export type FeatureDashboardKey = 'blocks' | 'detect_face' | 'detect_phone' | 'detect_door'

export type FeatureDashboardProfile = {
  pageTitle: string
  pageSubtitle: string
  videoTitle: string
  metricLabel: string
  eventLabel: string
  overlayLabel: string
  statusSubject: string
}

export const FEATURE_DASHBOARD_PROFILES: Record<FeatureDashboardKey, FeatureDashboardProfile> = {
  blocks: {
    pageTitle: '区域入侵检测监控与配置',
    pageSubtitle: '警戒区域实时监控面板',
    videoTitle: '区域入侵检测监控',
    metricLabel: '警戒方向',
    eventLabel: '入侵告警',
    overlayLabel: 'alarm_line',
    statusSubject: '警戒线',
  },
  detect_face: {
    pageTitle: '人脸检测监控与配置',
    pageSubtitle: '人脸识别实时监控面板',
    videoTitle: '人脸检测监控',
    metricLabel: '人脸置信度阈值',
    eventLabel: '人脸告警',
    overlayLabel: 'face_roi',
    statusSubject: '人脸区域',
  },
  detect_phone: {
    pageTitle: '手机识别检测监控与配置',
    pageSubtitle: '手机使用识别监控面板',
    videoTitle: '手机识别检测监控',
    metricLabel: '确认持续时间',
    eventLabel: '手机告警',
    overlayLabel: 'phone_roi',
    statusSubject: '手机区域',
  },
  detect_door: {
    pageTitle: '大门开关检测监控与配置',
    pageSubtitle: '大门状态异常监控面板',
    videoTitle: '大门开关检测监控',
    metricLabel: '首次告警时间',
    eventLabel: '大门告警',
    overlayLabel: 'door_roi',
    statusSubject: '大门区域',
  },
}

export function isFeatureDashboardKey(value: string): value is FeatureDashboardKey {
  return Object.hasOwn(FEATURE_DASHBOARD_PROFILES, value)
}

export type CameraFeatureValueState = {
  cameraKey: string
  value: Record<string, unknown>
}

export function resolveCameraFeatureValue(
  state: CameraFeatureValueState | null,
  selectedCamera: string,
) {
  return state?.cameraKey === selectedCamera ? state.value : null
}

export function isFeatureOverlayConfigured(
  feature: FeatureDashboardKey,
  roiCount: number,
  alarmLineCount: number,
) {
  return feature === 'blocks' ? alarmLineCount > 0 : roiCount > 0
}

function isSameLocalDay(value: string | undefined, now: Date) {
  if (!value) return false
  const parsed = new Date(value)
  return !Number.isNaN(parsed.getTime())
    && parsed.getFullYear() === now.getFullYear()
    && parsed.getMonth() === now.getMonth()
    && parsed.getDate() === now.getDate()
}

export function buildFeatureAlarmSummary(
  alarms: AlarmEvent[],
  feature: FeatureDashboardKey,
  cameraKey: string,
  cameraName: string,
  now = new Date(),
) {
  const today = alarms
    .filter((alarm) => alarm.event_type === feature)
    .filter((alarm) => alarm.camera_no === cameraKey || (!alarm.camera_no && alarm.camera_name === cameraName))
    .filter((alarm) => isSameLocalDay(alarm.created_at, now))
    .sort((left, right) => new Date(right.created_at || 0).getTime() - new Date(left.created_at || 0).getTime())

  return { todayCount: today.length, recent: today.slice(0, 5) }
}
