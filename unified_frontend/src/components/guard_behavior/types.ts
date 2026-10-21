import type { DepartmentId } from '@/auth/permissions'

export type GuardSite = {
  id: number
  name: string
  department: DepartmentId
  enabled: boolean
  sort_order: number
  created_at: string
  updated_at: string
}
export type SiteCreate = Pick<GuardSite, 'name' | 'department'> & Partial<Pick<GuardSite, 'enabled' | 'sort_order'>>
export type SiteUpdate = Partial<Pick<GuardSite, 'name' | 'enabled' | 'sort_order'>>
export type GuardMember = {
  id: number
  camera_id: number
  name: string
  shm_name: string
  department: DepartmentId
  physical_enabled: boolean
  member_enabled: boolean
  sort_order: number
  created_at: string
  updated_at: string
}
export type VehicleRoiPoint = [number, number]
export type CameraRoi = { camera_id: number; enable: boolean; vehicle_roi_pos: VehicleRoiPoint[] }

export type SitePolicyValues = {
  cap_interval: number
  person_confidence_threshold: number
  phone_confidence_threshold: number
  uniform_confidence_threshold: number
  vehicle_confidence_threshold: number
  model_iou_threshold: number
  person_phone_imgsz: number
  phone_crop_imgsz: number
  pose_imgsz: number
  vehicle_imgsz: number
  guard_hold_seconds: number
  absent_alarm_seconds: number
  phone_seconds: number
  phone_window_seconds: number
  phone_min_hits_in_window: number
  phone_grace_seconds: number
  phone_near_person_px: number
  phone_near_head_px: number
  prone_sleep_seconds: number
  static_motion_threshold: number
  prone_head_down_ratio_threshold: number
  prone_bbox_height_ratio_threshold: number
  prone_consecutive_frames: number
  state_ttl_seconds: number
  vehicle_inspection_enabled: boolean
  vehicle_camera_id: number | null
  vehicle_occlusion_seconds: number
  vehicle_near_px: number
  vehicle_exit_direction: 'any' | 'left' | 'right' | 'up' | 'down'
  vehicle_direction_min_delta_ratio: number
  vehicle_reassociate_seconds: number
}
export type SitePolicy = SitePolicyValues & { id: number; site_id: number; created_at: string; updated_at: string }
export type GuardAlarmType = 8 | 9 | 10 | 11
export type AlarmPolicyValues = {
  alarm_interval: number
  horn_interval: number | null
  wechat_interval: number | null
  sql_enable: boolean
  horn_enable: boolean
  horn_id: number | null
  horn_event_id: number | null
  wechat_enable: boolean
  wechat_user: string
}
export type AlarmPolicy = AlarmPolicyValues & {
  id: number; site_id: number; violation_type: GuardAlarmType; created_at: string; updated_at: string
}
export type CameraAvailability = 'READY' | 'OFFLINE' | 'STALE' | 'PHYSICAL_DISABLED' | 'INFERENCE_ERROR'
export type RuleDecision = {
  availability: 'available' | 'degraded' | 'unavailable'
  state: 'normal' | 'pending' | 'alarm' | 'unknown' | 'idle' | 'monitoring'
  reason: string
  primary_camera_id: number | null
  offending_camera_ids: number[]
  confidence: number
  duration_seconds: number
}
export type SiteStatus = {
  site_id: number
  running: boolean
  status: 'disabled' | 'unconfigured' | 'healthy' | 'degraded' | 'unavailable'
  camera_states: Record<string, CameraAvailability>
  camera_online: Record<string, boolean>
  camera_metrics?: Record<string, { guard_count: number | null; guard_confidence: number | null; fps: number | null }>
  absence: RuleDecision
  phone: RuleDecision
  prone: RuleDecision
  vehicle: RuleDecision
  updated_at: number | null
}
