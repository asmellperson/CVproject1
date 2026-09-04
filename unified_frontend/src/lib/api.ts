import type {
  AppConfigPayload,
  BackendStatus,
  ControlResponse,
  GuardRoomCamera,
  GuardRoomSite,
  StatisticsResponse,
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

const PUBLIC_ORIGIN = trimTrailingSlash((import.meta.env.VITE_PUBLIC_ORIGIN as string | undefined) || '')
const API_BASE = trimTrailingSlash((import.meta.env.VITE_API_BASE as string | undefined) || PUBLIC_ORIGIN)
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

export const getStatus = () => apiGet<BackendStatus>('/status')

export type PlatformServiceStatus = {
  name: string
  url: string
  online: boolean
  running?: boolean
  latency_ms?: number | null
  error?: string | null
  camera_count?: number
  enabled_camera_count?: number
  online_camera_count?: number
  offline_camera_count?: number
  last_frame_age_sec?: number | null
  fps?: number | null
  frame_count?: number | null
  running_cameras?: string[]
  running_models?: string[]
  running_consumers?: string[]
  feature_status?: Record<string, {
    camera_count?: number
    enabled_camera_count?: number
    online_camera_count?: number
    offline_camera_count?: number
  }>
  model_status?: {
    loaded?: boolean
    running_count?: number
    pose_enabled?: boolean
    vlm_ok?: boolean
  }
  worker_status?: Record<string, unknown>
  stats?: Record<string, unknown>
}

export type PlatformStatus = {
  ok: boolean
  level: 'healthy' | 'degraded' | 'down' | string
  generated_at: number
  summary: {
    service_total: number
    service_online: number
    service_running: number
    camera_total: number
    camera_online: number
    camera_offline: number
    model_loaded: Record<string, boolean>
  }
  services: {
    guard_room: PlatformServiceStatus
    aivision: PlatformServiceStatus
    security_vlm: PlatformServiceStatus
  }
}

export const PLATFORM_STATUS_POLL_INTERVAL_MS = 30_000
export const PLATFORM_STATUS_REQUEST_TIMEOUT_MS = 8_000
export const getPlatformStatus = (init?: RequestInit) => apiGet<PlatformStatus>('/platform/status', init)

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
  department?: string | null
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

type AlarmDispositionsResponse = {
  items?: AlarmDisposition[]
}

export const getAlarmDispositions = async (): Promise<AlarmDisposition[]> => {
  const data = await apiGet<AlarmDispositionsResponse>('/alarm-dispositions')
  return data.items || []
}

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

export const getAlarms = async (limit = 100, eventTypes?: readonly string[] | null): Promise<AlarmEvent[]> => {
  const data = await apiGet<AlarmEvent[] | AlarmsResponse>(`/alarms?limit=${limit}${eventTypesQuery(eventTypes)}`)
  return Array.isArray(data) ? data : (data?.items || [])
}

export const getStatistics = async (eventTypes?: readonly string[] | null) =>
  apiGet(`/statistics?days=7${eventTypesQuery(eventTypes)}`)
export const getGuardRoomStatistics = () => apiGet<StatisticsResponse>('/statistics')
export const getConfig = () => apiGet<AppConfigPayload>('/config')
export const saveConfig = (payload: Partial<AppConfigPayload>) => apiPost<{ ok: boolean; restarted: boolean; config: AppConfigPayload }>('/config', payload)
export const startRuntime = () => apiPost<ControlResponse>('/control/start')
export const stopRuntime = () => apiPost<ControlResponse>('/control/stop')
export const restartRuntime = () => apiPost<ControlResponse>('/control/restart')
export const streamUrl = () => `${API_PREFIX}/stream.mjpg`
export const frameUrl = () => `${API_PREFIX}/frame.jpg`
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
  department?: string
  enabled?: boolean
  description?: string | null
  sort_order?: number
}

export type UpdateGuardRoomSitePayload = Partial<CreateGuardRoomSitePayload>

export type CreateGuardRoomCameraPayload = {
  name: string
  rtsp_url: string
  enabled?: boolean
  sort_order?: number
}

export type UpdateGuardRoomCameraPayload = Partial<CreateGuardRoomCameraPayload>

export const guardRoomSitesPath = (department?: string | null) =>
  withQuery('/sites', { department })

export const getGuardRoomSites = async (department?: string | null): Promise<GuardRoomSite[]> => {
  const data = await apiGet<GuardRoomSitesResponse>(guardRoomSitesPath(department))
  return data.items || []
}

export const createGuardRoomSite = (payload: CreateGuardRoomSitePayload) =>
  apiPost<GuardRoomSite>('/sites', payload)

export const updateGuardRoomSite = (siteId: number, payload: UpdateGuardRoomSitePayload) =>
  apiPut<GuardRoomSite>(`/sites/${siteId}`, payload)

export const deleteGuardRoomSite = (siteId: number) =>
  apiDelete<{ success: boolean }>(`/sites/${siteId}`)

export const getGuardRoomSiteConfig = (siteId: number, department?: string | null) =>
  apiGet<AppConfigPayload>(withQuery(`/sites/${siteId}/config`, { department }))

export const saveGuardRoomSiteConfig = (siteId: number, payload: Partial<AppConfigPayload>) =>
  apiPost<{ success: boolean; config: AppConfigPayload }>(`/sites/${siteId}/config`, payload)

export const getGuardRoomSiteStatus = (siteId: number, department?: string | null) =>
  apiGet<BackendStatus>(withQuery(`/sites/${siteId}/status`, { department }))

export const startGuardRoomSiteRuntime = async (siteId: number) => {
  const result = await apiPost<ControlResponse>(`/sites/${siteId}/control/start`)
  notifyPlatformRuntimeChanged()
  return result
}

export const stopGuardRoomSiteRuntime = async (siteId: number) => {
  const result = await apiPost<ControlResponse>(`/sites/${siteId}/control/stop`)
  notifyPlatformRuntimeChanged()
  return result
}

export const restartGuardRoomSiteRuntime = async (siteId: number) => {
  const result = await apiPost<ControlResponse>(`/sites/${siteId}/control/restart`)
  notifyPlatformRuntimeChanged()
  return result
}

export const getGuardRoomSiteCameras = async (siteId: number, department?: string | null): Promise<GuardRoomCamera[]> => {
  const data = await apiGet<GuardRoomCamerasResponse>(withQuery(`/sites/${siteId}/cameras`, { department }))
  return data.items || []
}

export const createGuardRoomSiteCamera = async (siteId: number, payload: CreateGuardRoomCameraPayload) => {
  const camera = await apiPost<GuardRoomCamera>(`/sites/${siteId}/cameras`, payload)
  notifyPlatformCamerasChanged()
  return camera
}

export const updateGuardRoomCamera = async (cameraId: number, payload: UpdateGuardRoomCameraPayload) => {
  const camera = await apiPut<GuardRoomCamera>(`/cameras/${cameraId}`, payload)
  notifyPlatformCamerasChanged()
  return camera
}

export const deleteGuardRoomCamera = async (cameraId: number) => {
  const result = await apiDelete<{ success: boolean }>(`/cameras/${cameraId}`)
  notifyPlatformCamerasChanged()
  return result
}

export const guardRoomSiteFrameUrl = (siteId: number, department?: string | null) =>
  `${API_PREFIX}${withQuery(`/sites/${siteId}/frame.jpg`, { department })}`
export const guardRoomSiteCameraFrameUrl = (siteId: number, cameraId: string, nonce?: number, department?: string | null) => {
  return `${API_PREFIX}${withQuery(`/sites/${siteId}/cameras/${encodeURIComponent(cameraId)}/frame.jpg`, { t: nonce, department })}`
}
