import type { DepartmentId } from '@/auth/permissions'
import { apiUrl } from '@/lib/api'
import type { DetectionStatus } from '@/components/monitor/useDetectionStatus'

export type SmokeParameter = {
  key: string
  label: string
  kind: 'boolean' | 'integer'
  value: boolean | number
  minimum: number | null
  maximum: number | null
}
export type SmokeParametersState = {
  supported: boolean
  message: string
  channel_id: number
  global_enabled: boolean | null
  parameters: SmokeParameter[]
}
export type SmokeShieldPoint = { x: number; y: number }
export type SmokeShieldRegion = { id: number; enabled: boolean; name: string; points: SmokeShieldPoint[] }
export type SmokeShieldState = {
  supported: boolean
  writable: boolean
  message: string
  enabled: boolean
  channel_id: number
  coordinate_width: number | null
  coordinate_height: number | null
  max_regions: number
  min_points: number
  max_points: number
  regions: SmokeShieldRegion[]
}

function smokePath(cameraKey: string, resource: string, department: DepartmentId) {
  return `/aivision/smoke/${encodeURIComponent(cameraKey)}/${resource}?department=${encodeURIComponent(department)}`
}

async function request<T>(path: string, method: 'GET' | 'PUT', body?: unknown, signal?: AbortSignal): Promise<T> {
  const response = await fetch(apiUrl(path), {
    method, credentials: 'include', cache: 'no-store', signal,
    headers: body === undefined ? undefined : { 'Content-Type': 'application/json' },
    body: body === undefined ? undefined : JSON.stringify(body),
  })
  if (response.status === 401) window.dispatchEvent(new Event('aicv:unauthorized'))
  if (!response.ok) {
    const payload = await response.json().catch(() => null) as { detail?: unknown } | null
    const detail = typeof payload?.detail === 'string' ? payload.detail : `设备请求失败（${response.status}）`
    throw new Error(detail)
  }
  return response.json() as Promise<T>
}

export const readSmokeParameters = (key: string, department: DepartmentId, signal?: AbortSignal) =>
  request<SmokeParametersState>(smokePath(key, 'parameters', department), 'GET', undefined, signal)
export const saveSmokeParameters = (key: string, department: DepartmentId, values: Record<string, boolean | number>) =>
  request<SmokeParametersState>(smokePath(key, 'parameters', department), 'PUT', { values })
export const readSmokeShields = (key: string, department: DepartmentId, signal?: AbortSignal) =>
  request<SmokeShieldState>(smokePath(key, 'shields', department), 'GET', undefined, signal)
export const saveSmokeShields = (key: string, department: DepartmentId, value: Pick<SmokeShieldState, 'enabled' | 'regions'>) =>
  request<SmokeShieldState>(smokePath(key, 'shields', department), 'PUT', value)
export const smokePictureUrl = (key: string, department: DepartmentId) => apiUrl(smokePath(key, 'picture', department))
export type SmokeStatus = Omit<DetectionStatus, 'alarm'> & {
  alarm: boolean | null
  alarm_state: 'active' | 'inactive' | 'unknown'
  connection_state: string
  last_event_at: string | null
  event_channel_id: number
  message: string
}
export const readSmokeStatus = (key: string, department: DepartmentId, signal?: AbortSignal) =>
  request<SmokeStatus>(smokePath(key, 'status', department), 'GET', undefined, signal)
