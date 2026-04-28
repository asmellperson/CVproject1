import type {
  AppConfigPayload,
  BackendStatus,
  ControlResponse,
  StatisticsResponse,
} from '@/types'

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

export const getStatus = () => apiGet<BackendStatus>('/status')
// api.ts
export type AlarmEvent = {
  id: string
  source?: 'aivision' | 'guard_room'
  source_id?: string
  event_type: 'absent' | 'phone_use' | 'prone_sleep' | string
  event_label?: string
  violation_type?: number
  camera_no?: string
  camera_name?: string
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
}

type AlarmsResponse = {
  items?: AlarmEvent[]
}

async function aiVisionGet<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`/api/aivision${path}`, {
    ...init,
    method: 'GET',
    credentials: 'include',
    headers: {
      ...(init?.headers || {}),
    },
  })

  notifyUnauthorized(response)
  if (!response.ok) {
    throw new Error(`GET /api/aivision${path} failed: ${response.status} ${response.statusText}`)
  }

  return response.json() as Promise<T>
}

const GUARD_EVENT_META: Record<string, { event_type: string; event_label: string }> = {
  absent: { event_type: 'guard_absent', event_label: '保安离岗' },
  phone_use: { event_type: 'guard_phone_use', event_label: '保安玩手机' },
  prone_sleep: { event_type: 'guard_prone_sleep', event_label: '保安趴睡' },
}

function normalizeGuardAlarm(alarm: AlarmEvent): AlarmEvent {
  const sourceId = String(alarm.id)
  const meta = GUARD_EVENT_META[alarm.event_type] || { event_type: `guard_${alarm.event_type}`, event_label: '保安行为' }
  return {
    ...alarm,
    id: `guard:${sourceId}`,
    source: 'guard_room',
    source_id: sourceId,
    event_type: meta.event_type,
    event_label: meta.event_label,
    camera_no: alarm.camera_name || 'guard_room',
    camera_name: alarm.camera_name || '保安行为规范检测',
    image_url: `${API_PREFIX}/alarms/${encodeURIComponent(sourceId)}/image`,
    video_url: alarm.video_status === 'ready' ? `${API_PREFIX}/alarms/${encodeURIComponent(sourceId)}/video` : null,
  }
}

function normalizeAiVisionAlarm(alarm: AlarmEvent): AlarmEvent {
  const sourceId = String(alarm.id)
  return {
    ...alarm,
    id: `aivision:${sourceId}`,
    source: 'aivision',
    source_id: sourceId,
    image_url: alarm.image_url || `/api/aivision/alarms/${encodeURIComponent(sourceId)}/image`,
    video_url: alarm.video_url || null,
  }
}

export const getGuardRoomAlarms = async (limit = 100): Promise<AlarmEvent[]> => {
  const data = await apiGet<AlarmEvent[] | AlarmsResponse>(`/alarms?limit=${limit}`)
  const items = Array.isArray(data) ? data : (data?.items || [])
  return items.map(normalizeGuardAlarm)
}
export const getAiVisionAlarms = async (limit = 100): Promise<AlarmEvent[]> => {
  const data = await aiVisionGet<AlarmEvent[] | AlarmsResponse>(`/alarms?limit=${limit}`)
  const items = Array.isArray(data) ? data : (data?.items || [])
  return items.map(normalizeAiVisionAlarm)
}
export const getAlarms = async (limit = 100): Promise<AlarmEvent[]> => {
  const [aiVision, guardRoom] = await Promise.allSettled([getAiVisionAlarms(limit), getGuardRoomAlarms(limit)])
  const items = [
    ...(aiVision.status === 'fulfilled' ? aiVision.value : []),
    ...(guardRoom.status === 'fulfilled' ? guardRoom.value : []),
  ]
  return items
    .sort((a, b) => new Date(b.created_at || 0).getTime() - new Date(a.created_at || 0).getTime())
    .slice(0, limit)
}
export const getStatistics = async () => {
  const alarms = await getAlarms(1000)
  const now = new Date()
  const todayStart = new Date(now.getFullYear(), now.getMonth(), now.getDate())
  const rangeStart = new Date(todayStart)
  rangeStart.setDate(todayStart.getDate() - 6)
  const inRange = alarms.filter((alarm) => new Date(alarm.created_at || 0) >= rangeStart)

  const byTypeMap = new Map<string, { event_type: string; name: string; value: number; color: string }>()
  const byCameraMap = new Map<string, { camera_no: string; name: string; value: number }>()
  const typeColor: Record<string, string> = {
    blocks: '#ef4444',
    detect_door: '#f59e0b',
    detect_phone: '#f97316',
    detect_face: '#8b5cf6',
    detect_human: '#2563eb',
    guard_absent: '#dc2626',
    guard_phone_use: '#ea580c',
    guard_prone_sleep: '#ca8a04',
  }
  const typeName: Record<string, string> = {
    blocks: '区域入侵',
    detect_door: '大门开关',
    detect_phone: '手机检测',
    detect_face: '人脸检测',
    detect_human: '人体逗留',
    guard_absent: '保安离岗',
    guard_phone_use: '保安玩手机',
    guard_prone_sleep: '保安趴睡',
  }

  const daily = Array.from({ length: 7 }, (_, index) => {
    const day = new Date(rangeStart)
    day.setDate(rangeStart.getDate() + index)
    return { day: `${day.getMonth() + 1}-${String(day.getDate()).padStart(2, '0')}`, total: 0 } as Record<string, number | string>
  })
  const hourly = Array.from({ length: 24 }, (_, hour) => ({ time: `${String(hour).padStart(2, '0')}:00`, total: 0 } as Record<string, number | string>))

  for (const alarm of inRange) {
    const created = new Date(alarm.created_at || 0)
    if (Number.isNaN(created.getTime())) continue
    const eventType = alarm.event_type
    const label = alarm.event_label || typeName[eventType] || eventType
    const typeRow = byTypeMap.get(eventType) || {
      event_type: eventType,
      name: label,
      value: 0,
      color: typeColor[eventType] || '#64748b',
    }
    typeRow.value += 1
    byTypeMap.set(eventType, typeRow)

    const cameraNo = alarm.camera_no || alarm.camera_name || 'unknown'
    const cameraRow = byCameraMap.get(cameraNo) || {
      camera_no: cameraNo,
      name: alarm.camera_name || cameraNo,
      value: 0,
    }
    cameraRow.value += 1
    byCameraMap.set(cameraNo, cameraRow)

    const dayIndex = Math.floor((new Date(created.getFullYear(), created.getMonth(), created.getDate()).getTime() - rangeStart.getTime()) / 86400000)
    if (dayIndex >= 0 && dayIndex < daily.length) {
      daily[dayIndex].total = Number(daily[dayIndex].total || 0) + 1
      daily[dayIndex][eventType] = Number(daily[dayIndex][eventType] || 0) + 1
    }
    hourly[created.getHours()].total = Number(hourly[created.getHours()].total || 0) + 1
    hourly[created.getHours()][eventType] = Number(hourly[created.getHours()][eventType] || 0) + 1
  }

  const hourlyPeak = hourly.reduce((best, item) => (Number(item.total) > Number(best.total) ? item : best), hourly[0])
  return {
    summary: {
      total: inRange.length,
      today: inRange.filter((alarm) => new Date(alarm.created_at || 0) >= todayStart).length,
      week: inRange.length,
      avg_per_day: Number((inRange.length / 7).toFixed(2)),
      active_cameras: byCameraMap.size,
      peak_hour: hourlyPeak.time || '-',
    },
    by_type: Array.from(byTypeMap.values()),
    by_camera: Array.from(byCameraMap.values()).sort((a, b) => b.value - a.value).slice(0, 8),
    daily,
    hourly,
    recent: alarms.slice(0, 8),
  }
}
export const getGuardRoomStatistics = () => apiGet<StatisticsResponse>('/statistics')
export const getConfig = () => apiGet<AppConfigPayload>('/config')
export const saveConfig = (payload: Partial<AppConfigPayload>) => apiPost<{ ok: boolean; restarted: boolean; config: AppConfigPayload }>('/config', payload)
export const startRuntime = () => apiPost<ControlResponse>('/control/start')
export const stopRuntime = () => apiPost<ControlResponse>('/control/stop')
export const restartRuntime = () => apiPost<ControlResponse>('/control/restart')
export const streamUrl = () => `${API_PREFIX}/stream.mjpg`
export const frameUrl = () => `${API_PREFIX}/frame.jpg`
export const alarmImageUrl = (alarmId: string) => `/api/aivision/alarms/${alarmId}/image`
export const alarmVideoUrl = (alarmId: string) => `/api/aivision/alarms/${alarmId}/video`
