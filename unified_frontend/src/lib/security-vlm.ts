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

export type SecurityVlmDepartment =
  | 'general_electric'
  | 'electronics_electrician'
  | 'electrical_components'
  | 'precious_metal_recycling'

const departmentApi = (department: SecurityVlmDepartment) =>
  `/api/departments/${encodeURIComponent(department)}`

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

export type SecurityVlmRoiPoint = [number, number]
export type SecurityVlmRoiPolygon = SecurityVlmRoiPoint[]
export type SecurityVlmLegacyRoiRect = [number, number, number, number]
export type SecurityVlmRoiValue = SecurityVlmRoiPolygon | SecurityVlmLegacyRoiRect
export type SecurityVlmRoiMap = Record<string, SecurityVlmRoiValue>

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
  staff_rois?: SecurityVlmRoiMap
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
  staff_rois?: SecurityVlmRoiMap
  cameras?: SecurityVlmCamera[]
}

export type SecurityVlmRoisResponse = {
  staff_rois: SecurityVlmRoiMap
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

export const getSecurityVlmHealth = (department: SecurityVlmDepartment) =>
  securityVlmGet<SecurityVlmHealth>(`${departmentApi(department)}/health`)

export const getSecurityVlmHistory = (
  department: SecurityVlmDepartment,
  limit = 100,
  cameraId?: string,
) => {
  const query = new URLSearchParams({ limit: String(limit) })
  if (cameraId) query.set('camera_id', cameraId)
  return securityVlmGet<{ date?: string; stats?: SecurityVlmStats; history?: SecurityVlmHistoryItem[] }>(
    `${departmentApi(department)}/history?${query}`,
  )
}

export const getSecurityVlmCameras = (department: SecurityVlmDepartment) =>
  securityVlmGet<{ cameras: SecurityVlmCamera[] }>(
    `${departmentApi(department)}/cameras`,
  )

export const getSecurityVlmCameraCredentials = (
  department: SecurityVlmDepartment,
  cameraId: string,
) =>
  securityVlmGet<{ camera: SecurityVlmCameraCredentials }>(
    `${departmentApi(department)}/cameras/${encodeURIComponent(cameraId)}/credentials`,
  )

export const createSecurityVlmCamera = (
  department: SecurityVlmDepartment,
  name: string,
  rtspUrl: string,
) =>
  securityVlmPost<{ ok: boolean; camera: SecurityVlmCamera }>(
    `${departmentApi(department)}/cameras`,
    { name, rtsp_url: rtspUrl },
  )

export const updateSecurityVlmCamera = (
  department: SecurityVlmDepartment,
  cameraId: string,
  name: string,
  rtspUrl: string,
) =>
  securityVlmPut<{ ok: boolean; camera: SecurityVlmCamera }>(
    `${departmentApi(department)}/cameras/${encodeURIComponent(cameraId)}`,
    { name, rtsp_url: rtspUrl },
  )

export const deleteSecurityVlmCamera = (
  department: SecurityVlmDepartment,
  cameraId: string,
) =>
  securityVlmDelete<{ ok: boolean; camera: SecurityVlmCamera }>(
    `${departmentApi(department)}/cameras/${encodeURIComponent(cameraId)}`,
  )

export const testSecurityVlmCamera = (
  department: SecurityVlmDepartment,
  rtspUrl: string,
) =>
  securityVlmPost<{ ok: boolean; codec_name: string; width: number; height: number }>(
    `${departmentApi(department)}/cameras/test`,
    { rtsp_url: rtspUrl },
  )

export const controlSecurityVlmCamera = (
  department: SecurityVlmDepartment,
  cameraId: string,
  action: 'start' | 'stop' | 'restart',
) =>
  securityVlmPost<SecurityVlmControlResponse>(
    `${departmentApi(department)}/cameras/${encodeURIComponent(cameraId)}/control/${action}`,
  )

export const startAllSecurityVlmCameras = (department: SecurityVlmDepartment) =>
  securityVlmPost<SecurityVlmControlResponse>(
    `${departmentApi(department)}/cameras/control/start-all`,
  )

export const stopAllSecurityVlmCameras = (department: SecurityVlmDepartment) =>
  securityVlmPost<SecurityVlmControlResponse>(
    `${departmentApi(department)}/cameras/control/stop-all`,
  )

export const getSecurityVlmCameraRois = (
  department: SecurityVlmDepartment,
  cameraId: string,
) =>
  securityVlmGet<SecurityVlmRoisResponse>(
    `${departmentApi(department)}/cameras/${encodeURIComponent(cameraId)}/rois`,
  )

export const saveSecurityVlmCameraRois = (
  department: SecurityVlmDepartment,
  cameraId: string,
  staffRois: Record<string, SecurityVlmRoiPolygon>,
) =>
  securityVlmPost<SecurityVlmRoisResponse>(
    `${departmentApi(department)}/cameras/${encodeURIComponent(cameraId)}/rois`,
    { staff_rois: staffRois },
  )

export const getSecurityVlmRois = () => securityVlmGet<SecurityVlmRoisResponse>('/api/rois')

export const saveSecurityVlmRois = (
  staff_rois: Record<string, SecurityVlmRoiPolygon>,
) =>
  securityVlmPost<SecurityVlmRoisResponse>('/api/rois', { staff_rois })

export const startSecurityVlmRuntime = () => securityVlmPost<{ success?: boolean; running: boolean }>('/api/control/start')

export const stopSecurityVlmRuntime = () => securityVlmPost<{ success?: boolean; running: boolean }>('/api/control/stop')

export const restartSecurityVlmRuntime = () => securityVlmPost<{ success?: boolean; running: boolean }>('/api/control/restart')

export const securityVlmVideoUrl = (kind: 'original' | 'rule', nonce?: number) =>
  `/security-vlm/video/${kind}${nonce ? `?t=${nonce}` : ''}`

export const securityVlmCameraVideoUrl = (
  department: SecurityVlmDepartment,
  cameraId: string,
  kind: 'original' | 'rule',
  nonce?: number,
) =>
  `/security-vlm${departmentApi(department)}/video/${encodeURIComponent(cameraId)}/${kind}${nonce ? `?t=${nonce}` : ''}`
