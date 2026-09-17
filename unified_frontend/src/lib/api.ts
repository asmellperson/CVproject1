import type { DepartmentId } from '@/auth/permissions'
import type {
  AppConfigPayload,
  BackendStatus,
  ControlResponse,
  GuardRoomCamera,
  GuardRoomSite,
} from '@/types'
import { notifyPlatformCamerasChanged } from '@/lib/camera-events'
import { notifyPlatformRuntimeChanged } from '@/lib/runtime-events'

function trimTrailingSlash(value: string) {
  return value.replace(/\/+$/, '')
}

function joinUrl(base: string, path: string) {
  const normalizedPath = path.startsWith('/') ? path : `/${path}`
  return base ? `${trimTrailingSlash(base)}${normalizedPath}` : normalizedPath
}

function toWsBase(base: string) {
  if (base.startsWith('https://')) return `wss://${base.slice('https://'.length)}`
  if (base.startsWith('http://')) return `ws://${base.slice('http://'.length)}`
  return base
}

const API_BASE = trimTrailingSlash((import.meta.env.VITE_API_BASE as string | undefined) || '')
const WS_BASE = trimTrailingSlash((import.meta.env.VITE_WS_BASE as string | undefined) || toWsBase(API_BASE))

export const API_PREFIX = joinUrl(API_BASE, '/api')
export const WS_PREFIX = joinUrl(WS_BASE, '/ws')

export const apiUrl = (path: string) => joinUrl(API_PREFIX, path)

function notifyUnauthorized(response: Response) {
  if (response.status === 401) {
    window.dispatchEvent(new Event('aicv:unauthorized'))
  }
}

export async function apiGet<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${API_PREFIX}${path}`, {
    ...init,
    method: 'GET',
    credentials: 'include',
    headers: {
      ...(init?.headers || {}),
    },
  })

  notifyUnauthorized(response)
  if (!response.ok) {
    throw new Error(`GET ${path} failed: ${response.status} ${response.statusText}`)
  }

  return response.json() as Promise<T>
}

export async function apiPost<T>(path: string, body?: unknown, init?: RequestInit): Promise<T> {
  const response = await fetch(`${API_PREFIX}${path}`, {
    ...init,
    method: 'POST',
    credentials: 'include',
    headers: {
      'Content-Type': 'application/json',
      ...(init?.headers || {}),
    },
    body: body === undefined ? undefined : JSON.stringify(body),
  })

  notifyUnauthorized(response)
  if (!response.ok) {
    const detail = await response.text().catch(() => '')
    throw new Error(`POST ${path} failed: ${response.status} ${response.statusText} ${detail}`)
  }

  return response.json() as Promise<T>
}

export async function apiPut<T>(path: string, body?: unknown, init?: RequestInit): Promise<T> {
  const response = await fetch(`${API_PREFIX}${path}`, {
    ...init,
    method: 'PUT',
    credentials: 'include',
    headers: {
      'Content-Type': 'application/json',
      ...(init?.headers || {}),
    },
    body: body === undefined ? undefined : JSON.stringify(body),
  })

  notifyUnauthorized(response)
  if (!response.ok) {
    const detail = await response.text().catch(() => '')
    throw new Error(`PUT ${path} failed: ${response.status} ${response.statusText} ${detail}`)
  }

  return response.json() as Promise<T>
}

export async function apiPatch<T>(path: string, body?: unknown, init?: RequestInit): Promise<T> {
  const response = await fetch(`${API_PREFIX}${path}`, {
    ...init,
    method: 'PATCH',
    credentials: 'include',
    headers: {
      'Content-Type': 'application/json',
      ...(init?.headers || {}),
    },
    body: body === undefined ? undefined : JSON.stringify(body),
  })

  notifyUnauthorized(response)
  if (!response.ok) {
    const detail = await response.text().catch(() => '')
    throw new Error(`PATCH ${path} failed: ${response.status} ${response.statusText} ${detail}`)
  }

  return response.json() as Promise<T>
}

export async function apiDelete<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${API_PREFIX}${path}`, {
    ...init,
    method: 'DELETE',
    credentials: 'include',
  })

  notifyUnauthorized(response)
  if (!response.ok) {
    const detail = await response.text().catch(() => '')
    throw new Error(`DELETE ${path} failed: ${response.status} ${response.statusText} ${detail}`)
  }

  return response.json() as Promise<T>
}


export type OverviewServiceStatus = {
  online: boolean
  running: boolean
  error: string | null
  latency_ms: number | null
  camera_count: number
  online_camera_count: number
  model_ready: boolean
}

export type OverviewCapability = {
  id: string
  name: string
  source: 'aivision' | 'guard_room' | 'security_vlm'
  camera_count: number
  online_camera_count: number
  running: boolean
  model_ready: boolean
}

export type OverviewCamera = {
  key: string
  source: OverviewCapability['source']
  camera_id: string | number
  name: string
  department: DepartmentId
  identifier: string
  enabled: boolean
  online: boolean
  capabilities: string[]
  running_capabilities: string[]
  logistics_memberships: import('@/components/logistics_single_person/types').LogisticsCameraInventoryMembership[]
  aivision_camera: import('./aivision').AiVisionCamera | null
  site_id: number | null
}

export type OverviewStatus = {
  department: DepartmentId
  ok: boolean
  level: 'healthy' | 'degraded' | 'down'
  generated_at: number
  inventory_complete: boolean
  inventory_errors: Record<string, string>
  summary: {
    capability_total: number
    capability_online: number
    capability_running: number
    camera_total: number
    camera_online: number
    camera_offline: number
  }
  capabilities: OverviewCapability[]
  cameras: OverviewCamera[]
  services: Record<OverviewCapability['source'], OverviewServiceStatus>
  guard_room_sites: Array<{ id: number; name: string; department: DepartmentId }>
}

export const OVERVIEW_POLL_INTERVAL_MS = 30_000
export const OVERVIEW_REQUEST_TIMEOUT_MS = 8_000
export const getOverview = (department: DepartmentId, init?: RequestInit) => apiGet<OverviewStatus>(`/overview?department=${department}`, init)

export type AlarmEvent = {
  id: string
  source?: 'aivision' | 'guard_room' | 'security_vlm'
  source_id?: string
  site_id?: number
  site_name?: string
  event_type: 'absent' | 'phone_use' | 'prone_sleep' | string
  event_label?: string
  violation_type?: number | null
  feature_name?: string | null
  department: DepartmentId
  subject_type?: string
  subject_id?: string | null
  subject_name?: string | null
  channel_id?: string | null
  channel_name?: string | null
  camera_no?: string | null
  camera_name?: string | null
  reason: string
  confidence: number
  created_at?: string
  frame_index?: number
  track_id?: number | null
  image_path?: string
  image_url?: string
  video_path?: string | null
  video_url?: string | null
  video_status?: 'pending' | 'ready' | 'failed'
  camera_ids?: number[]
  camera_names?: Record<string, string>
  camera_counts?: Record<string, number | null>
  camera_states?: Record<string, Record<string, unknown>>
  offending_camera_ids?: number[]
  evidence_error?: string | null
  metadata?: Record<string, unknown>
  disposition_status?: AlarmDispositionStatus
  disposition_note?: string
  disposition_updated_at?: string
  disposition_updated_by?: AlarmDispositionActor | null
}

type AlarmsResponse = {
  items?: AlarmEvent[]
}

export type AlarmDispositionStatus = 'pending' | 'acknowledged' | 'resolved' | 'false_positive'

export type AlarmDispositionActor = {
  employee_id: string
  name: string
}

export type AlarmDisposition = {
  alarm_id: string
  status: AlarmDispositionStatus
  note: string
  updated_at: string
  updated_by?: AlarmDispositionActor | null
}

export type AlarmDispositionsPage = {
  items: AlarmDisposition[]
  next_cursor: string | null
  stop_reason: 'page_full' | 'scan_limit' | 'end'
}

// scan_limit 可能返回空页；只有 next_cursor === null 才表示结束。
export const getAlarmDispositions = (
  options: { limit?: number; cursor?: string | null } = {},
  signal?: AbortSignal,
): Promise<AlarmDispositionsPage> =>
  apiGet<AlarmDispositionsPage>(withQuery('/alarm-dispositions', options), { signal })

export const updateAlarmDisposition = async (
  alarmId: string,
  status: AlarmDispositionStatus,
  note = '',
): Promise<AlarmDisposition> => {
  const data = await apiPost<{ success: boolean; item: AlarmDisposition }>('/alarm-dispositions', {
    alarm_id: alarmId,
    status,
    note,
  })
  return data.item
}

function eventTypesQuery(eventTypes?: readonly string[] | null) {
  return eventTypes && eventTypes.length > 0 ? `&event_types=${encodeURIComponent(eventTypes.join(','))}` : ''
}

function queryString(params: Record<string, string | number | undefined | null>) {
  const query = new URLSearchParams()
  Object.entries(params).forEach(([key, value]) => {
    if (value !== undefined && value !== null && String(value).trim()) {
      query.set(key, String(value))
    }
  })
  const text = query.toString()
  return text ? `?${text}` : ''
}

function withQuery(path: string, params: Record<string, string | number | undefined | null>) {
  const query = queryString(params)
  if (!query) return path
  return `${path}${path.includes('?') ? `&${query.slice(1)}` : query}`
}

export const getAlarms = async (limit = 100, eventTypes?: readonly string[] | null, department?: DepartmentId): Promise<AlarmEvent[]> => {
  const data = await apiGet<AlarmEvent[] | AlarmsResponse>(withQuery(`/alarms?limit=${limit}${eventTypesQuery(eventTypes)}`, { department }))
  return Array.isArray(data) ? data : (data?.items || [])
}

export const getStatistics = async (eventTypes?: readonly string[] | null) =>
  apiGet(`/statistics?days=7${eventTypesQuery(eventTypes)}`)
export const alarmImageUrl = (alarmId: string) => `/api/alarms/${alarmId}/image`
export const alarmVideoUrl = (alarmId: string) => `/api/alarms/${alarmId}/video`

type GuardRoomSitesResponse = {
  items?: GuardRoomSite[]
}

type GuardRoomCamerasResponse = {
  items?: GuardRoomCamera[]
}

export type CreateGuardRoomSitePayload = {
  name: string
  department: DepartmentId
  enabled?: boolean
  description?: string | null
  sort_order?: number
}

export type UpdateGuardRoomSitePayload = Partial<Omit<CreateGuardRoomSitePayload, 'department'>>

export type CreateGuardRoomCameraPayload = {
  name: string
  rtsp_url: string
  enabled?: boolean
  sort_order?: number
}

export type UpdateGuardRoomCameraPayload = Partial<CreateGuardRoomCameraPayload>

export const guardRoomSitesPath = (department: DepartmentId) =>
  withQuery('/guard-room/sites', { department })

export const getGuardRoomSites = async (department: DepartmentId): Promise<GuardRoomSite[]> => {
  const data = await apiGet<GuardRoomSitesResponse>(guardRoomSitesPath(department))
  return data.items || []
}

export const createGuardRoomSite = (payload: CreateGuardRoomSitePayload) =>
  apiPost<GuardRoomSite>('/guard-room/sites', payload)

export const updateGuardRoomSite = (siteId: number, payload: UpdateGuardRoomSitePayload, department: DepartmentId) =>
  apiPut<GuardRoomSite>(withQuery(`/guard-room/sites/${siteId}`, { department }), payload)

export const deleteGuardRoomSite = (siteId: number, department: DepartmentId) =>
  apiDelete<{ success: boolean }>(withQuery(`/guard-room/sites/${siteId}`, { department }))

export const getGuardRoomSiteConfig = (siteId: number, department: DepartmentId) =>
  apiGet<AppConfigPayload>(withQuery(`/guard-room/sites/${siteId}/config`, { department }))

export const saveGuardRoomSiteConfig = (siteId: number, payload: Partial<AppConfigPayload>, department: DepartmentId) =>
  apiPost<{ success: boolean; config: AppConfigPayload }>(withQuery(`/guard-room/sites/${siteId}/config`, { department }), payload)

export const getGuardRoomSiteStatus = (siteId: number, department: DepartmentId) =>
  apiGet<BackendStatus>(withQuery(`/guard-room/sites/${siteId}/status`, { department }))

export const startGuardRoomSiteRuntime = async (siteId: number, department: DepartmentId) => {
  const result = await apiPost<ControlResponse>(withQuery(`/guard-room/sites/${siteId}/control/start`, { department }))
  notifyPlatformRuntimeChanged()
  return result
}

export const stopGuardRoomSiteRuntime = async (siteId: number, department: DepartmentId) => {
  const result = await apiPost<ControlResponse>(withQuery(`/guard-room/sites/${siteId}/control/stop`, { department }))
  notifyPlatformRuntimeChanged()
  return result
}

export const restartGuardRoomSiteRuntime = async (siteId: number, department: DepartmentId) => {
  const result = await apiPost<ControlResponse>(withQuery(`/guard-room/sites/${siteId}/control/restart`, { department }))
  notifyPlatformRuntimeChanged()
  return result
}

export const getGuardRoomSiteCameras = async (siteId: number, department: DepartmentId): Promise<GuardRoomCamera[]> => {
  const data = await apiGet<GuardRoomCamerasResponse>(withQuery(`/guard-room/sites/${siteId}/cameras`, { department }))
  return data.items || []
}

export const createGuardRoomSiteCamera = async (siteId: number, payload: CreateGuardRoomCameraPayload, department: DepartmentId) => {
  const camera = await apiPost<GuardRoomCamera>(withQuery(`/guard-room/sites/${siteId}/cameras`, { department }), payload)
  notifyPlatformCamerasChanged()
  return camera
}

export const updateGuardRoomCamera = async (cameraId: number, payload: UpdateGuardRoomCameraPayload, department: DepartmentId) => {
  const camera = await apiPut<GuardRoomCamera>(withQuery(`/guard-room/cameras/${cameraId}`, { department }), payload)
  notifyPlatformCamerasChanged()
  return camera
}

export const deleteGuardRoomCamera = async (cameraId: number, department: DepartmentId) => {
  const result = await apiDelete<{ success: boolean }>(withQuery(`/guard-room/cameras/${cameraId}`, { department }))
  notifyPlatformCamerasChanged()
  return result
}

export const guardRoomSiteFrameUrl = (siteId: number, department: DepartmentId) =>
  `${API_PREFIX}${withQuery(`/guard-room/sites/${siteId}/frame.jpg`, { department })}`
export const guardRoomSiteCameraFrameUrl = (siteId: number, cameraId: string, nonce: number | undefined, department: DepartmentId) => {
  return `${API_PREFIX}${withQuery(`/guard-room/sites/${siteId}/cameras/${encodeURIComponent(cameraId)}/frame.jpg`, { t: nonce, department })}`
}
