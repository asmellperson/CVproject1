import type { DepartmentId } from '@/auth/permissions'
import type { AiVisionFeatureConfig } from '@/lib/aivision'
import { apiGet } from '@/lib/api'
import type { NormalizedFeatureAlarmConfig } from '@/lib/alarm-config'

export const FENCE_FEATURE = 'security_fence'
export const NUMBER_FIELDS = [
  ['threshold', '人体检测置信度', 0.01, 1, 0.01],
  ['detection_threshold', '人脸检测置信度', 0.01, 1, 0.01],
  ['similarity_threshold', '身份匹配阈值', 0.01, 1, 0.01],
  ['unknown_similarity_threshold', '未匹配判定阈值', 0, 0.99, 0.01],
  ['confirmation_frames', '身份确认帧数', 2, 10, 1],
  ['min_face_size', '最小人脸尺寸（像素）', 32, 512, 1],
  ['min_face_sharpness', '最低人脸清晰度', 0, undefined, 1],
  ['max_face_asymmetry', '最大人脸偏转指标', 0.01, 1, 0.01],
  ['cap_interval', '检测间隔（秒）', 0.1, 1, 0.1],
  ['tracking_overlap_threshold', '跟踪重叠保护阈值', 0.01, 1, 0.01],
  ['tracking_gap_seconds', '跟踪中断重置间隔（秒）', 1, 5, 0.1],
  ['alarm_interval', '报警冷却（秒）', 1, undefined, 1],
] as const
export type NumberField = typeof NUMBER_FIELDS[number][0]
export type FenceValue = Record<NumberField, number> & {
  roi_pos: number[][]; forbidden_start: string; forbidden_end: string; timezone: string; allowed_person_ids: number[]
}
export type FenceConfig = AiVisionFeatureConfig & { value: FenceValue; alarm: NormalizedFeatureAlarmConfig }
export type FencePerson = {
  track_id: number; bbox: number[]; in_roi: boolean; identity: 'pending' | 'allowed' | 'unauthorized'
  person_id: number | null; person_name: string | null; similarity: number | null; alarm: boolean; reason: string | null
}
export type FenceStatus = {
  camera_key: string; state: 'disabled' | 'offline' | 'waiting' | 'stale' | 'error' | 'ready'
  mode: 'forbidden' | 'whitelist'; timezone: string; online: boolean; count: number | null; pending_count: number | null
  persons: FencePerson[]; alarm: boolean | null; updated_at: string | null; error: string | null
}
export type PersonChoice = { id: number; person_name: string | null; job_no: string | null; is_active: boolean }
export type PersonChoices = { total: number; items: PersonChoice[] }

export const getFenceStatus = (key: string, signal: AbortSignal) =>
  apiGet<FenceStatus>(`/security-fence/cameras/${encodeURIComponent(key)}/status`, { signal, cache: 'no-store' })

export function getFencePersons(department: DepartmentId, keyword: string, page: number, signal: AbortSignal, ids?: number[]) {
  const params = new URLSearchParams({ department, keyword, page: String(page), page_size: '20' })
  ids?.forEach((id) => params.append('person_ids', String(id)))
  return apiGet<PersonChoices>(`/security-fence/persons?${params}`, { signal, cache: 'no-store' })
}
