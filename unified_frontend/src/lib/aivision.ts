import type { DepartmentId } from '@/auth/permissions'
import { notifyPlatformCamerasChanged } from '@/lib/camera-events'
import { validateHornBinding } from '@/lib/horn-alarm-binding'
import type { NormalizedFeatureAlarmConfig } from '@/lib/alarm-config'

function trimTrailingSlash(value: string) {
  return value.replace(/\/+$/, '')
}

const PUBLIC_ORIGIN = trimTrailingSlash((import.meta.env.VITE_PUBLIC_ORIGIN as string | undefined) || '')

export const AIVISION_URL =
  (import.meta.env.VITE_AIVISION_URL as string | undefined) ||
  (PUBLIC_ORIGIN ? `${PUBLIC_ORIGIN}/aivision/` : '/aivision/')

export type AiVisionCamera = {
  id: string
  name: string
  shm_name: string
  url?: string
  camera_id: number
  sort_order: number
  fps?: number
  enabled: boolean
  functions: Record<string, boolean>
  department: DepartmentId | null
}

export type AiVisionDepartment = {
  name: DepartmentId
  display_name: string
}

export type AiVisionFeatureMeta = {
  name: string
  display_name: string
  required_models: string[]
  violation_type: number
  default_config: AiVisionFeatureConfig
  config_schema: Record<string, unknown>
}

export type CreateAiVisionCameraPayload = {
  name: string
  url: string
  shm_name: string
  fps?: number
  enabled?: boolean
  department: DepartmentId
}

export type CreateAiVisionFeatureCameraPayload = Omit<CreateAiVisionCameraPayload, 'shm_name' | 'department'> & {
  shm_name?: string
  department: DepartmentId
}

export type UpdateAiVisionCameraPayload = Partial<Pick<CreateAiVisionCameraPayload, 'name' | 'url' | 'fps' | 'enabled' | 'department'>>

export type AiVisionExceptionAlertSettings = {
  wechat_enable: boolean
  wechat_user: string
  repeat_interval_minutes: number
}

export type AiVisionModel = {
  name: string
  type: string
  path: string
  runtime: {
    status: 'not_started' | 'running' | 'starting' | 'backoff' | 'exhausted' | 'stopped' | 'failed'
    running: boolean
    alive: boolean
    loaded_path: string
    last_failure: string
    shared_models: string[]
    restart_attempts: number
    next_restart_in_seconds: number
  }
  reload: {
    status: 'idle' | 'loading' | 'succeeded' | 'failed' | 'not_started'
    error: string
  }
}

export type AiVisionModelPathSaveResult = {
  configuration_saved: boolean
  name: string
  path: string
  load_status: 'loading' | 'not_started'
}

export type AiVisionFeatureConfig = {
  enable: boolean
  value: Record<string, unknown>
  alarm?: NormalizedFeatureAlarmConfig
}

export type AiVisionLogisticsSinglePersonStatus = {
  camera_key: string
  feature: string
  online: boolean
  count: number | null
  alarm: boolean
  reason: 'normal' | 'empty' | 'multiple' | 'unknown'
  updated_at: string | null
}

export type AiVisionHumanDwellStatus = {
  camera_key: string
  feature: string
  online: boolean
  count: number | null
  alarm: boolean
  reason: 'normal' | 'loitering' | 'unknown'
  duration_seconds: number | null
  threshold_seconds: number | null
  updated_at: string | null
}

type AiVisionFeatureConfigResponse = {
  camera: {
    id: number
    name: string
    shm_name: string
    enable: boolean
  }
  feature: string
  config: AiVisionFeatureConfig
}

type AiVisionCamerasResponse = AiVisionCamera[]

async function readAiVisionError(response: Response) {
  if (response.status === 401) {
    window.dispatchEvent(new Event('aicv:unauthorized'))
  }
  let detail = await response.text().catch(() => '')
  try {
    const parsed = JSON.parse(detail) as { detail?: string }
    detail = parsed.detail || detail
  } catch {
    void 0
  }
  return detail || `${response.status} ${response.statusText}`
}

export async function saveAiVisionCameraOrder(department: DepartmentId, cameraIds: number[]): Promise<void> {
  const response = await fetch('/api/cameras/order', {
    method: 'PUT', credentials: 'include', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ department, camera_ids: cameraIds }),
  })
  if (!response.ok) throw new Error(await readAiVisionError(response))
}

export async function getAiVisionCameras(department: DepartmentId) {
  const params = new URLSearchParams({ department })
  const response = await fetch(`/api/cameras?${params}`, { credentials: 'include' })
  if (!response.ok) {
    throw new Error(await readAiVisionError(response))
  }

  const payload = (await response.json()) as AiVisionCamerasResponse
  return payload
}

export async function getAiVisionLogisticsSinglePersonStatus(cameraKey: string, feature: string) {
  const response = await fetch(
    `/api/features/${encodeURIComponent(feature)}/cameras/${encodeURIComponent(cameraKey)}/status`,
    { credentials: 'include' },
  )
  if (!response.ok) {
    throw new Error(await readAiVisionError(response))
  }
  return (await response.json()) as AiVisionLogisticsSinglePersonStatus
}

export async function getAiVisionHumanDwellStatus(cameraKey: string, feature = 'detect_human') {
  const response = await fetch(
    `/api/features/${encodeURIComponent(feature)}/cameras/${encodeURIComponent(cameraKey)}/status`,
    { credentials: 'include' },
  )
  if (!response.ok) {
    throw new Error(await readAiVisionError(response))
  }
  return (await response.json()) as AiVisionHumanDwellStatus
}

export async function getAiVisionDepartments(signal?: AbortSignal) {
  const response = await fetch('/api/departments', { credentials: 'include', signal })
  if (!response.ok) {
    throw new Error(await readAiVisionError(response))
  }
  return (await response.json()) as AiVisionDepartment[]
}

export async function getAiVisionDepartmentFeatures(departmentName: DepartmentId) {
  const response = await fetch(`/api/departments/${encodeURIComponent(departmentName)}/features`, { credentials: 'include' })
  if (!response.ok) {
    throw new Error(await readAiVisionError(response))
  }
  return (await response.json()) as Array<{ name: string; display_name: string }>
}

export function getAiVisionCameraKey(camera: Pick<AiVisionCamera, 'shm_name' | 'id' | 'camera_id'>) {
  return camera.shm_name || camera.id || String(camera.camera_id)
}

export function isAiVisionFeatureEnabled(camera: AiVisionCamera, feature: string) {
  return Boolean(camera.functions[feature])
}

export type AiVisionFrameOptions = {
  maxWidth?: number
  maxHeight?: number
  quality?: number
}

export function aiVisionFrameUrl(cameraKey: string, feature?: string, nonce?: number, options: AiVisionFrameOptions = {}) {
  const params = new URLSearchParams()
  if (feature) params.set('feature', feature)
  if (nonce) params.set('t', String(nonce))
  if (options.maxWidth) params.set('max_width', String(options.maxWidth))
  if (options.maxHeight) params.set('max_height', String(options.maxHeight))
  if (options.quality) params.set('quality', String(options.quality))
  const query = params.toString()
  return `/api/cameras/${encodeURIComponent(cameraKey)}/frame.jpg${query ? `?${query}` : ''}`
}

export async function createAiVisionCamera(payload: CreateAiVisionCameraPayload) {
  const response = await fetch('/api/cameras', {
    method: 'POST',
    credentials: 'include',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  })
  if (!response.ok) {
    throw new Error(await readAiVisionError(response))
  }

  const camera = (await response.json()) as AiVisionCamera
  window.dispatchEvent(new Event('aivision:cameras-changed'))
  notifyPlatformCamerasChanged()
  return camera
}

export async function createAiVisionFeatureCamera(
  feature: string,
  payload: CreateAiVisionFeatureCameraPayload,
) {
  const response = await fetch(`/api/features/${encodeURIComponent(feature)}/cameras`, {
    method: 'POST',
    credentials: 'include',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  })
  if (!response.ok) {
    throw new Error(await readAiVisionError(response))
  }

  const camera = (await response.json()) as AiVisionCamera
  window.dispatchEvent(new Event('aivision:cameras-changed'))
  notifyPlatformCamerasChanged()
  return camera
}

export async function updateAiVisionCamera(cameraKey: string, payload: UpdateAiVisionCameraPayload) {
  const response = await fetch(`/api/cameras/${encodeURIComponent(cameraKey)}`, {
    method: 'PATCH',
    credentials: 'include',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  })
  if (!response.ok) {
    throw new Error(await readAiVisionError(response))
  }

  const camera = (await response.json()) as AiVisionCamera
  window.dispatchEvent(new Event('aivision:cameras-changed'))
  notifyPlatformCamerasChanged()
  return camera
}

export async function deleteAiVisionCamera(cameraKey: string) {
  const response = await fetch(`/api/cameras/${encodeURIComponent(cameraKey)}`, {
    method: 'DELETE',
    credentials: 'include',
  })
  if (!response.ok) {
    throw new Error(await readAiVisionError(response))
  }

  window.dispatchEvent(new Event('aivision:cameras-changed'))
  notifyPlatformCamerasChanged()
  return (await response.json()) as { ok: boolean }
}

export async function getAiVisionExceptionAlertSettings() {
  const response = await fetch('/api/exception-alert', { credentials: 'include' })
  if (!response.ok) {
    throw new Error(await readAiVisionError(response))
  }
  return (await response.json()) as AiVisionExceptionAlertSettings
}

export async function saveAiVisionExceptionAlertSettings(payload: AiVisionExceptionAlertSettings) {
  const response = await fetch('/api/exception-alert', {
    method: 'PUT',
    credentials: 'include',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  })
  if (!response.ok) {
    throw new Error(await readAiVisionError(response))
  }
  return (await response.json()) as AiVisionExceptionAlertSettings
}

export async function getAiVisionFeatureConfig(feature: string, cameraKey: string) {
  const response = await fetch(`/api/features/${encodeURIComponent(feature)}/configs/${encodeURIComponent(cameraKey)}`, {
    credentials: 'include',
  })
  if (!response.ok) {
    throw new Error(await readAiVisionError(response))
  }

  return (await response.json()) as AiVisionFeatureConfigResponse
}

export async function saveAiVisionFeatureConfig(feature: string, cameraKey: string, config: AiVisionFeatureConfig) {
  const horn = config.alarm?.horn
  const hornError = horn && validateHornBinding(horn)
  if (hornError) throw new Error(hornError)
  const response = await fetch(`/api/features/${encodeURIComponent(feature)}/configs/${encodeURIComponent(cameraKey)}`, {
    method: 'PUT',
    credentials: 'include',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(config),
  })
  if (!response.ok) {
    throw new Error(await readAiVisionError(response))
  }

  window.dispatchEvent(new Event('aivision:cameras-changed'))
  return (await response.json()) as AiVisionFeatureConfigResponse
}

export async function getAiVisionModels(signal?: AbortSignal) {
  const response = await fetch('/api/models', { credentials: 'include', signal })
  if (!response.ok) {
    throw new Error(await readAiVisionError(response))
  }

  return (await response.json()) as AiVisionModel[]
}

export async function updateAiVisionModelPath(modelName: string, path: string) {
  const response = await fetch(`/api/models/${encodeURIComponent(modelName)}/path`, {
    method: 'PATCH',
    credentials: 'include',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ path }),
  })
  if (!response.ok) {
    throw new Error(await readAiVisionError(response))
  }

  return (await response.json()) as AiVisionModelPathSaveResult
}
