import { apiUrl } from '@/lib/api'

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

export type HornSip = { username: string; auth_id: string; port: number; password_set: boolean }
export type HornSipWrite = { username: string; auth_id: string; port: number; password?: string }
export type HornAudio = { id: number; name: string; size: number; duration: number }
export type HornSipServer = { enabled: boolean; address: string; port: number; running: boolean; last_error: string | null }
export type HornPlaybackResult = HornConnectionResult & { message: string }

export type HornDevice = {
  id: number
  name: string
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

  constructor(status: number, message: string) {
    super(message)
    this.name = 'HornApiError'
    this.status = status
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
    const message = response.status === 403 ? '当前账号无权访问喇叭设备，请使用管理员账号。'
      : response.status === 404 ? (typeof data?.detail === 'string' ? data.detail : '记录已不存在，请刷新列表。')
        : method === 'DELETE' && response.status === 409
          ? '该设备仍被检测配置引用，请先解除普通检测功能或物流通道中的喇叭绑定，再删除设备。'
          : typeof data?.detail === 'string' ? data.detail
            : response.status === 422 ? '设备信息校验失败，请检查名称、地址、用户名和密码。'
              : `喇叭设备请求失败（HTTP ${response.status}），请稍后重试。`
    throw new HornApiError(response.status, message)
  }
  // DELETE 成功没有响应体，不能按 JSON 解析。
  if (response.status === 204) return undefined as T
  return response.json() as Promise<T>
}

export const listHorns = (signal?: AbortSignal) => request<HornDevice[]>('', 'GET', undefined, signal)
export const getHorn = (id: number, signal?: AbortSignal) => request<HornDevice>(`/${id}`, 'GET', undefined, signal)
export const createHorn = (payload: HornWrite & { password: string }, signal?: AbortSignal) =>
  request<HornDevice>('', 'POST', payload, signal)
export const updateHorn = (id: number, payload: Partial<HornWrite>, signal?: AbortSignal) =>
  request<HornDevice>(`/${id}`, 'PATCH', payload, signal)
export const deleteHorn = (id: number, signal?: AbortSignal) => request<void>(`/${id}`, 'DELETE', undefined, signal)
export const getHornStatus = (id: number, signal?: AbortSignal) => request<HornRuntime>(`/${id}/status`, 'GET', undefined, signal)
export const testHornConnection = (payload: HornConnectionInput, signal?: AbortSignal) =>
  request<HornConnectionResult>('/test-connection', 'POST', payload, signal)

export const getHornSipServer = (signal?: AbortSignal) => request<HornSipServer>('/sip-server', 'GET', undefined, signal)
export const saveHornSipServer = (payload: Pick<HornSipServer, 'enabled' | 'address' | 'port'>, signal?: AbortSignal) =>
  request<HornSipServer>('/sip-server', 'PUT', payload, signal)
export const listHornAudio = (signal?: AbortSignal) => request<HornAudio[]>('/audio', 'GET', undefined, signal)
export const uploadHornAudio = (file: File, signal?: AbortSignal) => request<HornAudio>('/audio', 'POST', file, signal)
export const deleteHornAudio = (id: number, signal?: AbortSignal) => request<void>(`/audio/${id}`, 'DELETE', undefined, signal)
export const testHornPlayback = (hornId: number, audioId: number, signal?: AbortSignal) =>
  request<HornPlaybackResult>(`/${hornId}/test-play`, 'POST', { audio_id: audioId }, signal)
