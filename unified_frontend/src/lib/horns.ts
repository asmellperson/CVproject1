import { apiUrl } from '@/lib/api'
import type { DepartmentId } from '@/auth/permissions'

export type HornScope = DepartmentId | 'unassigned'
export type HornReference = {
  key: string; kind: 'camera' | 'logistics_channel' | 'guard_site'; feature: string; feature_label: string
  department: string | null; department_label: string; resource_id: number; resource_name: string
  detection_enabled: boolean; horn_enabled: boolean; audio_id: number | null; alarm_label: string | null
}
export type HornUsage = { horn_id: number; device_enabled: boolean; references: HornReference[]; revision: string }
export type HornDeleteRequest = { detach_bindings: boolean; expected_revision: string }

export type HornState = 'disabled' | 'not_started' | 'pending' | 'connecting' | 'online'
  | 'offline' | 'failed' | 'stopping' | 'stopped'

export type HornRuntime = {
  state: HornState
  online: boolean
  heartbeat_alive: boolean
  last_error: string | null
  last_seen_at: number | null
  sip_ready?: boolean
  playing?: boolean
}

export type HornSip = { username: string; auth_id: string; port: number; volume_percent: number; password_set: boolean }
export type HornSipWrite = { username: string; auth_id: string; port: number; volume_percent: number; password?: string }
export type HornAudio = { id: number; name: string; size: number; duration: number }
export type HornSipServer = { enabled: boolean; address: string; port: number; running: boolean; last_error: string | null }
export type HornPlaybackResult = HornConnectionResult & { message: string }

export type HornDevice = {
  id: number
  name: string
  department: DepartmentId | null
  url: string
  username: string
  password_set: boolean
  enable: boolean
  description: string | null
  runtime: HornRuntime
  sip?: HornSip | null
}

export type HornWrite = {
  name: string
  department: DepartmentId
  url: string
  username: string
  password?: string
  enable: boolean
  description: string | null
  sip?: HornSipWrite | null
}

export type HornConnectionInput = {
  horn_id?: number
  url?: string
  username?: string
  password?: string
}

export type HornConnectionResult = { success: boolean; runtime: HornRuntime }

export class HornApiError extends Error {
  readonly status: number
  readonly usage?: HornUsage

  constructor(status: number, message: string, usage?: HornUsage) {
    super(message)
    this.name = 'HornApiError'
    this.status = status
    this.usage = usage
  }
}

async function request<T>(path: string, method = 'GET', body?: unknown, signal?: AbortSignal): Promise<T> {
  const response = await fetch(apiUrl(`/horns${path}`), {
    method, credentials: 'include', signal,
    headers: body === undefined ? undefined : typeof File !== 'undefined' && body instanceof File
      ? { 'Content-Type': 'application/octet-stream', 'X-Audio-Filename': encodeURIComponent(body.name) }
      : { 'Content-Type': 'application/json' },
    body: body === undefined ? undefined : typeof File !== 'undefined' && body instanceof File ? body : JSON.stringify(body),
  })
  if (response.status === 401) window.dispatchEvent(new Event('aicv:unauthorized'))
  if (!response.ok) {
    const data = await response.json().catch(() => null) as { detail?: unknown } | null
    const detail = data?.detail as { message?: string; usage?: HornUsage } | string | undefined
    const serverMessage = typeof detail === 'string' ? detail : detail?.message
    const message = response.status === 403 ? '当前账号无权访问喇叭设备，请使用管理员账号。'
      : response.status === 404 ? (typeof data?.detail === 'string' ? data.detail : '记录已不存在，请刷新列表。')
        : serverMessage ? serverMessage
            : response.status === 422 ? '设备信息校验失败，请检查名称、地址、账号、密码和音频响度。'
              : `喇叭设备请求失败（HTTP ${response.status}），请稍后重试。`
    throw new HornApiError(response.status, message, typeof detail === 'object' ? detail?.usage : undefined)
  }
  // DELETE 成功没有响应体，不能按 JSON 解析。
  if (response.status === 204) return undefined as T
  return response.json() as Promise<T>
}

const scoped = (path: string, scope: HornScope) => `${path}?${new URLSearchParams(scope === 'unassigned' ? { unassigned: 'true' } : { department: scope })}`
export const listHorns = (scope: HornScope, signal?: AbortSignal) => request<HornDevice[]>(scoped('', scope), 'GET', undefined, signal)
export const getHorn = (id: number, scope: HornScope, signal?: AbortSignal) => request<HornDevice>(scoped(`/${id}`, scope), 'GET', undefined, signal)
export const createHorn = (payload: HornWrite & { password: string }, signal?: AbortSignal) =>
  request<HornDevice>('', 'POST', payload, signal)
export const updateHorn = (id: number, payload: Partial<HornWrite>, scope: HornScope, signal?: AbortSignal) =>
  request<HornDevice>(scoped(`/${id}`, scope), 'PATCH', payload, signal)
export const deleteHorn = (id: number, scope: HornScope, payload: HornDeleteRequest, signal?: AbortSignal) =>
  request<void>(scoped(`/${id}`, scope), 'DELETE', payload, signal)
export const getHornStatus = (id: number, scope: HornScope, signal?: AbortSignal) => request<HornRuntime>(scoped(`/${id}/status`, scope), 'GET', undefined, signal)
export const getHornUsage = (id: number, scope: HornScope, signal?: AbortSignal) => request<HornUsage>(scoped(`/${id}/references`, scope), 'GET', undefined, signal)
export const testHornConnection = (payload: HornConnectionInput, scope: HornScope, signal?: AbortSignal) =>
  request<HornConnectionResult>(scoped('/test-connection', scope), 'POST', payload, signal)

export const getHornSipServer = (signal?: AbortSignal) => request<HornSipServer>('/sip-server', 'GET', undefined, signal)
export const saveHornSipServer = (payload: Pick<HornSipServer, 'enabled' | 'address' | 'port'>, signal?: AbortSignal) =>
  request<HornSipServer>('/sip-server', 'PUT', payload, signal)
export const listHornAudio = (signal?: AbortSignal) => request<HornAudio[]>('/audio', 'GET', undefined, signal)
export const uploadHornAudio = (file: File, signal?: AbortSignal) => request<HornAudio>('/audio', 'POST', file, signal)
export const deleteHornAudio = (id: number, signal?: AbortSignal) => request<void>(`/audio/${id}`, 'DELETE', undefined, signal)
export const testHornPlayback = (hornId: number, audioId: number, scope: HornScope, signal?: AbortSignal) =>
  request<HornPlaybackResult>(scoped(`/${hornId}/test-play`, scope), 'POST', { audio_id: audioId }, signal)
