export type AlarmType = 'absent' | 'phone_use' | 'prone_sleep' | 'vehicle_unattended'

export interface Detection {
  cls_id: number
  conf: number
  bbox: [number, number, number, number]
  track_id?: number
}

export interface AlarmEvent {
  id: string
  event_type: AlarmType
  site_id?: number
  site_name?: string
  timestamp_s: number
  frame_index: number
  track_id?: number
  confidence: number
  reason: string
  image_path?: string
  image_url?: string
  video_path?: string | null
  video_status?: 'pending' | 'ready' | 'failed'
  created_at?: string
}

export interface RuleConfig {
  absent_seconds: number
  phone_seconds: number
  prone_sleep_seconds: number
  vehicle_occlusion_seconds?: number
  phone_near_person_px: number
  phone_near_head_px: number
  vehicle_near_px?: number
  vehicle_roi?: [number, number][]
  vehicle_exit_direction?: string
  vehicle_direction_min_delta_ratio?: number
  static_motion_threshold: number
  prone_head_down_ratio_threshold: number
  prone_bbox_height_ratio_threshold: number
  prone_consecutive_frames: number
  state_ttl_seconds: number
  phone_window_seconds: number
  phone_min_hits_in_window: number
  phone_grace_seconds: number
  guard_hold_seconds: number
  dual_sync_seconds: number
  absent_alarm_seconds: number
  alarm_cooldown_absent: number
  alarm_cooldown_phone: number
  alarm_cooldown_prone_sleep: number
  alarm_cooldown_vehicle_unattended?: number
}

export interface VideoConfig {
  source: string
  source_cam1: string
  source_cam2: string
  source_cam3: string
  process_every_n_frames: number
  output_dir: string
  save_annotated_video: boolean
  annotated_video_fps: number
  reconnect_seconds: number
  jpeg_quality: number
  camera_buffer_size: number
}

export interface ModelConfig {
  detector_model: string
  vehicle_detector_model?: string
  uniform_cls_model: string
  pose_model_task: string
  detector_conf: number
  phone_conf: number
  vehicle_conf?: number
  detector_iou: number
  detector_imgsz: number
  vehicle_imgsz?: number
  tracker: string
  device: string
  uniform_cls_imgsz: number
  uniform_cls_conf: number
}

export interface RoomConfig {
  frame_width: number
  frame_height: number
}

export interface ClassConfig {
  person: number
  play_phone: number
  vehicle_bicycle?: number
  vehicle_car?: number
  vehicle_motorcycle?: number
}

export interface RuntimeConfig {
  show_window: boolean
  debug: boolean
  draw_debug: boolean
  max_alarm_history: number
  phone_detect_mode?: string
  enable_vehicle_unattended?: boolean
  vehicle_camera_id?: string
}

export interface WechatConfig {
  enable: boolean
  corpid: string
  corpsecret: string
  agentid: number
  alarm_user: string
  camera_name: string
  clip_seconds: number
  enable_phone?: boolean
  enable_absent?: boolean
  enable_prone_sleep?: boolean
}

export interface AppConfigPayload {
  video: VideoConfig
  models: ModelConfig
  room: RoomConfig
  rules: RuleConfig
  classes: ClassConfig
  runtime: RuntimeConfig
  wechat: WechatConfig
}

export interface StatisticsSummary {
  total: number
  absent: number
  phone_use: number
  prone_sleep: number
  vehicle_unattended?: number
  today: number
  week: number
}

export interface StatisticsResponse {
  summary: StatisticsSummary
  hourly: { time: string; absent: number; phone: number; prone_sleep: number; vehicle_unattended?: number }[]
  weekly: { day: string; absent: number; phone: number; prone_sleep: number; vehicle_unattended?: number }[]
  pie: { name: string; value: number; color: string }[]
}

export interface BackendStatus {
  site_id?: number
  site_name?: string
  running: boolean
  fps: number
  frame_count: number
  pose_enabled: boolean
  source: string
  error?: string | null
  reader_warning?: string | null
  updated_at: string
  uptime_sec: number
  last_alarm: AlarmEvent | null
  stream_url: string
  frame_url: string
  persons: Detection[]
  phones: Detection[]
  vehicles?: Detection[]
  pose_features: Record<string, Record<string, number>>
  decisions: {
    absent: boolean
    phone_use: boolean
    prone_sleep: boolean
    vehicle_unattended?: boolean
  }
  metrics: {
    person_confidence: number
    phone_confidence: number
    vehicle_confidence?: number
    head_down_ratio: number
  }
  counts: {
    persons: number
    phones: number
    vehicles?: number
  }
  stream_time_s: number
}

export interface ControlResponse {
  ok?: boolean
  success?: boolean
  message?: string
  running?: boolean
  site_id?: number
  site_name?: string
}

export interface GuardRoomCamera {
  id: number
  site_id: number
  name: string
  rtsp_url: string
  enabled: boolean
  sort_order: number
  created_at?: string | null
  updated_at?: string | null
}

export interface GuardRoomSite {
  id: number
  department: string
  name: string
  enabled: boolean
  sort_order: number
  description?: string | null
  camera_count: number
  enabled_camera_count: number
  cameras: GuardRoomCamera[]
  created_at?: string | null
  updated_at?: string | null
}

export interface AlarmStatistics {
  total: number
  absent: number
  phone_use: number
  prone_sleep: number
  today: number
  week: number
}

export interface PersonState {
  track_id: number
  motion_score: number
  in_post_roi: boolean
  head_down_frames: number
  phone_frames: number
  drowsy_frames: number
  visible: boolean
}

export interface SystemStatus {
  isRunning: boolean
  fps: number
  frameCount: number
  poseEnabled: boolean
  lastAlarm: AlarmEvent | null
}
