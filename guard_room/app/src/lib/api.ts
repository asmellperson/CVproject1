import type {
  AppConfigPayload,
  BackendStatus,
  ControlResponse,
  StatisticsResponse,
} from '@/types'

const API_BASE = (import.meta.env.VITE_API_BASE as string) || 'http://localhost:5000'
export const API_PREFIX = `${API_BASE}/api`
export const WS_PREFIX = '/ws'

export async function apiGet<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${API_PREFIX}${path}`, {
    ...init,
    method: 'GET',
    headers: {
      ...(init?.headers || {}),
    },
  })

  if (!response.ok) {
    throw new Error(`GET ${path} failed: ${response.status} ${response.statusText}`)
  }

  return response.json() as Promise<T>
}

export async function apiPost<T>(path: string, body?: unknown, init?: RequestInit): Promise<T> {
  const response = await fetch(`${API_PREFIX}${path}`, {
    ...init,
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      ...(init?.headers || {}),
    },
    body: body === undefined ? undefined : JSON.stringify(body),
  })

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
  event_type: 'absent' | 'phone_use' | 'prone_sleep' | string
  reason: string
  confidence: number
  created_at?: string
  frame_index?: number
  track_id?: number | null
  image_path?: string
  video_path?: string | null
  video_status?: 'pending' | 'ready' | 'failed'
}

type AlarmsResponse = {
  items?: AlarmEvent[]
}

export const getAlarms = async (limit = 100): Promise<AlarmEvent[]> => {
  const data = await apiGet<AlarmEvent[] | AlarmsResponse>(`/alarms?limit=${limit}`)
  return Array.isArray(data) ? data : (data?.items || [])
}
export const getStatistics = () => apiGet<StatisticsResponse>('/statistics')
export const getConfig = () => apiGet<AppConfigPayload>('/config')
export const saveConfig = (payload: Partial<AppConfigPayload>) => apiPost<{ ok: boolean; restarted: boolean; config: AppConfigPayload }>('/config', payload)
export const startRuntime = () => apiPost<ControlResponse>('/control/start')
export const stopRuntime = () => apiPost<ControlResponse>('/control/stop')
export const restartRuntime = () => apiPost<ControlResponse>('/control/restart')
export const streamUrl = () => `${API_PREFIX}/stream.mjpg`
export const frameUrl = () => `${API_PREFIX}/frame.jpg`
export const alarmImageUrl = (alarmId: string) => `${API_PREFIX}/alarms/${alarmId}/image`
export const alarmVideoUrl = (alarmId: string) => `${API_PREFIX}/alarms/${alarmId}/video`
