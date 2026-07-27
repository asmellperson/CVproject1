function readError(response: Response) {
  return response.text().then((text) => {
    if (!text) return `${response.status} ${response.statusText}`
    try {
      const parsed = JSON.parse(text) as { detail?: string; message?: string }
      return parsed.detail || parsed.message || text
    } catch {
      return text
    }
  })
}

async function securityVlmRequest<T>(
  method: 'GET' | 'POST' | 'PUT' | 'DELETE',
  path: string,
  body?: unknown,
  init?: RequestInit,
): Promise<T> {
  const response = await fetch(`/security-vlm${path}`, {
    ...init,
    method,
    credentials: 'include',
    headers: {
      ...(body === undefined ? {} : { 'Content-Type': 'application/json' }),
      ...(init?.headers || {}),
    },
    body: body === undefined ? undefined : JSON.stringify(body),
  })

  if (response.status === 401) {
    window.dispatchEvent(new Event('aicv:unauthorized'))
  }
  if (!response.ok) {
    throw new Error(await readError(response))
  }

  return response.json() as Promise<T>
}

const securityVlmGet = <T>(path: string, init?: RequestInit) =>
  securityVlmRequest<T>('GET', path, undefined, init)
const securityVlmPost = <T>(path: string, body?: unknown, init?: RequestInit) =>
  securityVlmRequest<T>('POST', path, body, init)
const securityVlmPut = <T>(path: string, body?: unknown, init?: RequestInit) =>
  securityVlmRequest<T>('PUT', path, body, init)
const securityVlmDelete = <T>(path: string, init?: RequestInit) =>
  securityVlmRequest<T>('DELETE', path, undefined, init)

export type SecurityVlmWorkerStatus = {
  ok?: boolean
  width?: number
  height?: number
  fps?: number
  [key: string]: unknown
}

export type SecurityVlmStats = {
  total?: number
  compliant?: number
  non_compliant?: number
  error?: number
  rate?: number
  queue?: number
  budget?: {
    spent_yuan?: number
    daily_limit_yuan?: number
  }
}

export type SecurityVlmHistoryItem = {
  time?: string
  session_id?: string
  camera_id?: string
  camera_name?: string
  roi_name?: string
  duration_sec?: number
  status?: 'compliant' | 'non_compliant' | 'error' | string
  upper_checked?: boolean | null
  middle_checked?: boolean | null
  lower_checked?: boolean | null
  arms_open?: boolean | null
  reason?: string
  error?: string
}

export type SecurityVlmCamera = {
  camera_id: string
  name: string
  rtsp_url: string
  has_rtsp_url: boolean
  running: boolean
  desired_running?: boolean
  workers?: Record<string, boolean>
  last_error?: string
  restart_at?: number | null
  capture?: SecurityVlmWorkerStatus
  detector?: SecurityVlmWorkerStatus
  session?: SecurityVlmWorkerStatus
  staff_rois?: Record<string, number[]>
}

export type SecurityVlmCameraCredentials = Pick<
  SecurityVlmCamera,
  'camera_id' | 'name' | 'rtsp_url'
>

export type SecurityVlmHealth = {
  running?: boolean
  ts?: number
  capture?: SecurityVlmWorkerStatus
  detector?: SecurityVlmWorkerStatus
  session?: SecurityVlmWorkerStatus
  vlm?: SecurityVlmWorkerStatus
  stats?: SecurityVlmStats
  history?: SecurityVlmHistoryItem[]
  staff_rois?: Record<string, number[]>
  cameras?: SecurityVlmCamera[]
}

export type SecurityVlmRoisResponse = {
  staff_rois: Record<string, number[]>
  available_slots: string[]
  video_id?: string
  camera_id?: string
  ok?: boolean
}

export type SecurityVlmControlResponse = {
  ok?: boolean
  success?: boolean
  camera_id?: string
  running?: boolean
  desired_running?: boolean
  message?: string
  results?: Record<string, SecurityVlmControlResponse>
}

export const getSecurityVlmHealth = () => securityVlmGet<SecurityVlmHealth>('/health')

export const getSecurityVlmHistory = (limit = 100, cameraId?: string) => {
  const query = new URLSearchParams({ limit: String(limit) })
  if (cameraId) query.set('camera_id', cameraId)
  return securityVlmGet<{ date?: string; stats?: SecurityVlmStats; history?: SecurityVlmHistoryItem[] }>(`/api/history?${query}`)
}

export const getSecurityVlmCameras = () =>
  securityVlmGet<{ cameras: SecurityVlmCamera[] }>('/api/cameras')

export const getSecurityVlmCameraCredentials = (cameraId: string) =>
  securityVlmGet<{ camera: SecurityVlmCameraCredentials }>(
    `/api/cameras/${encodeURIComponent(cameraId)}/credentials`,
  )

export const createSecurityVlmCamera = (name: string, rtspUrl: string) =>
  securityVlmPost<{ ok: boolean; camera: SecurityVlmCamera }>('/api/cameras', {
    name,
    rtsp_url: rtspUrl,
  })

export const updateSecurityVlmCamera = (cameraId: string, name: string, rtspUrl: string) =>
  securityVlmPut<{ ok: boolean; camera: SecurityVlmCamera }>(
    `/api/cameras/${encodeURIComponent(cameraId)}`,
    { name, rtsp_url: rtspUrl },
  )

export const deleteSecurityVlmCamera = (cameraId: string) =>
  securityVlmDelete<{ ok: boolean; camera: SecurityVlmCamera }>(
    `/api/cameras/${encodeURIComponent(cameraId)}`,
  )

export const testSecurityVlmCamera = (rtspUrl: string) =>
  securityVlmPost<{ ok: boolean; codec_name: string; width: number; height: number }>(
    '/api/cameras/test',
    { rtsp_url: rtspUrl },
  )

export const controlSecurityVlmCamera = (
  cameraId: string,
  action: 'start' | 'stop' | 'restart',
) =>
  securityVlmPost<SecurityVlmControlResponse>(
    `/api/cameras/${encodeURIComponent(cameraId)}/control/${action}`,
  )

export const startAllSecurityVlmCameras = () =>
  securityVlmPost<SecurityVlmControlResponse>('/api/cameras/control/start-all')

export const stopAllSecurityVlmCameras = () =>
  securityVlmPost<SecurityVlmControlResponse>('/api/cameras/control/stop-all')

export const getSecurityVlmCameraRois = (cameraId: string) =>
  securityVlmGet<SecurityVlmRoisResponse>(
    `/api/cameras/${encodeURIComponent(cameraId)}/rois`,
  )

export const saveSecurityVlmCameraRois = (
  cameraId: string,
  staffRois: Record<string, number[]>,
) =>
  securityVlmPost<SecurityVlmRoisResponse>(
    `/api/cameras/${encodeURIComponent(cameraId)}/rois`,
    { staff_rois: staffRois },
  )

export const getSecurityVlmRois = () => securityVlmGet<SecurityVlmRoisResponse>('/api/rois')

export const saveSecurityVlmRois = (staff_rois: Record<string, number[]>) =>
  securityVlmPost<SecurityVlmRoisResponse>('/api/rois', { staff_rois })

export const startSecurityVlmRuntime = () => securityVlmPost<{ success?: boolean; running: boolean }>('/api/control/start')

export const stopSecurityVlmRuntime = () => securityVlmPost<{ success?: boolean; running: boolean }>('/api/control/stop')

export const restartSecurityVlmRuntime = () => securityVlmPost<{ success?: boolean; running: boolean }>('/api/control/restart')

export const securityVlmVideoUrl = (kind: 'original' | 'rule', nonce?: number) =>
  `/security-vlm/video/${kind}${nonce ? `?t=${nonce}` : ''}`

export const securityVlmCameraVideoUrl = (
  cameraId: string,
  kind: 'original' | 'rule',
  nonce?: number,
) =>
  `/security-vlm/video/${encodeURIComponent(cameraId)}/${kind}${nonce ? `?t=${nonce}` : ''}`
