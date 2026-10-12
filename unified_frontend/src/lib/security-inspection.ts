import type { DepartmentId } from '@/auth/permissions'
import type { NormalizedFeatureAlarmConfig } from '@/lib/alarm-config'
import { apiGet, apiPut, apiUrl } from '@/lib/api'

export const INSPECTION_FEATURE = 'security_inspection'
export type RoiMap = Record<string, [number, number][]>
export type InspectionConfig = {
  enable: boolean
  value: { staff_rois: RoiMap } & Record<InspectionParameter, number>
  alarm: NormalizedFeatureAlarmConfig
}

export const INSPECTION_PARAMETERS = [
  ['cap_interval', '检测间隔（秒）', 0.05, 5, 0.05],
  ['conf', '人体检测置信度', 0.01, 1, 0.01],
  ['iou', '检测框重叠阈值', 0.01, 1, 0.01],
  ['imgsz', '推理输入尺寸', 160, 1920, 32],
  ['pair_start_hold_frames', '配对持续帧数', 1, 300, 1],
  ['fingerprint_lost_seconds', '人员丢失结束时间（秒）', 0.1, 60, 0.1],
  ['no_interact_seconds', '停止交互结束时间（秒）', 0.1, 60, 0.1],
  ['max_session_seconds', '会话最长时间（秒）', 1, 600, 1],
  ['keyframe_interval_sec', '关键帧间隔（秒）', 0.1, 30, 0.1],
  ['keyframes_per_session', '关键帧数量上限', 2, 32, 1],
  ['roi_crop_padding', '关键帧外扩距离（像素）', 0, 1000, 1],
  ['fp_match_threshold', '人员指纹匹配阈值', 0, 1, 0.01],
  ['interact_distance_max_ratio', '交互距离与身高比上限', 0.21, 10, 0.01],
  ['interact_motion_min_pixels', '交互最小位移（像素）', 0, 1000, 1],
  ['roi_enter_overlap_ratio', '进入工位重叠比例', 0, 1, 0.01],
  ['roi_hold_overlap_ratio', '保持工位重叠比例', 0, 1, 0.01],
  ['alarm_interval', '报警间隔（秒）', 0, 86400, 1],
] as const
type InspectionParameter = typeof INSPECTION_PARAMETERS[number][0]

export const VLM_PARAMETERS = [
  ['max_tokens', '输出长度上限', 128, 16384, 1],
  ['temperature', '采样温度', 0, 2, 0.1],
  ['api_timeout_sec', '请求超时（秒）', 1, 180, 1],
  ['queue_timeout_sec', '排队超时（秒）', 1, 600, 1],
  ['max_concurrent', '最大并发请求数', 1, 16, 1],
  ['queue_capacity', '排队容量', 1, 256, 1],
  ['image_max_side', '图片最长边', 160, 1920, 1],
  ['image_jpeg_quality', '图片质量', 30, 100, 1],
] as const
export type VlmSettings = { base_url: string; model: string } & Record<typeof VLM_PARAMETERS[number][0], number>
export type InspectionStatus = {
  running: boolean
  queue: number
  active: number
  error: string | null
  vlm: {
    reachable: boolean | null
    checking: boolean
    last_success: string | null
    last_error: string | null
    consecutive_failures: number
    circuit_state: 'closed' | 'open' | 'half_open'
    retry_after_sec: number | null
  }
}
export type InspectionSession = {
  session_id: string
  camera_id: number | null
  camera_name: string
  roi_name: string
  started_at: string
  ended_at: string
  duration_sec: number
  status: 'compliant' | 'non_compliant' | 'error' | 'cancelled'
  verdict: { compliant: boolean; confidence: number; reason: string } | null
  error: string | null
  latency_sec: number | null
  has_image: boolean
}
export type InspectionHistory = {
  retention_days: number
  stats: { total: number; compliant: number; non_compliant: number; error: number; cancelled: number; rate: number }
  items: InspectionSession[]
}

export const inspectionImageUrl = (department: DepartmentId, sessionId: string) =>
  apiUrl(`/security-inspection/history/${encodeURIComponent(sessionId)}/image.jpg?${new URLSearchParams({ department })}`)

export function getInspectionHistory(department: DepartmentId, limit: number, offset: number, cameraId?: number, signal?: AbortSignal) {
  const params = new URLSearchParams({ department, limit: String(limit), offset: String(offset) })
  if (cameraId !== undefined) params.set('camera_id', String(cameraId))
  return apiGet<InspectionHistory>(`/security-inspection/history?${params}`, { signal })
}
export const getInspectionStatus = (department: DepartmentId, signal?: AbortSignal) =>
  apiGet<InspectionStatus>(`/security-inspection/status?department=${encodeURIComponent(department)}`, { signal })
export const getVlmSettings = () => apiGet<VlmSettings>('/security-inspection/settings')
export const saveVlmSettings = (settings: VlmSettings) =>
  apiPut<{ settings: VlmSettings; vlm: InspectionStatus['vlm'] }>('/security-inspection/settings', settings)
