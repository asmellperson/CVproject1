export const LOGISTICS_FEATURES = [
  'detect_logistics_single_person',
  'detect_logistics_single_person_electronics_electrician',
  'detect_logistics_single_person_electrical_components',
  'detect_logistics_single_person_precious_metal_recycling',
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
  horn_id: number | null
  horn_event_id: number | null
}

export type LogisticsChannelAlarmWechat = {
  enabled: boolean
  user: string
}

export type LogisticsChannelAlarmConfig = {
  sql_enable: boolean
  horn: LogisticsChannelAlarmHorn
  wechat: LogisticsChannelAlarmWechat
}

/** Backend time values are timezone-free `HH:MM:SS` strings. */
export type LogisticsDetectionTime = string

export type LogisticsChannelConfig = {
  enabled: boolean
  detection_start: LogisticsDetectionTime
  detection_end: LogisticsDetectionTime
  confidence_threshold: number
  empty_grace_seconds: number
  multi_grace_seconds: number
  alarm_interval: number
  alarm: LogisticsChannelAlarmConfig
}

export type LogisticsChannelConfigPayload = LogisticsChannelConfig

export type LogisticsChannelMember = {
  id: number
  channel_id: number
  camera_id: number
  enabled: boolean
  sort_order: number
  created_at: string | null
  updated_at: string | null
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
  feature_name: LogisticsFeatureName
  channel_id: number
  channel_name: string
  reason: LogisticsChannelReason
  alarm: boolean
  duration_seconds: number | null
  threshold_seconds: number | null
  camera_ids: number[]
  camera_counts: Record<string, number | null>
  camera_states: Record<string, LogisticsChannelCameraStatus>
  offending_camera_ids: number[]
  updated_at: number | null
}

export type LogisticsChannelAlarm = {
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

export type CreateLogisticsChannelPayload = { name: string }

export type UpdateLogisticsChannelPayload = {
  name?: string
  enabled?: boolean
  sort_order?: number
  config?: LogisticsChannelConfigPayload
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
  max_restart?: number
  department?: string | null
  shm_name?: string
}

export type LogisticsChannelMemberPayload =
  | BindExistingLogisticsCameraPayload
  | CreateLogisticsCameraPayload

export type LogisticsCameraRoiPoint = [number, number]
export type LogisticsCameraRoiPolygon = LogisticsCameraRoiPoint[]

export type LogisticsCameraDetectionValue = {
  roi_pos: LogisticsCameraRoiPolygon[]
  region?: number[]
  CONF_THRESHOLD?: number
  IOU_THR?: number
  MIN_BOX_AREA?: number
  ASPECT_RATIO_RANGE?: [number, number]
  cap_interval?: number
  [key: string]: unknown
}

export type LogisticsCameraConfigPayload = {
  enable: boolean
  value: LogisticsCameraDetectionValue
  alarm?: unknown
}

export type LogisticsCameraConfigResponse = {
  camera: {
    id: number
    name: string
    shm_name: string
    enable: boolean
  }
  feature: LogisticsFeatureName
  config: LogisticsCameraConfigPayload
}
