import type { DepartmentId } from '@/auth/permissions'
export const LOGISTICS_FEATURES = [
  'detect_logistics_single_person',
] as const

export type LogisticsFeatureName = (typeof LOGISTICS_FEATURES)[number]

export type LogisticsChannelReason =
  | 'normal'
  | 'empty'
  | 'multiple'
  | 'unknown'
  | 'unconfigured'
  | 'inactive'

export type LogisticsChannelAlarmHorn = {
  enabled: boolean
  interval: number | null
  horn_id: number | null
  horn_event_id: number | null
}

export type LogisticsChannelAlarmWechat = {
  enabled: boolean
  interval: number | null
  user: string
}

export type LogisticsChannelAlarmConfig = {
  sql_enable: boolean
  horn: LogisticsChannelAlarmHorn
  wechat: LogisticsChannelAlarmWechat
}

export type LogisticsSchedule = { weekdays: number[]; start: string; end: string; timezone: string }

export type LogisticsChannelConfig = {
  schedule: LogisticsSchedule
  confidence_threshold: number
  model_iou_threshold: number
  min_box_area: number
  min_aspect_ratio: number
  max_aspect_ratio: number
  cap_interval: number
  empty_grace_seconds: number
  multi_grace_seconds: number
  alarm_interval: number
  alarm: LogisticsChannelAlarmConfig
}

export type LogisticsChannelDetectionConfig = Omit<LogisticsChannelConfig, 'alarm' | 'alarm_interval'>

export type LogisticsChannelAlarmDraft = Pick<LogisticsChannelConfig, 'alarm' | 'alarm_interval'>

export type LogisticsChannelConfigPatch = Partial<LogisticsChannelConfig>

export type LogisticsChannelMember = {
  id: number
  channel_id: number
  camera_id: number
  enabled: boolean
  sort_order: number
  created_at: string | null
  updated_at: string | null
}

export type LogisticsCameraInventoryMembership = {
  feature_name: LogisticsFeatureName
  channel_id: number
  channel_name: string
  enabled: boolean
  online: boolean
}

export type LogisticsCameraInventoryItem = {
  camera_id: number
  name: string
  shm_name: string
  department: DepartmentId | null
  enabled: boolean
  online: boolean
  memberships: LogisticsCameraInventoryMembership[]
}

export type LogisticsCameraInventoryResponse = {
  items: LogisticsCameraInventoryItem[]
}

export type LogisticsChannelCameraStatus = {
  camera_id: number
  camera_name: string
  count: number | null
  status: LogisticsChannelReason
  online: boolean
  updated_at: number | null
  stale_reason: string | null
}

export type LogisticsChannelStoredStatus = {
  reason: LogisticsChannelReason
  online: boolean | null
  person_count: number | null
  stale: boolean
  stale_reason: string | null
  duration_seconds: number | null
  updated_at: string | null
}

export type LogisticsChannel = {
  id: number
  name: string
  feature_name: LogisticsFeatureName
  department: DepartmentId
  enabled: boolean
  sort_order: number
  created_at: string | null
  updated_at: string | null
}

export type LogisticsChannelDetail = LogisticsChannel & {
  config: LogisticsChannelConfig
  members: LogisticsChannelMember[]
  status: LogisticsChannelStoredStatus | null
}

export type LogisticsChannelListResponse = {
  items: LogisticsChannel[]
}

export type LogisticsChannelRuntimeStatus = {
  department: DepartmentId
  feature_name: LogisticsFeatureName
  channel_id: number
  channel_name: string
  reason: LogisticsChannelReason
  alarm: boolean
  alarm_suppressed: boolean
  duration_seconds: number | null
  threshold_seconds: number | null
  camera_ids: number[]
  camera_counts: Record<string, number | null>
  camera_states: Record<string, LogisticsChannelCameraStatus>
  offending_camera_ids: number[]
  updated_at: number | null
}

export type LogisticsChannelAlarm = {
  department: DepartmentId | null
  id: string
  feature_name: LogisticsFeatureName | null
  channel_id: number
  channel_name: string | null
  reason: string | null
  created_at: string | null
  image_url: string
  metadata: Record<string, unknown>
}

export type LogisticsChannelAlarmListResponse = {
  items: LogisticsChannelAlarm[]
}

export type LogisticsChannelStatistics = {
  summary: {
    total: number
    today: number
  }
  daily: Array<{
    day: string
    count: number
  }>
}

export type LogisticsChannelOkResponse = { ok: boolean }

export type CreateLogisticsChannelPayload = { name: string; department: DepartmentId }

export type UpdateLogisticsChannelPayload = {
  name?: string
  enabled?: boolean
  sort_order?: number
  config?: LogisticsChannelConfigPatch
}

export type BindExistingLogisticsCameraPayload = {
  camera_id: number
  name?: never
  url?: never
}

export type CreateLogisticsCameraPayload = {
  camera_id?: never
  name: string
  url: string
  fps?: number
  shm_name?: string
}

export type LogisticsChannelMemberPayload =
  | BindExistingLogisticsCameraPayload
  | CreateLogisticsCameraPayload

export type LogisticsCameraRoiPoint = [number, number]
export type LogisticsCameraRoiPolygon = LogisticsCameraRoiPoint[]

export type LogisticsCameraRoiPayload = {
  roi_pos: LogisticsCameraRoiPolygon
}

export type LogisticsCameraRoiResponse = LogisticsCameraRoiPayload & {
  camera: {
    id: number
    name: string
    shm_name: string
    enable: boolean
  }
}
